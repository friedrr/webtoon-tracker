# -*- coding: utf-8 -*-
"""
네이버웹툰 실시간 인기웹툰 랭킹 수집 (GitHub Actions용)
- API: https://comic.naver.com/api/realtime/ranking/list?rankTabType=...
- 결과: data/ranking_log.csv 에 누적 (대시보드 ranking.html 이 이 파일을 읽음)
- 파싱 실패 시: data/ranking_debug_{탭}.json 에 원본 저장 → 구조 확인용
"""

import csv
import json
import os
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_PATH = os.path.join(DATA_DIR, "ranking_log.csv")

API_URL = "https://comic.naver.com/api/realtime/ranking/list"

# '전체'는 DEFAULT로 확인됨. 여성/남성은 추정값 - 실패하면 로그에 표시됨.
TAB_TYPES = {
    "전체": "DEFAULT",
    "여성": "FEMALE",
    "남성": "MALE",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://comic.naver.com/webtoon",
    "Accept": "application/json",
}

CSV_HEADER = ["기록시각", "탭", "순위", "제목", "titleId", "작가"]

KST = timezone(timedelta(hours=9))


def find_item_list(obj):
    """JSON 어디에 있든 '딕셔너리들의 리스트'(랭킹 목록)를 찾아 반환."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            return obj
        for x in obj:
            found = find_item_list(x)
            if found:
                return found
    elif isinstance(obj, dict):
        for v in obj.values():
            found = find_item_list(v)
            if found:
                return found
    return None


def pick(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return ""


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    all_rows = []

    for tab_name, tab_type in TAB_TYPES.items():
        try:
            r = requests.get(
                API_URL,
                params={"rankTabType": tab_type},
                headers=HEADERS,
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"[실패] {tab_name}({tab_type}): {e}")
            continue

        items = find_item_list(data)
        if not items:
            debug_path = os.path.join(DATA_DIR, f"ranking_debug_{tab_type}.json")
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[파싱 0건] {tab_name}({tab_type}) → {debug_path} 저장")
            continue

        for idx, it in enumerate(items, start=1):
            title = pick(it, "titleName", "title", "name")
            title_id = pick(it, "titleId", "id")
            author = pick(it, "author", "displayAuthor", "writer", "painter")
            rank = pick(it, "rank", "ranking") or idx
            all_rows.append([ts, tab_name, rank, title, title_id, author])
        print(f"[성공] {tab_name}: {len(items)}건")

    if not all_rows:
        print("수집 결과가 없어 CSV를 갱신하지 않습니다.")
        return

    new_file = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(CSV_HEADER)
        writer.writerows(all_rows)
    print(f"총 {len(all_rows)}건 기록 완료 → {CSV_PATH}")


if __name__ == "__main__":
    main()
