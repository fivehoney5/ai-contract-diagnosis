import unittest

from ai.registry_evidence import load_registry_guides, load_trust_guides
from ai.report_cards import build_report, enrich_analysis_result


class TrustReportTests(unittest.TestCase):
    def setUp(self):
        self.flag = {"code": "TRUST_REGISTERED", "level": "위험", "value": 1}
        self.analysis = {"analysis_id": "demo", "grade": "위험", "flags": [self.flag]}

    def test_only_trust_evidence_used_and_grade_preserved(self):
        records = load_registry_guides() + load_trust_guides()
        analysis = {**self.analysis, "flags": [self.flag, self.flag, {
            "code": "REGISTRY_OUTDATED", "level": "주의", "value": 10,
        }]}
        report = build_report(analysis, trust_guides=records, registry_guides=records)
        trust, registry = report["report_cards"]
        self.assertEqual(report["grade"], "위험")
        self.assertEqual(trust["level"], "위험")
        self.assertEqual(len(trust["evidence"]), 2)
        self.assertTrue(all(":trust-" in item["id"] for item in trust["evidence"]))
        self.assertTrue(all(item["text_type"] == "paraphrase" for item in trust["evidence"]))
        self.assertFalse(any(":trust-" in item["id"] for item in registry["evidence"]))

    def test_missing_sources_keep_default_action(self):
        card = build_report(self.analysis, trust_guides=[])["report_cards"][0]
        self.assertEqual(card["evidence"], [])
        self.assertIn("신탁원부", card["actions"][0])

    def test_normal_entrypoint_adds_card_without_changing_input(self):
        result = enrich_analysis_result(self.analysis)
        self.assertEqual(result["report_cards"][0]["code"], self.flag["code"])
        self.assertTrue(result["report_cards"][0]["evidence"])
        self.assertNotIn("report_cards", self.analysis)

    def test_restriction_and_trust_have_separate_sources(self):
        restriction = {"code": "OWNERSHIP_RESTRICTED", "level": "위험", "value": 1}
        result = enrich_analysis_result({**self.analysis, "flags": [restriction, self.flag]})
        first, second = result["report_cards"]
        self.assertEqual(first["code"], "OWNERSHIP_RESTRICTED")
        self.assertEqual([item["id"] for item in first["evidence"]], ["guide:hug:ownership-restriction"])
        self.assertEqual(len(second["evidence"]), 2)
        self.assertTrue(all(":trust-" in item["id"] for item in second["evidence"]))
