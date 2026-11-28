import unittest

from ai.report_cards import build_report, enrich_analysis_result


class RegistryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.analysis = {
            "analysis_id": "demo",
            "grade": "주의",
            "special_terms": {"section_text": "PRIVATE_TEST_MARKER"},
            "flags": [
                {"code": "REGISTRY_OUTDATED", "level": "주의", "value": 10},
                {"code": "SPECIAL_TERMS_CHECK_NEEDED", "level": "확인필요"},
            ],
        }

    def test_public_evidence_is_only_on_registry_card(self):
        report = enrich_analysis_result(self.analysis)
        registry, terms = report["report_cards"]
        self.assertEqual(report["grade"], self.analysis["grade"])
        self.assertIn("10일 전", registry["description"])
        self.assertTrue(registry["evidence"])
        self.assertIn(registry["evidence"][0]["summary"], registry["description"])
        self.assertTrue(all(item["text_type"] == "paraphrase" for item in registry["evidence"]))
        self.assertEqual(terms["evidence"], [])
        self.assertNotIn("PRIVATE_TEST_MARKER", str(report["report_cards"]))

    def test_empty_sources_keep_only_default_guidance(self):
        registry = build_report(self.analysis, registry_guides=[])["report_cards"][0]
        self.assertEqual(registry["evidence"], [])
        self.assertEqual(registry["actions"], ["최신 등기부를 준비해 다시 확인해 주세요."])

    def test_without_signal_no_registry_card_is_added(self):
        report = build_report({**self.analysis, "flags": self.analysis["flags"][1:]})
        self.assertEqual([card["code"] for card in report["report_cards"]], ["SPECIAL_TERMS_CHECK_NEEDED"])
