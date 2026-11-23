# Field notes: what makes web-reading Intelligent Contracts reach consensus

*Evidence from live studionet runs of six GenLayer contracts (PropCourt, PriceGuard, RuleReader, VERDICT SettlementCourt + ReputationLedger, QuoteCheck, DomainProof), November 2026.*

GenLayer's promise is that a contract can read the open web and use model judgement, and that independent validators will still agree on the result. Builders learn quickly that this is not automatic. Whether validators agree depends almost entirely on **what you ask them to compare.** These notes collect the measured outcomes of my own live runs, the failures I hit on the way (with the evidence), and the design rules that came out of them.

All numbers come from the live-run JSON files in each repository, which record what the chain returned. The table is produced by [`tally.py`](tally.py), so anyone can recompute it.

## 1. The dataset

| Contract | What validators compare | Model calls? | Live record |
|---|---|---|---|
| PropCourt | per-rule numbers read from a prop firm's own rules page (kept only if the quote is on the page and the number is in the quote) + a conduct label | yes | [run.json](https://github.com/yoyoblair333-wq/propcourt/blob/main/docs/live/run.json) |
| PriceGuard | the price read from a retailer page, as integer cents, with an anchored quote | yes | [run.json](https://github.com/yoyoblair333-wq/priceguard/blob/main/docs/live/run.json) |
| RuleReader | a typed record `{status, values}` of up to 6 fields read from any page | yes | [run.json](https://github.com/yoyoblair333-wq/rulereader/blob/main/docs/live/run.json) |
| SettlementCourt (VERDICT) | per-deliverable kept/broken/disputed labels → a ruling derived in code; panels of 3, 5, 7 | yes | [settlement-run.json](https://github.com/yoyoblair333-wq/verdict/blob/main/docs/live/settlement-run.json) |
| QuoteCheck (glkit example) | one word: FOUND / NOT_FOUND / UNREADABLE | no | [run.json](https://github.com/yoyoblair333-wq/glkit/blob/main/examples/quote_check/live/run.json) |
| DomainProof | one outcome code from fetching `/.well-known/genlayer-proof.txt` | no | [run.json](https://github.com/yoyoblair333-wq/domainproof/blob/main/docs/live/run.json) |

## 2. Results

| Run | txs | majority_agree | finalized | exec_error | vote_agree | vote_disagree | vote_timeout | vote_idle |
|---|---|---|---|---|---|---|---|---|
| propcourt | 24 | 24 | 24 | 0 | 85 | 0 | 0 | 35 |
| priceguard | 16 | 16 | 15 | 0 | 52 | 0 | 0 | 28 |
| rulereader | 6 | 6 | 6 | 0 | 18 | 1 | 0 | 11 |
| verdict (SettlementCourt + ReputationLedger) | 19 | 19 | 19 | 2 | 67 | 0 | 2 | 26 |
| glkit (QuoteCheck) | 4 | 4 | 4 | 1 | 13 | 0 | 0 | 7 |
| domainproof | 10 | 10 | 10 | 1 | 37 | 0 | 0 | 13 |
| **total** | 79 | 79 | 78 | 4 | 272 | 1 | 2 | 120 |

`finalized` counts the status stored in each run file at its last refresh. One PriceGuard transaction was still recorded as decided when that file was last written.

How to read the vote columns: studionet seats five validators per round. `agree` and `disagree` are validators that compared their own result with the leader's. `idle` validators did not take part in that round. A `timeout` validator did not finish in its allotted time.

**Finding 1: when the compared record is canonical, disagreement is rare.** Every transaction reached `MAJORITY_AGREE`. Across all agree/disagree votes cast, exactly **one** validator disagreed. That was on RuleReader's first read of the IRS mileage-rate page, and the round still reached a majority. That page lists three periods (Jan–Jun, Jul–Dec, prior year) with overlapping numbers. A subject-scoped read of a multi-period page is the hardest case in the set, so the single disagreement landing there is consistent with the design and is not noise.

**Finding 2: expected reverts reach consensus too.** The rows with `exec_error` are deliberate adversarial calls: an unredacted case refused before any model call, an appeal after a case was final, an `http://` URL, and a URL passed where a bare domain was required. Validators agreed that each one should fail. A run that records only successes is weaker evidence than one that shows the contract refusing what it should refuse.

**Finding 3: bigger model panels run into time limits first.** Both `timeout` votes in the dataset are on SettlementCourt's appeal transactions: the 5-juror Tier 2 of case 1 and the 7-juror Tier 3 of case 4. Each validator runs one model pass per juror, so runtime grows with the panel size. The rounds still reached a majority, but this is the first place a builder will see `UNDETERMINED` if they under-allocate time. Since the November 2026 fee change, the allocation is explicit: leader and validator time units must sit in 30..600 (`PhaseTimeoutOutOfBounds(v,30,600)` otherwise). Panel-style contracts should request the maximum.

## 3. Failures I hit, and what fixed them

Each of these cost real time, and each is now a rule in glkit.

| # | Failure | Evidence | Fix |
|---|---|---|---|
| 1 | **A text render drops collapsed tabs.** A prop firm's rules sat in collapsed product tabs. The rendered text the model saw did not contain them, so "not stated" looked like a valid reading. | PropCourt README, "how the page is read" | Reduce **raw HTML** to text first (scripts and styles dropped); render only when the raw text is under 400 chars (a JavaScript shell). `glkit.proof.fetch_page` |
| 2 | **Substring number matching.** Checking that a value appears "in the quote" by substring accepted 7 inside 76 and 72.5 inside 2072.5. | RuleReader tests | Match **whole numbers** parsed from the quote, with thousands separators and decimals handled. `glkit.proof.number_in_quote` |
| 3 | **Floats in calldata.** A leader result carrying airport coordinates as floats ended `UNDETERMINED`: GenVM calldata has no float type (`not calldata encodable 40.6398: float`). | [DelayProof run-0](https://github.com/yoyoblair333-wq/delayproof/blob/main/docs/live/run-0-float-bug.json) | Store **integers in fixed units** (basis points, cents), or take deterministic fields from a table inside the contract. Ask the model for text and parse it, rather than using `response_format="json"`, which can hand back floats. |
| 4 | **Tolerance-based validation that stores the leader's exact value.** A price oracle accepted a leader price within 25 bp but stored the leader's exact number, so two accepted values could flip a downstream threshold decision. | GenLayer steward review of PythReader (rejected): *"Two accepted values can therefore produce opposite downstream threshold decisions."* | If the validator accepts a range, store **the decision the range supports** (or a value rounded so every accepted input maps to the same stored output), never the leader's raw value. |
| 5 | **The network changed under the scripts.** After the fee-aware ConsensusMain rollout, every deploy failed with a bare `Transaction failed` (underneath: `FeesDistributionMissing`). Over-large time allocations reverted with `PhaseTimeoutOutOfBounds`. Status fields moved from `status_name` to `lifecycle`. | Live runs on 2026-11-23 | genlayer-py ≥ 0.19 with an estimated, in-bounds `fees=`. Read both transaction shapes. Keep genlayer-test in its own environment because it pins genlayer-py < 0.17. `glkit.chain`, `glkit doctor` |
| 6 | **"The address is on the page" as proof of ownership.** A credit protocol let a borrower establish control of a business page because the page displayed the borrower's address. | GenLayer steward review of Credence (rejected): *"borrower-controlled pages can establish ownership merely by displaying an address"* | Prove control with a **contract-issued nonce at a fixed operator-only path** (`/.well-known/`), exact line match, expiry, and anyone-can-recheck revocation. That is DomainProof. |

## 4. Design rules

1. **Decide what validators compare before writing any prompt.** It should be small, typed and canonical: an enum, integers in fixed units, or a derived ruling. Never prose.
2. **Let the model label and quote; let code decide.** Keep a model's value only if its quote is on the validator's *own* copy of the page and its number is a whole number inside the quote.
3. **Derive outcomes in code from per-item labels** (SettlementCourt's kept/broken → ruling). Validators then agree on the derivation even when their models word things differently.
4. **Bucket anything that drifts between fetches** (page length, counts that tick) or leave it out of the compared record.
5. **Prefer no model at all when an exact rule exists.** QuoteCheck and DomainProof call no model, which gives them the strongest agreement profile in the dataset.
6. **Test the disagreement path.** In direct mode, change the mocked page and assert `run_validator()` is `False`. Then assert it is `True` when the page is the same, so you know your validator is not simply strict.
7. **Record refusals live.** Include at least one expected revert in every live run.
8. **Give panel-style contracts the maximum time allocation**, and expect the larger tiers to be the first to time out.

## 5. Limits of this study

- 79 transactions across six contracts is a field report, not a benchmark. Most of my inputs were chosen to be clear-cut, and the single disagreement shows where harder inputs live: multi-period, multi-product pages.
- Studionet validators are a test network. Model mix, timeouts and fee levels on a production network may differ.
- Idle and timeout counts depend on network load at the time of each run.

*Data and tally script: this folder. Tooling: [glkit](https://github.com/yoyoblair333-wq/glkit). Building on GenLayer yourself? [Join the builder program](https://portal.genlayer.foundation/?ref=JTR01FHP).*
