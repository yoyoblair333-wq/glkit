"""python -m glkit {doctor|bundle|evidence} ..."""

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="glkit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="check SDK version, network, fee policy and a balance")
    d.add_argument("--address", default="")
    b = sub.add_parser("bundle", help="inline glkit modules into a single-file contract")
    b.add_argument("src")
    b.add_argument("out")
    e = sub.add_parser("evidence", help="render a live-run JSON file as Markdown")
    e.add_argument("run_json")
    e.add_argument("out_md")
    e.add_argument("--title", default="Live evidence")
    e.add_argument("--refresh", action="store_true", help="re-read every tx from studionet first")
    a = ap.parse_args(argv)
    if a.cmd == "doctor":
        from .doctor import run
        return run(a.address)
    if a.cmd == "bundle":
        from .bundle import bundle_file
        print(bundle_file(a.src, a.out))
        return 0
    from .evidence import refresh, render
    run_data = json.load(open(a.run_json))
    if a.refresh:
        from genlayer_py import create_client
        from genlayer_py.chains import studionet
        refresh(run_data, create_client(chain=studionet))
        with open(a.run_json, "w") as fh:
            json.dump(run_data, fh, indent=1)
            fh.write("\n")
    with open(a.out_md, "w") as fh:
        fh.write(render(run_data, title=a.title))
    print(a.out_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
