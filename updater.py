from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

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

# アウェイ戦の一般発売日は、ユーザー指定の各クラブ公式ページだけを参照する。
# 検索エンジン経由ではなく、ここに登録したURLを直接取得する。
AWAY_SOURCE_DEFINITIONS = [
    ("水戸ホーリーホック", ["水戸"], "https://www.mito-hollyhock.net/news_cat/ticket/"),
    ("鹿島アントラーズ", ["鹿島"], "https://www.antlers.co.jp/blogs/news/260703cm5rd0"),
    ("浦和レッズ", ["浦和"], "https://www.urawa-reds.co.jp/ticket/saleperiod.php"),
    ("ジェフユナイテッド千葉", ["ジェフユナイテッド市原・千葉", "千葉"], "https://jefunited.co.jp/news/detail/5285"),
    ("柏レイソル", ["柏"], "https://www.reysol.co.jp/ticket/tktscd.php"),
    ("ＦＣ東京", ["FC東京"], "https://www.fctokyo.co.jp/ticket/price/"),
    ("東京ヴェルディ", ["東京V", "東京Ｖ"], "https://www.verdy.co.jp/content/ticket/buy/"),
    ("ＦＣ町田ゼルビア", ["FC町田ゼルビア", "町田"], "https://www.zelvia.co.jp/stadium-ticket/schedule/"),
    ("川崎フロンターレ", ["川崎"], "https://www.frontale.co.jp/tickets/"),
    ("横浜Ｆ・マリノス", ["横浜F・マリノス", "横浜FM", "横浜ＦＭ"], "https://www.f-marinos.com/ticket/schedule"),
    ("清水エスパルス", ["清水"], "https://www.s-pulse.co.jp/tickets/schedule"),
    ("名古屋グランパス", ["名古屋"], "https://nagoya-grampus.jp/ticket/schedule/"),
    ("京都サンガF.C.", ["京都サンガ", "京都"], "https://www.sanga-fc.jp/ticket/schedule"),
    ("ガンバ大阪", ["G大阪", "Ｇ大阪"], "https://www.gamba-osaka.net/ticket/schedule/"),
    ("セレッソ大阪", ["C大阪", "Ｃ大阪"], "https://www.cerezo.jp/ticket/"),
    ("ヴィッセル神戸", ["神戸"], "https://www.vissel-kobe.co.jp/ticket/schedule/"),
    ("ファジアーノ岡山", ["岡山"], "https://www.fagiano-okayama.com/ticket/ticket_schedule/"),
    ("サンフレッチェ広島", ["広島"], "https://www.sanfrecce.co.jp/tickets/schedule"),
    ("アビスパ福岡", ["福岡"], "https://www.avispa.co.jp/news/post-87276"),
    ("Ｖ・ファーレン長崎", ["V・ファーレン長崎", "長崎"], "https://www.v-varen.com/tickets_new"),
]

AWAY_TICKET_SOURCES: dict[str, dict[str, str]] = {}
for canonical_name, aliases, source_url in AWAY_SOURCE_DEFINITIONS:
    source = {"name": canonical_name, "url": source_url}
    for alias in [canonical_name, *aliases]:
        AWAY_TICKET_SOURCES[alias] = source

KYOTO_ALIASES = ("京都サンガF.C.", "京都サンガ", "京都")

DATE_MD_RE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])[./月](3[01]|[12]?\d)(?:日)?")
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)")
ROUND_RE = re.compile(r"(第\s*\d+\s*節|第\s*\d+\s*回戦|準々決勝|準決勝|決勝|プレーオフ[^\s]*)")


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
    for team_name in AWAY_TICKET_SOURCES:
        if team_name in container.get_text(" ", strip=True):
            candidates.append(team_name)
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


def get_away_ticket_source(opponent: str) -> dict[str, str] | None:
    """対戦相手名から、指定済みの公式チケット情報ページを返す。"""
    if opponent in AWAY_TICKET_SOURCES:
        return AWAY_TICKET_SOURCES[opponent]
    compact = normalize_space(opponent).replace(" ", "")
    for alias, source in AWAY_TICKET_SOURCES.items():
        alias_compact = alias.replace(" ", "")
        if compact == alias_compact or compact in alias_compact or alias_compact in compact:
            return source
    return None


