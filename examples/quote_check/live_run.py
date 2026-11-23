#!/usr/bin/env python3
"""
Deploy the bundled QuoteCheck example to studionet with glkit.LiveRun and check
real quotes on a real public page. Resumable; writes examples/quote_check/live/run.json.

    python examples/quote_check/live_run.py
    python -m glkit evidence examples/quote_check/live/run.json examples/quote_check/LIVE_EVIDENCE.md
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from glkit import LiveRun  # noqa: E402

PAGE = "https://www.irs.gov/tax-professionals/standard-mileage-rates"
TRUE_QUOTE = "standard mileage rates"
FALSE_QUOTE = "standard mileage rates are abolished"


def main():
    run = LiveRun(os.path.join(HERE, "live", "run.json"), roles=["owner", "caller"],
                  keys_path=os.path.join(HERE, "live", ".keys.json")).connect()
    qc = run.deploy("deploy_quote_check", "owner", os.path.join(HERE, "quote_check.py"))
    run.write("check_real_quote", "caller", qc, "check", [PAGE, TRUE_QUOTE], fee="llm")
    run.note("check_1", run.read(qc, "get_check", [1]))
    run.write("check_invented_quote", "caller", qc, "check", [PAGE, FALSE_QUOTE], fee="llm")
    run.note("check_2", run.read(qc, "get_check", [2]))
    run.write("check_bad_url_must_revert", "caller", qc, "check", ["http://www.irs.gov/", TRUE_QUOTE])
    run.note("count", run.read(qc, "count"))
    run.finish()


if __name__ == "__main__":
    main()
