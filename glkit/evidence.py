"""
glkit.evidence - render a LiveRun JSON file as a reviewer-friendly Markdown page.

    python -m glkit evidence docs/live/run.json docs/LIVE_EVIDENCE.md [--refresh]

With --refresh every transaction is re-read from the chain first, so the page shows
its latest status (useful once a transaction has moved from decided to finalized).
"""

from __future__ import annotations

import json
from typing import Optional

from .chain import jsonable, summarize
from .run import STUDIO_EXPLORER

_SKIP = {"steps", "reads", "roles", "network", "contracts", "finished_at"}


def refresh(run: dict, client) -> dict:
    for st in run.get("steps", []):
        try:
            st["latest"] = summarize(client.get_transaction(st["tx"]))
        except Exception as e:  # noqa: BLE001
            st.setdefault("latest", {"error": str(e)[:120]})
    return run


def _cell(x) -> str:
    s = "" if x is None else str(x)
    return s.replace("|", "\\|").replace("\n", " ")


def render(run: dict, title: str = "Live evidence", explorer: str = STUDIO_EXPLORER,
           note: Optional[str] = None) -> str:
    out = [f"# {title}", ""]
    out.append(note or ("Rendered by `glkit evidence` from the live-run JSON, which the run script wrote "
                        "from chain data. Test-network GEN has no value; all keys are throwaway test keys."))
    out += ["", f"Network: {_cell(run.get('network', ''))}", ""]
    contracts = run.get("contracts") or {}
    if contracts:
        out += ["## Contracts", "", "| Deploy step | Address |", "|---|---|"]
        for label, c in contracts.items():
            out.append(f"| {_cell(label)} | [`{c['address']}`]({c.get('explorer') or explorer + '/address/' + c['address']}) |")
        out.append("")
    roles = run.get("roles") or {}
    if roles:
        out += ["## Roles (throwaway keys)", "", "| Role | Address |", "|---|---|"]
        out += [f"| {_cell(r)} | `{a}` |" for r, a in roles.items()]
        out.append("")
    out += ["## Transactions", "",
            "| # | Step | Tx | Status | Consensus | Leader execution | Votes | Contract error |",
            "|---|---|---|---|---|---|---|---|"]
    for i, st in enumerate(run.get("steps", []), 1):
        cur = st.get("latest") or st
        tx = st.get("tx", "")
        short = tx[:10] + "…" + tx[-6:] if len(tx) > 20 else tx
        votes = ", ".join(f"{v} {n}" for v, n in _count(cur.get("votes") or []))
        out.append(f"| {i} | {_cell(st['step'])} | [`{short}`]({explorer}/tx/{tx}) | {_cell(cur.get('status'))} | "
                   f"{_cell(cur.get('result'))} | {_cell(cur.get('execution'))} | {_cell(votes)} | "
                   f"{_cell(cur.get('error') or '')} |")
    out.append("")
    reads = run.get("reads") or {}
    if reads:
        out += ["## State read back from the contracts", ""]
        for k, v in reads.items():
            out += [f"### {k}", "", "```json", json.dumps(jsonable(v), indent=1, ensure_ascii=False), "```", ""]
    extra = {k: v for k, v in run.items() if k not in _SKIP and not k.startswith("funded_") and not k.endswith("_address")}
    if extra:
        out += ["## Run metadata", "", "```json", json.dumps(jsonable(extra), indent=1), "```", ""]
    if run.get("finished_at"):
        out.append(f"Run finished at {run['finished_at']}.")
    return "\n".join(out) + "\n"


def _count(votes: list) -> list:
    seen = {}
    for v in votes:
        seen[v] = seen.get(v, 0) + 1
    return sorted(seen.items())
