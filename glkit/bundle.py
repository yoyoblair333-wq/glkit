"""
glkit.bundle - inline glkit modules into a single-file GenVM contract.

GenVM deploys one source file. Write your contract with an include marker on its
own line:

    # glkit:include proof

and run

    python -m glkit bundle contracts/my_contract.src.py contracts/my_contract.py

The marker is replaced by the code between the module's `# --- glkit:begin <name> ---`
and `# --- glkit:end <name> ---` lines, wrapped in banners that name the module and
its sha256, so a reviewer can verify the inlined code against glkit. Bundling is
deterministic and idempotent: bundling a bundled file changes nothing.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INCLUDE_RE = re.compile(r"^[ \t]*# glkit:include ([a-z_]+)[ \t]*$", re.M)


class BundleError(Exception):
    pass


def module_block(name: str) -> str:
    path = os.path.join(HERE, name + ".py")
    if not os.path.isfile(path):
        raise BundleError(f"unknown glkit module {name!r}")
    src = open(path, encoding="utf-8").read()
    begin, end = f"# --- glkit:begin {name} ---\n", f"# --- glkit:end {name} ---"
    a, b = src.find(begin), src.find(end)
    if a < 0 or b < 0 or b < a:
        raise BundleError(f"module {name!r} has no begin/end markers")
    return src[a + len(begin):b].rstrip() + "\n"


def bundle_source(src: str) -> str:
    names = INCLUDE_RE.findall(src)
    if len(names) != len(set(names)):
        raise BundleError("a module is included more than once")

    def repl(m: re.Match) -> str:
        name = m.group(1)
        block = module_block(name)
        digest = hashlib.sha256(block.encode("utf-8")).hexdigest()[:16]
        return (f"# ===== glkit.{name} (inlined by glkit bundle, sha256:{digest}) =====\n"
                f"{block}"
                f"# ===== end glkit.{name} =====")

    return INCLUDE_RE.sub(repl, src)


def bundle_file(src_path: str, out_path: str) -> str:
    src = open(src_path, encoding="utf-8").read()
    if not src.startswith("# {"):
        raise BundleError("the contract must start with its GenVM '# { \"Depends\": ... }' header line")
    out = bundle_source(src)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    return out_path


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) != 3:
        sys.exit("usage: python -m glkit.bundle SRC OUT")
    print(bundle_file(sys.argv[1], sys.argv[2]))
