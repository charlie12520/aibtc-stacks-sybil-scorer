# AIBTC B8 Submission

Bounty: `mplaqh8w60b5b1a6146f`

Public repo: https://github.com/charlie12520/aibtc-stacks-sybil-scorer

## Deliverable

This repo contains a Python standard-library CLI that scores one or more Stacks
addresses for sybil-cluster likelihood from public signals only.

## Acceptance Criteria Mapping

- Takes one or more STX addresses:
  `python -m stacks_sybil_scorer.cli SP... SP... --pretty`
- Pulls public signals:
  Hiro balances/transactions/NFT holdings, AIBTC agents/verify/inbox, and
  mempool.space BTC address stats.
- Outputs structured scores:
  JSON contains score, label, top 3 signals, all signal reasons, facts, and
  endpoint errors.
- Seed cluster support:
  `--seed` and `--seed-file` adjust scores based on shared funders,
  counterparties, contracts, and linked identities.
- Explainability:
  every signal has points, max_points, and a natural-language reason.
- License:
  MIT.

## Validation

Commands:

```bash
python -m unittest discover -s tests -v
python -m stacks_sybil_scorer.cli --demo --pretty
python -m py_compile stacks_sybil_scorer/*.py tests/*.py
```

Expected:

- Unit tests pass. Current local run: 7 tests passed.
- Demo returns two likely-clean fixtures and two high-risk/watchlist fixtures.
- No private data, API keys, paid endpoints, or black-box ML.
- Live smoke: a new Level 1 agent with no chain activity scores high risk, while
  an established Genesis-level address scores likely clean.

Update after first submission: added Agent Identity v2 NFT mint-block batch
timing as an explicit signal and test case.

## Trust Model

The scorer trusts public read-only APIs to mirror chain/platform state:

- Hiro for Stacks chain data.
- AIBTC for agent registry and inbox counts.
- mempool.space for linked BTC address stats.

The score is a heuristic triage tool, not a final accusation. It is designed to
help a bounty poster decide which addresses need deeper manual review.
