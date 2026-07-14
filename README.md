from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dateutil import parser as dtparser

from site_config import get_team_config

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MATCHES_PATH = DATA_DIR / "matches.csv"
NEWS_PATH = DATA_DIR / "ticket_news.csv"
METADATA_PATH = DATA_DIR / "metadata.json"
JST = timezone(timedelta(hours=9))

TEAM = get_team_config()
SALE_LABELS = TEAM.get("home_sale_labels", {})

MATCH_COLUMNS = [
    "match_key", "season", "competition_group", "competition_name",
    "round_name", "kickoff", "date_text", "sort_date", "side",
    "home", "away", "opponent", "stadium", "match_url",
    "season_pass_at", "sc_fastest_at", "sc_early_at", "sc_member_at",
    "general_at", "ticket_source_url", "ticket_source_name", "ticket_note",
    "last_checked",
]
NEWS_COLUMNS = ["published_at", "title", "url", "fetched_at"]

st.set_page_config(
    page_title=str(TEAM["page_title"]),
    page_icon=str(TEAM.get("page_icon", "🎟️")),
    layout="wide",
    initial_sidebar_state="collapsed",
)


def read_csv_safe(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (pd.errors.EmptyDataError, UnicodeDecodeError):
        return pd.DataFrame(columns=columns)
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df[columns].fillna("")


def read_metadata() -> dict:
    if not METADATA_PATH.exists():
        return {}
    try:
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def format_datetime(value: str, empty: str = "未発表") -> str:
    if not value or value in ("None", "nan", "NaT"):
        return empty
    try:
        dt = dtparser.isoparse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST).strftime("%Y/%m/%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return value


def format_match_date(kickoff: str, date_text: str) -> str:
    """スマホ表示用に試合日だけを返す。"""
    if kickoff:
        try:
            dt = dtparser.isoparse(kickoff)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            return dt.astimezone(JST).strftime("%Y/%m/%d")
        except (TypeError, ValueError, OverflowError):
            pass
    match = re.search(r"20\d{2}[/-]\d{1,2}[/-]\d{1,2}", date_text or "")
    if match:
        return match.group(0).replace("-", "/")
    return date_text or "未定"


def build_mobile_match_cards(df: pd.DataFrame) -> str:
    """スマホ版は誤タップ回避のため、試合リンクをカード内に置かない。"""
    cards: list[str] = []
    for _, row in df.iterrows():
        side = row["side"]
        side_label = "H" if side == "HOME" else "A"
        side_class = "home" if side == "HOME" else "away"
        match_date = format_match_date(row["kickoff"], row["date_text"])
        opponent = row["opponent"] or (
            row["away"] if side == "HOME" else row["home"]
        )
        general_sale = format_datetime(row["general_at"])
        bold_class = (
            " mobile-sale-bold"
            if side == "AWAY" and general_sale != "未発表"
            else ""
        )
        note = row.get("ticket_note", "")
        note_html = ""
        if note:
            note_html = (
                '<div class="mobile-ticket-note">'
                f'{html.escape(str(note))}</div>'
            )
        cards.append(
            f'<div class="mobile-match-card {side_class}">'
            '<div class="mobile-match-top">'
            f'<span class="mobile-match-date">{html.escape(match_date)}</span>'
            f'<span class="mobile-side-badge {side_class}">{side_label}</span>'
            f'<span class="mobile-opponent">{html.escape(str(opponent))}</span>'
            '</div>'
            '<div class="mobile-sale-row">'
            '<span class="mobile-sale-label">一般発売</span>'
            f'<span class="mobile-sale-value{bold_class}">'
            f'{html.escape(general_sale)}</span>'
            '</div>'
            f'{note_html}'
            '</div>'
        )
    return '<div class="mobile-match-list">' + "".join(cards) + "</div>"


def display_table(
    df: pd.DataFrame,
    filter_mode: str,
    include_competition: bool = False,
) -> None:
    if df.empty:
        st.info("該当する試合はありません。")
        return

    rows: list[dict] = []
    sides: list[str] = []
    for _, row in df.iterrows():
        is_home = row["side"] == "HOME"
        item = {
            "試合日": row["date_text"],
            "区分": "ホーム" if is_home else "アウェイ",
            "節・ラウンド": row["round_name"] or "—",
            "対戦カード": f"{row['home']} vs {row['away']}",
            "会場": row["stadium"] or "未定",
        }
        if filter_mode != "アウェイ":
            for key in ("season_pass_at", "sc_fastest_at", "sc_early_at", "sc_member_at"):
                label = str(SALE_LABELS.get(key, key))
                item[label] = format_datetime(row[key]) if is_home else "—"
        item["一般発売"] = format_datetime(row["general_at"])
        item["公式情報"] = row["ticket_source_url"] or row["match_url"]
        if include_competition:
            item = {"大会": row["competition_name"], **item}
        rows.append(item)
        sides.append(row["side"])

    view = pd.DataFrame(rows)

    def row_style(row: pd.Series) -> list[str]:
        side = sides[row.name]
        background = (
            f"background-color:{home_color}"
            if side == "HOME"
            else f"background-color:{away_color}"
        )
        styles = [background] * len(row)
        if side == "AWAY" and row.get("一般発売") != "未発表":
            column_index = view.columns.get_loc("一般発売")
            styles[column_index] = background + ";font-weight:700"
        return styles

    base_config: dict[str, object] = {
        "試合日": st.column_config.TextColumn("試合日", width=108),
        "区分": st.column_config.TextColumn("区分", width=72),
        "節・ラウンド": st.column_config.TextColumn("節・ラウンド", width=90),
        "対戦カード": st.column_config.TextColumn("対戦カード", width=245),
        "会場": st.column_config.TextColumn("会場", width=150),
        "一般発売": st.column_config.TextColumn("一般発売", width=130),
        "公式情報": st.column_config.LinkColumn(
            "公式情報", display_text="確認", width=72
        ),
    }
    if "大会" in view.columns:
        base_config["大会"] = st.column_config.TextColumn("大会", width=100)
    for key in ("season_pass_at", "sc_fastest_at", "sc_early_at", "sc_member_at"):
        label = str(SALE_LABELS.get(key, key))
        if label in view.columns:
            base_config[label] = st.column_config.TextColumn(label, width=130)

    st.markdown(build_mobile_match_cards(df), unsafe_allow_html=True)
    st.dataframe(
        view.style.apply(row_style, axis=1),
        use_container_width=True,
        hide_index=True,
        column_config=base_config,
    )


home_color = str(TEAM.get("home_row_color", "#f1eafd"))
away_color = str(TEAM.get("away_row_color", "#fff2df"))
brand_primary = str(TEAM.get("brand_primary", "#5b2a86"))
brand_secondary = str(TEAM.get("brand_secondary", "#d5a100"))
home_badge = str(TEAM.get("home_badge_color", brand_primary))
away_badge = str(TEAM.get("away_badge_color", "#c56b13"))

st.markdown(
    f"""
<style>
[data-testid="stSidebar"] {{display:none;}}
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] .main {{overflow-x:hidden;}}
.block-container {{max-width:1480px; padding-top:2.3rem; padding-bottom:2rem;}}
[data-testid="stDataFrame"] {{width:100% !important;}}
[data-testid="stDataFrameResizable"] {{width:100% !important;}}
.home-legend,.away-legend {{
  display:inline-block; padding:3px 10px; border-radius:5px;
  margin-right:8px; font-size:.85rem; border:1px solid rgba(0,0,0,.08);
}}
.home-legend {{background:{home_color};}}
.away-legend {{background:{away_color};}}
.desktop-title-wrap {{display:flex; align-items:center; gap:14px; margin:2px 0 8px;}}
.mobile-title-wrap {{display:none;}}
.ticket-icon {{display:flex; align-items:center; gap:3px; flex:0 0 auto;}}
.ticket-main {{
  width:34px; height:22px; border-radius:6px; position:relative;
  background:{brand_primary};
  box-shadow:inset 0 0 0 1px rgba(0,0,0,.05);
}}
.ticket-main:before,.ticket-main:after {{
  content:""; position:absolute; top:7px; width:6px; height:8px;
  background:#fff; border-radius:50%; opacity:.95;
}}
.ticket-main:before {{left:-3px;}}
.ticket-main:after {{right:-3px;}}
.ticket-stub {{
  width:9px; height:22px; border-radius:4px;
  background:{brand_primary};
}}
.desktop-app-title {{font-size:2.55rem; font-weight:800; line-height:1.15; margin:0; min-width:0;}}
.mobile-match-list,.mobile-news-list {{display:none;}}
.mobile-match-card {{
  border:1px solid rgba(0,0,0,.08); border-radius:10px; padding:10px 11px;
  margin:0 0 8px; box-shadow:0 1px 3px rgba(0,0,0,.04);
}}
.mobile-match-card.home {{background:{home_color};}}
.mobile-match-card.away {{background:{away_color};}}
.mobile-match-top {{display:grid; grid-template-columns:auto auto minmax(0,1fr); align-items:center; gap:7px;}}
.mobile-match-date {{font-weight:600; font-size:.84rem; white-space:nowrap;}}
.mobile-side-badge {{
  display:inline-flex; align-items:center; justify-content:center;
  width:24px; height:24px; border-radius:6px; font-size:.78rem; font-weight:800; color:white;
}}
.mobile-side-badge.home {{background:{home_badge};}}
.mobile-side-badge.away {{background:{away_badge};}}
.mobile-opponent {{font-weight:700; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}}
.mobile-sale-row {{
  display:flex; justify-content:space-between; align-items:center; gap:12px;
  border-top:1px solid rgba(0,0,0,.08); margin-top:8px; padding-top:7px;
}}
.mobile-sale-label {{font-size:.78rem; color:#64748b;}}
.mobile-sale-value {{font-size:.88rem;}}
.mobile-sale-bold {{font-weight:800;}}
.mobile-ticket-note {{font-size:.72rem; color:#7c2d12; margin-top:5px; line-height:1.35;}}
.mobile-news-item {{
  display:block; padding:9px 10px; margin-bottom:7px;
  border:1px solid #e2e8f0; border-radius:8px; background:#fff;
  color:#0f172a !important; text-decoration:none !important;
}}
.mobile-news-item span {{display:block; color:#64748b; font-size:.75rem; margin-bottom:2px;}}
.mobile-news-item strong {{font-size:.88rem; line-height:1.35;}}
@media (max-width:900px) {{.desktop-app-title {{font-size:2rem;}}}}
@media (max-width:700px) {{
  html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] .main {{
    width:100%; max-width:100%; overflow-x:hidden !important;
  }}
  .block-container {{
    width:100%; max-width:100%; box-sizing:border-box;
    padding-left:1rem; padding-right:1rem; padding-top:4.75rem; overflow-x:hidden !important;
  }}
  [data-testid="stDataFrame"] {{display:none !important;}}
  .mobile-match-list,.mobile-news-list {{display:block;}}
  .desktop-title-wrap {{display:none !important;}}
  .mobile-title-wrap {{
    display:flex !important; align-items:flex-start; gap:9px;
    width:100%; max-width:100%; margin:0 0 10px; box-sizing:border-box; overflow:hidden;
  }}
  .mobile-title-text {{
    min-width:0; max-width:calc(100% - 48px); font-weight:800;
    color:#262730; letter-spacing:-.035em;
  }}
  .mobile-title-main {{display:block; font-size:1.48rem; line-height:1.18; white-space:nowrap; overflow:hidden;}}
  .mobile-title-edition {{display:block; font-size:1.30rem; line-height:1.18; margin-top:3px; white-space:nowrap;}}
  .mobile-title-wrap .ticket-icon {{display:flex !important; margin-top:3px; flex:0 0 auto;}}
  .mobile-title-wrap .ticket-main {{width:27px; height:18px;}}
  .mobile-title-wrap .ticket-main:before,.mobile-title-wrap .ticket-main:after {{top:5px; height:7px;}}
  .mobile-title-wrap .ticket-stub {{width:7px; height:18px;}}
}}
</style>
<div class="desktop-title-wrap">
  <div class="ticket-icon"><div class="ticket-stub"></div><div class="ticket-main"></div></div>
  <h1 class="desktop-app-title">{html.escape(str(TEAM['service_name']))}｜{html.escape(str(TEAM['edition_name']))}</h1>
</div>
<div class="mobile-title-wrap">
  <div class="ticket-icon"><div class="ticket-stub"></div><div class="ticket-main"></div></div>
  <div class="mobile-title-text">
    <span class="mobile-title-main">{html.escape(str(TEAM['service_name']))}</span>
    <span class="mobile-title-edition">{html.escape(str(TEAM['edition_name']))}</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)
st.caption(f"{TEAM['subtitle']}｜{TEAM.get('season_label', '')}・非公式")

metadata = read_metadata()
last_updated = metadata.get("last_updated", "")
if last_updated:
    st.caption(f"最終更新：{format_datetime(last_updated, last_updated)}")
else:
    st.warning("データ更新待ちです。GitHub Actionsの『Run workflow』を実行してください。")

warnings = metadata.get("warnings", [])
if warnings and metadata.get("show_warning", False):
    with st.expander("データ取得時の注意"):
        for warning in warnings:
            st.write(f"・{warning}")

matches = read_csv_safe(MATCHES_PATH, MATCH_COLUMNS)
news = read_csv_safe(NEWS_PATH, NEWS_COLUMNS)

if not matches.empty:
    matches = matches.sort_values(["sort_date", "competition_group"], kind="stable")

if matches.empty:
    st.info("試合データはまだありません。初回データ更新後に表示されます。")
else:
    filter_mode = st.radio(
        "開催区分", ["すべて", "ホーム", "アウェイ"], horizontal=True, index=0
    )
    hide_finished = st.checkbox(
        "終了済みの試合を非表示",
        value=True,
        help="試合日が今日より前の試合を一覧から除外します。",
    )

    if filter_mode == "ホーム":
        filtered = matches[matches["side"] == "HOME"].copy()
    elif filter_mode == "アウェイ":
        filtered = matches[matches["side"] == "AWAY"].copy()
    else:
        filtered = matches.copy()

    if hide_finished:
        today_jst = datetime.now(JST).date()

        def is_upcoming_match(row: pd.Series) -> bool:
            for value in (row.get("kickoff", ""), row.get("sort_date", "")):
                if not value:
                    continue
                try:
                    dt = dtparser.isoparse(str(value))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=JST)
                    return dt.astimezone(JST).date() >= today_jst
                except (TypeError, ValueError, OverflowError):
                    continue
            match = re.search(r"20\d{2}[/-]\d{1,2}[/-]\d{1,2}", row.get("date_text", ""))
            if match:
                try:
                    return datetime.strptime(match.group(0).replace("/", "-"), "%Y-%m-%d").date() >= today_jst
                except ValueError:
                    pass
            return True

        filtered = filtered[filtered.apply(is_upcoming_match, axis=1)].copy()

    st.markdown(
        '<span class="home-legend">ホーム</span>'
        '<span class="away-legend">アウェイ</span>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["すべて", "Ｊ１リーグ", "ルヴァンカップ", "天皇杯", "その他試合"])
    with tabs[0]:
        display_table(filtered, filter_mode, include_competition=True)

    groups = ["Ｊ１リーグ", "ＪリーグＹＢＣルヴァンカップ", "天皇杯", "その他試合"]
    for tab, group in zip(tabs[1:], groups):
        with tab:
            display_table(filtered[filtered["competition_group"] == group], filter_mode)

    if filter_mode == "アウェイ":
        st.caption("アウェイでは、ホームクラブ発表の一般発売日時だけを表示します。")
    else:
        st.caption(
            "ホームはシーズンパス・SANGA CREW先行・一般発売、"
            "アウェイはホームクラブ発表の一般発売を表示します。"
        )

st.divider()
st.subheader(f"{TEAM['team_name']} チケットニュースリンク集")
st.link_button(
    f"{TEAM['team_name']}公式 チケットニュース一覧を開く",
    str(TEAM["ticket_news_url"]),
)
if news.empty:
    st.caption(f"初回データ更新後、{TEAM['team_name']}公式チケットニュースへのリンクが表示されます。")
else:
    news = news.sort_values("published_at", ascending=False, kind="stable").head(40)
    news_view = news[["published_at", "title", "url"]].rename(
        columns={"published_at": "掲載日", "title": "タイトル", "url": "リンク"}
    )

    mobile_news_items: list[str] = []
    for _, news_row in news.iterrows():
        mobile_news_items.append(
            f'<a class="mobile-news-item" href="{html.escape(news_row["url"], quote=True)}" '
            'target="_blank" rel="noopener noreferrer">'
            f'<span>{html.escape(news_row["published_at"])}</span>'
            f'<strong>{html.escape(news_row["title"])}</strong></a>'
        )
    st.markdown('<div class="mobile-news-list">' + "".join(mobile_news_items) + "</div>", unsafe_allow_html=True)

    st.dataframe(
        news_view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "掲載日": st.column_config.TextColumn("掲載日", width=92),
            "タイトル": st.column_config.TextColumn("タイトル", width="large"),
            "リンク": st.column_config.LinkColumn("リンク", display_text="開く", width="small"),
        },
    )

st.caption("データは毎日7:00・19:00（日本時間）に自動更新します。GitHub Actionsの実行状況により遅れる場合があります。")
st.caption(str(TEAM["disclaimer"]))
