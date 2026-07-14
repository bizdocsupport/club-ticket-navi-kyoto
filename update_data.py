from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote_plus, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag
from dateutil import parser as dtparser

from site_config import get_team_config

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MATCHES_PATH = DATA_DIR / "matches.csv"
NEWS_PATH = DATA_DIR / "ticket_news.csv"
METADATA_PATH = DATA_DIR / "metadata.json"
OVERRIDES_PATH = DATA_DIR / "manual_overrides.csv"
JST = timezone(timedelta(hours=9))
TEAM = get_team_config()

MATCH_COLUMNS = [
    "match_key", "season", "competition_group", "competition_name",
    "round_name", "kickoff", "date_text", "sort_date", "side",
    "home", "away", "opponent", "stadium", "match_url",
    "season_pass_at", "sc_fastest_at", "sc_early_at", "sc_member_at",
    "general_at", "ticket_source_url", "ticket_source_name", "ticket_note",
    "last_checked",
]
NEWS_COLUMNS = ["published_at", "title", "url", "fetched_at"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 "
        "club-ticket-navi/1.0"
    ),
    "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
}

# 2026/27 J1の対戦クラブを中心に収録。URLは公式ドメインだけを検索対象にする。
OFFICIAL_DOMAINS = {
    "Ｖ・ファーレン長崎": "v-varen.com",
    "V・ファーレン長崎": "v-varen.com",
    "川崎フロンターレ": "frontale.co.jp",
    "水戸ホーリーホック": "mito-hollyhock.net",
    "アビスパ福岡": "avispa.co.jp",
    "横浜Ｆ・マリノス": "f-marinos.com",
    "横浜F・マリノス": "f-marinos.com",
    "ＦＣ東京": "fctokyo.co.jp",
    "FC東京": "fctokyo.co.jp",
    "柏レイソル": "reysol.co.jp",
    "ファジアーノ岡山": "fagiano-okayama.com",
    "ＦＣ町田ゼルビア": "zelvia.co.jp",
    "FC町田ゼルビア": "zelvia.co.jp",
    "サンフレッチェ広島": "sanfrecce.co.jp",
    "鹿島アントラーズ": "antlers.co.jp",
    "ガンバ大阪": "gamba-osaka.net",
    "名古屋グランパス": "nagoya-grampus.jp",
    "浦和レッズ": "urawa-reds.co.jp",
    "セレッソ大阪": "cerezo.jp",
    "東京ヴェルディ": "verdy.co.jp",
    "ジェフユナイテッド千葉": "jefunited.co.jp",
    "ジェフユナイテッド市原・千葉": "jefunited.co.jp",
    "ヴィッセル神戸": "vissel-kobe.co.jp",
    "清水エスパルス": "s-pulse.co.jp",
    "京都サンガF.C.": "sanga-fc.jp",
}

DATE_MD_RE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])[./月](3[01]|[12]?\d)(?:日)?")
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)")
ROUND_RE = re.compile(r"(第\s*\d+\s*節|第\s*\d+\s*回戦|準々決勝|準決勝|決勝|プレーオフ[^\s]*)")


@dataclass
class SearchCandidate:
    title: str
    url: str
    snippet: str = ""


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def get(url: str, *, timeout: int = 30) -> requests.Response:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response


def detect_season_label(soup: BeautifulSoup) -> str:
    selected = soup.select_one("select option[selected]")
    if selected:
        value = normalize_space(selected.get_text(" ", strip=True))
        if re.fullmatch(r"20\d{2}(?:/\d{2})?", value):
            return value
    text = soup.get_text(" ", strip=True)
    match = re.search(r"シーズン\s*(20\d{2}(?:/\d{2})?)", text)
    if match:
        return match.group(1)
    match = re.search(r"年次選択\s*(20\d{2}(?:/\d{2})?)", text)
    return match.group(1) if match else "2026/27"


def infer_year(season: str, month: int) -> int:
    if "/" in season:
        first = int(season[:4])
        # 秋春制。7～12月は前半年、1～6月は後半年。
        return first if month >= 7 else first + 1
    return int(season[:4]) if re.match(r"20\d{2}", season) else datetime.now(JST).year


