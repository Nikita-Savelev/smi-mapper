import os
import random
import sys
import uuid
from configparser import ConfigParser
import time as tm
import asyncio
import aiohttp
import re
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

sys.path.append(os.path.dirname(os.path.realpath(os.path.abspath(''))))

from component.arangoconnector.connector import ArangoConnector
from loguru import logger
import datetime
import dateparser
from component.news_collector import determinant_collect_element
from multiprocessing import shared_memory
import time
from aiohttp_socks import ProxyConnector
import linecache
from common.utils import get_connection_options
import sys
from common import utils

weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Th', 'Thu', 'Thur', 'Fri', 'Sat']

# D.3: map-assembly minimum items (was hard-coded 5).
MIN_MAP_NEWS = 3


def check_time(time: int) -> int or None:
    now = int(datetime.datetime.now().timestamp())
    if not time or time > now:
        return now
    return time




class NewsCollector:
    def __init__(self, config_ini='src/config/config.ini', service_type='NewsCollector'):
        self.service_type = service_type
        self.config = ConfigParser()
        self.config.read(config_ini)
        self.rss_config_df = None
        self.config_df = None
        self.auto_config_df = None
        # self.logger = get_run_logger()
        self.logger = logger
        self.arango = ArangoConnector()
        self.mode = self.config[self.service_type]['mode']
        self.proxy_pool = []
        self.semaphore = asyncio.Semaphore(int(self.config[self.service_type]['semaphore']))
        self.channels = None

    async def set_proxy_pool(self):
        self.proxy_pool.extend(self.arango.get_proxy_pool())

    def get_connection_mode(self, channel):
        report_connection = channel["report"]["used_connections"] if "report" in channel and "used_connections" in channel["report"] else []
        if "connection_mode" in channel and channel["connection_mode"] not in report_connection:
            return channel["connection_mode"]
        if not "report" in channel:
            return "default"
        proxy_pool_filter = set(self.proxy_pool).difference(set(channel["report"]["used_connections"]))
        return list(proxy_pool_filter)[0] if proxy_pool_filter else "tor"

    def get_items_recursive(self, map: dict, page: list) -> [BeautifulSoup]:
        if not map["next"]:
            all_els = []
            for el in page:
                all_els.extend(el.find_all(map["name"], attrs=map['attrs']))
            return all_els
        else:
            all_els = []
            for element in page:
                for level in map["el_list"]:
                    all_els.extend(element.find_all(level["name"], attrs=level['attrs']))
            return self.get_items_recursive(map["next"], all_els)


    @staticmethod
    def _abs_url(base_url: str, href: str):
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            return None
        href = href.strip()
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("http://") or href.startswith("https://"):
            return href
        base = base_url.rstrip("/")
        if href.startswith("/"):
            # scheme://host
            m = re.match(r"(https?://[^/]+)", base)
            if not m:
                return None
            return m.group(1) + href
        return f"{base}/{href.lstrip('/')}"

    @staticmethod
    def _same_site(url: str, site: str) -> bool:
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        site = site.lower().lstrip(".")
        if host == site or host == f"www.{site}":
            return True
        # соседние поддомены ленты, не CDN/assets
        if host.endswith("." + site):
            sub = host[: -len(site) - 1]
            return bool(re.search(r"(^|[.-])(rss|feed|atom|news|www)([.-]|$)", sub))
        return False

    @staticmethod
    def _feed_hint(href: str, text: str = "") -> bool:
        if not href:
            return False
        if re.search(r"\.(css|js|mjs|png|jpe?g|gif|webp|svg|woff2?|ttf|ico)(?:$|\?)", href, flags=re.I):
            return False
        low = href.lower()
        if "feedback" in low or "/auth" in low or "/kek/" in low:
            return False
        blob = f"{href} {text or ''}".lower()
        keys = ("rss", "atom", "feed")
        if any(k in blob for k in keys):
            return True
        return bool(re.search(r"[\./]xml(?:$|\?)", href, flags=re.I))

    @staticmethod
    def _candidate_score(url: str) -> int:
        u = url.lower()
        score = 0
        if "feedback" in u or "/auth" in u or "/kek/" in u or "/page" in u:
            return -1000
        if re.search(r"/rss(?:\.xml)?(?:/|$|\?)", u) or re.search(r"[\./]rss(?:/|$|\?)", u):
            score += 80
        if "atom" in u:
            score += 60
        if re.search(r"\.xml(?:$|\?)", u):
            score += 40
        if re.search(r"/feed(?:/|$|\?)", u):
            score += 15
        if u.startswith("https://"):
            score += 2
        return score

    async def _http_get(self, url, connection_mode, headers=None):
        timeout = aiohttp.ClientTimeout(total=60)
        proxy, default_headers = get_connection_options(connection_mode, response_type=str)
        if not headers:
            headers = default_headers
        try:
            async with aiohttp.request("get", url, headers=headers, timeout=timeout, proxy=proxy) as response:
                status = response.status
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                try:
                    body = await response.text()
                except UnicodeDecodeError:
                    body = (await response.read()).decode("utf-8", errors="ignore")
                return status, content_type, body
        except Exception:
            self.logger.warning(utils.get_exception())
            return None, None, None

    def _count_feed_items(self, body: str, content_type: str):
        """Return (is_feed_like, item_count). Reject HTML stubs without feed nodes."""
        if not body:
            return False, 0
        soup = BeautifulSoup(body, "lxml")
        items = soup.find_all("item")
        if not items:
            items = soup.find_all("entry")
        n = len(items)
        ct = content_type or ""
        has_feed_root = bool(soup.find("rss") or soup.find("feed") or soup.find("rdf:RDF") or soup.find("RDF"))
        if n > 0:
            return True, n
        if "rss" in ct or "atom" in ct or ("xml" in ct and has_feed_root):
            return True, 0
        if soup.find("html") and not has_feed_root:
            return False, 0
        if has_feed_root:
            return True, 0
        return False, 0

    async def probe_rss_url(self, url, connection_mode, site=None):
        status, content_type, body = await self._http_get(url, connection_mode)
        if status is None:
            self.logger.info(
                f'[map_feed] url={site or "-"} step=rss_probe feed={url} result=error'
            )
            return None
        is_feed, n = self._count_feed_items(body, content_type)
        self.logger.info(
            f'[map_feed] url={site or "-"} step=rss_probe feed={url} '
            f'status={status} ctype={content_type or "-"} items={n} is_feed={is_feed}'
        )
        if not is_feed:
            return {"url": url, "len": 0, "status": status, "content_type": content_type, "is_feed": False}
        return {"url": url, "len": n, "status": status, "content_type": content_type, "is_feed": True}

    def _extract_feed_links_from_soup(self, page_url: str, soup: BeautifulSoup, site: str):
        found = []
        for el in soup.find_all("link"):
            rel = " ".join(el.get("rel") if isinstance(el.get("rel"), list) else [el.get("rel") or ""]).lower()
            typ = (el.get("type") or "").lower()
            href = el.get("href")
            if "alternate" in rel and ("rss" in typ or "atom" in typ or "xml" in typ):
                abs_u = self._abs_url(page_url, href)
                if abs_u:
                    found.append(abs_u)
            elif self._feed_hint(href or "", ""):
                abs_u = self._abs_url(page_url, href)
                if abs_u:
                    found.append(abs_u)
        for el in soup.find_all("a"):
            href = el.get("href")
            text = el.get_text(" ", strip=True)[:80]
            if self._feed_hint(href or "", text):
                abs_u = self._abs_url(page_url, href)
                if abs_u:
                    found.append(abs_u)
        # prefer same-site, keep order, dedupe
        out = []
        seen = set()
        for u in found:
            if u in seen:
                continue
            seen.add(u)
            if site and not self._same_site(u, site):
                continue
            out.append(u)
        return out

    async def crawl_feed_candidates(self, channel, connection_mode, max_depth=1):
        site = channel["url"]
        seeds = [f"https://{site}/", f"http://{site}/"]
        candidates = []
        seen_pages = set()
        queue = [(u, 0) for u in seeds]
        while queue:
            page_url, depth = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            status, content_type, body = await self._http_get(page_url, connection_mode)
            if not body or status is None or status >= 400:
                continue
            soup = BeautifulSoup(body, "lxml")
            links = self._extract_feed_links_from_soup(page_url, soup, site)
            for link in links:
                candidates.append(link)
                # глубже только явные rss/atom-хабы, не HTML /feed/pageN
                if (
                    depth < max_depth
                    and re.search(r"(rss|atom)(?:\.xml)?(?:/|$|\?)", link, flags=re.I)
                    and "feedback" not in link.lower()
                ):
                    if link not in seen_pages:
                        queue.append((link, depth + 1))
        # dedupe preserve order
        out, seen = [], set()
        for u in candidates:
            if u not in seen:
                seen.add(u)
                out.append(u)
        self.logger.info(
            f'[map_feed] url={site} step=rss_crawl pages={len(seen_pages)} candidates={len(out)}'
        )
        return out

    async def find_rss(self, url, connection_mode, channel):
        """Probe a single URL (kept for compatibility)."""
        return await self.probe_rss_url(url, connection_mode, channel.get("url"))

    async def get_data_rss_pid4(self, connection_mode, rss_link, headers=None, return_rss_link=False, site=None):
        ua = UserAgent()
        if not headers:
            headers = {'User-Agent': ua.chrome}
        rss_link = re.findall("http[^']+", rss_link)[0]
        site = site or re.sub(r"^https?://", "", rss_link).split("/")[0]

        async def _load(url):
            status, content_type, body = await self._http_get(url, connection_mode, headers=headers)
            if status is None:
                return None, url, status, content_type
            is_feed, n = self._count_feed_items(body or "", content_type or "")
            self.logger.info(
                f'[map_feed] url={site} step=rss_fetch feed={url} '
                f'status={status} ctype={content_type or "-"} items={n} is_feed={is_feed}'
            )
            if not is_feed or n == 0 or not body:
                return None, url, status, content_type
            soup = BeautifulSoup(body, "lxml")
            items = soup.find_all("item") or soup.find_all("entry")
            return items, url, status, content_type

        items, used, status, ctype = await _load(rss_link)
        if not items:
            # scheme mirror
            if rss_link.startswith("https://"):
                alt = "http://" + rss_link[len("https://"):]
            elif rss_link.startswith("http://"):
                alt = "https://" + rss_link[len("http://"):]
            else:
                alt = None
            if alt:
                items, used, status, ctype = await _load(alt)
        if not items:
            # 1–2 common alternate paths on same host
            host = re.match(r"(https?://[^/]+)", used or rss_link)
            if host:
                base = host.group(1)
                for path in ("/feed", "/rss.xml", "/atom.xml"):
                    alt = base + path
                    if alt.rstrip("/") == (used or rss_link).rstrip("/"):
                        continue
                    items, used, status, ctype = await _load(alt)
                    if items:
                        break
        if return_rss_link:
            return items, used if items else rss_link
        return items

    async def get_items_pid55(self, connection_mode, link, collect_elements):
        proxy, headers = get_connection_options(connection_mode, response_type=str)
        timeout = aiohttp.ClientTimeout(total=60)
        try:
            async with aiohttp.request("get", link, headers=headers, timeout=timeout, proxy=proxy) as response:
                try:
                    response = await response.text()
                    soup = BeautifulSoup(response, 'lxml', multi_valued_attributes=None)
                except UnicodeDecodeError:
                    soup = BeautifulSoup(await response.read(), 'lxml', multi_valued_attributes=None)
        except Exception as ex:
            logger.info(utils.get_exception())
            return None
        items = []
        for el in collect_elements:
            items.extend(self.get_items_recursive(el, [soup]))
        return items

    async def get_collect_map(self, channel, connection_mode):
        collect_url = None
        if "collect_url" in channel:
            collect_url = channel['collect_url']
        collect_elements, collect_url, report, pattern, connect_error = await determinant_collect_element.run(channel, collect_url, connection_mode)
        if not connect_error:
            channel["collector_id"] = 55
            channel['collect_elements'] = collect_elements
            channel['collect_url'] = collect_url
            channel["link_pattern"] = pattern
        else:
            pass
        return channel, report, connect_error

    async def find_rss_process(self, connection_mode, channel):
        site = channel["url"]
        static_paths = [
            "/rss", "/feed", "/rss.xml", "/atom", "/atom.xml",
            "/index.xml", "/feeds/posts/default", "/ru/rss", "/rss/news", "/news/rss",
        ]
        static = []
        for scheme in ("https", "http"):
            for path in static_paths:
                static.append(f"{scheme}://{site}{path}")
        crawled = []
        try:
            crawled = await self.crawl_feed_candidates(channel, connection_mode, max_depth=1)
        except Exception:
            self.logger.warning(utils.get_exception())

        # crawl + typical paths; rank by feed-likeness so /rss не вытесняется HTML /feed
        merged = []
        seen = set()
        for u in crawled + static:
            if u not in seen:
                seen.add(u)
                merged.append(u)
        merged.sort(key=self._candidate_score, reverse=True)
        candidates = [u for u in merged if self._candidate_score(u) > -500][:24]

        probes = utils.del_none(
            await asyncio.gather(*[self.probe_rss_url(u, connection_mode, site) for u in candidates])
        )
        feed_probes = [p for p in probes if p.get("is_feed")]
        if not feed_probes:
            self.logger.info(f'[map_feed] url={site} step=rss found=False candidates={len(candidates)} feeds=0')
            return None
        best = max(feed_probes, key=lambda p: p.get("len") or 0)
        if (best.get("len") or 0) > 4:
            self.logger.info(
                f'[map_feed] url={site} step=rss found=True '
                f'url={best["url"]} items={best["len"]} candidates={len(candidates)} feeds={len(feed_probes)}'
            )
            return best["url"]
        self.logger.info(
            f'[map_feed] url={site} step=rss found=False '
            f'best_url={best.get("url")} items={best.get("len")} reason=too_few_items '
            f'candidates={len(candidates)} feeds={len(feed_probes)}'
        )
        return None


    async def _items_to_news(self, items, channel, site):
        """Filter raw RSS/HTML items into news docs. Returns (new_data, raw_n)."""
        raw_n = len(items) if items else 0
        if not items:
            self.logger.info(f'[map_feed] url={site} step=items raw=0 filtered=0')
            return [], 0
        docs = []
        use_pid55 = channel.get("collector_id") in [55]
        for item in items:
            if use_pid55:
                data = await self.create_docs_pid55(item, channel)
            else:
                data = await self.create_docs_pid50(item, channel)
            if data:
                docs.append(data)

        def _depth(link: str) -> int:
            return len(re.findall("/", re.sub("(?:https*://|//)", "", link)))

        def _filter(docs_in, toler: int):
            out, seen = [], []
            target = channel.get("link_pattern")
            for data in docs_in:
                link_ok = True
                if target is not None:
                    link_ok = abs(_depth(data["link"]) - target) <= toler
                if data["link"] not in seen and link_ok:
                    seen.append(data["link"])
                    out.append(data)
            return out

        # Exact pattern first; if too few — soft ±1; then recount mode from docs (D.3).
        if channel.get("link_pattern") is not None:
            new_data = _filter(docs, 0)
            if len(new_data) < MIN_MAP_NEWS:
                soft = _filter(docs, 1)
                if len(soft) > len(new_data):
                    new_data = soft
                    self.logger.info(
                        f'[map_feed] url={site} step=link_pattern relaxed=±1 '
                        f'kept={len(new_data)}'
                    )
            if len(new_data) < MIN_MAP_NEWS and docs:
                depths = [_depth(d["link"]) for d in docs]
                mode = max(set(depths), key=depths.count)
                channel["link_pattern"] = mode
                new_data = _filter(docs, 1)
                self.logger.info(
                    f'[map_feed] url={site} step=link_pattern recount mode={mode} '
                    f'kept={len(new_data)}'
                )
        else:
            new_data = _filter(docs, 0)

        self.logger.info(f'[map_feed] url={site} step=items raw={raw_n} filtered={len(new_data)}')
        return new_data, raw_n

    async def _assemble_via_html(self, report, channel, site, reason: str):
        """Build map from HTML listing. Clears RSS success flags. Returns (channel, report, new_data|None, fail_kind|None)."""
        channel.pop("rss_link", None)
        report["rss"] = False
        self.logger.info(f'[map_feed] url={site} step=rss_failed reason={reason} try_html=1')
        channel, report["collector"], connect_error = await self.get_collect_map(
            channel, channel["connection_mode"]
        )
        if connect_error or not channel.get("collect_url"):
            return channel, report, None, "find_collect_elements"
        items = await self.get_items_pid55(
            channel["connection_mode"], channel["collect_url"], channel["collect_elements"]
        )
        new_data, _ = await self._items_to_news(items, channel, site)
        if len(new_data) < MIN_MAP_NEWS:
            return channel, report, None, f"collect_news:{len(new_data)}"
        return channel, report, new_data, None

    async def start_collector_map_assembly_process(self, report, channel, link, unittest=False):
        site = channel["url"]
        tried_rss = False

        # Bench / HTML-only: skip RSS seed and discovery (D HTML measurement).
        if channel.get("skip_rss") or channel.get("force_html"):
            link = None
            report["rss"] = False
            channel.pop("rss_link", None)
            self.logger.info(f'[map_feed] url={site} step=rss skipped=force_html')
            channel, report, new_data, fail_kind = await self._assemble_via_html(
                report, channel, site, "force_html"
            )
            if new_data:
                if unittest:
                    return True
                return channel, report, new_data
            if unittest:
                return False
            if fail_kind == "find_collect_elements":
                self.logger.warning(f'FAILED find collect_elements on {site}')
                report["failed_log"] = "FAILED find collect_elements"
                report["status"] = 2
            elif fail_kind and fail_kind.startswith("collect_news:"):
                n = fail_kind.split(":", 1)[1]
                self.logger.warning(f'FAILED collected news on {site} {n}')
                report["failed_log"] = f"FAILED collect news ({n})"
                report["status"] = 3
            else:
                self.logger.warning(f'FAILED collect items on {site}')
                report["failed_log"] = "FAILED collect items"
                report["status"] = 3
            return channel, report, None

        if not link:
            rss = await self.find_rss_process(channel["connection_mode"], channel)
            if rss:
                report["rss"] = True
                channel["rss_link"] = [rss]
                link = rss
                tried_rss = True
            else:
                report["rss"] = False
        else:
            report["rss"] = True
            tried_rss = True
            self.logger.info(f'[map_feed] url={site} step=rss found=True url={link} source=seed')

        # --- RSS path (discovered or seed) ---
        if tried_rss and link:
            items, rss_link = await self.get_data_rss_pid4(
                channel["connection_mode"],
                link,
                headers=channel["headers"] if "headers" in channel else None,
                return_rss_link=True,
                site=site,
            )
            if items:
                channel["rss_link"] = [rss_link]
                new_data, _ = await self._items_to_news(items, channel, site)
                if len(new_data) >= MIN_MAP_NEWS:
                    if unittest:
                        return True
                    return channel, report, new_data
                reason = f"too_few_news:{len(new_data)}"
            else:
                reason = "empty_feed"

            # RSS did not yield a usable map → full HTML retry
            channel, report, new_data, fail_kind = await self._assemble_via_html(
                report, channel, site, reason
            )
            if new_data:
                if unittest:
                    return True
                return channel, report, new_data
            if unittest:
                return False
            if fail_kind == "find_collect_elements":
                self.logger.warning(f'FAILED find collect_elements on {site}')
                report["failed_log"] = "FAILED find collect_elements"
                report["status"] = 2
            elif fail_kind and fail_kind.startswith("collect_news:"):
                n = fail_kind.split(":", 1)[1]
                self.logger.warning(f'FAILED collected news on {site} {n}')
                report["failed_log"] = f"FAILED collect news ({n})"
                report["status"] = 3
            else:
                self.logger.warning(f'FAILED collect items on {site}')
                report["failed_log"] = "FAILED collect items"
                report["status"] = 3
            return channel, report, None

        # --- HTML-only path (no RSS candidate) ---
        if 'collector_id' in channel and channel['collector_id'] in [55] and channel.get("collect_url"):
            items = await self.get_items_pid55(
                channel["connection_mode"], channel["collect_url"], channel["collect_elements"]
            )
        else:
            channel, report["collector"], connect_error = await self.get_collect_map(
                channel, channel["connection_mode"]
            )
            if connect_error:
                if unittest:
                    return False
                self.logger.warning(f'FAILED find collect_elements on {site}')
                report["failed_log"] = "FAILED find collect_elements"
                report["status"] = 2
                return channel, report, None
            if not channel.get("collect_url"):
                if unittest:
                    return False
                self.logger.warning(f'FAILED find collect_url {site}')
                report["failed_log"] = "FAILED find collect_url"
                report["status"] = 3
                return channel, report, None
            items = await self.get_items_pid55(
                channel["connection_mode"], channel["collect_url"], channel["collect_elements"]
            )

        new_data, _ = await self._items_to_news(items, channel, site)
        if len(new_data) < MIN_MAP_NEWS:
            if unittest:
                return False
            if not items:
                self.logger.warning(f'FAILED collect items on {site}')
                report["failed_log"] = "FAILED collect items"
                report["status"] = 3
            else:
                self.logger.warning(f'FAILED collected news on {site} {len(new_data)}')
                report["failed_log"] = f"FAILED collect news ({len(new_data)})"
                report["status"] = 3
            return channel, report, None
        if unittest:
            return True
        return channel, report, new_data


    async def create_docs_pid50(self, item, channel):
        try:
            title = utils.clean(item.find('title').get_text())
        except:
            return None
        description = None
        if channel['url'].find('media.ru') != -1 or channel['url'].find('media.su') != -1 :
            if channel['url'] not in ['www.intermedia.ru', 'crypto-media.ru', "nashemedia.ru", "gorets-media.ru"]:
                description = item.find('description').get_text()
        if description and '<![CDATA' in description:
            description = None
        try:
            pubdate = int(dateparser.parse(item.find('pubdate').get_text()).timestamp())
        except:
            try:
                pubdate = int(dateparser.parse(item.find('published').get_text()).timestamp())
            except:
                return None
        link = item.find("link").get_text(strip=True)
        if not link:
            link = utils.del_none([utils.get_first_el(re.findall(r'http[^\r\n\t\]\["]+', text_item)) for text_item in
                             item.get_text("|").split('|')])
            if not link:
                link = utils.del_none([utils.get_first_el(re.findall(r'.*(/[^\r\n\t\]\["]+)', text_item)) for text_item in
                                 item.get_text("|").split('|')])
            if link:
                link = re.sub(']]>', '', link[0].strip())
                if link[-3:] in weekdays:
                    link = link[:-3]
                if re.fullmatch('.+\.html[А-Яа-я]+', link):
                    link = re.sub('\.html[А-Яа-я]+', '.html', link)
            else:
                return None
        item_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, link))

        if 'www.rbc.ru' in channel['url']:
            description = utils.clean(item.find('description').get_text())
        img = [item.find('enclosure', type='image/jpeg').get('url')] if item.find('enclosure',
                                                                                  type='image/jpeg') else None
        if not re.fullmatch('(?:.+?)(?:\.jpg|\.jpeg|\.jepeg|\.webp)(?:.*?[ "<>])', str(img)):
            img = None
        imgF = True if img else False
        collect_date = int(tm.mktime(datetime.datetime.now().timetuple()))
        important = False
        if 'important' in channel.keys():
            if channel['important']:
                important = True
        doc = {
            "important": important,
            "_key": item_uuid,
            "uuid": item_uuid,
            "link": link,
            "site": channel['url'],
            "title": title,
            "feed_id": channel.get('feed_id'),
            "user_id": channel.get('user_id'),
            "collect_date": collect_date,
            "published_date": check_time(pubdate),
            "description": description,
            "imgF": imgF,
            "videoF": False,
            "main": channel.get('main'),
            "parser_id": channel.get('parser_id'),
            "news_element" if channel.get('parser_id') not in [53] else "news_elements": channel['news_element'] if 'news_element' in channel else channel['news_elements'] if 'news_elements' in channel else None,
            "div_white_list": channel['div_white_list'] if 'div_white_list' in channel else None,
            "additional_element": channel['additional_element'] if 'additional_element' in channel else None,
            "trash_items": channel['trash_items'] if 'trash_items' in channel else None,
            'breaker_items': {'breaker_el_list': [], 'breaker_re_strings': []},
            "debug": True,
            "split_br_tags": True,
            "rss_data": {
                "images": img
            }
        }
        return doc

    async def create_docs_pid55(self, item, channel):
        link = None
        title = None
        pubdate = None
        protocol = re.findall("(https*):", channel["collect_url"])[0]
        all_text = item.get_text('|').split('|')
        try:
            title = utils.clean(item.find(lambda el: re.fullmatch("h[0-9]+", el.name)).get_text(strip=True))
        except:
            pass
        bigest_text = {"long": 0, "text": None}
        for text_item in all_text:
            if not pubdate:
                try:
                    pubdate = int(dateparser.parse(text_item).timestamp())
                    continue
                except:
                    pass
            if not title:
                if len(text_item) > bigest_text["long"]:
                    bigest_text = {"long": len(text_item), "text": text_item}
        if not title:
            if not bigest_text["text"]:
                return
            title = utils.clean(bigest_text["text"])
        if len(re.findall("[а-яА-ЯЁёA-Za-z]+", title)) < 3:
            return
        title_els = item.find_all(lambda el: utils.soup_clean(str(el)) == utils.soup_clean(title))
        if not title_els:
            return
        title_el: BeautifulSoup = title_els[-1]
        while title_el:
            if link:
                break
            try:
                link = title_el.get("href") if "href" in title_el.attrs else None
            except:
                pass
            title_el = title_el.parent
        links = [el.get('href') for el in item.find_all(lambda element: True if "href" in element.attrs else False)]
        if link: links.insert(0, link)
        if links:
            link = links[0]
            if not link.startswith('http'):
                link = f'{protocol}://{channel["url"]}/{link if not re.fullmatch(f"""(?:/|{channel["url"]})+.+""", link, flags=re.DOTALL) else str(utils.get_first_el(re.findall(f"""(?:/|{channel["url"]})+(.+)""", link, flags=re.DOTALL)))}'
            link = re.sub("/{3,}", "//", link)
            item_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, re.sub("https*://", "", link)))
        #print(f'link {link}\ntitle {title}\npubdate ')
        # D.3: pubdate optional on HTML listing — keep title+link; date may appear later.
        if link and title:
            collect_date = int(tm.mktime(datetime.datetime.now().timetuple()))
            published = check_time(pubdate) if pubdate else collect_date
            doc = {
                "important": channel['important'] if "important" in channel else False,
                "_key": item_uuid,
                "uuid": item_uuid,
                "link": link,
                "site": channel['url'],
                "title": title,
                "feed_id": channel['feed_id'],
                "user_id": channel['user_id'],
                "collect_date": collect_date,
                "published_date": published,
                "description": None,
                "imgF": False,
                "videoF": False,
                "main": channel['main'] if "main" in channel else False,
                "parser_id": channel['parser_id'],
                "news_element" if channel['parser_id'] not in [53, 54] else "news_elements": channel['news_element'] if 'news_element' in channel else channel['news_elements'] if 'news_elements' in channel else None,
                "div_white_list": channel['div_white_list'] if 'div_white_list' in channel else None,
                "additional_element": channel['additional_element'] if 'additional_element' in channel else None,
                "trash_items": channel['trash_items'] if 'trash_items' in channel else None,
                'breaker_items': {'breaker_el_list': [], 'breaker_re_strings': []},
                "dont_get_header_img": channel['dont_get_header_img'] if 'dont_get_header_img' in channel else False,
                "split_br_tags": channel['split_br_tags'] if 'split_br_tags' in channel else True,
                "debug": channel['debug'] if 'debug' in channel else False,
                "get_all_iframe": channel['get_all_iframe'] if 'get_all_iframe' in channel else False
            }
            return doc