def year_for_sale(month: int, match_date: date) -> int:
    candidates = [match_date.year - 1, match_date.year, match_date.year + 1]
    valid = [date(y, month, 1) for y in candidates]
    return min(valid, key=lambda d: abs((d - match_date).days)).year


def extract_general_sale(text: str, match_date: date) -> datetime | None:
    """「一般販売／一般発売」の近くにある日時を抽出する。"""
    clean = normalize_space(text.replace("：", ":"))
    month_day = r"(?:(?P<year>20\d{2})[年/.-])?(?P<month>1[0-2]|0?[1-9])[月/.-](?P<day>3[01]|[12]?\d)日?"
    clock = r"(?P<hour>[01]?\d|2[0-3])[:時](?P<minute>[0-5]\d)?"
    general = r"一般(?:販売|発売|向け販売|チケット販売)"
    patterns = [
        re.compile(rf"{general}.{{0,100}}?{month_day}.{{0,40}}?{clock}", re.I),
        re.compile(rf"{month_day}.{{0,40}}?{clock}.{{0,100}}?{general}", re.I),
        re.compile(rf"{general}.{{0,100}}?{month_day}", re.I),
        re.compile(rf"{month_day}.{{0,100}}?{general}", re.I),
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
        if candidate.date() <= match_date and (match_date - candidate.date()).days <= 180:
            return candidate
    return None


def match_date_tokens(match_date: date) -> tuple[str, ...]:
    return (
        f"{match_date.month}/{match_date.day}",
        f"{match_date.month:02d}/{match_date.day:02d}",
        f"{match_date.month}.{match_date.day}",
        f"{match_date.month:02d}.{match_date.day:02d}",
        f"{match_date.month}月{match_date.day}日",
        f"{match_date.year}/{match_date.month}/{match_date.day}",
        f"{match_date.year}.{match_date.month}.{match_date.day}",
    )


def tag_text(tag: Tag) -> str:
    """本文に画像altも加え、対戦相手名を拾いやすくする。"""
    parts = [tag.get_text(" ", strip=True)]
    parts.extend(normalize_space(str(img.get("alt", ""))) for img in tag.find_all("img"))
    return normalize_space(" ".join(part for part in parts if part))


def contains_kyoto(text: str) -> bool:
    return any(alias in text for alias in KYOTO_ALIASES)


def extract_candidate_datetimes(text: str, match_date: date) -> list[datetime]:
    """試合日より前にある発売日候補をすべて抽出する。"""
    clean = normalize_space(text.replace("：", ":"))
    pattern = re.compile(
        r"(?:(?P<year>20\d{2})\s*[年/.-]\s*)?"
        r"(?P<month>1[0-2]|0?[1-9])\s*[月/.-]\s*"
        r"(?P<day>3[01]|[12]?\d)\s*日?"
        r"(?:\s*[（(][^）)]{0,12}[）)])?"
        r"(?:\s*(?P<hour>[01]?\d|2[0-3])\s*[:時]\s*(?P<minute>[0-5]\d)?\s*分?)?"
    )
    candidates: list[datetime] = []
    for match in pattern.finditer(clean):
        month, day = int(match.group("month")), int(match.group("day"))
        year = int(match.group("year")) if match.group("year") else year_for_sale(month, match_date)
        hour = int(match.group("hour") or 10)
        minute = int(match.group("minute") or 0)
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=JST)
        except ValueError:
            continue
        days_before = (match_date - candidate.date()).days
        if 0 < days_before <= 180 and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def candidate_block_score(text: str, match_date: date) -> int:
    score = 0
    if contains_kyoto(text):
        score += 60
    if any(token in text for token in match_date_tokens(match_date)):
        score += 45
    if re.search(r"一般(?:販売|発売)", text):
        score += 30
    if "チケット" in text:
        score += 5
    # 大きな親要素より、1試合分に近い小さな要素を優先する。
    score -= min(len(text) // 250, 20)
    return score


def extract_general_sale_from_page(html_text: str, match_date: date) -> datetime | None:
    """クラブごとに異なる表・カード型ページから一般発売日時を抽出する。"""
    soup = BeautifulSoup(html_text, "html.parser")
    tokens = match_date_tokens(match_date)

    # 表形式：対象行に複数の先行日がある場合、試合日前で最も遅い日時を一般発売として扱う。
    for row in soup.find_all("tr"):
        text = tag_text(row)
        if not (contains_kyoto(text) or any(token in text for token in tokens)):
            continue
        direct = extract_general_sale(text, match_date)
        if direct:
            return direct
        table = row.find_parent("table")
        table_text = tag_text(table) if isinstance(table, Tag) else ""
        if re.search(r"一般(?:販売|発売)", table_text):
            candidates = extract_candidate_datetimes(text, match_date)
            if candidates:
                return max(candidates)

    # カード／記事形式：京都名または試合日を含む小さな要素から順に確認する。
    blocks: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for tag in soup.find_all(["article", "section", "li", "dl", "div"]):
        text = tag_text(tag)
        if not text or text in seen or len(text) > 4500:
            continue
        if not (contains_kyoto(text) or any(token in text for token in tokens)):
            continue
        seen.add(text)
        blocks.append((candidate_block_score(text, match_date), len(text), text))
    blocks.sort(key=lambda item: (-item[0], item[1]))

    for score, _, text in blocks[:80]:
        if score < 40:
            continue
        direct = extract_general_sale(text, match_date)
        if direct:
            return direct
        # 同一カード内に一般発売ラベルがあり、日時が列分割されている場合の補完。
        if re.search(r"一般(?:販売|発売)", text):
            candidates = extract_candidate_datetimes(text, match_date)
            if candidates:
                return max(candidates)

    # 最終フォールバック。ページ全体から京都戦の周辺だけを切り出す。
    page_text = tag_text(soup)
    anchors: list[int] = []
    for alias in KYOTO_ALIASES:
        anchors.extend(match.start() for match in re.finditer(re.escape(alias), page_text))
    for token in tokens:
        anchors.extend(match.start() for match in re.finditer(re.escape(token), page_text))
    for anchor in sorted(set(anchors)):
        window = page_text[max(0, anchor - 260): anchor + 900]
        if not (contains_kyoto(window) and any(token in window for token in tokens)):
            continue
        direct = extract_general_sale(window, match_date)
        if direct:
            return direct
    return None


def find_away_ticket_info(
    row: dict[str, str],
    page_cache: dict[str, str] | None = None,
) -> tuple[str, str, str, str]:
    opponent = row["opponent"]
    source = get_away_ticket_source(opponent)
    if not source:
        return "", "", "", "対戦クラブの公式チケットページが未登録です"
    source_url = source["url"]
    source_name = f"{source['name']}公式 チケット販売情報"
    if not row["sort_date"] or row["sort_date"] == "9999-12-31":
        return "", source_url, source_name, "試合日確定後に一般発売日を確認します"

    match_date = date.fromisoformat(row["sort_date"])
    cache = page_cache if page_cache is not None else {}
    if source_url not in cache:
        cache[source_url] = get(source_url, timeout=30).text
    sale = extract_general_sale_from_page(cache[source_url], match_date)
    if sale:
        return sale.isoformat(timespec="minutes"), source_url, source_name, ""
    return "", source_url, source_name, "一般発売日は未発表または自動取得できていません"


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


def enrich_away_matches(rows: list[dict[str, str]]) -> list[str]:
    warnings: list[str] = []
    today = datetime.now(JST).date()
    targets = [
        row for row in rows
        if row["side"] == "AWAY"
        and row["sort_date"] != "9999-12-31"
        and date.fromisoformat(row["sort_date"]) >= today
    ]
    targets.sort(key=lambda x: x["sort_date"])
    page_cache: dict[str, str] = {}
    for row in targets:
        source = get_away_ticket_source(row["opponent"])
        if source:
            # 取得エラー時でも、指定された公式ページへのリンクは残す。
            row["ticket_source_url"] = source["url"]
            row["ticket_source_name"] = f"{source['name']}公式 チケット販売情報"
        try:
            general, source_url, source_name, note = find_away_ticket_info(row, page_cache)
            if general:
                row["general_at"] = general
            if source_url:
                row["ticket_source_url"] = source_url
                row["ticket_source_name"] = source_name
            row["ticket_note"] = note
        except Exception as exc:
            row["ticket_note"] = "公式ページを取得できませんでした。リンク先をご確認ください"
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
            "away_ticket_pages": {name: url for name, _, url in AWAY_SOURCE_DEFINITIONS},
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
