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

def get_first_el(some_list):
    return some_list[0] if len(some_list) >= 1 else None

def soup_clean(text):
    return re.sub('[^a-zA-Z0-9а-яА-Я]', '', clean(text))

def erect_to_percent(num, percent):
    return num / 100 * percent

def clean(item):
    if type(item) is list:
        string = []
        for i in item:
            string.append(re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\"|\\n|\\t)+', '', i))).strip())
        return string
    return re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\n|\\t)+', '', item))).strip()

async def get_page(link, connection_mode):
    timeout = aiohttp.ClientTimeout(total=60)
    connector, headers = get_connection_options(connection_mode, response_type=str)
    retry = 0
    while retry <= 3:
        try:
            async with aiohttp.request("get", link, headers=headers, timeout=timeout, proxy=connector) as response:
                status = response.status
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
    for link in [re.sub("[0-9]+", "[0-9]+", re.sub("(.+/)(.+)", r"\1.+?", re.sub("([\\\|\[\]{}()+*^])", r"\\\1", el.get("href") if el.get("href")[-1] != "/" else el.get("href")[:-1]), flags=re.DOTALL)) + "/*" for el in page.find_all(lambda el: "href" in el.attrs) if el.get("href")]:
        if link not in all_links:
            all_links[link] = 1
        all_links[link] += 1
        if all_links[link] > best_pattern["count"]:
            best_pattern = {"pattern": link, "count": all_links[link]}
    return page.find_all(lambda el: "href" in el.attrs and re.fullmatch(best_pattern["pattern"], el.get("href"), flags=re.DOTALL)), best_pattern["pattern"]

def get_href(item):
    pubdate = None
    title = None
    link = None
    all_text = item.get_text('|').split('|')
    try:
        title = clean(item.find(lambda el: re.fullmatch("h[0-9]+", el.name)).get_text(strip=True))
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
        title = clean(bigest_text["text"])
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
    all_elements = {}
    all_date_elements = page.find_all(required_parameters)
    all_patterns = {}
    if not all_date_elements:
        optimum_elements, pattern = find_optimum_elements(page)
    else:
        optimum_elements = all_date_elements
    unical_els = {}
    for el in optimum_elements:
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
                    # href = parent.find_all(lambda element: "href" in element.attrs and (len(re.findall("/", re.sub("https*://", "", element.get("href")))) == pattern if pattern else True))
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
    # for el in unical_els:
    #     print(el)
    maps = []
    for el in all_elements:
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
                    name, attrs = el_full_name.split('|')
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
    res = {"response_code": status, "all_date_elements": len(all_date_elements), "fit_elements": len(all_elements), "map_els": len(maps)}
    best_patern = {"len_options": None, "count": 0}
    for pat in all_patterns:
        if all_patterns[pat] > best_patern["count"]:
            best_patern["len_options"] = pat
            best_patern["count"] = all_patterns[pat]
    pattern = best_patern["len_options"]
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

async def get_valid_page(data, newdata):
    page, status, link = data
    collector_elements, report, pattern = find_collector_element(page, newdata['url'], status)
    connect_error = False
    if collector_elements:
        return collector_elements, link, report, pattern, connect_error

async def run(newdata, collect_url, connection_mode):
    possible_links = [f"https://{newdata['url']}/news", f"http://{newdata['url']}/news", f"https://{newdata['url']}", f"http://{newdata['url']}", f"https://{newdata['url']}/articles", f"http://{newdata['url']}/articles"] if not collect_url else [collect_url]
    report = None
    connect_error = True
    all_data = del_none(await asyncio.gather(*[get_page(link, connection_mode) for link in possible_links]))
    best_map = {"len_els": 0, "map": None}
    for map in del_none(await asyncio.gather(*[get_valid_page(data, newdata) for data in all_data])):
        collector_elements, link, report, pattern, connect_error = map
        if best_map["len_els"] < len(collector_elements):
            best_map = {"len_els": len(collector_elements), "map": map}
    if best_map["map"]:
        return best_map["map"]
    return None, None, report, None, connect_error
