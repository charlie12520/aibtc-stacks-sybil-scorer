from __future__ import annotations

import json
import unittest

from stacks_sybil_scorer.core import batch_timing_signal, build_cohort, score_addresses
from stacks_sybil_scorer.fixtures import DEMO_FACTS


class SybilScorerTests(unittest.TestCase):
    def test_demo_fixtures_classify_clean_and_risky_addresses(self) -> None:
        report = score_addresses([], offline_facts=DEMO_FACTS)
        labels = {result["address"]: result["label"] for result in report["results"]}

        self.assertEqual(labels["SP20GPDS5RYB2DV03KG4W08EG6HD11KYPK6FQJE1"], "likely_clean")
        self.assertEqual(labels["SP1SC59Y3G1A0WNY5837R9HDCEPWRJSF852YM7GEW"], "likely_clean")
        self.assertEqual(labels["SPSYBIL000000000000000000000000000000001"], "high_sybil_risk")
        self.assertIn(labels["SPSYBIL000000000000000000000000000000002"], {"watchlist", "high_sybil_risk"})

    def test_output_is_json_serializable_and_explainable(self) -> None:
        report = score_addresses([], offline_facts=DEMO_FACTS[:1])
        encoded = json.dumps(report, sort_keys=True)

        self.assertIn('"score"', encoded)
        self.assertIn('"top_signals"', encoded)
        self.assertTrue(report["results"][0]["signals"])
        self.assertIn("reason", report["results"][0]["signals"][0])

    def test_seed_cluster_directly_raises_seed_score(self) -> None:
        seed = "SPSYBIL000000000000000000000000000000001"
        report = score_addresses([], seeds=[seed], offline_facts=[DEMO_FACTS[2]])

        self.assertEqual(report["results"][0]["label"], "high_sybil_risk")
        self.assertTrue(any(signal["name"] == "seed_overlap" for signal in report["results"][0]["top_signals"]))

    def test_shared_funding_source_is_scored_for_batch(self) -> None:
        report = score_addresses([], offline_facts=DEMO_FACTS[2:])
        by_address = {result["address"]: result for result in report["results"]}

        first = by_address["SPSYBIL000000000000000000000000000000001"]
        funding = [signal for signal in first["signals"] if signal["name"] == "funding_cluster"][0]
        self.assertGreater(funding["points"], 0)

    def test_seed_cluster_scores_shared_public_facts(self) -> None:
        seed = {
            **DEMO_FACTS[2],
            "address": "SPSEED0000000000000000000000000000000001",
            "contracts": ["shared-contract"],
            "counterparties": ["SPSHAREDCOUNTERPARTY00000000000000000001"],
        }
        target = {
            **DEMO_FACTS[3],
            "address": "SPTARGET00000000000000000000000000000001",
            "contracts": ["shared-contract"],
            "counterparties": ["SPSHAREDCOUNTERPARTY00000000000000000001"],
        }
        report = score_addresses([], seeds=[seed["address"]], offline_facts=[target, seed])
        target_result = {result["address"]: result for result in report["results"]}[target["address"]]
        seed_signal = [signal for signal in target_result["signals"] if signal["name"] == "seed_overlap"][0]

        self.assertGreater(seed_signal["points"], 0)
        self.assertIn("shares", seed_signal["reason"])

    def test_identity_nft_batch_timing_is_explainable(self) -> None:
        first = {
            **DEMO_FACTS[0],
            "address": "SPIDENTITYBATCH0000000000000000000000001",
            "identity_nft_blocks": [9000000],
        }
        second = {
            **DEMO_FACTS[1],
            "address": "SPIDENTITYBATCH0000000000000000000000002",
            "identity_nft_blocks": [9000007],
            "nft_identity": True,
        }
        third = {
            **DEMO_FACTS[1],
            "address": "SPIDENTITYBATCH0000000000000000000000003",
            "identity_nft_blocks": [9000009],
            "nft_identity": True,
        }

        report = score_addresses([], offline_facts=[first, second, third])
        signal = [
            signal
            for signal in report["results"][0]["signals"]
            if signal["name"] == "identity_mint_batch"
        ][0]

        self.assertEqual(signal["points"], 8)
        self.assertIn("10-block window", signal["reason"])

    def test_global_registry_batch_timing_counts_single_address_waves(self) -> None:
        fact = {
            "agent": {
                "verifiedAt": "2026-05-27T12:03:45Z",
            }
        }
        cohort = build_cohort(
            [fact],
            [],
            registry_agents=[
                {"verifiedAt": "2026-05-27T12:03:01Z"},
                {"verifiedAt": "2026-05-27T12:03:20Z"},
                {"verifiedAt": "2026-05-27T12:03:59Z"},
            ],
        )

        signal = batch_timing_signal(fact, cohort)

        self.assertEqual(signal.points, 8)
        self.assertIn("public AIBTC agents", signal.reason)


if __name__ == "__main__":
    unittest.main()
