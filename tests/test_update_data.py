from datetime import date

from update_data import (
    compute_kyoto_home_sales,
    extract_general_sale,
    parse_matches,
    parse_ticket_news,
)


def test_home_sale_schedule():
    sales = compute_kyoto_home_sales(date(2026, 8, 22))
    assert sales["season_pass_at"].startswith("2026-07-25T11:00")
    assert sales["sc_fastest_at"].startswith("2026-07-27T12:00")
    assert sales["sc_early_at"].startswith("2026-07-29T12:00")
    assert sales["sc_member_at"].startswith("2026-07-31T12:00")
    assert sales["general_at"].startswith("2026-08-01T12:00")


def test_extract_general_sale():
    text = "一般販売は7月18日(土)10:00より開始します。"
    sale = extract_general_sale(text, date(2026, 8, 9))
    assert sale is not None
    assert sale.isoformat(timespec="minutes").startswith("2026-07-18T10:00")


def test_parse_matches_fixture():
    html = """
    <html><body>
      <select><option selected>2026/27</option></select>
      <section><h2>明治安田Ｊ１リーグ</h2>
        <article class="game-card">
          <span>AWAY</span><span>第1節</span><span>PEACE STADIUM Connected by SoftBank</span>
          <span>8.9 [日] 19:00</span>
          <img alt="ロゴ：京都サンガF.C."><span>京都サンガF.C.</span>
          <span>vs</span><img alt="ロゴ：Ｖ・ファーレン長崎"><span>Ｖ・ファーレン長崎</span>
          <a href="/game/info/2026080902">試合情報</a>
        </article>
        <article class="game-card">
          <span>HOME</span><span>第3節</span><span>サンガスタジアム by KYOCERA</span>
          <span>8.22 [土] 19:00</span>
          <img alt="ロゴ：京都サンガF.C."><span>京都サンガF.C.</span>
          <span>vs</span><img alt="ロゴ：水戸ホーリーホック"><span>水戸ホーリーホック</span>
          <a href="/game/info/2026082201">試合情報</a>
        </article>
      </section>
    </body></html>
    """
    rows = parse_matches(html, "https://www.sanga-fc.jp/game")
    assert len(rows) == 2
    assert rows[0]["opponent"] == "Ｖ・ファーレン長崎"
    assert rows[0]["side"] == "AWAY"
    assert rows[0]["sort_date"] == "2026-08-09"
    assert rows[1]["side"] == "HOME"
    assert rows[1]["general_at"].startswith("2026-08-01T12:00")


def test_parse_ticket_news_fixture():
    html = """
    <ul>
      <li><a href="/news/detail/21158">2026/7/3 チケット 【2026/27】チケット販売スケジュールのお知らせ</a></li>
    </ul>
    """
    rows = parse_ticket_news(html, "https://www.sanga-fc.jp/news/tickets")
    assert len(rows) == 1
    assert rows[0]["published_at"] == "2026/07/03"
    assert rows[0]["url"].endswith("/news/detail/21158")
