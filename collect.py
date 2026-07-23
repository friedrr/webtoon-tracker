# -*- coding: utf-8 -*-
"""
네이버 웹툰 관심수 수집 스크립트 (다중 작품, 정각 수집)
- titles.txt 에 적힌 모든 작품의 관심수를 data/<titleId>.csv 에 기록합니다.
- 예약 실행 시: 다음 정각(:00)까지 기다렸다가 수집 → 기록 간격이 균일해짐.
- 수동 실행 시: 기다리지 않고 즉시 수집 (테스트용).
- 외부 패키지 없이 표준 라이브러리만 사용합니다.
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
META_PATH = DATA_DIR / "meta.json"
TITLES_PATH = BASE_DIR / "titles.txt"

# titles.txt 가 없을 때 사용할 기본 목록
DEFAULT_TITLE_IDS = ["851689"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def page_url(title_id: str) -> str:
    return f"https://comic.naver.com/webtoon/list?titleId={title_id}"


def api_url(title_id: str) -> str:
    return f"https://comic.naver.com/api/article/list/info?titleId={title_id}"


def http_get(url: str, referer: str) -> str:
    headers = dict(HEADERS)
    headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
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


def load_title_ids():
    """titles.txt 에서 titleId 목록을 읽음. URL을 붙여넣어도 숫자만 추출."""
    if not TITLES_PATH.exists():
        return list(DEFAULT_TITLE_IDS)
    ids = []
    for raw in TITLES_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()  # '#' 뒤는 메모로 취급
        if not line:
            continue
        m = re.search(r"titleId=(\d+)", line) or re.fullmatch(r"(\d+)", line)
        if m:
            tid = m.group(1)
            if tid not in ids:
                ids.append(tid)
        else:
            print(f"[SKIP] titleId를 찾을 수 없는 줄: {raw!r}", file=sys.stderr)
    return ids or list(DEFAULT_TITLE_IDS)


def fetch_favorite_count(title_id: str):
    """(favorite_count, title_name) 반환. 실패 시 예외."""
    errors = []
    referer = page_url(title_id)

    # 1차: 공식 API 엔드포인트
    try:
        data = json.loads(http_get(api_url(title_id), referer))
        fav = find_key(data, "favoriteCount")
        name = find_key(data, "titleName")
        if fav is not None:
            return int(fav), (str(name) if name else None)
        errors.append("API 응답에 favoriteCount 키가 없음")
    except Exception as e:
        errors.append(f"API 요청 실패: {e!r}")

    # 2차 폴백: 작품 페이지 HTML에 포함된 JSON에서 추출
    try:
        html = http_get(referer, referer)
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

    raise RuntimeError(" / ".join(errors))


def seconds_until_next_hour(now: datetime) -> float:
    """다음 정각(:00:00)까지 남은 초. 이미 정각이면 0."""
    remainder = (now.minute * 60 + now.second + now.microsecond / 1e6)
    if remainder == 0:
        return 0.0
    return 3600.0 - remainder


def wait_or_yield(title_ids) -> bool:
    """
    예약 실행의 행동 결정. 수집을 진행해야 하면 True, 물러나야 하면 False.

    예약은 매시 :35, :45, :55 세 번 걸려 있고 규칙은 다음과 같다.
    - 분 >= 30 에 시작: 정상 도착 → 다음 정각까지 대기 후 수집.
    - 분 < 30 에 시작(지연으로 정각을 넘김):
        * 이번 시간대 기록이 이미 있으면 → 다른 실행이 처리했으므로 종료.
        * 없으면 → 늦었지만 즉시 수집(빠진 기록보다 늦은 기록이 낫다).
    - 수동 실행(workflow_dispatch)은 테스트 목적이므로 즉시 수집.
    """
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event != "schedule":
        print(f"[WAIT] 예약 실행이 아니므로({event or '로컬'}) 즉시 수집")
        return True

    now = datetime.now(timezone.utc)
    if now.minute >= 30:
        secs = seconds_until_next_hour(now)
        print(f"[WAIT] {now:%H:%M:%S UTC} 시작 → 정각까지 {secs/60:.1f}분 대기")
        time.sleep(secs)
        return True

    if all(already_recorded_this_hour(t, now) for t in title_ids):
        print(f"[YIELD] {now:%H:%M UTC} — 이번 시간대는 이미 기록됨, 종료")
        return False

    print(f"[WAIT] 정각을 지나 시작됨({now:%H:%M UTC}) → 밀린 기록 즉시 수집")
    return True


def already_recorded_this_hour(title_id: str, now: datetime) -> bool:
    """같은 시간대(UTC 기준 시각의 '시')에 이미 기록이 있으면 True (중복 방지)."""
    path = DATA_DIR / f"{title_id}.csv"
    if not path.exists():
        return False
    try:
        last = path.read_text(encoding="utf-8").rstrip().splitlines()[-1]
        ts = last.split(",", 1)[0]
        prev = datetime.fromisoformat(ts)
        return (prev.year, prev.month, prev.day, prev.hour) == (
            now.year, now.month, now.day, now.hour
        )
    except Exception:
        return False


def migrate_legacy():
    """예전 단일 작품 시절의 data/history.csv 를 data/851689.csv 로 이동."""
    legacy = DATA_DIR / "history.csv"
    target = DATA_DIR / "851689.csv"
    if legacy.exists() and not target.exists():
        legacy.rename(target)
        print("[MIGRATE] history.csv -> 851689.csv")


def append_record(title_id: str, when: datetime, fav: int):
    path = DATA_DIR / f"{title_id}.csv"
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp_utc", "favorite_count"])
        writer.writerow([when.isoformat(), fav])


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    migrate_legacy()

    title_ids = load_title_ids()
    if not wait_or_yield(title_ids):
        return
    now = datetime.now(timezone.utc).replace(microsecond=0)

    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    titles_meta = meta.get("titles", {})

    ok, failed = [], []
    for tid in title_ids:
        try:
            if already_recorded_this_hour(tid, now):
                print(f"[SKIP] {tid}  이 시간대 기록이 이미 있음 (중복 방지)")
                ok.append(tid)
                continue
            fav, name = fetch_favorite_count(tid)
            append_record(tid, now, fav)
            prev = titles_meta.get(tid, {})
            titles_meta[tid] = {
                "titleName": name or prev.get("titleName"),
                "pageUrl": page_url(tid),
                "latestCount": fav,
                "updatedAtUtc": now.isoformat(),
            }
            ok.append(tid)
            print(f"[OK] {tid}  favoriteCount={fav}  title={name or '(미확인)'}")
        except Exception as e:
            failed.append(tid)
            print(f"[FAIL] {tid}  {e}", file=sys.stderr)

    meta = {
        "updatedAtUtc": now.isoformat(),
        "titleOrder": title_ids,
        "titles": titles_meta,
    }
    META_PATH.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[DONE] 성공 {len(ok)}건 / 실패 {len(failed)}건")
    # 전부 실패했을 때만 워크플로를 빨간 X로 표시
    if ok == [] and failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
