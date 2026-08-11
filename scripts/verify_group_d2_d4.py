#!/usr/bin/env python3
"""Acceptance tests for Groups D.2–D.4 (cards anchor, soft filters, map score)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402
from loguru import logger  # noqa: E402

from component.news_collector import determinant_collect_element as dce  # noqa: E402
from component.news_collector.news_collector_class import (  # noqa: E402
    MIN_MAP_NEWS,
    NewsCollector,
)


def _cards_html():
    # No dates — only repeating cards with title+link (D.2)
    cards = []
    for i in range(1, 7):
        cards.append(
            f'<div class="card"><h3><a href="/news/2024/0{i}/story-number-{i}-long">'
            f'Заголовок новости номер {i} длинный</a></h3><p>анонс</p></div>'
        )
    return BeautifulSoup(
        "<html><body><main>" + "".join(cards) + "</main></body></html>",
        "lxml",
    )


def _menu_html():
    links = [
        ("/about", "О компании нашей"),
        ("/contact", "Связаться с нами"),
        ("/privacy", "Политика конфиденциальности"),
        ("/login", "Войти в кабинет"),
        ("/help", "Помощь пользователю"),
        ("/faq", "Частые вопросы сайта"),
    ]
    items = "".join(
        f'<div class="nav-item"><a href="{h}"><span>{t}</span></a></div>' for h, t in links
    )
    return BeautifulSoup(f"<html><body><nav>{items}</nav></body></html>", "lxml")


def test_d2_cards_anchor() -> dict:
    page = _cards_html()
    cards = dce.find_card_anchor_elements(page, min_repeat=3)
    maps, report, pattern = dce.find_collector_element(page, "example.com", 200)
    ok = (
        len(cards) >= 3
        and report.get("anchor") == "cards"
        and maps
        and report.get("card_elements", 0) >= 3
    )
    return {"ok": ok, "anchor": report.get("anchor"), "cards": len(cards), "maps": len(maps), "pattern": pattern}


def test_d4_score_prefers_articles() -> dict:
    cards_page = _cards_html()
    menu_page = _menu_html()
    maps_c, rep_c, pat_c = dce.find_collector_element(cards_page, "example.com", 200)
    maps_m, rep_m, pat_m = dce.find_collector_element(menu_page, "example.com", 200)
    sc_c = dce.score_listing_candidate(cards_page, maps_c, rep_c, pat_c, "example.com")
    sc_m = dce.score_listing_candidate(menu_page, maps_m or [], rep_m, pat_m, "example.com")
    ok = (not sc_c.get("rejected")) and sc_c["score"] > (sc_m.get("score") or -1e9)
    # menu should be rejected or much weaker
    menu_bad = sc_m.get("rejected") or sc_m["score"] < sc_c["score"] - 10
    return {
        "ok": ok and menu_bad,
        "cards": sc_c,
        "menu": sc_m,
        "menu_maps": len(maps_m or []),
    }


async def test_d3_soft_filters() -> dict:
    nc = NewsCollector.__new__(NewsCollector)
    nc.logger = logger

    # Fake HTML card without date
    item = BeautifulSoup(
        '<div class="card"><h2><a href="https://example.com/news/2024/01/hello-world-article">'
        "Большой заголовок без даты тут</a></h2></div>",
        "lxml",
    ).div
    ch = {
        "url": "example.com",
        "collect_url": "https://example.com/news",
        "feed_id": "t",
        "user_id": "t",
        "main": False,
        "parser_id": 55,
        "collector_id": 55,
        "link_pattern": 2,  # wrong on purpose; real depth is higher
    }
    doc = await nc.create_docs_pid55(item, ch)
    no_date_ok = bool(doc and doc.get("link") and doc.get("title"))

    # link_pattern ±1 / recount
    items = []
    for i in range(4):
        items.append(
            BeautifulSoup(
                f'<div><h2><a href="https://example.com/a/b/c/story-{i}-xxxx">Заголовок новости {i} текст</a></h2></div>',
                "lxml",
            ).div
        )
    ch2 = dict(ch)
    ch2["link_pattern"] = 1  # depths will be ~3 for a/b/c/story
    filtered, raw = await nc._items_to_news(items, ch2, "example.com")
    soft_ok = len(filtered) >= MIN_MAP_NEWS and MIN_MAP_NEWS == 3
    return {
        "ok": no_date_ok and soft_ok,
        "no_date_ok": no_date_ok,
        "soft_ok": soft_ok,
        "filtered": len(filtered),
        "min_map_news": MIN_MAP_NEWS,
        "link_pattern_after": ch2.get("link_pattern"),
    }


async def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "GROUP-D2-D4.log"
    lines: list[str] = []
    logger.remove()
    logger.add(lambda m: lines.append(str(m).rstrip()), format="{message}")
    logger.add(str(log_path), format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    d2 = test_d2_cards_anchor()
    d4 = test_d4_score_prefers_articles()
    d3 = await test_d3_soft_filters()

    print("=== SUMMARY ===")
    print(f"D2_cards: {'PASS' if d2['ok'] else 'FAIL'} {d2}")
    print(f"D3_soft: {'PASS' if d3['ok'] else 'FAIL'} {d3}")
    print(f"D4_score: {'PASS' if d4['ok'] else 'FAIL'} {d4}")
    overall = d2["ok"] and d3["ok"] and d4["ok"]
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    print(f"LOG: {log_path}")
    return 0 if overall else 1


if __name__ == "__main__":
    evidence = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT.parent / "docs/tasks/evidence/mapper-success"
    )
    raise SystemExit(asyncio.run(main(evidence)))
