from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
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
OFFICIAL_SCHEDULES_PATH = DATA_DIR / "official_ticket_schedules.csv"
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

# 以下は京都サンガF.C.公式「試合日程・結果」だけを正とする項目。
# 対戦クラブのチケットページや補正CSVからは変更しない。
FIXTURE_SOURCE_COLUMNS = (
    "season", "competition_group", "competition_name", "round_name",
    "kickoff", "date_text", "sort_date", "side", "home", "away",
    "opponent", "stadium", "match_url",
)

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
GENERAL_SALE_LABEL = r"一般\s*(?:向け\s*)?(?:前売\s*)?(?:販売|発売)(?:日)?"
GENERAL_SALE_LABEL_RE = re.compile(GENERAL_SALE_LABEL, re.I)

# 試合日・会場・大会・H/A・対戦カードは、京都公式「試合日程・結果」
# の取得結果だけを正とする。静的な試合補正は持たない。
OFFICIAL_FIXTURE_CORRECTIONS: tuple[dict[str, str], ...] = ()


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
    """試合リンクを含む、1試合分のカード要素を選ぶ。

    京都公式では会場名が対戦カード本体の外側に置かれることがあるため、
    単純に最小の親要素を返すと会場を取りこぼす。試合リンク数、節、
    会場らしい文字列を加点し、複数試合を巻き込む大きな親要素は減点する。
    """
    best: Tag = link
    best_score = -10_000
    stadium_words = (
        "スタジアム", "競技場", "サッカー場", "ドーム",
        "フィールド", "パーク", "アリーナ", "ウイング",
    )
    for depth, parent in enumerate(link.parents):
        if not isinstance(parent, Tag) or parent.name in {"body", "html"}:
            break
        text = normalize_space(parent.get_text(" ", strip=True))
        has_side = bool(re.search(r"\b(?:HOME|AWAY)\b", text))
        has_team = any(alias in text for alias in team_aliases)
        has_date = bool(DATE_MD_RE.search(text) or "日程未定" in text)
        if not (has_side and has_team and has_date):
            continue

        game_link_count = len(parent.select('a[href*="/game/info/"]'))
        has_round = bool(ROUND_RE.search(text))
        has_stadium = any(word in text for word in stadium_words)
        score = 0
        score += 120 if game_link_count == 1 else -100 * max(game_link_count - 1, 1)
        score += 35 if has_stadium else 0
        score += 20 if has_round else 0
        score -= min(len(text) // 180, 35)
        score -= depth
        if score > best_score:
            best = parent
            best_score = score
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
    """京都公式の日程カードから会場名を抽出する。

    「第10節」と「エディオンピースウイング広島」が別要素の場合にも、
    節の直後にある候補を会場として扱う。試合日やチーム名は除外する。
    """
    pieces = [normalize_space(piece) for piece in re.split(r"[\n\r]+", text) if normalize_space(piece)]
    banned_exact = {"HOME", "AWAY", "vs", "VS", "放送予定", "DAZN", opponent, *aliases}

    def plausible(candidate: str) -> bool:
        if not candidate or candidate in banned_exact:
            return False
        if DATE_MD_RE.search(candidate) or TIME_RE.search(candidate):
            return False
        if ROUND_RE.fullmatch(candidate):
            return False
        if any(word in candidate for word in ("京都サンガ", "放送予定", "オフィシャルチケット", "試合情報")):
            return False
        return len(candidate) <= 80

    for index, piece in enumerate(pieces):
        round_match = ROUND_RE.search(piece)
        if not round_match:
            continue
        rest = normalize_space(piece.replace(round_match.group(0), ""))
        if plausible(rest):
            return rest
        # 節と会場が別タグになっているケース。節の直後を優先する。
        for candidate in pieces[index + 1:index + 4]:
            if plausible(candidate):
                return candidate

    stadium_words = (
        "スタジアム", "競技場", "サッカー場", "ドーム",
        "フィールド", "パーク", "アリーナ", "ウイング",
    )
    for piece in pieces:
        if any(word in piece for word in stadium_words) and plausible(piece):
            return piece
    return "未定"


def competition_from_context(link: Tag, container: Tag) -> tuple[str, str]:
    """大会名は京都公式ページの大会見出しだけを正とする。

    試合カード内の注記には「ルヴァンカップ決勝進出時は…」のような
    文言が含まれるため、カード本文から大会を推測するとJ1福岡戦などを
    誤分類する。最も近い直前の大会見出しを参照する。
    """
    heading = link.find_previous(["h2", "h3"])
    if heading:
        heading_text = normalize_space(heading.get_text(" ", strip=True))
        if "ルヴァン" in heading_text:
            return "ＪリーグＹＢＣルヴァンカップ", heading_text
        if "天皇杯" in heading_text:
            return "天皇杯", heading_text
        if "Ｊ１" in heading_text or "J1" in heading_text or "明治安田" in heading_text:
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


def fixture_match_key(row: dict[str, str]) -> str:
    key_source = (
        f"{row.get('season', '')}|{row.get('competition_group', '')}|"
        f"{row.get('round_name', '')}|{row.get('sort_date', '')}|"
        f"{row.get('side', '')}|{row.get('opponent', '')}"
    )
    return hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:16]


def normalize_round_name(value: str) -> str:
    return normalize_space(value).replace("第", "").replace(" ", "")


