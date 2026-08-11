#!/usr/bin/env python3
"""Acceptance test for Group D.1: HTML feed page candidates (paths + nav)."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402
from loguru import logger  # noqa: E402

from component.news_collector import determinant_collect_element as dce  # noqa: E402


def _has(lines, *parts):
    return any(all(p in l for p in parts) for l in lines)


def test_offline() -> dict:
    seeds = dce.seed_html_feed_urls("example.com")
    seed_paths = {u.split("example.com", 1)[-1] for u in seeds}
    need_paths = {"/", "/news", "/novosti", "/press", "/articles", "/lenta"}
    has_paths = need_paths.issubset(seed_paths)

    page = BeautifulSoup(
        """
        <html><body>
          <nav>
            <a href="/novosti">Новости</a>
            <a href="/press-center">Пресс-центр</a>
            <a href="/about">О нас</a>
            <a href="https://other.com/news">Чужой</a>
            <a href="/login">Войти</a>
            <a href="/articles/2024/01/15/long-story">Статья глубоко</a>
          </nav>
          <a href="/media">Media</a>
        </body></html>
        """,
        "lxml",
    )
    nav = dce.extract_nav_feed_candidates(page, "https://example.com/", "example.com")
    nav_ok = (
        any(u.rstrip("/").endswith("/novosti") for u in nav)
        and any("press-center" in u for u in nav)
        and any(u.rstrip("/").endswith("/media") for u in nav)
        and not any(u.rstrip("/").endswith("/about") for u in nav)
        and not any("other.com" in u for u in nav)
        and not any(u.rstrip("/").endswith("/login") for u in nav)
        and not any("long-story" in u for u in nav)
    )

    built = dce.build_html_feed_candidates(
        "example.com",
        nav_urls=["https://example.com/novosti", "https://example.com/custom-news"],
        max_total=16,
    )
    urls = [c["url"] for c in built]
    sources = {c["source"] for c in built}
    # home first, then nav (must not be crowded out by seeds), then seeds
    built_ok = (
        len(built) <= 16
        and "home" in sources
        and "seed" in sources
        and "nav" in sources
        and any("custom-news" in u for u in urls)
        and any(u.rstrip("/").endswith("/novosti") for u in urls)
        and built[0]["source"] == "home"
        and any(c["source"] == "nav" for c in built[:6])
    )

    ok = has_paths and nav_ok and built_ok
    return {
        "ok": ok,
        "has_paths": has_paths,
        "nav_ok": nav_ok,
        "nav": nav,
        "built_ok": built_ok,
        "built_n": len(built),
        "seed_n": len(seeds),
    }


async def test_live(lines: list) -> dict:
    site = "lenta.ru"
    t0 = time.perf_counter()
    html_res = await dce.run({"url": site}, None, "default")
    dur = time.perf_counter() - t0
    logger.info(
        f'[map_feed] url={site} step=done status=html_direct '
        f'failed=None rss=False duration_s={dur:.1f}'
    )
    feed = [l for l in lines if f"url={site}" in l and "[map_feed]" in l]
    map_ok = html_res[0] is not None
    pages_ok = (
        _has(feed, "step=html_candidates")
        and _has(feed, "step=html_pages")
        and _has(feed, "sources=")
        and _has(feed, "step=html_map", "reason=best_score", "source=")
        and _has(feed, "step=done")
    )
    # Must try more than the old fixed 6 URLs (news/articles/home × http/https).
    tried_more = False
    for l in feed:
        if "step=html_pages" in l and "tried=" in l:
            try:
                n = int(l.split("tried=")[1].split()[0])
                tried_more = n > 6
            except Exception:
                pass
            break
    return {
        "ok": map_ok and pages_ok and tried_more,
        "map_ok": map_ok,
        "pages_ok": pages_ok,
        "tried_more": tried_more,
        "duration_s": round(dur, 1),
        "map_feed_lines": feed,
        "error": None if (map_ok and pages_ok and tried_more) else "live html_pages checks failed",
    }


async def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "GROUP-D1-html-pages.log"
    lines: list[str] = []
    logger.remove()
    logger.add(lambda m: lines.append(str(m).rstrip()), format="{message}")
    logger.add(str(log_path), format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    offline = test_offline()
    live = await test_live(lines)

    print("=== SUMMARY ===")
    print(f"offline: {'PASS' if offline['ok'] else 'FAIL'} detail={offline}")
    print(
        f"live_lenta: {'PASS' if live['ok'] else 'FAIL'} "
        f"map_ok={live['map_ok']} pages_ok={live['pages_ok']} "
        f"tried_more={live['tried_more']} duration_s={live['duration_s']}"
    )
    for l in live.get("map_feed_lines") or []:
        print(l)
    overall = offline["ok"] and live["ok"]
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    print(f"LOG: {log_path}")
    return 0 if overall else 1


if __name__ == "__main__":
    evidence = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT.parent / "docs/tasks/evidence/mapper-success"
    )
    raise SystemExit(asyncio.run(main(evidence)))