def extract_date_and_time(text: str, season: str) -> tuple[str, str, str]:
    dates = list(DATE_MD_RE.finditer(text))
    if not dates:
        return "", "日程未定", "9999-12-31"
    first = dates[0]
    month, day = int(first.group(1)), int(first.group(2))
    year = infer_year(season, month)
    base_date = date(year, month, day)

    time_match = TIME_RE.search(text[first.end():])
    kickoff = ""
    if time_match and "キックオフ未定" not in text:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        kickoff = datetime.combine(base_date, dt_time(hour, minute), tzinfo=JST).isoformat(timespec="minutes")

    if len(dates) >= 2 and re.search(r"\bor\b|または|もしくは", text, re.IGNORECASE):
        second = dates[1]
        m2, d2 = int(second.group(1)), int(second.group(2))
        y2 = infer_year(season, m2)
        date_text = f"{year}/{month}/{day} または {y2}/{m2}/{d2}"
    else:
        date_text = f"{year}/{month}/{day}"
        if time_match and "キックオフ未定" not in text:
            date_text += f" {int(time_match.group(1)):02d}:{int(time_match.group(2)):02d}"
        elif "キックオフ未定" in text:
            date_text += " 時刻未定"
    return kickoff, date_text, base_date.isoformat()


def nearest_match_container(link: Tag, team_aliases: list[str]) -> Tag:
    best: Tag = link
    for parent in link.parents:
        if not isinstance(parent, Tag) or parent.name in {"body", "html"}:
            break
        text = normalize_space(parent.get_text(" ", strip=True))
        has_side = bool(re.search(r"\b(?:HOME|AWAY)\b", text))
        has_team = any(alias in text for alias in team_aliases)
        has_date = bool(DATE_MD_RE.search(text) or "日程未定" in text)
        if has_side and has_team and has_date:
            best = parent
            # 小さすぎず、他試合を巻き込みにくいサイズを優先。
            if len(text) >= 35:
                return parent
    return best


def extract_opponent(container: Tag, aliases: list[str]) -> str:
    candidates: list[str] = []
    for img in container.find_all("img"):
        alt = normalize_space(img.get("alt", ""))
        alt = re.sub(r"^(?:ロゴ|エンブレム)[：:]\s*", "", alt)
        if alt:
            candidates.append(alt)
    for domain_name in OFFICIAL_DOMAINS:
        if domain_name in container.get_text(" ", strip=True):
            candidates.append(domain_name)
    unique: list[str] = []
    for candidate in candidates:
        if any(alias == candidate or alias in candidate for alias in aliases):
            continue
        if candidate not in unique and len(candidate) <= 30:
            unique.append(candidate)
    return unique[0] if unique else "対戦相手未取得"


def extract_stadium(text: str, opponent: str, aliases: list[str]) -> str:
    pieces = [normalize_space(piece) for piece in re.split(r"[\n\r]+", text) if normalize_space(piece)]
    banned = ["HOME", "AWAY", "vs", "放送予定", "DAZN", opponent, *aliases]
    for piece in pieces:
        round_match = ROUND_RE.search(piece)
        if round_match:
            rest = normalize_space(piece.replace(round_match.group(0), ""))
            if rest and not DATE_MD_RE.search(rest):
                return rest
    stadium_words = ("スタジアム", "競技場", "サッカー場", "ドーム", "フィールド", "パーク")
    for piece in pieces:
        if any(word in piece for word in stadium_words) and not any(piece == item for item in banned):
            return piece
    return "未定"


def competition_from_context(link: Tag, container: Tag) -> tuple[str, str]:
    text = normalize_space(container.get_text(" ", strip=True))
    if "ルヴァン" in text:
        return "ＪリーグＹＢＣルヴァンカップ", "ＪリーグYBCルヴァンカップ"
    if "天皇杯" in text:
        return "天皇杯", "天皇杯"
    if "Ｊ１" in text or "J1" in text or "明治安田" in text:
        return "Ｊ１リーグ", "明治安田Ｊ１リーグ"
    heading = link.find_previous(["h2", "h3", "h4"])
    if heading:
        heading_text = normalize_space(heading.get_text(" ", strip=True))
        if "ルヴァン" in heading_text:
            return "ＪリーグＹＢＣルヴァンカップ", heading_text
        if "天皇杯" in heading_text:
            return "天皇杯", heading_text
        if "Ｊ１" in heading_text or "J1" in heading_text:
            return "Ｊ１リーグ", heading_text
    return "その他試合", "その他試合"


