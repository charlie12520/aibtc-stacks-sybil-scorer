from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HIRO_BASE = "https://api.hiro.so"
AIBTC_BASE = "https://aibtc.com"
MEMPOOL_BASE = "https://mempool.space"
IDENTITY_REGISTRY = "SP1NMR7MY0TJ1QA7WQBZ6504KC79PZNTRQH4YGFJD.identity-registry-v2"


@dataclass(frozen=True)
class Signal:
    name: str
    points: float
    max_points: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": round(self.points, 2),
            "max_points": self.max_points,
            "reason": self.reason,
        }


class PublicApiClient:
    def __init__(self, timeout: float = 15.0, cache_dir: str | None = None) -> None:
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, url: str) -> tuple[dict[str, Any], str | None]:
        cache_path = self._cache_path(url)
        if cache_path and cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8")), None
            except json.JSONDecodeError:
                pass

        request = urllib.request.Request(url, headers={"User-Agent": "aibtc-stacks-sybil-scorer/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
            if cache_path:
                cache_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            return data, None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            return {}, f"{url}: {exc}"

    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        safe = urllib.parse.quote(url, safe="")
        return self.cache_dir / f"{safe}.json"


def score_addresses(
    addresses: list[str],
    *,
    seeds: list[str] | None = None,
    offline_facts: list[dict[str, Any]] | None = None,
    cache_dir: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    if not addresses and offline_facts is None:
        raise ValueError("provide at least one STX address or offline_facts")

    now = now or dt.datetime.now(dt.timezone.utc)
    seeds = [normalize_address(seed) for seed in (seeds or [])]

    if offline_facts is not None:
        facts = [dict(item) for item in offline_facts]
        cohort_facts = facts
        registry_agents: list[dict[str, Any]] = []
        seed_errors: list[str] = []
    else:
        client = PublicApiClient(cache_dir=cache_dir)
        agent_index, agent_errors = fetch_agent_index(client)
        registry_agents = list(agent_index.values())
        facts = [collect_facts(normalize_address(address), client, agent_index) for address in addresses]
        for fact in facts:
            fact.setdefault("errors", []).extend(agent_errors)
        scored = {fact.get("address") for fact in facts}
        seed_facts = [
            collect_facts(seed, client, agent_index)
            for seed in seeds
            if seed not in scored
        ]
        cohort_facts = facts + seed_facts
        seed_errors = [
            error
            for fact in seed_facts
            for error in fact.get("errors", [])
        ]

    cohort = build_cohort(cohort_facts, seeds, registry_agents=registry_agents)
    results = [score_one(fact, cohort, now) for fact in facts]

    return {
        "generated_at": now.isoformat(),
        "address_count": len(results),
        "seed_count": len(seeds),
        "seed_errors": seed_errors,
        "results": results,
    }


def collect_facts(address: str, client: PublicApiClient, agent_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    facts: dict[str, Any] = {
        "address": address,
        "contracts": [],
        "counterparties": [],
        "funding_source": None,
        "stx_balance_micro": 0,
        "ft_count": 0,
        "nft_identity": False,
        "agent": agent_index.get(address),
        "verify": {},
        "inbox": {},
        "btc": {},
        "errors": errors,
    }

    balances, error = client.get_json(f"{HIRO_BASE}/extended/v1/address/{address}/balances")
    if error:
        errors.append(error)
    else:
        facts["stx_balance_micro"] = int(balances.get("stx", {}).get("balance") or 0)
        facts["ft_count"] = len(balances.get("fungible_tokens", {}) or {})

    txs = fetch_transactions(address, client, errors)
    facts["tx_total"] = txs.get("total", 0)
    facts["first_seen_at"] = txs.get("first_seen_at")
    facts["contracts"] = sorted(txs.get("contracts", []))
    facts["counterparties"] = sorted(txs.get("counterparties", []))
    facts["funding_source"] = txs.get("funding_source")

    nft_holdings, error = client.get_json(
        f"{HIRO_BASE}/extended/v1/tokens/nft/holdings?principal={address}&limit=50"
    )
    if error:
        errors.append(error)
    else:
        facts["nft_identity"] = any(
            IDENTITY_REGISTRY in str(item.get("asset_identifier", ""))
            for item in nft_holdings.get("results", [])
        )

    agent = facts.get("agent") or {}
    btc_address = agent.get("btcAddress")
    if btc_address:
        verify, error = client.get_json(f"{AIBTC_BASE}/api/verify/{btc_address}")
        if error:
            errors.append(error)
        else:
            facts["verify"] = {
                "registered": bool(verify.get("registered")),
                "addressType": verify.get("addressType"),
                "level": verify.get("level"),
                "levelName": verify.get("levelName"),
            }

        inbox, error = client.get_json(f"{AIBTC_BASE}/api/inbox/{btc_address}")
        if error:
            errors.append(error)
        else:
            inbox_data = inbox.get("inbox", {})
            economics = inbox_data.get("economics", {})
            facts["inbox"] = {
                "totalCount": int(inbox_data.get("totalCount") or 0),
                "sentCount": int(inbox_data.get("sentCount") or 0),
                "receivedCount": int(inbox_data.get("receivedCount") or 0),
                "satsNet": int(economics.get("satsNet") or 0),
            }

        btc, error = client.get_json(f"{MEMPOOL_BASE}/api/address/{btc_address}")
        if error:
            errors.append(error)
        else:
            chain = btc.get("chain_stats", {})
            mempool = btc.get("mempool_stats", {})
            facts["btc"] = {
                "tx_count": int(chain.get("tx_count") or 0) + int(mempool.get("tx_count") or 0),
                "funded_txo_count": int(chain.get("funded_txo_count") or 0)
                + int(mempool.get("funded_txo_count") or 0),
            }

    return facts


def fetch_agent_index(client: PublicApiClient, limit: int = 200) -> tuple[dict[str, dict[str, Any]], list[str]]:
    agents: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    offset = 0
    while True:
        url = f"{AIBTC_BASE}/api/agents?limit={limit}&offset={offset}"
        data, error = client.get_json(url)
        if error:
            errors.append(error)
            break
        for agent in data.get("agents", []):
            stx = agent.get("stxAddress")
            if isinstance(stx, str):
                agents[normalize_address(stx)] = agent
        pagination = data.get("pagination", {})
        if not pagination.get("hasMore"):
            break
        offset += int(pagination.get("limit") or limit)
        if offset >= 2000:
            errors.append("agent index stopped at 2000 records to avoid runaway pagination")
            break
    return agents, errors


def fetch_transactions(address: str, client: PublicApiClient, errors: list[str]) -> dict[str, Any]:
    first_page, error = client.get_json(f"{HIRO_BASE}/extended/v1/address/{address}/transactions?limit=50&offset=0")
    if error:
        errors.append(error)
        return {"total": 0, "contracts": set(), "counterparties": set(), "funding_source": None}

    total = int(first_page.get("total") or 0)
    pages = [first_page]
    if total > 50:
        last_offset = max(total - 50, 0)
        last_page, error = client.get_json(
            f"{HIRO_BASE}/extended/v1/address/{address}/transactions?limit=50&offset={last_offset}"
        )
        if error:
            errors.append(error)
        else:
            pages.append(last_page)

    txs = [tx for page in pages for tx in page.get("results", [])]
    first_seen_at = oldest_time(txs)
    contracts: set[str] = set()
    counterparties: set[str] = set()
    inbound_candidates: list[tuple[str, str]] = []

    for tx in txs:
        sender = tx.get("sender_address")
        if isinstance(sender, str) and sender != address:
            counterparties.add(sender)
        call = tx.get("contract_call") or {}
        contract_id = call.get("contract_id")
        if isinstance(contract_id, str):
            contracts.add(contract_id)
        for arg in call.get("function_args", []) or []:
            repr_value = str(arg.get("repr", "")).lstrip("'")
            if repr_value.startswith("SP") and repr_value != address:
                counterparties.add(repr_value)
        if is_incoming_transfer(tx, address):
            if isinstance(sender, str):
                inbound_candidates.append((str(tx.get("block_time_iso") or ""), sender))

    inbound_candidates.sort(key=lambda item: item[0])
    funding_source = inbound_candidates[0][1] if inbound_candidates else None
    return {
        "total": total,
        "first_seen_at": first_seen_at,
        "contracts": contracts,
        "counterparties": counterparties,
        "funding_source": funding_source,
    }


def is_incoming_transfer(tx: dict[str, Any], address: str) -> bool:
    if tx.get("tx_type") == "token_transfer":
        token_transfer = tx.get("token_transfer") or {}
        return token_transfer.get("recipient_address") == address

    call = tx.get("contract_call") or {}
    if call.get("function_name") != "transfer":
        return False
    for arg in call.get("function_args", []) or []:
        if arg.get("name") == "recipient" and str(arg.get("repr", "")).lstrip("'") == address:
            return True
    return False


def build_cohort(
    facts: list[dict[str, Any]],
    seeds: list[str],
    *,
    registry_agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    funding_counts: dict[str, int] = {}
    verified_minutes: dict[str, int] = {}
    registry_verified_minutes: dict[str, int] = {}
    seed_set = set(seeds)
    for fact in facts:
        funder = fact.get("funding_source")
        if funder:
            funding_counts[funder] = funding_counts.get(funder, 0) + 1
        minute = minute_bucket((fact.get("agent") or {}).get("verifiedAt"))
        if minute:
            verified_minutes[minute] = verified_minutes.get(minute, 0) + 1
    for agent in registry_agents or []:
        minute = minute_bucket(agent.get("verifiedAt"))
        if minute:
            registry_verified_minutes[minute] = registry_verified_minutes.get(minute, 0) + 1
    return {
        "funding_counts": funding_counts,
        "verified_minutes": verified_minutes,
        "registry_verified_minutes": registry_verified_minutes,
        "seed_set": seed_set,
        "seed_funders": {
            fact.get("funding_source")
            for fact in facts
            if fact.get("address") in seed_set and fact.get("funding_source")
        },
        "seed_contracts": {
            contract
            for fact in facts
            if fact.get("address") in seed_set
            for contract in (fact.get("contracts") or [])
        },
        "seed_counterparties": {
            counterparty
            for fact in facts
            if fact.get("address") in seed_set
            for counterparty in (fact.get("counterparties") or [])
        },
    }


def score_one(fact: dict[str, Any], cohort: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    signals = [
        wallet_age_signal(fact, now),
        activity_signal(fact),
        identity_signal(fact),
        economic_signal(fact),
        diversity_signal(fact),
        inbox_signal(fact, now),
        funding_signal(fact, cohort),
        batch_timing_signal(fact, cohort),
        seed_overlap_signal(fact, cohort),
    ]
    total = min(100.0, sum(signal.points for signal in signals))
    label = label_for_score(total)
    sorted_signals = sorted(signals, key=lambda signal: signal.points, reverse=True)
    return {
        "address": fact.get("address"),
        "score": round(total, 2),
        "label": label,
        "top_signals": [signal.to_dict() for signal in sorted_signals[:3] if signal.points > 0],
        "signals": [signal.to_dict() for signal in signals],
        "facts": public_fact_summary(fact),
        "errors": fact.get("errors", []),
    }


def wallet_age_signal(fact: dict[str, Any], now: dt.datetime) -> Signal:
    first_seen = parse_time(fact.get("first_seen_at"))
    verified = parse_time((fact.get("agent") or {}).get("verifiedAt"))
    candidate = min_time(first_seen, verified)
    if not candidate:
        return Signal("wallet_age", 18, 18, "no public first-seen or verification timestamp found")
    age_days = max((now - candidate).total_seconds() / 86400, 0)
    if age_days < 1:
        points = 18
    elif age_days < 3:
        points = 14
    elif age_days < 14:
        points = 8
    elif age_days < 30:
        points = 4
    else:
        points = 0
    return Signal("wallet_age", points, 18, f"oldest public signal is {age_days:.1f} days old")


def activity_signal(fact: dict[str, Any]) -> Signal:
    total = int(fact.get("tx_total") or 0)
    if total == 0:
        points = 15
    elif total <= 2:
        points = 12
    elif total < 6:
        points = 8
    elif total < 15:
        points = 4
    else:
        points = 0
    return Signal("tx_activity", points, 15, f"Hiro reports {total} transactions for the address")


def identity_signal(fact: dict[str, Any]) -> Signal:
    agent = fact.get("agent") or {}
    level = int(agent.get("level") or 0)
    has_identity = bool(fact.get("nft_identity") or agent.get("erc8004AgentId"))
    if has_identity:
        return Signal("agent_identity", 0, 14, "Agent Identity v2 / ERC-8004 evidence is present")
    if level >= 2:
        return Signal("agent_identity", 4, 14, f"AIBTC agent is {agent.get('levelName')}, but no on-chain identity was visible")
    if level == 1:
        return Signal("agent_identity", 8, 14, "address is only a Level 1 verified agent")
    return Signal("agent_identity", 14, 14, "address was not found in the AIBTC agent registry")


def economic_signal(fact: dict[str, Any]) -> Signal:
    stx = int(fact.get("stx_balance_micro") or 0)
    ft_count = int(fact.get("ft_count") or 0)
    btc = fact.get("btc") or {}
    btc_txs = int(btc.get("tx_count") or 0)
    if stx == 0 and ft_count == 0 and btc_txs == 0:
        points = 12
        reason = "no STX balance, fungible token holdings, or BTC anchor activity found"
    elif stx < 10000 and ft_count == 0 and btc_txs <= 1:
        points = 8
        reason = "near-zero balances and little linked BTC activity"
    elif stx < 1000000 and ft_count == 0:
        points = 3
        reason = "low STX balance and no visible fungible-token diversity"
    else:
        points = 0
        reason = "balances or token/BTC activity show economic footprint"
    return Signal("economic_activity", points, 12, reason)


def diversity_signal(fact: dict[str, Any]) -> Signal:
    contracts = set(fact.get("contracts") or [])
    counterparties = set(fact.get("counterparties") or [])
    diversity = len(contracts) + len(counterparties)
    tx_total = int(fact.get("tx_total") or 0)
    if tx_total <= 2 and diversity <= 1:
        points = 12
    elif tx_total < 10 and diversity <= 2:
        points = 8
    elif diversity <= 3:
        points = 4
    else:
        points = 0
    return Signal(
        "graph_diversity",
        points,
        12,
        f"{len(contracts)} contracts and {len(counterparties)} counterparties observed",
    )


def inbox_signal(fact: dict[str, Any], now: dt.datetime) -> Signal:
    agent = fact.get("agent") or {}
    inbox = fact.get("inbox") or {}
    total = int(inbox.get("totalCount") or 0)
    verified = parse_time(agent.get("verifiedAt"))
    age_days = (now - verified).total_seconds() / 86400 if verified else 0
    if not agent:
        return Signal("inbox_pattern", 2, 8, "not an AIBTC agent, so no inbox graph expected")
    if total == 0 and age_days >= 1:
        return Signal("inbox_pattern", 8, 8, "registered agent has no inbox send/receive activity")
    if total == 0:
        return Signal("inbox_pattern", 4, 8, "new registered agent has no inbox activity yet")
    if int(inbox.get("satsNet") or 0) == 0 and total <= 2:
        return Signal("inbox_pattern", 3, 8, "very small inbox graph with no net paid activity")
    return Signal("inbox_pattern", 0, 8, "inbox graph has visible activity")


def funding_signal(fact: dict[str, Any], cohort: dict[str, Any]) -> Signal:
    funder = fact.get("funding_source")
    if not funder:
        return Signal("funding_cluster", 6, 18, "no first funding source could be derived")
    count = int(cohort.get("funding_counts", {}).get(funder, 0))
    seed_funders = cohort.get("seed_funders", set())
    if funder in seed_funders:
        return Signal("funding_cluster", 18, 18, "first funding source overlaps a seed-cluster address")
    if count >= 3:
        return Signal("funding_cluster", 16, 18, f"first funding source is shared by {count} scored addresses")
    if count == 2:
        return Signal("funding_cluster", 10, 18, "first funding source is shared by another scored address")
    return Signal("funding_cluster", 0, 18, "first funding source is not shared inside this scored batch")


def batch_timing_signal(fact: dict[str, Any], cohort: dict[str, Any]) -> Signal:
    minute = minute_bucket((fact.get("agent") or {}).get("verifiedAt"))
    if not minute:
        return Signal("batch_timing", 0, 8, "no AIBTC verification timestamp")
    local_count = int(cohort.get("verified_minutes", {}).get(minute, 0))
    registry_count = int(cohort.get("registry_verified_minutes", {}).get(minute, 0))
    count = max(local_count, registry_count)
    if count >= 3:
        return Signal("batch_timing", 8, 8, f"{count} public AIBTC agents verified in the same minute")
    if count == 2:
        return Signal("batch_timing", 4, 8, "two public AIBTC agents verified in the same minute")
    return Signal("batch_timing", 0, 8, "verification time is not batched in the scored set or public registry")


def seed_overlap_signal(fact: dict[str, Any], cohort: dict[str, Any]) -> Signal:
    address = fact.get("address")
    seeds = cohort.get("seed_set", set())
    if not seeds:
        return Signal("seed_overlap", 0, 20, "no seed cluster supplied")
    if address in seeds:
        return Signal("seed_overlap", 20, 20, "address is in the supplied seed cluster")
    neighbors = set(fact.get("counterparties") or [])
    contracts = set(fact.get("contracts") or [])
    overlap = len(neighbors & seeds)
    if overlap:
        return Signal("seed_overlap", min(20, 8 + 4 * overlap), 20, f"{overlap} direct counterparty overlaps with seed cluster")
    shared_contracts = len(contracts & set(cohort.get("seed_contracts", set())))
    shared_neighbors = len(neighbors & set(cohort.get("seed_counterparties", set())))
    if shared_contracts or shared_neighbors:
        points = min(16, 5 * shared_contracts + 3 * shared_neighbors)
        return Signal(
            "seed_overlap",
            points,
            20,
            f"shares {shared_contracts} contracts and {shared_neighbors} counterparties with seed facts",
        )
    return Signal("seed_overlap", 0, 20, "no seed-cluster overlap found")


def public_fact_summary(fact: dict[str, Any]) -> dict[str, Any]:
    agent = fact.get("agent") or {}
    return {
        "tx_total": fact.get("tx_total", 0),
        "first_seen_at": fact.get("first_seen_at"),
        "funding_source": fact.get("funding_source"),
        "contract_count": len(fact.get("contracts") or []),
        "counterparty_count": len(fact.get("counterparties") or []),
        "stx_balance_micro": fact.get("stx_balance_micro", 0),
        "fungible_token_count": fact.get("ft_count", 0),
        "has_identity_nft": bool(fact.get("nft_identity")),
        "agent_level": agent.get("level"),
        "agent_level_name": agent.get("levelName"),
        "agent_btc_address": agent.get("btcAddress"),
        "agent_verified_at": agent.get("verifiedAt"),
        "agent_last_active_at": agent.get("lastActiveAt"),
        "agent_erc8004_id": agent.get("erc8004AgentId"),
        "aibtc_verify": fact.get("verify") or {},
        "inbox": fact.get("inbox") or {},
        "btc": fact.get("btc") or {},
    }


def label_for_score(score: float) -> str:
    if score >= 65:
        return "high_sybil_risk"
    if score >= 35:
        return "watchlist"
    return "likely_clean"


def normalize_address(address: str) -> str:
    cleaned = address.strip()
    if not cleaned:
        raise ValueError("empty address")
    return cleaned


def parse_time(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def min_time(*values: dt.datetime | None) -> dt.datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def minute_bucket(value: Any) -> str | None:
    parsed = parse_time(value)
    if not parsed:
        return None
    return parsed.replace(second=0, microsecond=0).isoformat()


def oldest_time(txs: list[dict[str, Any]]) -> str | None:
    times = [str(tx.get("block_time_iso")) for tx in txs if tx.get("block_time_iso")]
    return min(times) if times else None


def pretty_print(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for result in report.get("results", []):
        lines.append(f"{result['address']}: {result['score']}/100 {result['label']}")
        for signal in result.get("top_signals", []):
            lines.append(f"  - {signal['name']}: +{signal['points']} ({signal['reason']})")
        if result.get("errors"):
            lines.append(f"  endpoint warnings: {len(result['errors'])}")
    return "\n".join(lines)
