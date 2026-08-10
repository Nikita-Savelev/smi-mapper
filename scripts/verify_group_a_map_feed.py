#!/usr/bin/env python3
"""Acceptance test for Group A: [map_feed] step logging.

Writes a log file and prints a machine-readable SUMMARY block.
Exit 0 only if all required scenarios pass.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger  # noqa: E402

from component.news_collector import determinant_collect_element  # noqa: E402
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


async def _run_collector(nc: NewsCollector, channel, link):
    report = _empty_report()
    t0 = time.perf_counter()
    try:
        channel, report, items = await nc.start_collector_map_assembly_process(
            report, channel, link
        )
        return channel, report, items, time.perf_counter() - t0, None
    except Exception as exc:
        return channel, report, None, time.perf_counter() - t0, exc


async def main(log_path: Path) -> int:
    lines: list[str] = []
    logger.remove()
    logger.add(lambda m: lines.append(str(m).rstrip()), format="{message}")
    logger.add(str(log_path), format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    nc = NewsCollector()
    results = {}

    # --- 1. HTML map logging (direct, independent of RSS) ---
    site_html = "lenta.ru"
    t0 = time.perf_counter()
    html_res = await determinant_collect_element.run(
        {"url": site_html}, None, "default"
    )
    dur_html = time.perf_counter() - t0
    logger.info(
        f'[map_feed] url={site_html} step=done status=html_direct '
        f'failed=None rss=False duration_s={dur_html:.1f}'
    )
    feed_html = [l for l in lines if f"url={site_html}" in l and "[map_feed]" in l]
    map_ok = html_res[0] is not None
    results["html_map_direct"] = {
        "ok": (
            _has(feed_html, "step=html_pages")
            and _has(feed_html, "step=html_map")
            and _has(feed_html, "step=done")
            and map_ok
        ),
        "error": None if map_ok else "no html map",
        "status": "html_direct",
        "failed_log": None,
        "rss": False,
        "items": html_res[0] and len(html_res[0]),
        "duration_s": round(dur_html, 1),
        "map_feed_lines": feed_html,
    }

    # --- 2. RSS discovery (link=None) ---
    site_disc = "habr.com"
    lines_before = len(lines)
    ch_d = _channel(site_disc)
    ch_d, rep_d, items_d, dur_d, err_d = await _run_collector(nc, ch_d, None)
    logger.info(
        f'[map_feed] url={site_disc} step=done status={rep_d.get("status")} '
        f'failed={rep_d.get("failed_log")} rss={rep_d.get("rss")} duration_s={dur_d:.1f}'
    )
    feed_d = [l for l in lines[lines_before:] if f"url={site_disc}" in l and "[map_feed]" in l]
    results["rss_discovery"] = {
        "ok": (
            err_d is None
            and _has(feed_d, "step=rss")
            and _has(feed_d, "step=items")
            and _has(feed_d, "step=done")
        ),
        "error": str(err_d) if err_d else None,
        "status": rep_d.get("status"),
        "failed_log": rep_d.get("failed_log"),
        "rss": rep_d.get("rss"),
        "items": None if items_d is None else len(items_d),
        "duration_s": round(dur_d, 1),
        "map_feed_lines": feed_d,
    }

    # --- 3. Seed RSS ---
    site_rss = "habr.com"
    rss_url = "https://habr.com/ru/rss/articles/?fl=ru"
    lines_before = len(lines)
    ch2 = _channel(site_rss, rss_link=[rss_url])
    ch2, rep2, items2, dur2, err2 = await _run_collector(nc, ch2, rss_url)
    logger.info(
        f'[map_feed] url={site_rss} step=done status={rep2.get("status")} '
        f'failed={rep2.get("failed_log")} rss={rep2.get("rss")} duration_s={dur2:.1f}'
    )
    feed2 = [l for l in lines[lines_before:] if "[map_feed]" in l and f"url={site_rss}" in l]
    # seed lines only for this scenario: filter source=seed / items after seed
    results["rss_seed"] = {
        "ok": (
            err2 is None
            and _has(feed2, "step=rss", "found=True", "source=seed")
            and _has(feed2, "step=items")
            and _has(feed2, "step=done")
        ),
        "error": str(err2) if err2 else None,
        "status": rep2.get("status"),
        "failed_log": rep2.get("failed_log"),
        "rss": rep2.get("rss"),
        "items": None if items2 is None else len(items2),
        "duration_s": round(dur2, 1),
        "map_feed_lines": feed2,
    }

    print("=== SUMMARY ===")
    for name, r in results.items():
        print(
            f"{name}: {'PASS' if r['ok'] else 'FAIL'} items={r['items']} "
            f"status={r['status']} failed={r.get('failed_log')} dur={r['duration_s']}s err={r['error']}"
        )
        for l in r["map_feed_lines"]:
            print(f"  {l}")
    all_ok = all(r["ok"] for r in results.values())
    print(f"OVERALL: {'PASS' if all_ok else 'FAIL'}")
    print(f"LOG: {log_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "GROUP-A-map-feed.log"
    raise SystemExit(asyncio.run(main(log_path)))