def compute_kyoto_home_sales(match_date: date) -> dict[str, str]:
    """京都公式の2026/27販売ルールを日付へ展開する。"""
    target_general = match_date - timedelta(days=21)
    general_sat = target_general - timedelta(days=(target_general.weekday() - 5) % 7)
    target_pass = match_date - timedelta(days=28)
    pass_sat = target_pass - timedelta(days=(target_pass.weekday() - 5) % 7)
    monday = general_sat - timedelta(days=5)
    wednesday = general_sat - timedelta(days=3)
    friday = general_sat - timedelta(days=1)

    def at(day: date, hour: int) -> str:
        return datetime.combine(day, dt_time(hour, 0), tzinfo=JST).isoformat(timespec="minutes")

    return {
        "season_pass_at": at(pass_sat, 11),
        "sc_fastest_at": at(monday, 12),
        "sc_early_at": at(wednesday, 12),
        "sc_member_at": at(friday, 12),
        "general_at": at(general_sat, 12),
    }


def parse_matches(html_text: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    season = detect_season_label(soup)
    aliases = [str(x) for x in TEAM.get("team_aliases", [])]
    official_name = str(TEAM["team_name"])
    seen: set[str] = set()
    matches: list[dict[str, str]] = []

    links = soup.select('a[href*="/game/info/"]')
    for link in links:
        href = urljoin(base_url, str(link.get("href", "")))
        if not href or href in seen:
            continue
        seen.add(href)
        container = nearest_match_container(link, aliases)
        raw_text = container.get_text("\n", strip=True)
        text = normalize_space(raw_text)
        side_match = re.search(r"\b(HOME|AWAY)\b", text)
        if not side_match:
            continue
        side = side_match.group(1)
        opponent = extract_opponent(container, aliases)
        kickoff, date_text, sort_date = extract_date_and_time(text, season)
        round_match = ROUND_RE.search(text)
        round_name = normalize_space(round_match.group(1)) if round_match else ""
        stadium = extract_stadium(raw_text, opponent, aliases)
        group, competition = competition_from_context(link, container)
        home = official_name if side == "HOME" else opponent
        away = opponent if side == "HOME" else official_name
        key_source = f"{season}|{group}|{round_name}|{sort_date}|{side}|{opponent}"
        match_key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:16]
        row = {column: "" for column in MATCH_COLUMNS}
        row.update({
            "match_key": match_key,
            "season": season,
            "competition_group": group,
            "competition_name": competition,
            "round_name": round_name,
            "kickoff": kickoff,
            "date_text": date_text,
            "sort_date": sort_date,
            "side": side,
            "home": home,
            "away": away,
            "opponent": opponent,
            "stadium": stadium,
            "match_url": href,
            "last_checked": now_iso(),
        })
        if side == "HOME" and sort_date != "9999-12-31":
            sale_dates = compute_kyoto_home_sales(date.fromisoformat(sort_date))
            row.update(sale_dates)
            row["ticket_source_url"] = str(TEAM["ticket_schedule_url"])
            row["ticket_source_name"] = "京都サンガF.C.公式 チケット販売スケジュール"
        matches.append(row)

    # URLが取得できないページ変更時の誤った全消去を避けるため、最低1件を要求。
    if not matches:
        raise RuntimeError("京都公式試合ページから試合カードを取得できませんでした。HTML構造変更の可能性があります。")
    return matches


def parse_ticket_news(html_text: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    fetched_at = now_iso()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="/news/detail/"]'):
        url = urljoin(base_url, str(link.get("href", "")))
        if not url or url in seen:
            continue
        seen.add(url)
        text = normalize_space(link.get_text(" ", strip=True))
        parent_text = normalize_space(link.parent.get_text(" ", strip=True)) if link.parent else text
        combined = normalize_space(f"{parent_text} {text}")
        date_match = re.search(r"(20\d{2})[./年](\d{1,2})[./月](\d{1,2})日?", combined)
        if not date_match:
            continue
        published = f"{int(date_match.group(1)):04d}/{int(date_match.group(2)):02d}/{int(date_match.group(3)):02d}"
        title = re.sub(r"^.*?20\d{2}[./年]\d{1,2}[./月]\d{1,2}日?\s*", "", combined)
        title = re.sub(r"^チケット\s*", "", title)
        title = normalize_space(title)
        if not title:
            continue
        rows.append({"published_at": published, "title": title, "url": url, "fetched_at": fetched_at})
    rows.sort(key=lambda x: x["published_at"], reverse=True)
    return rows[:80]


