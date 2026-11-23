"""
glkit.proof - helpers for Intelligent Contracts that read the web and must agree.

GenVM contracts are single files, so this module is written to be *inlined*:
`glkit bundle` copies everything between the begin/end markers below into your
contract where you write `# glkit:include proof`. The same code also imports as a
normal Python module, so it is unit-tested outside GenVM.

What it gives a contract:
  * fetch_page()       raw-HTML-first page text, falling back to a render only for
                       JavaScript-only pages (keeps text in collapsed tabs/accordions)
  * html_text()        script/style-free text from HTML, entities decoded
  * canonical_url()    https-only, public-host, credential-free URL normal form
  * focus()            deterministic budget-sized slice of a long page around a subject
  * squash()           the casefolded alphanumeric form quotes are compared in
  * quote_on_page()    is this "verbatim" quote really on the page?
  * numbers_in() / number_in_quote()
                       whole-number matching, so 7 never matches inside 76 and
                       72.5 never matches inside 2072.5
  * parse_json_reply() model reply -> dict, tolerant of ``` fences and prose
  * fence_for()        an unguessable-per-call fence tag for UNTRUSTED DATA blocks

The pattern these support: let the model *label and quote*, then let code decide.
A value survives only if its quote is on the page and its number is in its quote,
so validators compare a canonical record rather than model prose.
"""

# --- glkit:begin proof ---
import hashlib as _glk_hashlib
import json as _glk_json
import re as _glk_re
import unicodedata as _glk_unicodedata

GLK_MAX_URL_CHARS = 400
GLK_MAX_FETCH_BYTES = 3_000_000
GLK_MIN_RAW_TEXT = 400
GLK_UA = {"User-Agent": "Mozilla/5.0 (compatible; GenLayer-Intelligent-Contract; +https://genlayer.com)"}

_GLK_HOST_RE = _glk_re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
_GLK_NUM_RE = _glk_re.compile(r"(?<![\d.])(?<!\d,)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\d|[.,]\d)")
_GLK_DROP_RE = _glk_re.compile(r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1\s*>", _glk_re.S | _glk_re.I)
_GLK_TAG_RE = _glk_re.compile(r"<[^>]+>")
_GLK_ENT = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&#x27;": "'",
            "&ndash;": "-", "&mdash;": "-", "&rsquo;": "'", "&lsquo;": "'", "&ldquo;": '"', "&rdquo;": '"',
            "&percnt;": "%", "&euro;": "€", "&pound;": "£", "&dollar;": "$"}


class GlkInputError(ValueError):
    """Raised for bad caller input. Contracts usually convert it to gl.vm.UserError."""


def clean_text(raw) -> str:
    """NFKC, control characters to spaces, whitespace collapsed."""
    text = _glk_unicodedata.normalize("NFKC", str(raw))
    text = "".join(ch if _glk_unicodedata.category(ch)[0] != "C" else " " for ch in text)
    return _glk_re.sub(r"\s+", " ", text).strip()


def squash(raw) -> str:
    """Letters, digits and % only, casefolded: the form quotes are compared in."""
    t = _glk_unicodedata.normalize("NFKC", str(raw)).casefold()
    return "".join(ch for ch in t if ch.isalnum() or ch == "%")


def sha256_hex(s: str) -> str:
    return _glk_hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical_url(raw, max_chars: int = GLK_MAX_URL_CHARS) -> str:
    """https://host/path normal form. Rejects non-https, credentials, ports, IPs and
    private-looking hosts; drops the #fragment; lower-cases the host only."""
    if not isinstance(raw, str):
        raise GlkInputError("url must be text")
    url = raw.strip()
    if len(url) == 0 or len(url) > max_chars:
        raise GlkInputError(f"url must be 1..{max_chars} characters")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in url):
        raise GlkInputError("url must be printable ASCII without spaces")
    if url[:8].lower() != "https://":
        raise GlkInputError("url must use https://")
    rest = url[8:]
    cut = len(rest)
    for sep in "/?#":
        i = rest.find(sep)
        if 0 <= i < cut:
            cut = i
    host, tail = rest[:cut].lower(), rest[cut:]
    if "@" in host or ":" in host:
        raise GlkInputError("url must not carry credentials or a port")
    if _glk_re.fullmatch(r"[0-9.]+", host) or not _GLK_HOST_RE.fullmatch(host):
        raise GlkInputError("url host must be a public domain name")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
        raise GlkInputError("url host must be public")
    i = tail.find("#")
    if i >= 0:
        tail = tail[:i]
    return "https://" + host + (tail if tail else "/")


def html_text(html: str) -> str:
    """Visible-ish text of an HTML document: script/style/svg dropped, tags removed,
    common and numeric entities decoded, whitespace collapsed."""
    t = _GLK_DROP_RE.sub(" ", html)
    t = _GLK_TAG_RE.sub(" ", t)
    for k, v in _GLK_ENT.items():
        t = t.replace(k, v)
    t = _glk_re.sub(r"&#(\d{1,7});", lambda m: chr(int(m.group(1))) if int(m.group(1)) < 0x110000 else " ", t)
    t = _glk_re.sub(r"&#[xX]([0-9a-fA-F]{1,6});",
                    lambda m: chr(int(m.group(1), 16)) if int(m.group(1), 16) < 0x110000 else " ", t)
    return clean_text(t)


