import unittest
from datetime import date

from updater import (
    apply_official_fixture_corrections,
    apply_official_ticket_schedules,
    assert_fixture_fields_unchanged,
    capture_fixture_fields,
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

    def test_extract_frontale_general_advance_sale_from_table(self):
        html = """
        <html><body>
          <p>チケットの発売時間は、各発売日の10:00～となります。</p>
          <table>
            <thead>
              <tr>
                <th>カテゴリ</th><th>節</th><th>対戦相手</th>
                <th>試合日 キックオフ</th>
                <th>プレミアムプラン 超最速先行前売発売日</th>
                <th>会員向け 前売発売日</th>
                <th>一般向け 前売発売日</th><th>開催内容</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>J1リーグ</td><td>2</td><td>京都サンガF.C.</td>
                <td>8/15（土） 19:00</td><td>7/23(木)</td>
                <td>7/25(土)</td><td>8/1(土)</td><td>開催内容未定</td>
              </tr>
            </tbody>
          </table>
        </body></html>
        """
        sale = extract_general_sale_from_page(html, date(2026, 8, 15))
        self.assertIsNotNone(sale)
        self.assertEqual(sale.isoformat(timespec="minutes"), "2026-08-01T10:00+09:00")

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

    def test_static_fixture_correction_is_not_used(self):
        row = {
            "season": "2026/27",
            "competition_group": "ＪリーグＹＢＣルヴァンカップ",
            "round_name": "２回戦",
            "sort_date": "2026-09-29",
            "opponent": "ＦＣ東京",
        }
        rows = apply_official_fixture_corrections([row])
        self.assertIs(rows[0], row)
        self.assertEqual(rows[0]["sort_date"], "2026-09-29")
        self.assertEqual(rows[0]["opponent"], "ＦＣ東京")



    def test_apply_official_image_schedule_for_kyoto_away_at_fukuoka(self):
        row = {
            "side": "AWAY",
            "opponent": "アビスパ福岡",
            "sort_date": "2027-05-09",
            "round_name": "第34節",
            "competition_group": "Ｊ１リーグ",
            "general_at": "",
            "ticket_source_url": "",
            "ticket_source_name": "",
            "ticket_note": "",
        }
        count = apply_official_ticket_schedules([row])
        self.assertEqual(count, 1)
        self.assertEqual(row["general_at"], "2027-04-11T10:00+09:00")
        self.assertEqual(
            row["ticket_source_url"],
            "https://www.avispa.co.jp/news/post-87276",
        )

    def test_official_image_schedule_is_reusable_for_other_team_editions(self):
        row = {
            "side": "AWAY",
            "opponent": "ファジアーノ岡山",
            "sort_date": "2027-02-20",
            "round_name": "第２２節",
            "competition_group": "Ｊ１リーグ",
            "general_at": "",
            "ticket_source_url": "",
            "ticket_source_name": "",
            "ticket_note": "",
        }
        count = apply_official_ticket_schedules([row], team_name="ガンバ大阪")
        self.assertEqual(count, 1)
        self.assertEqual(row["general_at"], "2027-01-22T12:00+09:00")


    def test_sanga_schedule_is_source_of_truth_for_competition_and_stadium(self):
        html = """
        <html><body>
          <select><option selected>2026/27</option></select>
          <section>
            <h2>明治安田Ｊ１リーグ</h2>
            <article class="game-card">
              <div class="fixture-head">
                <span>AWAY</span><span>第10節</span>
                <span>エディオンピースウイング広島</span>
              </div>
              <div class="fixture-body">
                <span>10.17 [土] 14:00</span>
                <img alt="ロゴ：京都サンガF.C."><span>京都サンガF.C.</span>
                <span>vs</span><img alt="ロゴ：サンフレッチェ広島"><span>サンフレッチェ広島</span>
                <a href="/game/info/2026101701">試合情報</a>
              </div>
            </article>
            <article class="game-card">
              <div class="fixture-head">
                <span>AWAY</span><span>第34節</span><span>ベスト電器スタジアム</span>
              </div>
              <div class="fixture-body">
                <span>5.9 [日] 未定</span>
                <img alt="ロゴ：京都サンガF.C."><span>京都サンガF.C.</span>
                <span>vs</span><img alt="ロゴ：アビスパ福岡"><span>アビスパ福岡</span>
                <p>ルヴァンカップ決勝進出クラブの試合は別日に開催する可能性があります。</p>
                <a href="/game/info/2027050901">試合情報</a>
              </div>
            </article>
          </section>
          <section>
            <h2>ＪリーグYBCルヴァンカップ</h2>
            <article class="game-card">
              <span>AWAY</span><span>４回戦</span><span>町田ＧＩＯＮスタジアム</span>
              <span>10.3 [土] 16:00</span>
              <img alt="ロゴ：京都サンガF.C."><span>京都サンガF.C.</span>
              <span>vs</span><img alt="ロゴ：ＦＣ町田ゼルビア"><span>ＦＣ町田ゼルビア</span>
              <a href="/game/info/2026100307">試合情報</a>
            </article>
          </section>
        </body></html>
        """
        rows = parse_matches(html, "https://www.sanga-fc.jp/game")
        by_opponent = {row["opponent"]: row for row in rows}

        hiroshima = by_opponent["サンフレッチェ広島"]
        self.assertEqual(hiroshima["stadium"], "エディオンピースウイング広島")
        self.assertEqual(hiroshima["competition_group"], "Ｊ１リーグ")

        fukuoka = by_opponent["アビスパ福岡"]
        self.assertEqual(fukuoka["stadium"], "ベスト電器スタジアム")
        self.assertEqual(fukuoka["competition_group"], "Ｊ１リーグ")

        machida = by_opponent["ＦＣ町田ゼルビア"]
        self.assertEqual(machida["competition_group"], "ＪリーグＹＢＣルヴァンカップ")

    def test_ticket_enrichment_cannot_change_sanga_fixture_fields(self):
        row = {
            "season": "2026/27",
            "competition_group": "Ｊ１リーグ",
            "competition_name": "明治安田Ｊ１リーグ",
            "round_name": "第10節",
            "kickoff": "2026-10-17T14:00+09:00",
            "date_text": "2026/10/17 14:00",
            "sort_date": "2026-10-17",
            "side": "AWAY",
            "home": "サンフレッチェ広島",
            "away": "京都サンガF.C.",
            "opponent": "サンフレッチェ広島",
            "stadium": "エディオンピースウイング広島",
            "match_url": "https://www.sanga-fc.jp/game/info/example",
            "general_at": "",
            "ticket_source_url": "",
            "ticket_source_name": "",
            "ticket_note": "",
        }
        snapshot = capture_fixture_fields([row])
        row["general_at"] = "2026-09-01T10:00+09:00"
        row["ticket_source_url"] = "https://example.com/tickets"
        assert_fixture_fields_unchanged(snapshot, [row])

        row["stadium"] = "未定"
        with self.assertRaises(RuntimeError):
            assert_fixture_fields_unchanged(snapshot, [row])

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
