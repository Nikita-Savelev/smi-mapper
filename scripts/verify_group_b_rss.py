#!/usr/bin/env python3
"""Acceptance test for Group B: RSS crawl + empty-feed handling."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402
from loguru import logger  # noqa: E402

from component.news_collector.news_collector_class import NewsCollector  # noqa: E402


def _channel(url: str, **extra):
    ch = {
        "url": url,
        "feed_id": f"test-{url}",
        "user_id": "test-user",
        "main": False,
        "parser_id": 55,
        "connection_mode": "default",
    }
    ch.update(extra)
    return ch


def _empty_report():
    return {
        "rss": False,
        "collector": None,
        "parser": None,
        "failed_log": None,
        "status": None,
        "used_connections": [],
    }


def _has(lines, *parts):
    return any(all(p in l for p in parts) for l in lines)


def test_offline(nc: NewsCollector, lines: list) -> dict:
    rss_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>a</title><link>http://x/1</link></item>
      <item><title>b</title><link>http://x/2</link></item>
      <item><title>c</title><link>http://x/3</link></item>
      <item><title>d</title><link>http://x/4</link></item>
      <item><title>e</title><link>http://x/5</link></item>
      <item><title>f</title><link>http://x/6</link></item>
    </channel></rss>"""
    html_stub = "<html><body><a href='/rss'>RSS</a><p>not a feed</p></body></html>"
    empty_feed = """<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""

    ok_feed, n_feed = nc._count_feed_items(rss_xml, "application/rss+xml")
    ok_html, n_html = nc._count_feed_items(html_stub, "text/html")
    ok_empty, n_empty = nc._count_feed_items(empty_feed, "application/rss+xml")

    page = BeautifulSoup(
        """<html><head>
        <link rel="alternate" type="application/rss+xml" href="/news.rss"/>
        <link rel="alternate" type="application/atom+xml" href="https://example.com/atom.xml"/>
        </head><body><a href="/feed">Лента</a><a href="/about">About</a></body></html>""",
        "lxml",
    )
    links = nc._extract_feed_links_from_soup("https://example.com/", page, "example.com")

    ok = (
        ok_feed and n_feed == 6
        and (not ok_html) and n_html == 0
        and ok_empty and n_empty == 0
        and any(u.endswith("/news.rss") for u in links)
        and any("atom.xml" in u for u in links)
        and any(u.endswith("/feed") for u in links)
        and not any(u.endswith("/about") for u in links)
    )
    return {
        "ok": ok,
        "detail": {
            "rss_items": n_feed,
            "html_is_feed": ok_html,
            "empty_items": n_empty,
            "extracted": links,
        },
        "map_feed_lines": [],
    }


async def test_discovery(nc: NewsCollector, lines: list) -> dict:
    before = len(lines)
    site = "habr.com"
    url = await nc.find_rss_process("default", _channel(site))
    feed = [l for l in lines[before:] if "[map_feed]" in l]
    ok = (
        url is not None
        and _has(feed, "step=rss_crawl")
        and _has(feed, "step=rss_probe")
        and _has(feed, "step=rss", "found=True")
    )
    return {
        "ok": ok,
        "url": url,
        "map_feed_lines": [l for l in feed if "step=rss" in l or "step=rss_crawl" in l][:30],
    }


async def test_empty_seed(nc: NewsCollector, lines: list) -> dict:
    before = len(lines)
    site = "example.com"
    # HTML page is not a feed — must clear rss_link and try html / fail cleanly
    bogus = "https://example.com/"
    ch = _channel(site, rss_link=[bogus])
    report = _empty_report()
    ch, report, items = await nc.start_collector_map_assembly_process(report, ch, bogus)
    feed = [l for l in lines[before:] if "[map_feed]" in l]
    has_rss_link = bool(ch.get("rss_link"))
    ok = (
        (not has_rss_link)
        and report.get("rss") is False
        and _has(feed, "step=rss_fetch")
        and _has(feed, "rss_failed", "try_html=1")
    )
    return {
        "ok": ok,
        "rss_link": ch.get("rss_link"),
        "status": report.get("status"),
        "failed_log": report.get("failed_log"),
        "items": None if items is None else len(items),
        "map_feed_lines": feed[:40],
    }


async def test_few_rss_news_tries_html(nc: NewsCollector, lines: list) -> dict:
    """RSS returns items but <5 news after filter → must try HTML (not stop on RSS fail)."""
    before = len(lines)
    site = "few-items.test"
    # Minimal feed: 2 items → after create_docs may be 0–2 < 5 → HTML fallback
    few_xml = """<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>a</title><link>http://few-items.test/1</link><pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate></item>
      <item><title>b</title><link>http://few-items.test/2</link><pubDate>Mon, 01 Jan 2024 13:00:00 GMT</pubDate></item>
    </channel></rss>"""

    orig = nc.get_data_rss_pid4

    async def fake_rss(connection_mode, rss_link, headers=None, return_rss_link=False, site=None):
        soup = BeautifulSoup(few_xml, "xml")
        items = soup.find_all("item")
        if return_rss_link:
            return items, rss_link
        return items

    async def fake_html_map(channel, connection_mode):
        # pretend HTML map not found — we only assert the fallback was attempted
        return channel, {"response_code": 404}, True

    nc.get_data_rss_pid4 = fake_rss
    nc.get_collect_map = fake_html_map
    try:
        ch = _channel(site)
        report = _empty_report()
        seed = "https://few-items.test/rss"
        ch, report, items = await nc.start_collector_map_assembly_process(report, ch, seed)
        feed = [l for l in lines[before:] if "[map_feed]" in l]
        ok = (
            items is None
            and report.get("rss") is False
            and not ch.get("rss_link")
            and _has(feed, "rss_failed", "too_few_news", "try_html=1")
            and report.get("failed_log") == "FAILED find collect_elements"
        )
        return {
            "ok": ok,
            "rss": report.get("rss"),
            "rss_link": ch.get("rss_link"),
            "failed_log": report.get("failed_log"),
            "map_feed_lines": feed[:20],
        }
    finally:
        nc.get_data_rss_pid4 = orig
        # get_collect_map restored only if we saved it — re-bind from class
        nc.get_collect_map = NewsCollector.get_collect_map.__get__(nc, NewsCollector)


async def test_seed_ok(nc: NewsCollector, lines: list) -> dict:
    before = len(lines)
    site = "habr.com"
    rss = "https://habr.com/ru/rss/articles/?fl=ru"
    ch = _channel(site, rss_link=[rss])
    report = _empty_report()
    ch, report, items = await nc.start_collector_map_assembly_process(report, ch, rss)
    feed = [l for l in lines[before:] if "[map_feed]" in l]
    ok = (
        items is not None
        and len(items) >= 5
        and bool(ch.get("rss_link"))
        and _has(feed, "step=items")
    )
    return {
        "ok": ok,
        "items": None if items is None else len(items),
        "rss_link": ch.get("rss_link"),
        "map_feed_lines": feed[:20],
    }


async def main(log_path: Path) -> int:
    lines: list[str] = []
    logger.remove()
    logger.add(lambda m: lines.append(str(m).rstrip()), format="{message}")
    logger.add(str(log_path), format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    nc = NewsCollector()
    results = {
        "offline_parse": test_offline(nc, lines),
        "rss_discovery_crawl": await test_discovery(nc, lines),
        "empty_seed_no_rss_link": await test_empty_seed(nc, lines),
        "few_rss_tries_html": await test_few_rss_news_tries_html(nc, lines),
        "seed_rss_ok": await test_seed_ok(nc, lines),
    }

    print("=== SUMMARY ===")
    for name, r in results.items():
        print(f"{name}: {'PASS' if r['ok'] else 'FAIL'} { {k: v for k, v in r.items() if k not in ('map_feed_lines', 'ok')} }")
        for l in r.get("map_feed_lines") or []:
            print(f"  {l}")
    all_ok = all(r["ok"] for r in results.values())
    print(f"OVERALL: {'PASS' if all_ok else 'FAIL'}")
    print(f"LOG: {log_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    raise SystemExit(asyncio.run(main(out_dir / "GROUP-B-rss.log")))
