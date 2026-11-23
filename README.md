# glkit: a toolkit for shipping GenLayer Intelligent Contracts that read the web

glkit is the toolkit I extracted from building GenLayer contracts that read live web pages and still have to reach validator consensus (PropCourt, PriceGuard, RuleReader), and from driving my contracts through live runs on studionet (including VERDICT's SettlementCourt). It covers two places where builders lose time:

1. **Inside the contract:** fetching a page, turning it into text, and checking that a model's "quote" is really on the page. Validators then agree on a canonical record instead of on model prose.
2. **Outside the contract:** deploying and driving a contract on studionet after the November 2026 **fee-aware ConsensusMain** change, which makes older scripts fail with a bare `Transaction failed`. glkit also records every transaction so a reviewer can check it.

```
pip install "genlayer-py>=0.19"
python -m glkit doctor              # is this machine ready for the fee-aware network?
python -m glkit bundle SRC OUT      # inline glkit.proof into a single-file contract
python -m glkit evidence RUN.json OUT.md [--refresh]   # reviewer-ready evidence page
```

Everything here is used for real. The example contract in [`examples/quote_check/`](examples/quote_check/) was bundled with `glkit bundle`, deployed with `glkit.LiveRun`, and its evidence page was rendered with `glkit evidence`: [examples/quote_check/LIVE_EVIDENCE.md](examples/quote_check/LIVE_EVIDENCE.md). VERDICT's SettlementCourt live evidence was rendered with the same tool: [verdict/docs/SETTLEMENT_LIVE_EVIDENCE.md](https://github.com/yoyoblair333-wq/verdict/blob/main/docs/SETTLEMENT_LIVE_EVIDENCE.md).

---

## 1. The fee-aware network change (read this if your deploys started failing)

Since the fee-aware ConsensusMain rollout, studionet **rejects any transaction that carries no fee distribution.** The consensus contract reverts with `FeesDistributionMissing`. genlayer-py before 0.19 does not send one, and it reports the revert only as:

```
genlayer_py.exceptions.GenLayerError: Transaction failed
```

genlayer-py 0.19 can send fees, but only if you pass `fees=`. If you ask for more time than the network allows, the revert is `PhaseTimeoutOutOfBounds(1500,30,600)`: leader and validator time-unit allocations must sit between **30 and 600**.

glkit handles all three cases:

```python
from genlayer_py import create_client
from genlayer_py.chains import studionet
import glkit

client = create_client(chain=studionet, account=my_account)
tx = client.write_contract(address=addr, function_name="check", args=[url, quote],
                           fees=glkit.fees_for(client, "llm"))   # estimated, in-bounds
```

- `fees_for(client, "base" | "llm")` builds an estimated fee distribution. The `llm` preset gives a leader and its validators the maximum in-bounds time for model calls.
- `clamp_timeunits(options)` keeps any custom allocation inside 30..600.
- `explain_send_error(e)` turns the bare SDK failure into one actionable sentence. `send()` retries transient RPC errors, but never retries a fee or bounds revert, because a retry cannot fix those.
- `summarize(tx)` reads both the old transaction shape (`status_name`) and the new one (`lifecycle.state/outcome`, `fee_value`). Old evidence scripts that index `status_name` print `None` on the new network.
- `doctor` checks all of this in one command, including the trap below.

**Keep direct-mode tests in a second environment.** `genlayer-test` 0.29 pins `genlayer-py < 0.17`. Next to 0.19 its pytest plugin fails to import (`cannot import name 'TransactionStatus'`), which breaks *every* pytest run in that environment, even tests that never touch it. Use one environment for live runs (genlayer-py >= 0.19) and one for direct-mode tests (genlayer-test 0.29). `glkit doctor` warns when both are installed together.

## 2. `glkit.LiveRun`: resumable, fee-aware live runs that a reviewer can check

```python
from glkit import LiveRun

run = LiveRun("docs/live/run.json", roles=["owner", "alice"]).connect()   # throwaway keys, funded once
court = run.deploy("deploy_court", "owner", "contracts/court.py", args=[...])
run.write("alice_opens_case", "alice", court, "open_case", [...], fee="llm")
run.note("case_1", run.read(court, "get_case", [1]))
run.write("appeal_after_final_must_fail", "alice", court, "appeal", [1])   # expected reverts are recorded too
run.finish()
```

- **Hash first, then wait.** Each transaction hash is written to the JSON file before waiting, so an interrupted run resumes and never sends a step twice. A step that was sent but not yet summarised is waited on, not re-sent.
- **Every value is chain data:** status, consensus result, leader execution result, the vote list, the first tagged contract error (`[EXPECTED]`, `[REJECTED]`, …) and the fee paid.
- Keys are throwaway, stored next to the run in a file you gitignore, and each role is funded exactly once.

`python -m glkit evidence docs/live/run.json docs/LIVE_EVIDENCE.md --refresh` re-reads every transaction (so "decided" becomes "finalized" once it is) and writes a Markdown page. The page has contract and transaction links to the explorer, vote counts, contract errors, and the state the run read back.

## 3. `glkit.proof`: web-evidence helpers for inside a contract

GenVM deploys one file, so `glkit.proof` is written to be **inlined**. In your contract source, write:

```python
from genlayer import *
from dataclasses import dataclass

# glkit:include proof
```

then `python -m glkit bundle contract.src.py contract.py`. The marker is replaced by the module's code between banners that carry its sha256, so a reviewer can check the inlined code against glkit. Bundling is deterministic and idempotent.

| Helper | What it does | Why it matters for consensus |
|---|---|---|
| `fetch_page(url)` | Reduces the raw HTML to text first. Renders only if the page is a JavaScript shell (< 400 chars of text). | Text renders often drop collapsed tabs and accordions, which is exactly where rules and prices live. Leader and validators then see different pages. |
| `html_text(html)` | Drops script, style, svg and noscript; removes tags; decodes named and numeric entities. | Script text never counts as page text. |
| `canonical_url(url)` | https only; no credentials, ports, IPs or private hosts; drops `#fragment`. | Everyone fetches the same URL, and a contract cannot be pointed at internal hosts. |
| `focus(text, subject, budget)` | A deterministic budget-sized window around the subject, choosing the most digit-dense mention. | Leader and validators show their models the same slice of a long page. |
| `quote_on_page(quote, squash(page))` | Compares in squashed form (casefolded alphanumerics and %). | Forgives whitespace and punctuation, never invented text. |
| `number_in_quote(value, quote, scale)` | Whole-number matching only. | 7 never matches inside 76, and 72.5 never matches inside 2072.5 (both real bugs I hit). |
| `parse_json_reply(raw)` | Pulls one JSON object out of a reply with code fences or prose around it. | Models wrap JSON. Text-mode replies also avoid the float/calldata problem of `response_format="json"`. |
| `fence_for(...)` + `untrusted_block(...)` | A per-call fence tag derived from the call's own inputs, plus a block wrapper that neutralises look-alike markers. | Page text cannot forge the end of an UNTRUSTED DATA block, and the leader and validators derive the same tag. |

The pattern these support: **the model labels and quotes, the code decides.** A value survives only if its quote is on the page and its number is in its quote, and validators compare that canonical record exactly.

## The example: QuoteCheck

[`examples/quote_check/quote_check.src.py`](examples/quote_check/quote_check.src.py) (source) → [`quote_check.py`](examples/quote_check/quote_check.py) (bundled, deployable, `genvm-lint` clean). "Does this public page really say this?" Each validator fetches the page itself and the contract records FOUND / NOT_FOUND / UNREADABLE. No model is asked anything, so agreement is exact or the transaction fails.

Live on studionet ([evidence](examples/quote_check/LIVE_EVIDENCE.md)): a real quote on the IRS standard-mileage-rates page → `FOUND`; an invented quote on the same page → `NOT_FOUND`; an `http://` URL → reverted `[EXPECTED] url must use https://`. All finalized with majority agreement.

## Tests

```
# environment 1 (direct-mode tests):  pip install genlayer-test==0.29.2 pytest
python -m pytest -q tests          # 69 tests: proof, bundle, chain, evidence, and the
                                   # bundled example under the real GenVM v0.2.16 SDK
# environment 2 (live):               pip install "genlayer-py>=0.19"
python -m glkit doctor
python examples/quote_check/live_run.py
```

Direct-mode tests include a validator replay with a *different* page (`run_validator()` must return False), which is the consensus property that matters.

## Using it in your project

Copy the `glkit/` folder into your repo (it has no dependencies beyond genlayer-py for the live parts), or add this repository as a git submodule. MIT licensed.

If you're new to GenLayer and this saved you time, you can join the builder program through my referral link: [portal.genlayer.foundation/?ref=JTR01FHP](https://portal.genlayer.foundation/?ref=JTR01FHP).
