from datetime import date

from src.fetch_news import is_recent_article
from src.generate_insights import filter_verified_news


TODAY = date(2026, 6, 7)


def news(fecha="2026-06-07", url="https://www.reuters.com/sports/test", fuente="Reuters"):
    return {
        "titulo": "Noticia confirmada",
        "texto": "Baja confirmada para el Mundial",
        "fecha": fecha,
        "url": url,
        "fuente": fuente,
    }


def test_verified_news_accepts_only_current_four_day_window():
    items = [
        news("2026-06-07"),
        news("2026-06-04"),
        news("2026-06-03"),
        news("2026-06-08"),
    ]

    result = filter_verified_news(items, today=TODAY, url_checker=lambda _: True)

    assert [item["fecha"] for item in result] == ["2026-06-07", "2026-06-04"]


def test_verified_news_rejects_missing_or_untrusted_evidence():
    items = [
        news(url=""),
        news(url="https://x.com/rumor/123"),
        news(fuente=""),
        news(fecha="sin-fecha"),
    ]

    assert filter_verified_news(items, today=TODAY, url_checker=lambda _: True) == []


def test_verified_news_rejects_unreachable_url():
    assert filter_verified_news(
        [news()],
        today=TODAY,
        url_checker=lambda _: False,
    ) == []


def test_newsapi_articles_use_the_same_four_day_window():
    assert is_recent_article(
        {"publishedAt": "2026-06-04T23:59:00Z"},
        date(2026, 6, 4),
        TODAY,
    )
    assert not is_recent_article(
        {"publishedAt": "2026-06-03T23:59:00Z"},
        date(2026, 6, 4),
        TODAY,
    )
