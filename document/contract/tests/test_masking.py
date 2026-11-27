"""개인정보 마스킹 테스트. 모두 지어낸 값이다. 실행: python -m unittest discover -s document/contract/tests -v"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from document.contract import mask_special_terms, mask_text, party_names  # noqa: E402


class MaskTextTest(unittest.TestCase):
    def m(self, text, names=()):
        counts = {}
        return mask_text(text, list(names), counts), counts

    def test_resident_no_phone_email(self):
        out, c = self.m("임차인 주민번호 980715-2345678, 연락처 010-0000-5678 / 02-123-4567, a.b@example.com")
        self.assertNotIn("2345678", out)
        self.assertNotIn("5678", out)
        self.assertNotIn("4567", out)
        self.assertNotIn("example", out)
        self.assertEqual(c, {"resident_no": 1, "phone": 2, "email": 1})

    def test_account_but_not_dates_or_amounts(self):
        out, c = self.m("보증금 360,000,000원은 2027-01-29까지 계좌 110-123-456789로 보낸다. 제3조의6 제3항")
        self.assertIn("[계좌번호]", out)
        self.assertIn("360,000,000원", out)
        self.assertIn("2027-01-29", out)
        self.assertIn("제3조의6", out)
        self.assertEqual(c, {"account": 1})

    def test_plain_mobile(self):
        out, _ = self.m("임대인 연락처 01012345678")
        self.assertEqual(out, "임대인 연락처 ***-****-****")

    def test_names(self):
        out, c = self.m("임차인 이하늘은 임대인 김가람에게 통지한다.", ["이하늘", "김가람"])
        self.assertEqual(out, "임차인 ***은 임대인 ***에게 통지한다.")
        self.assertEqual(c, {"name": 2})

    def test_none(self):
        self.assertIsNone(mask_text(None, [], {}))


class PartyNamesTest(unittest.TestCase):
    def test_from_party_table(self):
        lines = [
            "주민등록번호 650312-1234567 전 화 010-0000-1234 성 명 김가람 ㊞",
            "대 리 인 주소 주민등록번호 성 명",
            "성명: 이하늘",
            "대 표 박중개 서명 및 날인 ㊞",
        ]
        self.assertEqual(party_names(lines), ["김가람", "박중개", "이하늘"])


class MaskResultTest(unittest.TestCase):
    def test_all_text_fields(self):
        res = {
            "section_text": "① 확정일자\n※ 기타\n1. 임차인 이하늘(010-1111-2222)에게 알린다.",
            "custom_terms_text": "1. 임차인 이하늘(010-1111-2222)에게 알린다.",
            "base_terms": [{"no": 1, "text": "확정일자", "note": None}],
            "custom_terms": [{"no": 1, "text": "1. 임차인 이하늘(010-1111-2222)에게 알린다."}],
            "masked": False,
        }
        out = mask_special_terms(res, ["성 명 이하늘"])
        self.assertTrue(out["masked"])
        for key in ("section_text", "custom_terms_text"):
            self.assertNotIn("이하늘", out[key])
            self.assertNotIn("2222", out[key])
        self.assertEqual(out["custom_terms"][0]["text"], "1. 임차인 ***(***-****-****)에게 알린다.")
        self.assertEqual(out["masking"]["counts"], {"phone": 1, "name": 1})
        self.assertFalse(res["masked"])  # 원본은 바꾸지 않는다


if __name__ == "__main__":
    unittest.main()
