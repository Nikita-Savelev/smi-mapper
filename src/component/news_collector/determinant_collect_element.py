from bs4 import BeautifulSoup
import aiohttp
import re
from fake_useragent import UserAgent
import json
import dateparser
from dateparser.search import search_dates
from aiohttp import client_exceptions
import asyncio
from aiohttp_socks import ProxyConnector
from common.utils import get_connection_options
import random
from urllib.parse import urljoin, urlparse
from loguru import logger

# HTML listing seeds beyond /news and /articles (D.1). Homepage added separately.
HTML_FEED_PATHS = (
    "/news",
    "/novosti",
    "/articles",
    "/press",
    "/pressa",
    "/press-center",
    "/press_center",
    "/media",
    "/lenta",
    "/publications",
    "/publikacii",
    "/blog",
    "/smi",
)

# Anchor/path tokens that look like a news section in site nav.
_NEWS_LINK_RE = re.compile(
    r"(новост|news|press|пресс|лент|article|стать|публикац|media|сми|"
    r"blog|блог|anons|анонс|событ|event|digest|дайджест)",
    re.I,
)

# Skip obvious non-listing paths even if text matches loosely.
_NAV_SKIP_RE = re.compile(
    r"(login|signin|signup|register|cabinet|account|cart|cookie|"
    r"privacy|policy|about|contact|контак|о[-_]?нас|search|поиск|"
    r"mailto:|tel:|javascript:|#)",
    re.I,
)

# Never fetch/parse as listing HTML (apk hung kommersant ~30+ min).
_BINARY_EXT_RE = re.compile(
    r"\.(apk|ipa|exe|dmg|msi|deb|rpm|zip|rar|7z|gz|tgz|tar|bz2|"
    r"pdf|docx?|xlsx?|pptx?|odt|ods|"
    r"jpe?g|png|gif|webp|svg|ico|bmp|"
    r"mp[34]|m4a|wav|avi|mkv|mov|webm|wasm|bin|iso)(?:$|\?|#)",
    re.I,
)

MAX_HTML_FEED_CANDIDATES = 16
MAX_NAV_FEED_CANDIDATES = 8
# GET for listing pages: hard cap (apk/binary must not hang the worker).
HTML_PAGE_TIMEOUT_SEC = 90


def _looks_like_binary_url(url: str) -> bool:
    path = urlparse(url or "").path or ""
    return bool(_BINARY_EXT_RE.search(path))


def _content_type_ok_for_html(ctype: str | None) -> bool:
    """False for apk/octet-stream/images; True if missing (many sites omit CT)."""
    if not ctype:
        return True
    ct = ctype.split(";")[0].strip().lower()
    if ct.startswith("text/"):
        return True
    if ct in ("application/xhtml+xml", "application/xml", "text/xml"):
        return True
    return False


def get_first_el(some_list):
    return some_list[0] if len(some_list) >= 1 else None

def soup_clean(text):
    return re.sub('[^a-zA-Z0-9а-яА-Я]', '', clean(text))

def erect_to_percent(num, percent):
    return num / 100 * percent

def clean(item):
    if item is None:
        return ""
    if type(item) is list:
        string = []
        for i in item:
            if i is None:
                continue
            string.append(re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\"|\\n|\\t)+', '', i))).strip())
        return string
    return re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\n|\\t)+', '', item))).strip()

