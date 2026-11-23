"""
glkit.run - a resumable, fee-aware live-run recorder.

A live run is a script that deploys a contract and drives it through a story on a
real network. LiveRun writes every transaction hash to a JSON file *before* it
waits, so a run that is interrupted (a timeout, a laptop lid) resumes where it
stopped and never sends the same step twice. Everything in the file is what the
chain returned; nothing is typed in by hand.

    run = LiveRun("docs/live/run.json", roles=["owner", "alice"])
    court = run.deploy("deploy_court", "owner", "contracts/court.py", args=[...])
    run.write("alice_opens", "alice", court, "open_case", [...], fee="llm")
    run.note("case_1", run.read(court, "get_case", [1]))
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable, Optional

from .chain import contract_address, fees_for, jsonable, send, summarize, wait

WEI = 10**18
STUDIO_EXPLORER = "https://explorer-studio.genlayer.com"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LiveRun:
    def __init__(self, path: str, roles: Iterable[str] = ("owner",), keys_path: Optional[str] = None,
                 chain=None, fund_wei: int = 20 * WEI, explorer: str = STUDIO_EXPLORER, log=print):
        self.path = path
        self.log = log
        self.explorer = explorer
        self.s = json.load(open(path)) if os.path.exists(path) else {}
        self.s.setdefault("steps", [])
        self.s.setdefault("reads", {})
        self.keys_path = keys_path or os.path.join(os.path.dirname(os.path.abspath(path)), ".keys.json")
        self._roles = list(roles)
        self._chain = chain
        self._fund_wei = fund_wei
        self.clients = {}
        self.accounts = {}

    # ---------------------------------------------------------------- setup

    def connect(self) -> "LiveRun":
        """Create (or reload) throwaway keys, build clients and fund each role once."""
        from eth_account import Account
        from genlayer_py import create_account, create_client
        if self._chain is None:
            from genlayer_py.chains import studionet
            self._chain = studionet
        self.s.setdefault("network", getattr(self._chain, "name", "studionet"))
        os.makedirs(os.path.dirname(os.path.abspath(self.keys_path)), exist_ok=True)
        keys = json.load(open(self.keys_path)) if os.path.exists(self.keys_path) else {}
        for role in self._roles:
            if role not in keys:
                keys[role] = "0x" + bytes(create_account().key).hex()
        with open(self.keys_path, "w") as fh:
            json.dump(keys, fh)
        for role in self._roles:
            acct = Account.from_key(keys[role])
            self.accounts[role] = acct
            self.clients[role] = create_client(chain=self._chain, account=acct)
        self.s["roles"] = {r: a.address for r, a in self.accounts.items()}
        for role, acct in self.accounts.items():
            flag = "funded_" + role
            if not self.s.get(flag) and self._fund_wei:
                for attempt in range(4):
                    try:
                        self.clients[role].fund_account(acct.address, self._fund_wei)
                        break
                    except Exception as e:  # noqa: BLE001 - transient RPC resets
                        if attempt == 3:
                            raise
                        self.log(f"  funding {role} failed ({str(e)[:100]}); retrying in 10s")
                        time.sleep(10)
                self.s[flag] = True
        self.save()
        return self

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(jsonable(self.s), fh, indent=1)
            fh.write("\n")
        os.replace(tmp, self.path)

    # ---------------------------------------------------------------- steps

    def step(self, label: str) -> Optional[dict]:
        for st in self.s["steps"]:
            if st["step"] == label:
                return st
        return None

    def _do(self, role: str, label: str, fn) -> dict:
        st = self.step(label)
        client = self.clients[role]
        if st and st.get("tx") and st.get("status"):
            self.log(f"[skip] {label}: {st['tx']}")
            return st
        if st and st.get("tx"):
            # sent before an interruption but never summarised: wait for it, do not resend
            self.log(f"[resume] {label}: {st['tx']}")
        else:
            self.log(f"[send] {label}")
            tx = send(fn, log=self.log)
            self.s["steps"] = [x for x in self.s["steps"] if x["step"] != label]
            st = {"step": label, "role": role, "tx": tx, "sent_at": _now()}
            self.s["steps"].append(st)
            self.save()
        t = wait(client, st["tx"])
        st.update(summarize(t))
        st["explorer"] = f"{self.explorer}/tx/{st['tx']}"
        self.save()
        self.log(f"  {st['tx']} {st['status']} {st['result']} exec={st['execution']} "
                 f"votes={st['votes']} err={st['error']}")
        return st

    def deploy(self, label: str, role: str, code_path: str, args: Optional[list] = None,
               fee: str = "base") -> str:
        key = label + "_address"
        if self.s.get(key):
            return self.s[key]
        client = self.clients[role]
        code = open(code_path, encoding="utf-8").read()
        st = self._do(role, label, lambda: client.deploy_contract(code=code, args=args or [],
                                                                  fees=fees_for(client, fee)))
        addr = contract_address(client.get_transaction(st["tx"]))
        self.s[key] = addr
        self.s.setdefault("contracts", {})[label] = {"address": addr,
                                                     "explorer": f"{self.explorer}/address/{addr}"}
        self.save()
        return addr

    def write(self, label: str, role: str, address: str, fn: str, args: Optional[list] = None,
              fee: str = "base", value: int = 0) -> dict:
        client = self.clients[role]
        return self._do(role, label, lambda: client.write_contract(
            address=address, function_name=fn, args=args or [], value=value, fees=fees_for(client, fee)))

    def read(self, address: str, fn: str, args: Optional[list] = None, role: Optional[str] = None) -> Any:
        client = self.clients[role or self._roles[0]]
        return client.read_contract(address=address, function_name=fn, args=args or [])

    def note(self, key: str, value: Any) -> Any:
        self.s["reads"][key] = jsonable(value)
        self.save()
        return value

    def finish(self) -> None:
        self.s["finished_at"] = _now()
        self.save()
