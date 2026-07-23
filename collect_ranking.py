# -*- coding: utf-8 -*-
"""
네이버웹툰 실시간 인기웹툰 랭킹 수집 v3 (GitHub Actions용)
- 확인된 실제 구조: 요청 1번(rankTabType=DEFAULT)에 세 탭 목록이 모두 포함됨
    totalRankingTitleList  → 전체
    femaleRankingTitleList → 여성
    maleRankingTitleList   → 남성
- 작가: displayAuthor 필드 사용 (예: "JP / 이히 / 유진성")
- 결과: data/ranking_log.csv 누적
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://comic.naver.com/webtoon",
    "Accept": "application/json",
}

# 응답의 목록 키 → 대시보드에 표시할 탭 이름
LIST_KEYS = {
    "totalRankingTitleList": "전체",
    "femaleRankingTitleList": "여성",
    "maleRankingTitleList": "남성",
}

CSV_HEADER = ["기록시각", "탭", "순위", "제목", "titleId", "작가"]

KST = timezone(timedelta(hours=9))


def pick(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return ""


def format_author(it):
    """displayAuthor를 우선 사용하고, 없으면 author 구조에서 조립."""
    da = it.get("displayAuthor")
    if isinstance(da, str) and da.strip():
        return da.strip()
    val = it.get("author")
    if isinstance(val, dict):
        def names(key):
            out = []
            for p in val.get(key, []) or []:
                if isinstance(p, dict) and p.get("name"):
                    out.append(str(p["name"]))
            return out
        writers, painters, origin = names("writers"), names("painters"), names("originAuthors")
        parts = []
        if writers and painters and writers == painters:
            parts.append(" · ".join(writers))
        else:
            if writers:
                parts.append("글 " + " · ".join(writers))
            if painters:
                parts.append("그림 " + " · ".join(painters))
        if origin:
            parts.append("원작 " + " · ".join(origin))
        return " / ".join(parts)
    return str(val) if val else ""


def find_ranking_lists(data):
    """알려진 키를 우선 사용하되, 이름이 바뀌어도 *RankingTitleList 형태의
    키를 재귀적으로 찾아 대응한다."""
    found = {}

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if (
                    isinstance(v, list)
                    and v
                    and all(isinstance(x, dict) for x in v)
                    and "rankingtitlelist" in k.lower()
                ):
                    found[k] = v
                else:
                    walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(data)
    return found


def tab_name_for_key(key):
    if key in LIST_KEYS:
        return LIST_KEYS[key]
    low = key.lower()
    if "female" in low:
        return "여성"
    if "male" in low:
        return "남성"
    if "total" in low or "all" in low:
        return "전체"
    return key  # 알 수 없는 키는 원문 그대로


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    try:
        r = requests.get(
            API_URL,
            params={"rankTabType": "DEFAULT"},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[실패] 요청 오류: {e}")
        return

    lists = find_ranking_lists(data)
    if not lists:
        debug_path = os.path.join(DATA_DIR, "ranking_debug.json")
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[실패] 랭킹 목록을 찾지 못함 → {debug_path} 저장")
        return

    all_rows = []
    # 전체 → 여성 → 남성 순서로 정렬해 기록
    order = {"전체": 0, "여성": 1, "남성": 2}
    for key in sorted(lists.keys(), key=lambda k: order.get(tab_name_for_key(k), 9)):
        tab = tab_name_for_key(key)
        items = lists[key]
        for idx, it in enumerate(items, start=1):
            title = pick(it, "titleName", "title", "name")
            title_id = pick(it, "titleId", "id")
            author = format_author(it)
            rank = pick(it, "rank", "ranking") or idx
            all_rows.append([ts, tab, rank, title, title_id, author])
        print(f"[성공] {tab}({key}): {len(items)}건")

    new_file = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(CSV_HEADER)
        writer.writerows(all_rows)
    print(f"총 {len(all_rows)}건 기록 완료 → {CSV_PATH}")


if __name__ == "__main__":
    main()
