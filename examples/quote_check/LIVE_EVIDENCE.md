# QuoteCheck live evidence (studionet)

Rendered by `glkit evidence` from the live-run JSON, which the run script wrote from chain data. Test-network GEN has no value; all keys are throwaway test keys.

Network: Genlayer Studio Network

## Contracts

| Deploy step | Address |
|---|---|
| deploy_quote_check | [`0xF1897A04534abC8a46b4bc896E86377A413D55f9`](https://explorer-studio.genlayer.com/address/0xF1897A04534abC8a46b4bc896E86377A413D55f9) |

## Roles (throwaway keys)

| Role | Address |
|---|---|
| owner | `0x75a35a832fD2f77Def8Ae3259814B7252431f4b7` |
| caller | `0xa73a56482D02fE8Ca708724B29b18290e8e866c0` |

## Transactions

| # | Step | Tx | Status | Consensus | Leader execution | Votes | Contract error |
|---|---|---|---|---|---|---|---|
| 1 | deploy_quote_check | [`0xeffe2235…3789ec`](https://explorer-studio.genlayer.com/tx/0xeffe223553f80fc67704c08369ebd86659bfd9c4227c8102fed7a450a43789ec) | finalized/accepted | MAJORITY_AGREE | SUCCESS | agree 3, idle 2 |  |
| 2 | check_real_quote | [`0x6bcb7a48…5fbe5c`](https://explorer-studio.genlayer.com/tx/0x6bcb7a482eb45731b98936f482e778dcd3dfb073e522c45cbea60cc93f5fbe5c) | finalized/accepted | MAJORITY_AGREE | SUCCESS | agree 3, idle 2 |  |
| 3 | check_invented_quote | [`0x6ace1947…93735d`](https://explorer-studio.genlayer.com/tx/0x6ace1947c3054936c6c30a7976ea5d9dd5c8b22fe891c4c4ff76e2fe1c93735d) | finalized/accepted | MAJORITY_AGREE | SUCCESS | agree 3, idle 2 |  |
| 4 | check_bad_url_must_revert | [`0xe2350766…e8e4c0`](https://explorer-studio.genlayer.com/tx/0xe23507669819c13fc61c7f0d8656509f991bbeff1cbc6ff0f0b51deeabe8e4c0) | finalized/accepted | MAJORITY_AGREE | ERROR | agree 4, idle 1 | [EXPECTED] url must use https:// |

## State read back from the contracts

### check_1

```json
{
 "checked_by": "0xa73a56482D02fE8Ca708724B29b18290e8e866c0",
 "id": 1,
 "page_size": "medium",
 "quote": "standard mileage rates",
 "status": "FOUND",
 "url": "https://www.irs.gov/tax-professionals/standard-mileage-rates"
}
```

### check_2

```json
{
 "checked_by": "0xa73a56482D02fE8Ca708724B29b18290e8e866c0",
 "id": 2,
 "page_size": "medium",
 "quote": "standard mileage rates are abolished",
 "status": "NOT_FOUND",
 "url": "https://www.irs.gov/tax-professionals/standard-mileage-rates"
}
```

### count

```json
2
```

Run finished at 2026-11-23T18:54:49Z.
