#!/usr/bin/env python3
"""Reproduce MAP ASSEMBLY NoneType on known fail hosts (collector path only)."""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402
from loguru import logger  # noqa: E402

from component.news_collector import determinant_collect_element as dce  # noqa: E402
from component.news_collector.news_collector_class import NewsCollector  # noqa: E402
from component.arangoconnector.connector import ArangoConnector  # noqa: E402


def unit_repro_null_href() -> dict:
    """Prove clean(None) / get_href path that caused TypeError before guards."""
    import re as _re
    from component.news_collector.determinant_collect_element import clean as dce_clean

    # Old crash: re.sub on None
    try:
        _re.sub("a", "b", None)
        clean_crash = False
    except TypeError:
        clean_crash = True

    # New clean must tolerate None
    cleaned = dce_clean(None)

    soup = BeautifulSoup(
        "<html><body><div class='card'><a href='/x'>.</a></div></body></html>",
        "lxml",
    )
    # element with no usable title text → previously clean(None)
    el = soup.find("div")
    href = dce.get_href(el)
    return {
        "re_sub_none_raises": clean_crash,
        "clean_none_ok": cleaned == "",
        "get_href_no_crash": href is None,
        "ok_reproduced_root_cause": clean_crash and cleaned == "",
    }


async def live_one(url: str, connection_mode: str, force_html: bool = True) -> dict:
    collector = NewsCollector()
    channel = {
        "url": url,
        "active": True,
        "connection_mode": connection_mode,
        "force_html": force_html,
        "report": {"used_connections": [], "status": None},
        "feed_id": "local_repro",
        "user_id": "local_repro",
        "main": True,
        "parser_id": 50,
    }
    report = {"used_connections": [], "status": None, "rss": False}
    try:
        channel, report, items = await collector.start_collector_map_assembly_process(
            report, channel, None
        )
        return {
            "url": url,
            "raised": False,
            "failed_log": report.get("failed_log"),
            "status": report.get("status"),
            "rss": report.get("rss"),
            "items": 0 if not items else len(items),
            "collect_url": channel.get("collect_url"),
        }
    except Exception as exc:
        logger.warning(f"live {url} raised:\n{traceback.format_exc()}")
        return {
            "url": url,
            "raised": True,
            "error": f"{type(exc).__name__}: {exc}",
            "tb": traceback.format_exc(),
        }


async def main(urls: list[str]):
    unit = unit_repro_null_href()
    print("UNIT", json.dumps(unit, ensure_ascii=False))

    # proxy from Arango local_smi_proxy / config
    arango = ArangoConnector()
    try:
        proxies = arango.get_proxy_pool() or []
    except Exception as exc:
        logger.warning(f"proxy pool unavailable: {exc}")
        proxies = []
    connection_mode = proxies[0] if proxies else "default"
    logger.info(f"connection_mode={connection_mode!r} proxies={len(proxies)}")

    results = []
    for u in urls:
        logger.info(f"=== live {u} ===")
        r = await live_one(u, connection_mode)
        results.append(r)
        print("LIVE", json.dumps({k: v for k, v in r.items() if k != "tb"}, ensure_ascii=False))

    out = {"unit": unit, "results": results}
    out_path = Path(__file__).resolve().parents[2] / "docs/tasks/evidence/mapper-success/bench/REPRO-nonetype-20260811.json"
    # workspace may be SMI root parent of smi-mapper
    candidates = [
        ROOT.parent / "docs/tasks/evidence/mapper-success/bench/REPRO-nonetype-20260811.json",
        ROOT / "REPRO-nonetype-20260811.json",
    ]
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
            print("wrote", p)
            break
        except Exception:
            continue
    raised = sum(1 for r in results if r.get("raised"))
    none_type = sum(
        1
        for r in results
        if r.get("raised") and "NoneType" in str(r.get("error", ""))
    )
    print(
        f"summary live_raised={raised}/{len(results)} none_type_raised={none_type} unit={unit}"
    )


if __name__ == "__main__":
    sample = ROOT.parent / "docs/tasks/evidence/mapper-success/bench/sample-exception-nonetype-20260811.json"
    if sample.exists():
        urls = json.loads(sample.read_text())["urls"]
    else:
        urls = ["73online.ru", "chastnik.ru", "kluch.media", "elementy.ru", "novvedomosti.ru"]
    # first 5 for speed unless --all
    if "--all" not in sys.argv:
        urls = urls[:5]
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        urls = sys.argv[1:]
    asyncio.run(main(urls))
