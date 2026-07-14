import unittest
from datetime import date

from updater import (
    apply_official_fixture_corrections,
    compute_kyoto_home_sales,
    extract_general_sale,
    extract_general_sale_from_page,
    get_away_ticket_source,
    parse_matches,
    parse_ticket_news,
)


class TestKyotoUpdater(unittest.TestCase):
    def test_home_sale_schedule(self):
        sales = compute_kyoto_home_sales(date(2026, 8, 22))
        self.assertTrue(sales["season_pass_at"].startswith("2026-07-25T11:00"))
        self.assertTrue(sales["sc_fastest_at"].startswith("2026-07-27T12:00"))
        self.assertTrue(sales["sc_early_at"].startswith("2026-07-29T12:00"))
        self.assertTrue(sales["sc_member_at"].startswith("2026-07-31T12:00"))
        self.assertTrue(sales["general_at"].startswith("2026-08-01T12:00"))

    def test_extract_general_sale(self):
        text = "一般販売は7月18日(土)10:00より開始します。"
        sale = extract_general_sale(text, date(2026, 8, 9))
        self.assertIsNotNone(sale)
        self.assertTrue(sale.isoformat(timespec="minutes").startswith("2026-07-18T10:00"))

    def test_fixed_away_source(self):
        source = get_away_ticket_source("鹿島アントラーズ")
        self.assertIsNotNone(source)
        self.assertEqual(
            source["url"],
            "https://www.antlers.co.jp/blogs/news/260703cm5rd0",
        )
        source = get_away_ticket_source("横浜F・マリノス")
        self.assertEqual(source["url"], "https://www.f-marinos.com/ticket/schedule")

    def test_extract_away_general_sale_from_table(self):
        html = """
        <table>
          <thead><tr><th>試合</th><th>会員先行</th><th>一般発売日</th></tr></thead>
          <tbody>
            <tr>
              <td>8/15 京都サンガF.C.</td>
              <td>7/18 10:00</td>
              <td>7/24 10:00</td>
            </tr>
          </tbody>
        </table>
        """
        sale = extract_general_sale_from_page(html, date(2026, 8, 15))
        self.assertIsNotNone(sale)
        self.assertTrue(sale.isoformat(timespec="minutes").startswith("2026-07-24T10:00"))

    def test_extract_away_general_sale_from_card(self):
        html = """
        <section class="ticket-card">
          <h3>8.15 SAT 京都サンガF.C.</h3>
          <dl><dt>一般販売</dt><dd>7月30日(木) 10:00</dd></dl>
        </section>
        """
        sale = extract_general_sale_from_page(html, date(2026, 8, 15))
        self.assertIsNotNone(sale)
        self.assertTrue(sale.isoformat(timespec="minutes").startswith("2026-07-30T10:00"))

    def test_parse_matches_fixture(self):
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
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["opponent"], "Ｖ・ファーレン長崎")
        self.assertEqual(rows[0]["side"], "AWAY")
        self.assertEqual(rows[0]["sort_date"], "2026-08-09")
        self.assertEqual(rows[1]["side"], "HOME")
        self.assertTrue(rows[1]["general_at"].startswith("2026-08-01T12:00"))

    def test_corrects_luvas_wrong_provisional_fixture(self):
        wrong = {
            "season": "2026/27",
            "competition_group": "ＪリーグＹＢＣルヴァンカップ",
            "competition_name": "ＪリーグYBCルヴァンカップ",
            "round_name": "２回戦",
            "kickoff": "2026-09-29T15:00+09:00",
            "date_text": "2026/9/29 15:00",
            "sort_date": "2026-09-29",
            "side": "AWAY",
            "home": "ＦＣ東京",
            "away": "京都サンガF.C.",
            "opponent": "ＦＣ東京",
            "stadium": "味の素スタジアム",
            "match_url": "https://example.invalid/provisional",
        }
        for column in (
            "match_key", "season_pass_at", "sc_fastest_at", "sc_early_at",
            "sc_member_at", "general_at", "ticket_source_url",
            "ticket_source_name", "ticket_note", "last_checked",
        ):
            wrong.setdefault(column, "")

        rows = apply_official_fixture_corrections([wrong])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["opponent"], "ＦＣ町田ゼルビア")
        self.assertEqual(rows[0]["sort_date"], "2026-10-03")
        self.assertEqual(rows[0]["kickoff"], "2026-10-03T16:00+09:00")
        self.assertEqual(rows[0]["round_name"], "４回戦")
        self.assertEqual(
            rows[0]["match_url"],
            "https://www.sanga-fc.jp/game/info/2026100307",
        )

    def test_parse_ticket_news_fixture(self):
        html = """
        <ul>
          <li><a href="/news/detail/21158">2026/7/3 チケット 【2026/27】チケット販売スケジュールのお知らせ</a></li>
        </ul>
        """
        rows = parse_ticket_news(html, "https://www.sanga-fc.jp/news/tickets")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["published_at"], "2026/07/03")
        self.assertTrue(rows[0]["url"].endswith("/news/detail/21158"))


if __name__ == "__main__":
    unittest.main()
