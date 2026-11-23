"""
glkit.doctor - is this machine ready to send transactions to a fee-aware network?

    python -m glkit doctor [--address 0x...]

Checks the genlayer-py version, reaches the network, reads the live fee policy,
builds a fee estimate (and clamps a large allocation into bounds), and optionally
reads an address's balance. Prints one line per check and exits non-zero on a failure.
"""

from __future__ import annotations

from importlib import metadata

from .chain import clamp_timeunits, PRESETS

MIN_SDK = (0, 19, 0)


def _ver(s: str) -> tuple:
    out = []
    for p in s.split(".")[:3]:
        n = "".join(ch for ch in p if ch.isdigit())
        out.append(int(n or 0))
    return tuple(out + [0] * (3 - len(out)))


def run(address: str = "", chain=None, out=print) -> int:
    ok = True
    try:
        v = metadata.version("genlayer-py")
    except metadata.PackageNotFoundError:
        out("FAIL genlayer-py is not installed (pip install 'genlayer-py>=0.19')")
        return 1
    if _ver(v) < MIN_SDK:
        ok = False
        out(f"FAIL genlayer-py {v}: older than 0.19, which cannot send fee-aware transactions "
            "(sends fail with FeesDistributionMissing / 'Transaction failed')")
    else:
        out(f"ok   genlayer-py {v}")
    try:
        gt = metadata.version("genlayer-test")
        if _ver(v) >= MIN_SDK and _ver(gt) <= (0, 29, 99):
            out(f"warn genlayer-test {gt} pins genlayer-py < 0.17 and fails to import next to {v}; "
                "keep it in its own virtualenv for direct-mode tests (see README: two environments)")
        else:
            out(f"ok   genlayer-test {gt}")
    except metadata.PackageNotFoundError:
        pass
    from genlayer_py import create_client
    if chain is None:
        from genlayer_py.chains import studionet
        chain = studionet
    client = create_client(chain=chain)
    try:
        from genlayer_py.contracts.actions import get_current_fee_policy
        pol = get_current_fee_policy(client)
        out(f"ok   network reachable; fee policy enabled={pol['enabled']} genPerTimeUnit={pol['genPerTimeUnit']} "
            f"receiptGasPrice={pol['receiptGasPrice']}")
    except Exception as e:  # noqa: BLE001
        out(f"FAIL could not read the fee policy: {str(e)[:160]}")
        return 1
    try:
        base = client.estimate_transaction_fees(None)
        llm = client.estimate_transaction_fees(clamp_timeunits(PRESETS["llm"]))
        out(f"ok   fee estimate: base {base['feeValue'] / 1e18:.6f} GEN, llm preset {llm['feeValue'] / 1e18:.6f} GEN")
    except Exception as e:  # noqa: BLE001
        ok = False
        out(f"FAIL fee estimate: {str(e)[:160]}")
    if address:
        try:
            bal = client.get_balance(address)
            out(f"ok   balance of {address}: {bal / 1e18:.4f} GEN")
            if bal < 10**18:
                out("warn balance below 1 GEN; on studionet fund it with client.fund_account(address, amount)")
        except Exception as e:  # noqa: BLE001
            ok = False
            out(f"FAIL balance: {str(e)[:160]}")
    return 0 if ok else 1
