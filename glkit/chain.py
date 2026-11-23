"""
glkit.chain - fee-aware sending, waiting and reading for GenLayer networks.

Since the fee-aware ConsensusMain rollout (November 2026), studionet rejects a
transaction that carries no fee distribution: the EVM call reverts with
`FeesDistributionMissing`. Older scripts that call `deploy_contract` /
`write_contract` without `fees=` now fail with the bare SDK message
"Transaction failed". A distribution whose leader or validator time-unit
allocation is outside the network's bounds reverts with
`PhaseTimeoutOutOfBounds(value, min, max)`.

This module wraps genlayer-py (>= 0.19) so every write carries a valid,
estimated fee distribution, clamps time-unit allocations into bounds, and
reads both the old and the new transaction shapes when summarising.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional

# Network bounds observed on studionet (PhaseTimeoutOutOfBounds(v, 30, 600)).
TIMEUNITS_MIN = 30
TIMEUNITS_MAX = 600

# Named presets. "base" = the SDK default estimate; "llm" gives a leader and its
# validators room for several model calls (a jury, a page read plus a prompt).
PRESETS = {
    "base": None,
    "llm": {"leaderTimeunitsAllocation": 600, "validatorTimeunitsAllocation": 600},
}

ERROR_TAGS = ("[EXPECTED]", "[REJECTED]", "[LLM_ERROR]", "[EXTERNAL]", "[ERROR]")


def clamp_timeunits(options: Optional[dict], lo: int = TIMEUNITS_MIN, hi: int = TIMEUNITS_MAX) -> Optional[dict]:
    """Return a copy of fee-estimate options with time-unit allocations inside [lo, hi]."""
    if options is None:
        return None
    out = dict(options)
    for key in ("leaderTimeunitsAllocation", "validatorTimeunitsAllocation",
                "leader_timeunits_allocation", "validator_timeunits_allocation"):
        if key in out and out[key] is not None:
            out[key] = max(lo, min(hi, int(out[key])))
    return out


def fees_for(client, kind: str = "base", options: Optional[dict] = None) -> dict:
    """An estimated, fee-aware `fees=` argument for deploy_contract / write_contract."""
    if options is None:
        if kind not in PRESETS:
            raise ValueError(f"unknown fee preset {kind!r}; use one of {sorted(PRESETS)}")
        options = PRESETS[kind]
    est = client.estimate_transaction_fees(clamp_timeunits(options))
    return {"distribution": est["distribution"], "feeValue": est["feeValue"]}


def hexs(tx: Any) -> str:
    h = tx.hex() if hasattr(tx, "hex") and not isinstance(tx, str) else str(tx)
    return h if h.startswith("0x") else "0x" + h


def jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (bytes, bytearray)):
        return "0x" + bytes(x).hex()
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


_REVERT_RE = re.compile(r"was reverted\.?\s*([A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?)")


def explain_send_error(err: Exception) -> str:
    """Turn a raw SDK send error into one actionable sentence."""
    msg = str(err)
    m = _REVERT_RE.search(msg)
    reason = m.group(1) if m else ""
    if "FeesDistributionMissing" in msg:
        return ("FeesDistributionMissing: this network is fee-aware; pass fees=glkit.fees_for(client) "
                "(genlayer-py >= 0.19).")
    if reason.startswith("PhaseTimeoutOutOfBounds"):
        return (f"{reason}: a time-unit allocation is outside the network bounds; "
                "use glkit.clamp_timeunits() on your fee options.")
    if msg.strip() == "Transaction failed":
        return ("Transaction failed with no reason: on genlayer-py < 0.19 this is usually "
                "FeesDistributionMissing. Upgrade genlayer-py and pass fees=glkit.fees_for(client).")
    return msg[:300]


def send(fn: Callable[[], Any], attempts: int = 4, delay_s: float = 10.0, log=print) -> str:
    """Call fn() (a deploy/write) with retries for transient RPC failures. Errors that
    a retry cannot fix (fee or bounds reverts) are raised at once with an explanation."""
    last = None
    for i in range(attempts):
        try:
            return hexs(fn())
        except Exception as e:  # noqa: BLE001 - SDK raises bare Exceptions
            last = e
            text = str(e)
            if "FeesDistributionMissing" in text or "PhaseTimeoutOutOfBounds" in text:
                raise RuntimeError(explain_send_error(e)) from e
            if i < attempts - 1:
                log(f"  send failed ({explain_send_error(e)[:140]}); retrying in {delay_s:.0f}s")
                time.sleep(delay_s)
    raise RuntimeError(explain_send_error(last)) from last


def wait(client, tx: str, interval_ms: int = 5000, retries: int = 360) -> dict:
    """Wait until the transaction is decided, then return the full transaction."""
    client.wait_for_transaction_receipt(transaction_hash=tx, interval=interval_ms, retries=retries)
    return client.get_transaction(tx)


def _status(t: dict) -> str:
    lc = t.get("lifecycle")
    if isinstance(lc, dict) and lc.get("state"):
        return f"{lc.get('state')}/{lc.get('outcome')}"
    return str(t.get("status_name") or t.get("status") or "")


def summarize(t: dict) -> dict:
    """Status, consensus result, leader execution result, vote list and the first
    tagged contract error, for both the pre- and post-fee transaction shapes."""
    cd = t.get("consensus_data") or {}
    votes = sorted(str(v) for v in (cd.get("votes") or {}).values())
    lr = cd.get("leader_receipt")
    lr = lr[0] if isinstance(lr, list) and lr else (lr or {})
    blob = json.dumps(jsonable(t))
    err = None
    for tag in ERROR_TAGS:
        i = blob.find(tag)
        if i >= 0:
            err = blob[i:i + 200].split('"')[0].split("\\")[0]
            break
    data = t.get("data") or {}
    return {
        "status": _status(t),
        "result": t.get("result_name"),
        "execution": lr.get("execution_result") if isinstance(lr, dict) else None,
        "votes": votes,
        "error": err,
        "fee_paid_wei": str(data.get("fee_value") or ""),
    }


def contract_address(t: dict) -> Optional[str]:
    data = t.get("data") or {}
    return data.get("contract_address") or t.get("recipient") or t.get("to_address")