async def get_page(link, connection_mode):
    if _looks_like_binary_url(link):
        logger.info(f'[map_feed] step=html_page skip=binary_ext url={link}')
        return (None, None, link)
    timeout = aiohttp.ClientTimeout(total=HTML_PAGE_TIMEOUT_SEC)
    connector, headers = get_connection_options(connection_mode, response_type=str)
    retry = 0
    while retry <= 3:
        try:
            async with aiohttp.request("get", link, headers=headers, timeout=timeout, proxy=connector) as response:
                status = response.status
                ctype = response.headers.get("Content-Type")
                # 4xx/5xx: drain body, skip BeautifulSoup — never used for map find.
                if status is None or status >= 400:
                    try:
                        await response.read()
                    except Exception:
                        pass
                    return (None, status, link)
                if not _content_type_ok_for_html(ctype):
                    try:
                        await response.read()
                    except Exception:
                        pass
                    logger.info(
                        f'[map_feed] step=html_page skip=content_type '
                        f'ctype={ctype!r} url={link}'
                    )
                    return (None, status, link)
                try:
                    response = await response.text()
                    soup = BeautifulSoup(response, 'lxml', multi_valued_attributes=None)
                except:
                    soup = BeautifulSoup(await response.read(), 'lxml', multi_valued_attributes=None)
                return (soup, status, link)
        except:
            retry += 1


def required_parameters(el):
    try:
        text = el.get_text(strip=True)
        int(dateparser.parse(text).timestamp())
        if len(re.findall("[0-9]", text)) > 0 and \
            len(re.findall(r"[\. :-]", text)) > 0:
            return True
    except:
        return False

def get_short_el_name(el):
    el_name = el.name
    el_attrs = el.attrs
    short_name = f'{el_name}|{json.dumps(el_attrs)}'
    return short_name


def find_optimum_elements(page):
    all_links = {}
    best_pattern = {"pattern": "", "count": 0}
    null_href_in_attrs = 0
    for el in page.find_all(lambda el: "href" in el.attrs):
        href = el.get("href")
        if href is None or not isinstance(href, str):
            null_href_in_attrs += 1
    if null_href_in_attrs:
        logger.warning(
            f"[map_feed] step=find_optimum_elements null_href_in_attrs={null_href_in_attrs} "
            f"(href in attrs but value not str — re.fullmatch risk)"
        )
    for link in [re.sub("[0-9]+", "[0-9]+", re.sub("(.+/)(.+)", r"\1.+?", re.sub("([\\\|\[\]{}()+*^])", r"\\\1", el.get("href") if el.get("href")[-1] != "/" else el.get("href")[:-1]), flags=re.DOTALL)) + "/*" for el in page.find_all(lambda el: "href" in el.attrs) if el.get("href")]:
        if link not in all_links:
            all_links[link] = 1
        all_links[link] += 1
        if all_links[link] > best_pattern["count"]:
            best_pattern = {"pattern": link, "count": all_links[link]}
    try:
        matched = page.find_all(
            lambda el: isinstance(el.get("href"), str)
            and bool(el.get("href"))
            and re.fullmatch(best_pattern["pattern"], el.get("href"), flags=re.DOTALL)
        )
    except TypeError as exc:
        logger.warning(
            f"[map_feed] step=find_optimum_elements TypeError pattern={best_pattern!r} "
            f"null_href_in_attrs={null_href_in_attrs} err={exc}"
        )
        raise
    return matched, best_pattern["pattern"]


def find_card_anchor_elements(page, min_repeat: int = 3):
    """
    D.2: repeating card wrappers (same attrs + link + title) without requiring a date.
    Returns list of card elements or [].
    """
    if page is None:
        return []
    by_name = {}
    for el in page.find_all(["div", "article", "li", "section", "tr"]):
        if not el or el.name in ("html", "body", "[document]"):
            continue
        # Prefer compact cards: too many nested links → section/menu
        n_links = len(el.find_all("a", href=True))
        if n_links == 0 or n_links > 8:
            continue
        href = get_href(el)
        if not href:
            continue
        sn = get_short_el_name(el)
        by_name.setdefault(sn, []).append(el)

    best_els = []
    best_key = None
    for sn, els in by_name.items():
        if len(els) < min_repeat:
            continue
        uniq = set()
        for e in els:
            h = get_href(e)
            if h:
                uniq.add(re.sub(r"/+$", "", h.lower()))
        if len(uniq) < min_repeat:
            continue
        # Prefer more unique links, then more cards
        key = (len(uniq), len(els))
        if best_key is None or key > best_key:
            best_key = key
            best_els = els
    return best_els


