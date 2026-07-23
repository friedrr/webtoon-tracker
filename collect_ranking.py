# -*- coding: utf-8 -*-
"""
네이버웹툰 실시간 인기웹툰 랭킹 수집 v2 (GitHub Actions용)
- 여성/남성 탭: 파라미터 후보를 순서대로 시도, 전체와 같은 결과가 오면 실패로 간주
- 작가: {'writers':..., 'painters':...} 구조를 "글 ○○ / 그림 ○○" 형태로 정리
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

# 각 탭에 대해 후보 파라미터를 순서대로 시도한다.
# '전체'(DEFAULT)와 완전히 같은 목록이 돌아오면 파라미터가 무시된 것으로 보고 다음 후보로 넘어간다.
TAB_CANDIDATES = {
    "전체": ["DEFAULT"],
    "여성": ["FEMALE", "WOMAN", "GIRL", "F"],
    "남성": ["MALE", "MAN", "BOY", "M"],
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


def format_author(val):
    """author가 {'writers':[...], 'painters':[...], 'originAuthors':[...]} 구조인
    경우를 '글 ○○ / 그림 ○○ / 원작 ○○' 형태의 문자열로 정리한다."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        def names(key):
            out = []
            for p in val.get(key, []) or []:
                if isinstance(p, dict) and p.get("name"):
                    out.append(str(p["name"]))
            return out

        writers = names("writers")
        painters = names("painters")
        origin = names("originAuthors")
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


def fetch_tab(tab_type):
    """해당 파라미터로 요청해 (성공여부, 아이템목록, 원본) 반환."""
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
        return False, None, str(e)
    items = find_item_list(data)
    if not items:
        return False, None, data
    return True, items, data


def signature(items):
    """목록 비교용 서명 (titleId 또는 제목의 순서열)."""
    return tuple(str(pick(it, "titleId", "id", "titleName", "title")) for it in items)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    all_rows = []
    default_sig = None

    for tab_name, candidates in TAB_CANDIDATES.items():
        got = None
        used = None
        for cand in candidates:
            ok, items, raw = fetch_tab(cand)
            if not ok:
                print(f"[시도 실패] {tab_name}({cand})")
                continue
            sig = signature(items)
            if tab_name != "전체" and default_sig is not None and sig == default_sig:
                # 파라미터가 무시되어 전체와 같은 결과가 온 경우
                print(f"[무시됨] {tab_name}({cand}) - 전체와 동일한 결과")
                continue
            got, used = items, cand
            break

        if got is None:
            # 마지막 응답 구조 확인용으로 디버그 저장
            debug_path = os.path.join(DATA_DIR, f"ranking_debug_{tab_name}.json")
            try:
                with open(debug_path, "w", encoding="utf-8") as f:
                    json.dump(raw if not isinstance(raw, str) else {"error": raw},
                              f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            print(f"[실패] {tab_name}: 유효한 파라미터를 찾지 못함")
            continue

        if tab_name == "전체":
            default_sig = signature(got)

        for idx, it in enumerate(got, start=1):
            title = pick(it, "titleName", "title", "name")
            title_id = pick(it, "titleId", "id")
            author = format_author(pick(it, "author", "displayAuthor", "writer", "communityArtists"))
            rank = pick(it, "rank", "ranking") or idx
            all_rows.append([ts, tab_name, rank, title, title_id, author])
        print(f"[성공] {tab_name}({used}): {len(got)}건")

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
