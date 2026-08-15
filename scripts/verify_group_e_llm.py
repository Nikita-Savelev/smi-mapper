#!/usr/bin/env python3
"""Acceptance tests for Group E — LLM collector map (offline + mock LLM)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402
from loguru import logger  # noqa: E402

from component.news_collector import llm_collector_map as llm  # noqa: E402


def _home_html():
    return BeautifulSoup(
        """
        <html><body>
          <nav>
            <a class="active" href="/news/" target="_self">Новости</a>
            <a href="/about">О компании</a>
            <a href="/login">Войти</a>
            <a href="https://other.com/x">Внешняя</a>
            <a href="/2024/08/11/sud-udovletvoril-isk-yabloko.html">
              Суд удовлетворил иск длинный заголовок новости
            </a>
          </nav>
          <main></main>
        </body></html>
        """,
        "lxml",
    )


def _listing_html():
    cards = []
    for i in range(1, 8):
        cards.append(
            f"""
            <div class="news-item">
              <span class="date">11.08.2024 10:{i:02d}</span>
              <h2><a href="/news/2024/story-number-{i}-long-title">
                Заголовок новости номер {i} длинный текст
              </a></h2>
              <p>анонс</p>
            </div>
            """
        )
    return BeautifulSoup(
        "<html><body><div class='news-list'>" + "".join(cards) + "</div>"
        "<nav><a href='/about'>О сайте</a></nav></body></html>",
        "lxml",
    )


def test_extract_home_links() -> dict:
    soup = _home_html()
    links = llm.extract_home_links(soup, "https://topwar.ru/", "topwar.ru", max_links=50)
    urls = [L["url"] for L in links]
    texts = {L["url"]: L["text"] for L in links}
    home_ok = links and links[0]["text"] == "__home__"
    news_ok = any("/news" in u for u in urls)
    news_text = any(t == "Новости" for t in texts.values())
    no_login = not any("/login" in u for u in urls)
    no_ext = not any("other.com" in u for u in urls)
    ok = home_ok and news_ok and news_text and no_login and no_ext
    return {"ok": ok, "n": len(links), "urls": urls[:8], "home_ok": home_ok, "news_text": news_text}


def test_count_blocks_requires_date() -> dict:
    listing = _listing_html()
    no_date = BeautifulSoup(
        """
        <html><body>
          <div class="card"><h3><a href="/a/1/long-title-here">Заголовок один длинный</a></h3></div>
          <div class="card"><h3><a href="/a/2/long-title-here">Заголовок два длинный</a></h3></div>
          <div class="card"><h3><a href="/a/3/long-title-here">Заголовок три длинный</a></h3></div>
        </body></html>
        """,
        "lxml",
    )
    with_date = llm.count_news_blocks(listing)
    without = llm.count_news_blocks(no_date)
    ok = with_date["blocks"] >= 5 and without["blocks"] < 3
    return {"ok": ok, "with_date": with_date["blocks"], "without": without["blocks"]}


def test_outline_and_validate() -> dict:
    soup = _listing_html()
    outline = llm.build_page_outline(soup)
    has_news = any(
        g.get("attrs", {}).get("class") == "news-item" or "news-item" in str(g.get("attrs"))
        for g in outline
    )
    good_map = {"name": "div", "attrs": {"class": "news-item"}, "next": False}
    bad_map = {"name": "nav", "attrs": {}, "next": False}
    valid = llm.filter_valid_collect_elements(soup, [good_map, bad_map], min_total=3)
    ok = has_news and len(valid) == 1
    return {"ok": ok, "outline_n": len(outline), "valid_n": len(valid), "has_news": has_news}


async def test_assemble_mock_llm() -> dict:
    home = _home_html()
    listing = _listing_html()

    async def fetch_page(url, connection_mode):
        if "/news" in url:
            return listing
        return home

    async def stage1(client, site, links, top_k):
        news = next(L for L in links if "/news" in L["url"])
        return [
            {"url": news["url"], "text": news["text"], "rank": 1, "reason": "mock"},
            {"url": links[0]["url"], "text": "__home__", "rank": 2, "reason": "home"},
        ][:top_k]

    async def stage2(client, collect_url, outline):
        return [{"name": "div", "attrs": {"class": "news-item"}, "next": False}]

    cfg = {
        "enabled": True,
        "api_key": "mock",
        "base_url": "http://invalid",
        "model": "mock",
        "top_k": 2,
        "max_home_links": 50,
        "timeout_sec": 5,
    }
    # client unused because stage1/2 mocked
    result = await llm.assemble_llm_collector_map(
        site="topwar.ru",
        connection_mode="default",
        cfg=cfg,
        fetch_page=fetch_page,
        client=object(),  # type: ignore
        stage1_fn=stage1,
        stage2_fn=stage2,
    )
    ok = bool(
        result.get("ok")
        and "/news" in (result.get("collect_url") or "")
        and (result.get("collect_elements") or [])
    )
    return {
        "ok": ok,
        "collect_url": result.get("collect_url"),
        "maps": len(result.get("collect_elements") or []),
        "reason": result.get("reason"),
    }


async def test_assemble_home_fallback() -> dict:
    """If shortlist pages have blocks=0, stage2 runs on home instead of no_listing."""
    home = _listing_html()
    empty = BeautifulSoup("<html><body><p>empty</p></body></html>", "lxml")

    async def fetch_page(url, connection_mode):
        if "/empty" in url:
            return empty
        return home

    async def stage1(client, site, links, top_k):
        return [{"url": "https://topwar.ru/empty/", "text": "Empty", "rank": 1, "reason": "mock"}]

    async def stage2(client, collect_url, outline):
        return [{"name": "div", "attrs": {"class": "news-item"}, "next": False}]

    cfg = {
        "enabled": True,
        "api_key": "mock",
        "base_url": "http://invalid",
        "model": "mock",
        "top_k": 2,
        "max_home_links": 50,
        "timeout_sec": 5,
    }
    result = await llm.assemble_llm_collector_map(
        site="topwar.ru",
        connection_mode="default",
        cfg=cfg,
        fetch_page=fetch_page,
        client=object(),  # type: ignore
        stage1_fn=stage1,
        stage2_fn=stage2,
    )
    cu = result.get("collect_url") or ""
    ok = bool(
        result.get("ok")
        and result.get("reason") != "no_listing"
        and (result.get("report") or {}).get("stage1", {}).get("home_fallback")
        and cu.rstrip("/").endswith("topwar.ru")
        and (result.get("collect_elements") or [])
    )
    return {
        "ok": ok,
        "collect_url": cu,
        "reason": result.get("reason"),
        "home_fallback": (result.get("report") or {}).get("stage1", {}).get("home_fallback"),
        "maps": len(result.get("collect_elements") or []),
    }


def main():
    log_path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else ROOT.parent / "docs/tasks/evidence/mapper-success/GROUP-E-2026-08-11.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(log_path, level="INFO")

    results = {
        "extract": test_extract_home_links(),
        "count": test_count_blocks_requires_date(),
        "outline": test_outline_and_validate(),
        "assemble": asyncio.run(test_assemble_mock_llm()),
        "home_fallback": asyncio.run(test_assemble_home_fallback()),
    }
    for name, r in results.items():
        logger.info(f"TEST {name}: {r}")
        print(f"{name}: {'PASS' if r.get('ok') else 'FAIL'} {r}")

    all_ok = all(r.get("ok") for r in results.values())
    print("PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