_MENU_PATH_RE = re.compile(
    r"/(?:about|contact|kontact|login|signin|signup|search|tag|tags|author|user|"
    r"privacy|cookie|cabinet|cart|faq|help)(?:/|$)",
    re.I,
)


def _href_path(href: str) -> str:
    try:
        if href.startswith("//"):
            href = "https:" + href
        if not re.match(r"^https?://", href, re.I):
            return href.split("?")[0]
        return urlparse(href).path or "/"
    except Exception:
        return href or "/"


def looks_like_article_url(href: str) -> bool:
    path = _href_path(href)
    parts = [p for p in path.split("/") if p]
    if re.search(r"\d{4}", path):
        return True
    if len(parts) >= 3:
        return True
    if len(parts) >= 2 and len(parts[-1]) >= 12:
        return True
    if re.search(r"\d{5,}", path):
        return True
    return False


def looks_like_menu_url(href: str) -> bool:
    path = _href_path(href)
    if _MENU_PATH_RE.search(path):
        return True
    parts = [p for p in path.split("/") if p]
    # bare section roots without article signals
    if len(parts) <= 1 and not re.search(r"\d", path):
        return True
    return False


def score_listing_candidate(page, maps, report, pattern, site: str) -> dict:
    """
    D.4: score a candidate listing page / map set.
    Higher is better. rejected=True → do not pick this page.
    """
    if not maps:
        return {"score": -1e9, "rejected": True, "reason": "no_maps", "uniq": 0, "article_like": 0}

    items = []
    for m in maps:
        try:
            items.extend(get_items_recursive(m, [page]))
        except Exception:
            continue

    links = []
    for it in items:
        h = get_href(it)
        if h:
            links.append(h)
    uniq = {re.sub(r"/+$", "", h.lower()) for h in links}
    article_like = sum(1 for u in uniq if looks_like_article_url(u))
    menu_like = sum(1 for u in uniq if looks_like_menu_url(u))

    score = 0.0
    score += min(len(uniq), 40) * 3
    score += article_like * 6
    score -= menu_like * 5
    score += min(len(maps), 8) * 0.5  # weak signal; not primary

    anchor = (report or {}).get("anchor")
    if anchor == "cards":
        score += 22
    elif anchor == "dates":
        score += 15
    elif anchor == "href_fallback":
        score -= 12

    # Few unique targets while many nodes → classic menu scrape
    if len(items) >= 6 and len(uniq) <= 2:
        score -= 60
    if article_like == 0 and menu_like >= max(3, len(uniq) // 2):
        return {
            "score": -1e6,
            "rejected": True,
            "reason": "menu_like",
            "uniq": len(uniq),
            "article_like": article_like,
            "menu_like": menu_like,
        }
    if len(uniq) == 0:
        return {
            "score": -1e6,
            "rejected": True,
            "reason": "no_links",
            "uniq": 0,
            "article_like": 0,
            "menu_like": menu_like,
        }

    return {
        "score": score,
        "rejected": False,
        "reason": "ok",
        "uniq": len(uniq),
        "article_like": article_like,
        "menu_like": menu_like,
        "anchor": anchor,
    }


def get_href(item):
    pubdate = None
    title = None
    link = None
    all_text = item.get_text('|').split('|')
    try:
        h_el = item.find(lambda el: el.name and re.fullmatch("h[0-9]+", el.name))
        if h_el is not None:
            title = clean(h_el.get_text(strip=True))
    except Exception:
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
        raw_title = bigest_text["text"]
        if raw_title is None:
            return
        title = clean(raw_title)
    if not title:
        return
    if len(re.findall("[а-яА-ЯЁёA-Za-z]+", title)) < 3:
        return
    links = [el.get("href") if "href" in el.attrs else None for el in item.find_all("a")]
    if links:
        if len(links) > 1:
            try:
                title_el: BeautifulSoup = item.find_all(lambda el: clean(str(el)).strip() == title.strip() or clean(str(el.get_text(strip=True))) == title.strip())[-1]
                while title_el:
                    if link:
                        break
                    try:
                        link = title_el.get("href") if "href" in title_el.attrs else None
                    except:
                        pass
                    title_el = title_el.parent
            except:
                link = links[0]
        else:
            link = links[0]
    return link


def find_collector_element(page, site, status):
    import time as _time
    t0 = _time.monotonic()
    all_elements = {}
    logger.info(f'[map_feed] url={site} step=html_find begin status={status}')
    all_date_elements = page.find_all(required_parameters)
    t_dates = _time.monotonic()
    logger.info(
        f'[map_feed] url={site} step=html_find phase=dates '
        f'n={len(all_date_elements)} ms={int((t_dates - t0) * 1000)}'
    )
    # Dates already give an anchor — skip expensive cards scan (quality-neutral).
    if all_date_elements:
        card_elements = []
        t_cards = t_dates
        logger.info(
            f'[map_feed] url={site} step=html_find phase=cards skipped=1 '
            f'reason=dates_found n_dates={len(all_date_elements)}'
        )
        optimum_elements = all_date_elements
        anchor = "dates"
    else:
        card_elements = find_card_anchor_elements(page, min_repeat=3)
        t_cards = _time.monotonic()
        logger.info(
            f'[map_feed] url={site} step=html_find phase=cards '
            f'n={len(card_elements) if card_elements else 0} ms={int((t_cards - t_dates) * 1000)}'
        )
        if card_elements:
            optimum_elements = card_elements
            anchor = "cards"
        else:
            logger.info(f'[map_feed] url={site} step=html_find phase=href_fallback_start')
            optimum_elements, _href_pat = find_optimum_elements(page)
            logger.info(
                f'[map_feed] url={site} step=html_find phase=href_fallback_done '
                f'n={len(optimum_elements) if optimum_elements else 0} '
                f'ms={int((_time.monotonic() - t_cards) * 1000)}'
            )
            anchor = "href_fallback"
    all_patterns = {}
    logger.info(
        f'[map_feed] url={site} step=html_find phase=anchor={anchor} '
        f'optimum_n={len(optimum_elements) if optimum_elements else 0}'
    )
    unical_els = {}
    t_climb0 = _time.monotonic()
    if anchor == "cards":
        # Card wrappers are already the listing items — don't climb to a bigger parent.
        for el in optimum_elements:
            href = get_href(el)
            if not href:
                continue
            short_el_name = get_short_el_name(el)
            len_options = len(re.findall("/", re.sub("(?:https*://|//)", "", href)))
            if len_options not in all_patterns:
                all_patterns[len_options] = 0
            all_patterns[len_options] += 1
            if short_el_name not in all_elements:
                all_elements[short_el_name] = {"count": 0, "parents": {}}
            all_elements[short_el_name]["count"] += 1
    else:
        for i, el in enumerate(optimum_elements):
            if i and i % 50 == 0:
                logger.info(
                    f'[map_feed] url={site} step=html_find phase=climb '
                    f'i={i}/{len(optimum_elements)} ms={int((_time.monotonic() - t_climb0) * 1000)}'
                )
            el_name = get_short_el_name(el)
            if el_name not in unical_els:
                unical_els[el_name] = {"count": 0, "text_in_el": 0, "href_in_el": 0}
            unical_els[el_name]["count"] += 1
            parent = el.parent
            element_found = False
            level = 1
            while parent:
                if parent.name in ["html", "body", "[document]"]:
                    parent = parent.parent
                    continue
                short_el_name = get_short_el_name(parent)
                if not element_found:
                    if del_none([True if len(re.findall("[А-Яа-яЁёa-zA-Z]+", text)) > 2 else False for text in parent.get_text('|').split('|')]):
                        unical_els[el_name]["text_in_el"] += 1
                        href = get_href(parent)
                        if href:
                            len_options = len(re.findall("/", re.sub("(?:https*://|//)", "", href)))
                            if len_options not in all_patterns:
                                all_patterns[len_options] = 0
                            all_patterns[len_options] += 1
                            unical_els[el_name]["href_in_el"] += 1
                            if short_el_name not in all_elements:
                                all_elements[short_el_name] = {"count": 0, "parents": {}}
                            all_elements[short_el_name]['count'] += 1
                            element_found = short_el_name
                else:
                    if level not in all_elements[element_found]["parents"]:
                        all_elements[element_found]["parents"][level] = [short_el_name]
                    if short_el_name not in all_elements[element_found]["parents"][level]:
                        all_elements[element_found]["parents"][level].append(short_el_name)
                    level += 1
                parent = parent.parent
    logger.info(
        f'[map_feed] url={site} step=html_find phase=climb_done '
        f'keys={len(all_elements)} ms={int((_time.monotonic() - t_climb0) * 1000)}'
    )
    # for el in unical_els:
    #     print(el)
    maps = []
    t_maps0 = _time.monotonic()
    for el_i, el in enumerate(all_elements):
        if el_i and el_i % 20 == 0:
            logger.info(
                f'[map_feed] url={site} step=html_find phase=build_maps '
                f'i={el_i}/{len(all_elements)} maps={len(maps)} '
                f'ms={int((_time.monotonic() - t_maps0) * 1000)}'
            )
        name = re.findall("(.+?)\|", el)[0]
        attrs = re.findall(".+?\|(.+)", el)[0]
        attrs = json.loads(attrs)
        count_el_in_page = len(page.find_all(name, attrs=attrs))
        if all_elements[el]['count'] < count_el_in_page:
            lmap = {"name": name, "attrs": attrs, "next": False}
            level = 0
            for _ in all_elements[el]["parents"]:
                level += 1
                el_list = []
                if len(all_elements[el]["parents"][level]) > 3:
                    continue
                for el_full_name in all_elements[el]["parents"][level]:
                    name, attrs = el_full_name.split('|', 1)
                    attrs = json.loads(attrs)
                    el_list.append({"name": name, "attrs": attrs})
                lmap = {"el_list": el_list, "next": lmap}
                if len(get_items_recursive(lmap, [page])) >= all_elements[el]['count']:
                    break
            maps.append(lmap)
        else:
            lmap = {"name": name, "attrs": attrs, "next": False, "special_path": {"title": None, "link": None, "pubdate": None}}
            maps.append(lmap)
            continue
    res = {
        "response_code": status,
        "all_date_elements": len(all_date_elements),
        "card_elements": len(card_elements) if card_elements else 0,
        "fit_elements": len(all_elements),
        "map_els": len(maps),
        "anchor": anchor,
    }
    best_patern = {"len_options": None, "count": 0}
    for pat in all_patterns:
        if all_patterns[pat] > best_patern["count"]:
            best_patern["len_options"] = pat
            best_patern["count"] = all_patterns[pat]
    pattern = best_patern["len_options"]
    logger.info(
        f'[map_feed] url={site} step=html_find done anchor={anchor} '
        f'dates={res["all_date_elements"]} cards={res["card_elements"]} '
        f'maps={len(maps)} total_ms={int((_time.monotonic() - t0) * 1000)}'
    )
    return maps, res, pattern

def get_items_recursive(map: dict, page: list) -> [BeautifulSoup]:
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
        return get_items_recursive(map["next"], all_els)

def del_none(some_list):
    return [item for item in some_list if item]


def _normalize_host(site: str) -> str:
    return re.sub(r"^https?://", "", (site or "").strip()).rstrip("/").lower()


def _same_site(url: str, site: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        base = _normalize_host(site)
        if base.startswith("www."):
            base = base[4:]
        return host == base or host.endswith("." + base)
    except Exception:
        return False


def _path_depth(url: str) -> int:
    path = urlparse(url).path or "/"
    return len([p for p in path.split("/") if p])


def seed_html_feed_urls(site: str) -> list:
    """Fixed listing URL seeds (http+https) for a host."""
    host = _normalize_host(site)
    urls = []
    for scheme in ("https", "http"):
        urls.append(f"{scheme}://{host}/")
        for path in HTML_FEED_PATHS:
            urls.append(f"{scheme}://{host}{path}")
    return urls


def _nav_link_score(href: str, text: str) -> int:
    score = 0
    path = (urlparse(href).path or "").lower()
    blob = f"{path} {text}".lower()
    if _NEWS_LINK_RE.search(path):
        score += 40
    if _NEWS_LINK_RE.search(text or ""):
        score += 25
    if _NEWS_LINK_RE.search(blob):
        score += 5
    depth = _path_depth(href)
    if depth == 1:
        score += 10
    elif depth == 2:
        score += 6
    elif depth > 4:
        score -= 15
    if href.startswith("https://"):
        score += 2
    return score


def extract_nav_feed_candidates(soup, page_url: str, site: str, limit: int = MAX_NAV_FEED_CANDIDATES) -> list:
    """Collect same-site nav/menu links that look like news listings."""
    if soup is None:
        return []
    ranked = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href_raw = (a.get("href") or "").strip()
        if not href_raw or href_raw.startswith("#"):
            continue
        if _NAV_SKIP_RE.search(href_raw):
            continue
        abs_url = urljoin(page_url, href_raw)
        if abs_url.startswith("//"):
            abs_url = "https:" + abs_url
        if not abs_url.startswith("http"):
            continue
        if not _same_site(abs_url, site):
            continue
        path = urlparse(abs_url).path or "/"
        if path in ("", "/"):
            continue
        if _looks_like_binary_url(abs_url):
            continue
        text = a.get_text(" ", strip=True) or ""
        if _NAV_SKIP_RE.search(text):
            continue
        if not (_NEWS_LINK_RE.search(path) or _NEWS_LINK_RE.search(text)):
            continue
        # Drop article-like deep URLs (dates / long numeric segments)
        if re.search(r"/\d{4}/\d{1,2}/\d{1,2}/", path):
            continue
        if _path_depth(abs_url) >= 3 and re.search(r"/\d{3,}", path):
            continue
        if _path_depth(abs_url) >= 4:
            continue
        key = abs_url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        ranked.append((_nav_link_score(abs_url, text), abs_url))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [u for _, u in ranked[:limit]]


def build_html_feed_candidates(site: str, nav_urls: list | None = None, max_total: int = MAX_HTML_FEED_CANDIDATES) -> list:
    """
    Merge homepage + nav links + seed paths into a capped candidate list.
    Nav goes before generic seeds so menu hits are not crowded out.
    Same path under http/https counts once (https wins), including homepage.
    Returns list of dicts: {url, source} where source is home|seed|nav.
    """
    host = _normalize_host(site)
    ordered = []
    seen = set()  # host+path without scheme
    by_key = {}

    def _canon(url: str) -> str:
        p = urlparse(url)
        path = (p.path or "/").rstrip("/") or "/"
        return f"{p.netloc.lower()}{path}"

    def _add(url: str, source: str):
        if not url:
            return
        key = _canon(url)
        prev = by_key.get(key)
        if prev:
            # upgrade http → https in place
            if prev["url"].startswith("http://") and url.startswith("https://"):
                prev["url"] = url
            return
        item = {"url": url, "source": source}
        by_key[key] = item
        seen.add(key)
        ordered.append(item)

    # https first so home key is https; http is same path → skipped (nav still uses both fetches).
    _add(f"https://{host}/", "home")
    _add(f"http://{host}/", "home")
    for url in nav_urls or []:
        _add(url, "nav")
    for url in seed_html_feed_urls(site):
        path = urlparse(url).path or "/"
        if path in ("", "/"):
            continue
        _add(url, "seed")

    return ordered[:max_total]


def _listing_path_key(url: str) -> str:
    """host+path without scheme — for scan dedupe of http/https twins."""
    p = urlparse(url or "")
    path = (p.path or "/").rstrip("/") or "/"
    return f"{(p.netloc or '').lower()}{path}"


async def get_valid_page(data, newdata):
    page, status, link = data
    collector_elements, report, pattern = find_collector_element(page, newdata['url'], status)
    connect_error = False
    if collector_elements:
        return collector_elements, link, report, pattern, connect_error

async def run(newdata, collect_url, connection_mode):
    site = newdata["url"]
    report = None
    connect_error = True
    candidate_meta = {}

    if collect_url:
        possible_links = [collect_url]
        candidate_meta[collect_url] = "given"
    else:
        # Phase 1: homepage — extract nav listing candidates, limit extra requests.
        home_urls = [f"https://{_normalize_host(site)}/", f"http://{_normalize_host(site)}/"]
        home_data = del_none(await asyncio.gather(*[get_page(link, connection_mode) for link in home_urls]))
        nav_urls = []
        for page, status, link in home_data:
            if status and status < 400 and page is not None:
                nav_urls.extend(extract_nav_feed_candidates(page, link, site))
        # dedupe nav preserve order
        nav_dedup, seen_nav = [], set()
        for u in nav_urls:
            k = u.rstrip("/").lower()
            if k not in seen_nav:
                seen_nav.add(k)
                nav_dedup.append(u)
        nav_urls = nav_dedup[:MAX_NAV_FEED_CANDIDATES]
        candidates = build_html_feed_candidates(site, nav_urls=nav_urls)
        possible_links = [c["url"] for c in candidates]
        candidate_meta = {c["url"]: c["source"] for c in candidates}
        logger.info(
            f'[map_feed] url={site} step=html_candidates '
            f'nav_found={len(nav_urls)} selected={len(possible_links)} '
            f'nav_sample={nav_urls[:5]}'
        )

    # Reuse already fetched home pages when possible.
    fetched = {}
    if not collect_url:
        for item in home_data:
            if item:
                fetched[item[2]] = item

    to_fetch = [u for u in possible_links if u not in fetched]
    new_data = del_none(await asyncio.gather(*[get_page(link, connection_mode) for link in to_fetch]))
    for item in new_data:
        fetched[item[2]] = item

    all_fetched = [fetched[u] for u in possible_links if u in fetched]
    # If https twin missing/bad, keep http (or any) good fetch for the same path.
    covered_ok = set()
    for _page, status, link in all_fetched:
        if status is not None and status < 400:
            covered_ok.add(_listing_path_key(link))
    for _url, item in fetched.items():
        if not item:
            continue
        _page, status, link = item
        if status is None or status >= 400:
            continue
        key = _listing_path_key(link)
        if key in covered_ok:
            continue
        all_fetched.append(item)
        covered_ok.add(key)
    pages_got = [(status, link) for _, status, link in all_fetched]
    # Scan only usable pages — 4xx/5xx already skipped for find (quality-neutral).
    all_data = []
    scanned_paths = set()
    skipped_bad = 0
    for item in all_fetched:
        page, status, link = item
        if status is None or status >= 400 or page is None:
            skipped_bad += 1
            continue
        path_key = _listing_path_key(link)
        if path_key in scanned_paths:
            continue
        scanned_paths.add(path_key)
        all_data.append(item)
    source_counts = {}
    for u in possible_links:
        src = candidate_meta.get(u, "?")
        source_counts[src] = source_counts.get(src, 0) + 1
    sources_s = ",".join(f"{k}:{v}" for k, v in sorted(source_counts.items()))
    logger.info(
        f'[map_feed] url={site} step=html_pages tried={len(possible_links)} '
        f'fetched={len(all_fetched)} scan={len(all_data)} skipped_bad={skipped_bad} '
        f'sources={sources_s} got={pages_got}'
    )
    best_map = {"score": None, "len_els": 0, "map": None, "source": None, "score_meta": None}
    import time as _time
    n_pages = len(all_data)
    logger.info(f'[map_feed] url={site} step=html_map_scan begin pages={n_pages}')
    for idx, data in enumerate(all_data, 1):
        page, status, link = data
        t_page = _time.monotonic()
        logger.info(
            f'[map_feed] url={site} step=html_map_scan page={idx}/{n_pages} '
            f'collect_url={link} status={status} start'
        )
        got = await get_valid_page(data, newdata)
        t_find = _time.monotonic()
        if not got or not got[0]:
            logger.info(
                f'[map_feed] url={site} step=html_map_scan page={idx}/{n_pages} '
                f'collect_url={link} result=no_map '
                f'find_ms={int((t_find - t_page) * 1000)}'
            )
            continue
        collector_elements, link, report, pattern, connect_error = got
        logger.info(
            f'[map_feed] url={site} step=html_map_scan page={idx}/{n_pages} '
            f'collect_url={link} maps={len(collector_elements)} '
            f'anchor={(report or {}).get("anchor")} '
            f'find_ms={int((t_find - t_page) * 1000)}'
        )
        meta = score_listing_candidate(page, collector_elements, report, pattern, site)
        logger.info(
            f'[map_feed] url={site} step=html_map_scan page={idx}/{n_pages} '
            f'collect_url={link} score={meta.get("score")} rejected={meta.get("rejected")} '
            f'reason={meta.get("reason")} '
            f'score_ms={int((_time.monotonic() - t_find) * 1000)} '
            f'page_ms={int((_time.monotonic() - t_page) * 1000)}'
        )
        if meta.get("rejected"):
            logger.info(
                f'[map_feed] url={site} step=html_map_skip collect_url={link} '
                f'reason={meta.get("reason")} uniq={meta.get("uniq")} '
                f'article_like={meta.get("article_like")} menu_like={meta.get("menu_like")}'
            )
            continue
        sc = meta["score"]
        if best_map["score"] is None or sc > best_map["score"]:
            best_map = {
                "score": sc,
                "len_els": len(collector_elements),
                "map": got,
                "source": candidate_meta.get(link, candidate_meta.get(link.rstrip("/"), "?")),
                "score_meta": meta,
            }
            logger.info(
                f'[map_feed] url={site} step=html_map_scan best_so_far '
                f'collect_url={link} score={sc:.1f}'
            )
    logger.info(
        f'[map_feed] url={site} step=html_map_scan done '
        f'best_score={best_map["score"]} best_url='
        f'{(best_map["map"][1] if best_map["map"] else None)}'
    )
    if best_map["map"]:
        collector_elements, link, report, pattern, connect_error = best_map["map"]
        reason = "best_score"
        src = best_map.get("source") or candidate_meta.get(link, "?")
        sm = best_map.get("score_meta") or {}
        logger.info(
            f'[map_feed] url={site} step=html_map collect_url={link} '
            f'reason={reason} source={src} score={best_map["score"]:.1f} '
            f'uniq={sm.get("uniq")} article_like={sm.get("article_like")} '
            f'els={best_map["len_els"]} '
            f'maps={report.get("map_els") if report else None} '
            f'dates={report.get("all_date_elements") if report else None} '
            f'cards={report.get("card_elements") if report else None} '
            f'fit={report.get("fit_elements") if report else None} '
            f'anchor={report.get("anchor") if report else None} pattern={pattern}'
        )
        return best_map["map"]
    # Нет usable HTML (status < 400) — сеть/ответ сайта; страницы были, карты нет — collect_elements.
    connect_error = len(all_data) == 0
    logger.info(
        f'[map_feed] url={site} step=html_map result=none '
        f'connect_error={int(connect_error)} scan={len(all_data)} collector={report}'
    )
    return None, None, report, None, connect_error
