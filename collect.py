# -*- coding: utf-8 -*-
"""
네이버 웹툰 관심수 수집 스크립트
- 매시간 GitHub Actions에서 실행되어 data/history.csv 에 한 줄씩 기록합니다.
- 외부 패키지 없이 표준 라이브러리만 사용합니다.
"""

import csv
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TITLE_ID = "851689"

API_URL = f"https://comic.naver.com/api/article/list/info?titleId={TITLE_ID}"
PAGE_URL = f"https://comic.naver.com/webtoon/list?titleId={TITLE_ID}"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CSV_PATH = DATA_DIR / "history.csv"
META_PATH = DATA_DIR / "meta.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": PAGE_URL,
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def find_key(obj, key):
    """중첩된 dict/list 어디에 있든 key 값을 찾아 반환 (응답 구조 변화에 대비)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key(item, key)
            if found is not None:
                return found
    return None


def fetch_favorite_count():
    """(favorite_count, title_name) 반환. 실패 시 예외."""
    errors = []

    # 1차: 공식 API 엔드포인트
    try:
        data = json.loads(http_get(API_URL))
        fav = find_key(data, "favoriteCount")
        name = find_key(data, "titleName")
        if fav is not None:
            return int(fav), (str(name) if name else None)
        errors.append("API 응답에 favoriteCount 키가 없음")
    except Exception as e:
        errors.append(f"API 요청 실패: {e!r}")

    # 2차 폴백: 작품 페이지 HTML에 포함된 JSON에서 추출
    try:
        html = http_get(PAGE_URL)
        m = re.search(r'"favoriteCount"\s*:\s*(\d+)', html)
        if m:
            fav = int(m.group(1))
            name = None
            mn = re.search(r'"titleName"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
            if mn:
                try:
                    name = json.loads(f'"{mn.group(1)}"')
                except Exception:
                    name = mn.group(1)
            return fav, name
        errors.append("페이지 HTML에서 favoriteCount 패턴을 찾지 못함")
    except Exception as e:
        errors.append(f"페이지 요청 실패: {e!r}")

    raise RuntimeError("관심수 수집 실패 → " + " / ".join(errors))


def main():
    fav, name = fetch_favorite_count()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    is_new = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp_utc", "favorite_count"])
        writer.writerow([now.isoformat(), fav])

    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta.update(
        {
            "titleId": TITLE_ID,
            "titleName": name or meta.get("titleName"),
            "pageUrl": PAGE_URL,
            "updatedAtUtc": now.isoformat(),
            "latestCount": fav,
        }
    )
    META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[OK] {now.isoformat()}  favoriteCount={fav}  title={name or '(미확인)'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        sys.exit(1)