def _glk_header(headers, name: str) -> str:
    if not isinstance(headers, dict):
        return ""
    for key, v in headers.items():
        if str(key).lower() == name:
            return v.decode("utf-8", "replace") if isinstance(v, (bytes, bytearray)) else str(v)
    return ""


def fetch_page(url: str, web=None, max_bytes: int = GLK_MAX_FETCH_BYTES, min_raw: int = GLK_MIN_RAW_TEXT) -> str:
    """Page text, or "" if unreadable. NON-DETERMINISTIC: call it inside a
    leader/validator function. `web` defaults to gl.nondet.web in a contract.

    Raw HTML is reduced to text first, because text renders often drop the content
    of collapsed tabs and accordions (where rules and prices tend to live). Only a
    page whose raw text is shorter than `min_raw` (a JavaScript-only shell) is rendered."""
    if web is None:
        web = gl.nondet.web  # noqa: F821 - defined by the contract this is inlined into
    try:
        r = web.get(url, headers=GLK_UA)
    except Exception:
        return ""
    if not (200 <= int(r.status) < 300):
        return ""
    body = r.body or b""
    if len(body) > max_bytes:
        return ""
    ctype = _glk_header(r.headers, "content-type").lower()
    if "text/plain" in ctype:
        return clean_text(body.decode("utf-8", "replace"))
    if not (ctype == "" or "html" in ctype):
        return ""
    raw = html_text(body.decode("utf-8", "replace"))
    if len(raw) >= min_raw:
        return raw
    try:
        return clean_text(web.render(url, mode="text"))
    except Exception:
        return raw


def focus(text: str, subject: str, budget: int, max_mentions: int = 200) -> str:
    """Budget-sized slice around the subject mention holding the most digits (first
    wins a tie). Deterministic given the same text, so leader and validators show
    their models the same window. At most `max_mentions` mentions are scored, which
    bounds the cost on pages that repeat the subject in every nav link."""
    if len(text) <= budget:
        return text
    low, needle = text.casefold(), subject.casefold()
    best_start, best_score, i, seen = 0, -1, low.find(needle), 0
    while i >= 0 and seen < max_mentions:
        start = max(0, min(i - budget // 8, len(text) - budget))
        score = sum(1 for ch in low[start:start + budget] if ch.isdigit())
        if score > best_score:
            best_start, best_score = start, score
        seen += 1
        i = low.find(needle, i + 1)
    return text[best_start:best_start + budget]


def quote_on_page(quote: str, page_squashed: str, min_len: int = 4) -> bool:
    """True if the quote, compared in squashed form, appears on the (squashed) page.
    Whitespace, punctuation and case differences are forgiven; invented text is not."""
    q = squash(quote)
    return len(q) >= min_len and q in page_squashed


def numbers_in(text: str) -> list:
    """Every number printed in the text, as floats ("1,250.75" -> 1250.75)."""
    out = []
    for m in _GLK_NUM_RE.finditer(text):
        try:
            out.append(float(m.group(0).replace(",", "")))
        except Exception:
            pass
    return out


def number_in_quote(value, quote: str, scale: int = 1) -> bool:
    """True if `value` (an integer in units of 1/scale, e.g. cents with scale=100)
    is one of the whole numbers printed in the quote."""
    for x in numbers_in(quote):
        if scale == 1:
            if float(x) == int(x) and int(x) == int(value):
                return True
        elif int(round(x * scale)) == int(value) and abs(x * scale - int(value)) < 1e-6:
            return True
    return False


def parse_json_reply(raw):
    """Model reply -> dict. Accepts a dict, or text holding one JSON object (code
    fences and surrounding prose are ignored). Raises ValueError otherwise."""
    if isinstance(raw, dict):
        return raw
    s = str(raw).strip().replace("```json", "").replace("```", "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON object in the reply")
    out = _glk_json.loads(s[a:b + 1])
    if not isinstance(out, dict):
        raise ValueError("reply is not a JSON object")
    return out


def fence_for(*parts) -> str:
    """A 12-hex fence tag derived from the call's own inputs (pass e.g. the tx
    hash, the sender and a counter). Page text cannot predict it, so it cannot
    forge the end of an UNTRUSTED DATA block; leader and validators derive the same tag."""
    return sha256_hex("|".join(str(p) for p in parts))[:12]


def untrusted_block(label: str, text: str, fence: str) -> str:
    """Wrap untrusted text in a fenced block, neutralising look-alike fence markers."""
    body = str(text).replace("<<<", "< < <").replace(">>>", "> > >")
    return f"<<<{label}_{fence}>>>\n{body}\n<<<END_{label}_{fence}>>>"
# --- glkit:end proof ---