def ddg_search(query: str, official_domain: str, max_results: int = 8) -> list[SearchCandidate]:
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    response = get(url, timeout=25)
    soup = BeautifulSoup(response.text, "html.parser")
    results: list[SearchCandidate] = []
    for item in soup.select(".result"):
        link = item.select_one("a.result__a")
        if not link:
            continue
        href = str(link.get("href", ""))
        title = normalize_space(link.get_text(" ", strip=True))
        snippet_node = item.select_one(".result__snippet")
        snippet = normalize_space(snippet_node.get_text(" ", strip=True)) if snippet_node else ""
        if official_domain not in href:
            continue
        results.append(SearchCandidate(title=title, url=href, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


def year_for_sale(month: int, match_date: date) -> int:
    candidates = [match_date.year - 1, match_date.year, match_date.year + 1]
    valid = [date(y, month, 1) for y in candidates]
    return min(valid, key=lambda d: abs((d - match_date).days)).year


def extract_general_sale(text: str, match_date: date) -> datetime | None:
    clean = normalize_space(text.replace("：", ":"))
    month_day = r"(?:(?P<year>20\d{2})[年/.-])?(?P<month>1[0-2]|0?[1-9])[月/.-](?P<day>3[01]|[12]?\d)日?"
    clock = r"(?P<hour>[01]?\d|2[0-3])[:時](?P<minute>[0-5]\d)?"
    patterns = [
        re.compile(rf"一般(?:販売|発売|向け販売).{{0,80}}?{month_day}.{{0,30}}?{clock}", re.I),
        re.compile(rf"{month_day}.{{0,30}}?{clock}.{{0,80}}?一般(?:販売|発売)", re.I),
        re.compile(rf"一般(?:販売|発売).{{0,80}}?{month_day}", re.I),
        re.compile(rf"{month_day}.{{0,80}}?一般(?:販売|発売)", re.I),
    ]
    for pattern in patterns:
        match = pattern.search(clean)
        if not match:
            continue
        month, day = int(match.group("month")), int(match.group("day"))
        year = int(match.group("year")) if match.groupdict().get("year") else year_for_sale(month, match_date)
        hour = int(match.groupdict().get("hour") or 10)
        minute = int(match.groupdict().get("minute") or 0)
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=JST)
        except ValueError:
            continue
        # 発売日は通常試合前。異常値は採用しない。
        if candidate.date() <= match_date and (match_date - candidate.date()).days <= 180:
            return candidate
    return None


def candidate_score(candidate: SearchCandidate, opponent: str, match_date: date) -> int:
    text = f"{candidate.title} {candidate.snippet}"
    score = 0
    if "チケット" in text:
        score += 4
    if "一般" in text and ("販売" in text or "発売" in text):
        score += 4
    if "京都" in text:
        score += 4
    if opponent in text:
        score += 1
    for token in (f"{match_date.month}/{match_date.day}", f"{match_date.month}月{match_date.day}日"):
        if token in text:
            score += 3
    if any(word in text for word in ("当日券", "イベント", "グッズ", "招待")):
        score -= 3
    return score


def find_away_ticket_info(row: dict[str, str]) -> tuple[str, str, str, str]:
    opponent = row["opponent"]
    domain = OFFICIAL_DOMAINS.get(opponent)
    if not domain or not row["sort_date"] or row["sort_date"] == "9999-12-31":
        return "", "", "", "対戦クラブ公式サイトの自動検索対象外"
    match_date = date.fromisoformat(row["sort_date"])
    queries = [
        f"site:{domain} 京都 チケット {match_date.month}月{match_date.day}日 一般販売",
        f"site:{domain} 京都戦 チケット 一般発売",
    ]
    candidates: list[SearchCandidate] = []
    for query in queries:
        try:
            candidates.extend(ddg_search(query, domain))
        except Exception:
            continue
        time.sleep(0.6)
    dedup: dict[str, SearchCandidate] = {c.url: c for c in candidates}
    ranked = sorted(dedup.values(), key=lambda c: candidate_score(c, opponent, match_date), reverse=True)
    best_url = ""
    best_title = ""
    for candidate in ranked[:6]:
        if candidate_score(candidate, opponent, match_date) < 3:
            continue
        if not best_url:
            best_url, best_title = candidate.url, candidate.title
        try:
            page = get(candidate.url, timeout=25)
            soup = BeautifulSoup(page.text, "html.parser")
            main = soup.select_one("main, article, .article, .news-detail, .entry-content") or soup
            sale = extract_general_sale(main.get_text(" ", strip=True), match_date)
            if sale:
                return sale.isoformat(timespec="minutes"), candidate.url, candidate.title, ""
        except Exception:
            continue
    if best_url:
        return "", best_url, best_title, "発売日時は公式記事内で確認してください"
    return "", "", "", "一般発売情報は未発表または自動取得できていません"


def load_previous() -> pd.DataFrame:
    if not MATCHES_PATH.exists() or MATCHES_PATH.stat().st_size == 0:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    try:
        df = pd.read_csv(MATCHES_PATH, dtype=str, keep_default_na=False)
    except Exception:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    for column in MATCH_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[MATCH_COLUMNS]


def merge_previous_away(rows: list[dict[str, str]], previous: pd.DataFrame) -> None:
    if previous.empty:
        return
    previous_by_key = {str(row["match_key"]): row for _, row in previous.iterrows()}
    for row in rows:
        if row["side"] != "AWAY":
            continue
        old = previous_by_key.get(row["match_key"])
        if old is None:
            continue
        for column in ("general_at", "ticket_source_url", "ticket_source_name", "ticket_note"):
            if not row.get(column) and old.get(column):
                row[column] = str(old[column])


def enrich_away_matches(rows: list[dict[str, str]], max_matches: int = 8) -> list[str]:
    warnings: list[str] = []
    today = datetime.now(JST).date()
    targets = [
        row for row in rows
        if row["side"] == "AWAY"
        and row["sort_date"] != "9999-12-31"
        and date.fromisoformat(row["sort_date"]) >= today
    ]
    targets.sort(key=lambda x: x["sort_date"])
    for row in targets[:max_matches]:
        try:
            general, source_url, source_name, note = find_away_ticket_info(row)
            if general:
                row["general_at"] = general
            if source_url:
                row["ticket_source_url"] = source_url
                row["ticket_source_name"] = source_name or f"{row['opponent']}公式"
            row["ticket_note"] = note
        except Exception as exc:
            row["ticket_note"] = "自動取得エラー。公式情報を確認してください"
            warnings.append(f"{row['opponent']}戦: {type(exc).__name__}")
    return warnings


def apply_manual_overrides(rows: list[dict[str, str]]) -> None:
    if not OVERRIDES_PATH.exists() or OVERRIDES_PATH.stat().st_size == 0:
        return
    with OVERRIDES_PATH.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        overrides = list(reader)
    for row in rows:
        for override in overrides:
            key_match = override.get("match_key", "") and override.get("match_key") == row["match_key"]
            field_match = (
                override.get("opponent", "") == row["opponent"]
                and override.get("sort_date", "") == row["sort_date"]
            )
            if not (key_match or field_match):
                continue
            for column in ("general_at", "ticket_source_url", "ticket_source_name", "ticket_note"):
                value = normalize_space(override.get(column, ""))
                if value:
                    row[column] = value


def write_outputs(matches: list[dict[str, str]], news: list[dict[str, str]], warnings: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    match_df = pd.DataFrame(matches)
    for column in MATCH_COLUMNS:
        if column not in match_df.columns:
            match_df[column] = ""
    match_df = match_df[MATCH_COLUMNS].sort_values(["sort_date", "competition_group"], kind="stable")
    match_df.to_csv(MATCHES_PATH, index=False, encoding="utf-8-sig")

    news_df = pd.DataFrame(news)
    for column in NEWS_COLUMNS:
        if column not in news_df.columns:
            news_df[column] = ""
    news_df[NEWS_COLUMNS].to_csv(NEWS_PATH, index=False, encoding="utf-8-sig")

    metadata = {
        "last_updated": now_iso(),
        "match_count": int(len(match_df)),
        "news_count": int(len(news_df)),
        "warnings": warnings,
        "show_warning": False,
        "sources": {
            "schedule": TEAM["schedule_url"],
            "ticket_news": TEAM["ticket_news_url"],
        },
    }
    METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    schedule_response = get(str(TEAM["schedule_url"]))
    ticket_response = get(str(TEAM["ticket_news_url"]))
    matches = parse_matches(schedule_response.text, str(TEAM["schedule_url"]))
    news = parse_ticket_news(ticket_response.text, str(TEAM["ticket_news_url"]))

    previous = load_previous()
    merge_previous_away(matches, previous)
    warnings = enrich_away_matches(matches)
    apply_manual_overrides(matches)
    write_outputs(matches, news, warnings)
    print(f"updated: matches={len(matches)} news={len(news)} warnings={len(warnings)}")


if __name__ == "__main__":
    main()
