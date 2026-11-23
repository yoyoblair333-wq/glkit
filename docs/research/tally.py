#!/usr/bin/env python3
"""Tally consensus outcomes across live-run JSON files (glkit / LiveRun format).

    python docs/research/tally.py RUN.json [RUN.json ...] > docs/research/tally.md
"""
import collections
import json
import sys


def main(paths):
    rows, tot = [], collections.Counter()
    for p in paths:
        s = json.load(open(p))
        steps = s.get("steps", [])
        c = collections.Counter()
        for st in steps:
            cur = st.get("latest") or st
            c["txs"] += 1
            c["majority_agree"] += cur.get("result") == "MAJORITY_AGREE"
            c["finalized"] += str(cur.get("status", "")).upper().startswith("FINALIZED")
            c["exec_error"] += cur.get("execution") == "ERROR"
            for v in cur.get("votes") or []:
                c["vote_" + v] += 1
        rows.append((p, c))
        tot.update(c)
    cols = ["txs", "majority_agree", "finalized", "exec_error", "vote_agree", "vote_disagree", "vote_timeout", "vote_idle"]
    print("| Run | " + " | ".join(cols) + " |")
    print("|---|" + "---|" * len(cols))
    for p, c in rows + [("**total**", tot)]:
        print(f"| {p} | " + " | ".join(str(c.get(k, 0)) for k in cols) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
