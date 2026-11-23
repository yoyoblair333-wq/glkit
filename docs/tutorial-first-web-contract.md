# Tutorial: your first GenLayer contract that reads the web and still reaches consensus

**Time:** about an hour. **You'll build:** QuoteCheck, a contract that answers "does this public page really say this?". You'll test it with the real GenVM SDK, deploy it to studionet with fees, and get a reviewer-ready evidence page.
**You need:** Python 3.11+, a terminal, and nothing else. Studionet test GEN is free.

Every step below was run for real. The finished contract and its live evidence are in [`examples/quote_check/`](../examples/quote_check/).

---

## Step 0: the one idea that makes web contracts work

On GenLayer, a write that touches the outside world runs on a **leader** and then on several **validators**, and each one does the work again on its own. The transaction stands only if the validators accept the leader's result.

So the question to design around is: **what exactly will two independent machines compare?**

- If they compare a model's prose, they will almost never match.
- If they compare raw page text, a timestamp or an ad rotating on the page breaks the match.
- If they compare **a small, canonical record computed by code from what each one saw**, they match whenever the facts match.

QuoteCheck compares one word: `FOUND`, `NOT_FOUND` or `UNREADABLE`. Keep that pattern in mind: **fetch, reduce to a canonical record, compare exactly.**

## Step 1: two Python environments (this saves an afternoon)

```bash
python -m venv .venv-test && .venv-test/bin/pip install genlayer-test==0.29.2 pytest genvm-linter==0.11.0
python -m venv .venv-live && .venv-live/bin/pip install "genlayer-py>=0.19"
```

Why two? Since November 2026 studionet only accepts transactions that carry a fee distribution, which needs genlayer-py 0.19 or newer. The direct-mode test runner, genlayer-test 0.29, pins genlayer-py below 0.17. Install both in one environment and every `pytest` run fails at import time, even tests that never touch the network.

Get glkit:

```bash
git clone https://github.com/yoyoblair333-wq/glkit && cd glkit
.venv-live/bin/python -m glkit doctor
```

`doctor` checks your SDK version, reaches studionet, reads the live fee policy, and warns if the two packages are mixed.

## Step 2: write the contract source

Create `quote_check.src.py`:

```python
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass

# glkit:include proof
```

The first line pins the GenVM SDK. **It must be the first line of the file.** The include marker is where `glkit bundle` will paste the web helpers, because GenVM deploys a single file and cannot import your other modules.

Now the core of the contract, the `check` method:

```python
    @gl.public.write
    def check(self, url: str, quote: str) -> dict:
        try:
            u = canonical_url(url)              # https only, public host, no #fragment
        except GlkInputError as e:
            _fail(str(e)); raise
        q = clean_text(quote)

        def leader_fn() -> dict:
            text = fetch_page(u)                # raw HTML -> text; render only for JS shells
            if text == "":
                return {"status": "UNREADABLE", "size": "empty"}
            found = quote_on_page(q, squash(text))
            return {"status": "FOUND" if found else "NOT_FOUND", "size": _bucket(len(text))}

        def validator_fn(leader_res) -> bool:
            if not isinstance(leader_res, gl.vm.Return):
                return False
            return leader_res.calldata == leader_fn()      # EXACT equality on the canonical record

        res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        ...  # store and return res
```

Three choices in this code matter:

1. **`fetch_page` reads the raw HTML first.** A text render often drops collapsed tabs and accordions, which is exactly where fees, limits and rules live. If the leader renders and a validator doesn't, they see different pages.
2. **`squash()` compares quotes on letters, digits and % only.** "Max daily loss: 5 %" and "max daily loss 5%" match, and an invented sentence never does.
3. **`_bucket(len(text))` stores the page size as small/medium/large, not as an exact number.** Two fetches a second apart can differ by a few bytes, and an exact length would make honest validators disagree.

Bundle it, then lint it:

```bash
python -m glkit bundle quote_check.src.py quote_check.py
genvm-lint check quote_check.py
```

## Step 3: test it like a validator would

