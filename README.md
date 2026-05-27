# AIBTC Stacks Sybil Scorer

Open-source, explainable sybil-likelihood scoring for Stacks/AIBTC agent
addresses.

This tool is built for AIBTC bounty `mplaqh8w60b5b1a6146f`. It takes one or
more Stacks addresses and returns a 0-100 sybil-likelihood score with the top
signals that drove the result. It uses public APIs only and has no model or
private-data dependency.

## Signals

The scorer combines these public signals:

- wallet age and first seen block time from Hiro transaction history
- transaction count, contract diversity, and counterparty diversity
- likely first funding source and shared funding source inside a scored batch
- AIBTC registration level, BTC link, verified time, and last active time
- Agent Identity v2 NFT / ERC-8004 identity evidence when visible
- AIBTC inbox sent/received counts and paid inbox economics
- BTC anchor activity for the linked Bitcoin address
- optional seed-cluster distance/overlap

Scores are explainable. Every output includes each signal, its points, the max
points, and a short reason.

## Install

Python 3.10+ is enough. No third-party packages are required.

```bash
python -m stacks_sybil_scorer.cli --demo --pretty
```

Score live addresses:

```bash
python -m stacks_sybil_scorer.cli SP20GPDS5RYB2DV03KG4W08EG6HD11KYPK6FQJE1 --pretty
```

Use seed addresses for known clusters:

```bash
python -m stacks_sybil_scorer.cli SP... SP... --seed SPSUSPECT... --pretty
```

Write JSON output:

```bash
python -m stacks_sybil_scorer.cli SP... --output result.json
```

## Public APIs

- Hiro: address balances, transactions, NFT holdings
- AIBTC: `/api/agents`, `/api/verify/{btc}`, `/api/inbox/{btc}`
- mempool.space: BTC address stats when an AIBTC BTC address is linked

The verifier degrades gracefully if one endpoint is temporarily unavailable:
the error is included in the output and the rest of the public signals still
score.

## Labels

- `likely_clean`: score below 35
- `watchlist`: score 35-64
- `high_sybil_risk`: score 65+

The thresholds are intentionally conservative. A high score means "needs human
review or cluster investigation," not proof of wrongdoing.

## Validation

```bash
python -m unittest discover -s tests -v
python -m stacks_sybil_scorer.cli --demo --pretty
python -m py_compile stacks_sybil_scorer/*.py tests/*.py
```

The bundled tests cover clean/risky fixture classification, JSON
explainability, shared funding-source clustering, seed-cluster overlap, and
registry-wide verification-batch timing.

## Cost

Normal use costs 0 sats. Live scoring uses read-only public HTTP APIs. The demo
fixture mode uses no network calls. Typical wall-clock time depends on public
API latency and the number of addresses; single-address scoring is usually a
few seconds or less.
