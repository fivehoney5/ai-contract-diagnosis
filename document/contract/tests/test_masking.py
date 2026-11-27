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


class ResidualRiskTest(unittest.TestCase):
    """리뷰 반영: masked와 별개로 주소·이름이 남으면 외부 전송을 막는다."""

    def test_address_left(self):
        from document.contract.masking import residual_risks
        for t in ("임차인은 서울특별시 노원구로 전입한다", "동일로 1414로 우편을 보낸다", "101동 707호", "상계동 123-4번지"):
            self.assertEqual(residual_risks(t), ["ADDRESS"], t)

    def test_name_only_in_terms(self):
        from document.contract.masking import residual_risks
        self.assertEqual(residual_risks("임차인 홍길동은 반려동물을 기르지 않는다."), ["POSSIBLE_NAME"])

    def test_no_false_alarm(self):
        from document.contract.masking import residual_risks
        for t in ("보증금으로 1,000만원을 낸다.", "임대인은임차인에게 통지한다.", "임대인 또는 임차인은 해지할 수 있다.",
                  "임차인 본인이 거주한다.", "최대 6개월까지 유예한다.", "제3조의6 제3항", "임차인 ***은 통지한다."):
            self.assertEqual(residual_risks(t), [], t)

    def test_result_flag(self):
        base = {"base_terms": [], "custom_terms": [], "masked": False}
        ok = mask_special_terms(dict(base, section_text="1. 반려동물을 기르지 않는다."), [])
        self.assertTrue(ok["masked"])
        self.assertTrue(ok["external_send_allowed"])
        bad = mask_special_terms(dict(base, section_text="1. 임차인 홍길동은 마들로 999에 산다."), [])
        self.assertTrue(bad["masked"])  # 마스킹은 했지만
        self.assertFalse(bad["external_send_allowed"])  # 외부로는 보내지 않는다
        self.assertEqual(bad["masking"]["residual_risks"], ["ADDRESS", "POSSIBLE_NAME"])


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
        self.assertTrue(out["external_send_allowed"])
        self.assertFalse(res["masked"])  # 원본은 바꾸지 않는다


if __name__ == "__main__":
    unittest.main()
