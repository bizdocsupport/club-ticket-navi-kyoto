from __future__ import annotations


def get_team_config() -> dict[str, object]:
    """京都サンガF.C.版の固定設定。クラブ選択UIは設けない。"""
    return {
        "team_name": "京都サンガF.C.",
        "team_aliases": ["京都サンガF.C.", "京都サンガ", "京都"],
        "service_name": "クラブチケットナビ",
        "edition_name": "京都サンガF.C.版",
        "page_title": "クラブチケットナビ｜京都サンガF.C.版",
        "page_icon": "🎟️",
        "subtitle": "京都サンガF.C.の試合日程とチケット発売情報を一覧化",
        "season_label": "2026/27シーズン",
        "schedule_url": "https://www.sanga-fc.jp/game",
        "ticket_news_url": "https://www.sanga-fc.jp/news/tickets",
        "ticket_schedule_url": "https://www.sanga-fc.jp/news/detail/21158",
        "home_row_color": "#f1eafd",
        "away_row_color": "#fff2df",
        "brand_primary": "#5b2a86",
        "brand_secondary": "#d5a100",
        "home_badge_color": "#6d35a2",
        "away_badge_color": "#c56b13",
        "home_sale_labels": {
            "season_pass_at": "シーズンパス",
            "sc_fastest_at": "SC最速",
            "sc_early_at": "SC先々行",
            "sc_member_at": "SC先行",
            "general_at": "一般発売",
        },
        "disclaimer": (
            "本サービスは非公式です。発売日時・席種・販売方法は変更される場合があります。"
            "購入前に必ずリンク先のクラブ公式情報をご確認ください。"
        ),
    }