Direct mode runs the real GenVM SDK in-process and lets you mock the web:

```python
def page(vm, body):
    vm.mock_web(r"^https://rules\.example\.org/payouts$", {"method": "GET", "response": {
        "status": 200, "headers": {"content-type": b"text/html"}, "body": body.encode()}})

def test_found_in_collapsed_section(qc, direct_vm):
    page(direct_vm, '<div hidden><p>Payouts are processed within 14 calendar days.</p></div>' + '<p>General terms.</p>' * 40)
    assert qc.check(URL, "processed within 14 calendar days")["status"] == "FOUND"

def test_validator_disagrees_when_its_page_says_otherwise(qc, direct_vm):
    page(direct_vm, PAGE)
    qc.check(URL, "processed within 14 calendar days")
    direct_vm.clear_mocks()
    page(direct_vm, PAGE.replace("14 calendar days", "30 calendar days"))
    assert direct_vm.run_validator() is False
```

The second test is the most important test you will write. `run_validator()` replays the validator with whatever the mocks say **now**, so you can prove that a validator who saw a different page refuses the leader. Also test the opposite: a validator who saw the same page must return `True`.

```bash
.venv-test/bin/python -m pytest -q tests
```

## Step 4: deploy and run it live, with fees

```python
from glkit import LiveRun

run = LiveRun("live/run.json", roles=["owner", "caller"]).connect()       # throwaway keys, funded once
qc = run.deploy("deploy_quote_check", "owner", "quote_check.py")
run.write("check_real_quote", "caller", qc, "check",
          ["https://www.irs.gov/tax-professionals/standard-mileage-rates", "standard mileage rates"], fee="llm")
run.write("check_invented_quote", "caller", qc, "check",
          ["https://www.irs.gov/tax-professionals/standard-mileage-rates", "standard mileage rates are abolished"], fee="llm")
run.write("check_bad_url_must_revert", "caller", qc, "check", ["http://www.irs.gov/", "standard mileage rates"])
run.note("check_1", run.read(qc, "get_check", [1]))
run.finish()
```

Three things happen that you would otherwise write by hand:

- **Fees.** Every write carries an estimated fee distribution. The `llm` preset asks for the maximum time the network allows: time units must stay between 30 and 600, or the transaction reverts with `PhaseTimeoutOutOfBounds`.
- **Resumability.** Each hash is saved before the script waits. Kill the script and run it again, and it picks up where it stopped without sending anything twice.
- **Honest records.** Status, consensus result, leader execution result, votes and the contract's own error message all come from the chain. Expected reverts are recorded too. A run that only shows successes is weaker evidence.

## Step 5: give reviewers something they can check

```bash
python -m glkit evidence live/run.json LIVE_EVIDENCE.md --refresh --title "QuoteCheck live evidence"
```

`--refresh` re-reads every transaction, so the page shows `finalized/accepted` once finality is reached. The page links every contract and transaction to the explorer. [Here is the real one](../examples/quote_check/LIVE_EVIDENCE.md): a real quote returned `FOUND`, an invented quote returned `NOT_FOUND`, and an `http://` URL reverted with `[EXPECTED] url must use https://`. All four transactions were finalized with majority agreement.

## Where to go next

- **Read a number, not just a quote.** RuleReader extends this pattern: the model returns `{value, quote}` per field, and code keeps a value only if the quote is on the page **and** the number is a whole number inside the quote. `glkit.proof.number_in_quote` does this, so 7 never matches inside 76.
- **Let a jury label, let code decide.** VERDICT's SettlementCourt has jurors label each promised deliverable kept/broken/disputed, then derives the ruling in code from the per-deliverable majority. Validators agree on the derivation, not on wording.
- **Prove identity without a model.** DomainProof verifies that a wallet controls a website using an exact line in a `/.well-known/` file. It shows that some of the most useful web contracts need no model at all.

If this helped you ship your first contract, you can join the GenLayer builder program through my referral link: [portal.genlayer.foundation/?ref=JTR01FHP](https://portal.genlayer.foundation/?ref=JTR01FHP).
