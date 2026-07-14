# クラブチケットナビ｜京都サンガF.C.版

京都サンガF.C.の試合日程と、ホーム／アウェイのチケット発売情報を一覧表示する非公式Streamlitアプリです。

## 主な機能

- 京都公式「試合日程・結果」から日程、H/A、対戦相手、会場を取得
- ホーム戦は京都公式の販売スケジュールから発売日時を表示
  - シーズンパス先行受付
  - SC最速先行販売
  - SC先々行販売
  - SC先行販売
  - 一般販売
- アウェイ戦は登録済みの対戦クラブ公式ページを直接取得し、「一般販売／一般発売」の日時だけを表示
- 検索エンジン経由の候補記事検索は行わない
- 京都公式チケットニュースのリンク集
- ホーム／アウェイ絞り込み、終了済み試合の非表示
- スマホ表示では試合カード内のリンクを表示せず、誤タップを防止
- GitHub Actionsで毎日7:00・19:00（日本時間）に更新

## 京都公式ページ

- 試合日程: https://www.sanga-fc.jp/game
- チケットニュース: https://www.sanga-fc.jp/news/tickets
- チケット販売スケジュール: https://www.sanga-fc.jp/ticket/schedule

## アウェイ戦の参照ページ

| ホームクラブ | 公式チケット情報ページ |
|---|---|
| 水戸 | https://www.mito-hollyhock.net/news_cat/ticket/ |
| 鹿島 | https://www.antlers.co.jp/blogs/news/260703cm5rd0 |
| 浦和 | https://www.urawa-reds.co.jp/ticket/saleperiod.php |
| 千葉 | https://jefunited.co.jp/news/detail/5285 |
| 柏 | https://www.reysol.co.jp/ticket/tktscd.php |
| FC東京 | https://www.fctokyo.co.jp/ticket/price/ |
| 東京V | https://www.verdy.co.jp/content/ticket/buy/ |
| 町田 | https://www.zelvia.co.jp/stadium-ticket/schedule/ |
| 川崎 | https://www.frontale.co.jp/tickets/ |
| 横浜FM | https://www.f-marinos.com/ticket/schedule |
| 清水 | https://www.s-pulse.co.jp/tickets/schedule |
| 名古屋 | https://nagoya-grampus.jp/ticket/schedule/ |
| 京都 | https://www.sanga-fc.jp/ticket/schedule |
| G大阪 | https://www.gamba-osaka.net/ticket/schedule/ |
| C大阪 | https://www.cerezo.jp/ticket/ |
| 神戸 | https://www.vissel-kobe.co.jp/ticket/schedule/ |
| 岡山 | https://www.fagiano-okayama.com/ticket/ticket_schedule/ |
| 広島 | https://www.sanfrecce.co.jp/tickets/schedule |
| 福岡 | https://www.avispa.co.jp/news/post-87276 |
| 長崎 | https://www.v-varen.com/tickets_new |

## GitHubへ配置する手順

1. ZIPを展開し、全ファイルを新しいGitHubリポジトリへアップロードします。
2. `.github/workflows/update-data.yml` がリポジトリ直下にあることを確認します。
3. GitHubの `Actions` → `Update Kyoto Sanga ticket data` → `Run workflow` を1回実行します。
4. 実行後、`data/matches.csv` 等が自動更新・コミットされます。
5. Streamlit Community Cloudでリポジトリを選び、Main file pathを `app.py` にします。

推奨リポジトリ名: `club-ticket-navi-kyoto`

## ローカル起動

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python updater.py
streamlit run app.py
```

## アウェイ情報を手動補正する場合

`data/manual_overrides.csv` に追記します。

- `match_key` または `opponent` + `sort_date` で対象試合を指定
- `general_at` は `2026-07-18T10:00+09:00` の形式
- 手動値は自動取得結果より優先されます

## 注意点

各クラブ公式サイトは表・カード・記事など構成が異なるため、一般発売日時を抽出できない場合があります。その場合も、指定された公式ページへのリンクは一覧に残します。購入前には必ずリンク先の公式情報をご確認ください。
