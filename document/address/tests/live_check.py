"""실제 도로명주소 API로 주소 변환을 확인한다 (.env의 JUSO_API_KEY 필요, 키 값은 출력하지 않음).

저장소 루트에서: python document/address/tests/live_check.py "서울 강남구 테헤란로 152"
캐시를 쓰려면 --cache (data/local/address_cache.sqlite)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from document.address import SQLiteAddressCache, resolve_address  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("addresses", nargs="+", help="확인할 주소 (여러 개 가능)")
    p.add_argument("--cache", action="store_true", help="SQLite 캐시 사용")
    args = p.parse_args()
    cache = SQLiteAddressCache() if args.cache else None
    for text in args.addresses:
        r = resolve_address(text, cache=cache)
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
