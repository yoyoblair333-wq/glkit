# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
QuoteCheck - the glkit example contract.

"Does this public page really say this?" A caller gives an https URL and a quote.
Each validator fetches the page itself (glkit.proof.fetch_page), and the contract
records FOUND / NOT_FOUND / UNREADABLE plus the page's text length bucket. No model
is asked anything: the decision is code (glkit.proof.quote_on_page), so validators
agree exactly or the transaction fails.

This file is the *source*. `python -m glkit bundle quote_check.src.py quote_check.py`
inlines glkit.proof where the include marker is, producing the deployable file.
"""

from genlayer import *

from dataclasses import dataclass


# glkit:include proof


ERR = "[EXPECTED]"
MAX_QUOTE = 300
MIN_QUOTE = 12


def _fail(msg: str):
    raise gl.vm.UserError(f"{ERR} {msg}")


def _bucket(n: int) -> str:
    """Coarse page-size bucket: validators fetching at slightly different moments
    may see a few characters' difference, so only the order of magnitude is compared."""
    if n == 0:
        return "empty"
    if n < 1_000:
        return "small"
    if n < 20_000:
        return "medium"
    return "large"


@allow_storage
@dataclass
class Check:
    id: u256
    url: str
    quote: str
    status: str
    page_size: str
    checked_by: Address


class QuoteCheck(gl.Contract):
    checks: TreeMap[u256, Check]
    next_id: u256

    def __init__(self):
        self.next_id = u256(1)

    @gl.public.write
    def check(self, url: str, quote: str) -> dict:
        try:
            u = canonical_url(url)
        except GlkInputError as e:
            _fail(str(e))
            raise
        q = clean_text(quote)
        if not MIN_QUOTE <= len(q) <= MAX_QUOTE:
            _fail(f"quote must be {MIN_QUOTE}..{MAX_QUOTE} characters")

        def leader_fn() -> dict:
            text = fetch_page(u)
            if text == "":
                return {"status": "UNREADABLE", "size": "empty"}
            found = quote_on_page(q, squash(text))
            return {"status": "FOUND" if found else "NOT_FOUND", "size": _bucket(len(text))}

        def validator_fn(leader_res) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False
            mine = leader_fn()
            return leader_res.calldata == mine

        res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        cid = self.next_id
        self.checks[cid] = Check(id=cid, url=u, quote=q, status=res["status"], page_size=res["size"],
                                 checked_by=gl.message.sender_address)
        self.next_id = u256(int(cid) + 1)
        return self._to_dict(self.checks[cid])

    def _to_dict(self, c: Check) -> dict:
        return {"id": int(c.id), "url": c.url, "quote": c.quote, "status": c.status,
                "page_size": c.page_size, "checked_by": c.checked_by.as_hex}

    @gl.public.view
    def get_check(self, check_id: int) -> dict:
        key = u256(check_id)
        if key not in self.checks:
            _fail("no such check")
        return self._to_dict(self.checks[key])

    @gl.public.view
    def count(self) -> int:
        return int(self.next_id) - 1
