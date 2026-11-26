"""실제 API로 한 건 조회해 보는 스크립트. .env에 PUBLIC_DATA_API_KEY가 있어야 한다.

예:
    python tests/live_check.py
    python tests/live_check.py --type 오피스텔 --lawd 11680 --dong 역삼동 --building 강남역 --area 30 --deposit 250000000
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))  # 저장소 루트

from dotenv import load_dotenv  # noqa: E402

from document.price import assess_jeonse  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--type", default="아파트", help="아파트 / 오피스텔 / 연립다세대")
    p.add_argument("--lawd", default="11680", help="법정동코드 앞 5자리 (11680=서울 강남구)")
    p.add_argument("--dong", default="대치동", help="법정동 이름")
    p.add_argument("--building", default="은마", help="건물명 또는 지번")
    p.add_argument("--area", type=float, default=76.79, help="전용면적(㎡)")
    p.add_argument("--deposit", type=int, default=1_500_000_000, help="보증금(원, 예: 1500000000 = 15억)")
    p.add_argument("--bjdong", help="10자리 법정동코드 (넣으면 건축물대장도 조회, 예: 1150010300 = 강서구 화곡동)")
    p.add_argument("--jibun", help="건축물대장 조회용 지번 (예: 355-14)")
    p.add_argument("--dong-nm", help="건축물대장 동 이름 (예: A동)")
    p.add_argument("--ho", help="호 (예: 401) - 넣으면 그 호의 용도도 확인")
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--show-samples", type=int, default=5, help="출력할 근거 거래 수")
    a = p.parse_args()

    load_dotenv()
    if not os.getenv("PUBLIC_DATA_API_KEY"):
        print(".env에 PUBLIC_DATA_API_KEY가 없어 실제 API 확인을 건너뜁니다.")
        return 0

    r = assess_jeonse(a.type, a.lawd, a.dong, a.building, a.area, a.deposit, months=a.months,
                      bjdong_cd=a.bjdong, jibun=a.jibun, dong_nm=a.dong_nm, ho_nm=a.ho)
    r["estimate"]["samples"] = r["estimate"]["samples"][: a.show_samples]
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