def apply_official_fixture_corrections(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """後方互換用。試合情報は京都公式日程ページをそのまま採用する。"""
    return rows


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
    return apply_official_fixture_corrections(matches)


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


def canonical_club_name(value: str) -> str:
    """クラブ名の表記揺れを、公式チケット参照先の名称へ寄せる。"""
    normalized = unicodedata.normalize("NFKC", normalize_space(value))
    source = get_away_ticket_source(normalized)
    if source:
        return source["name"]
    return normalized.replace(" ", "")


def normalized_key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def load_official_ticket_schedules(
    path: Path | None = None,
) -> list[dict[str, str]]:
    """公式画像から人手でテキスト化した販売日程を読み込む。"""
    schedule_path = path or OFFICIAL_SCHEDULES_PATH
    if not schedule_path.exists() or schedule_path.stat().st_size == 0:
        return []
    with schedule_path.open(encoding="utf-8-sig", newline="") as file:
        return [
            {key: normalize_space(value) for key, value in row.items()}
            for row in csv.DictReader(file)
        ]


def apply_official_ticket_schedules(
    rows: list[dict[str, str]],
    *,
    team_name: str | None = None,
    path: Path | None = None,
) -> int:
    """画像掲載の公式販売日程をアウェイ戦へ反映する。

    日付が確定している行は日付を優先し、未定・複数日候補の行は
    節番号で照合する。別クラブ版でも同じCSVと処理を再利用できる。
    """
    schedules = load_official_ticket_schedules(path)
    if not schedules:
        return 0

    visitor = canonical_club_name(team_name or str(TEAM["team_name"]))
    applied = 0
    for row in rows:
        if row.get("side") != "AWAY":
            continue
        host = canonical_club_name(row.get("opponent", ""))
        row_date = row.get("sort_date", "")
        row_round = normalized_key(row.get("round_name", ""))
        row_competition = normalized_key(row.get("competition_group", ""))

        best: tuple[int, dict[str, str]] | None = None
        for schedule in schedules:
            if canonical_club_name(schedule.get("host_club", "")) != host:
                continue
            if canonical_club_name(schedule.get("visitor_club", "")) != visitor:
                continue
            schedule_competition = normalized_key(schedule.get("competition_group", ""))
            if schedule_competition and row_competition and schedule_competition != row_competition:
                continue

            schedule_date = schedule.get("match_date", "")
            schedule_round = normalized_key(schedule.get("round_name", ""))
            date_match = bool(schedule_date and row_date and schedule_date == row_date)
            round_match = bool(schedule_round and row_round and schedule_round == row_round)
            if not (date_match or round_match):
                continue
            score = (2 if date_match else 0) + (1 if round_match else 0)
            if best is None or score > best[0]:
                best = (score, schedule)

        if best is None:
            continue
        schedule = best[1]
        for source_column, target_column in (
            ("general_at", "general_at"),
            ("source_url", "ticket_source_url"),
            ("source_name", "ticket_source_name"),
            ("ticket_note", "ticket_note"),
        ):
            value = schedule.get(source_column, "")
            if value:
                row[target_column] = value
        row["_official_schedule_applied"] = "1"
        applied += 1
    return applied


def year_for_sale(month: int, match_date: date) -> int:
    candidates = [match_date.year - 1, match_date.year, match_date.year + 1]
    valid = [date(y, month, 1) for y in candidates]
    return min(valid, key=lambda d: abs((d - match_date).days)).year


def extract_general_sale(text: str, match_date: date) -> datetime | None:
    """「一般販売／一般発売／一般向け前売発売日」の近くにある日時を抽出する。"""
    clean = normalize_space(text.replace("：", ":"))
    month_day = r"(?:(?P<year>20\d{2})[年/.-])?(?P<month>1[0-2]|0?[1-9])[月/.-](?P<day>3[01]|[12]?\d)日?"
    clock = r"(?P<hour>[01]?\d|2[0-3])[:時](?P<minute>[0-5]\d)?"
    general = GENERAL_SALE_LABEL
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
    if GENERAL_SALE_LABEL_RE.search(text):
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
        if GENERAL_SALE_LABEL_RE.search(table_text):
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
        if GENERAL_SALE_LABEL_RE.search(text):
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
        and not row.get("_official_schedule_applied")
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


def capture_fixture_fields(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {column: row.get(column, "") for column in FIXTURE_SOURCE_COLUMNS}
        for row in rows
    ]


def assert_fixture_fields_unchanged(
    expected: list[dict[str, str]],
    rows: list[dict[str, str]],
) -> None:
    actual = capture_fixture_fields(rows)
    if actual != expected:
        raise RuntimeError(
            "チケット情報の反映処理が、京都公式を正とする試合日程項目を変更しました。"
        )


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
            "official_ticket_schedules": str(OFFICIAL_SCHEDULES_PATH.name),
        },
    }
    METADATA_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    schedule_response = get(str(TEAM["schedule_url"]))
    ticket_response = get(str(TEAM["ticket_news_url"]))
    matches = parse_matches(schedule_response.text, str(TEAM["schedule_url"]))
    news = parse_ticket_news(ticket_response.text, str(TEAM["ticket_news_url"]))

    # 試合日・会場・大会・対戦カードは京都公式日程ページの値を固定する。
    fixture_snapshot = capture_fixture_fields(matches)
    previous = load_previous()
    merge_previous_away(matches, previous)
    official_schedule_count = apply_official_ticket_schedules(matches)
    warnings = enrich_away_matches(matches)
    apply_manual_overrides(matches)
    assert_fixture_fields_unchanged(fixture_snapshot, matches)
    write_outputs(matches, news, warnings)
    print(
        f"updated: matches={len(matches)} news={len(news)} "
        f"official_schedules={official_schedule_count} warnings={len(warnings)}"
    )


if __name__ == "__main__":
    main()
