# クラブチケットナビ｜京都サンガF.C.版

京都サンガF.C.の試合日程と、ホーム／アウェイのチケット発売情報を一覧表示する非公式Streamlitアプリです。

## 主な機能

- 京都公式「試合日程・結果」から日程、H/A、対戦相手、会場を取得
- ホーム戦は京都公式の2026/27シーズン販売ルールから発売日時を自動計算
  - シーズンパス先行受付
  - SC最速先行販売
  - SC先々行販売
  - SC先行販売
  - 一般販売
- アウェイ戦は対戦クラブ公式ドメインのチケット記事を検索し、一般発売日時を候補抽出
- 京都公式チケットニュースのリンク集
- ホーム／アウェイ絞り込み、終了済み試合の非表示
- スマホ表示では試合カード内のリンクを表示せず、誤タップを防止
- GitHub Actionsで毎日7:00・19:00（日本時間）に更新

## 使用している京都公式ページ

- 試合日程: https://www.sanga-fc.jp/game
- チケットニュース: https://www.sanga-fc.jp/news/tickets
- 2026/27販売ルール: https://www.sanga-fc.jp/news/detail/21158

## GitHubへ配置する手順

1. ZIPを展開し、全ファイルを新しいGitHubリポジトリへアップロードします。
2. GitHubの `Actions` → `Update ticket data` → `Run workflow` を1回実行します。
3. 実行後、`data/matches.csv` 等が自動更新・コミットされます。
4. Streamlit Community Cloudでリポジトリを選び、Main file pathを `app.py` にします。

推奨リポジトリ名: `club-ticket-navi-kyoto`

## ローカル起動

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python update_data.py
streamlit run app.py
```

## アウェイ情報を手動補正する場合

`data/manual_overrides.csv` に追記します。

- `match_key` または `opponent` + `sort_date` で対象試合を指定
- `general_at` は `2026-07-18T10:00+09:00` の形式
- 手動値は自動取得結果より優先されます

## 注意点

アウェイ発売情報は、クラブごとに公式サイトの構成や表現が異なるため、日時が抽出できない場合があります。その場合も候補となる公式記事リンクを表示し、最終確認できるようにしています。
