import os
import sys
import random
import uuid
from configparser import ConfigParser
import time as tm
import asyncio
import aiohttp
import re
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import datetime
import dateparser
from multiprocessing import shared_memory
import time
from loguru import logger
sys.path.append(os.path.dirname(os.path.realpath(os.path.abspath(''))))
from component.arangoconnector.connector import ArangoConnector
from component.news_collector import determinant_news_element, determinant_collect_element


weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Th', 'Thu', 'Thur', 'Fri', 'Sat']


def clean(item):
    if type(item) is list:
        string = []
        for i in item:
            string.append(re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub(
                '(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\"|\\n|\\t)+', '', i))).strip())
        return string
    return re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"',
                                                   re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\n|\\t)+',
                                                          '', item))).strip()


def del_none(some_list):
    return [item for item in some_list if item]


def check_time(time: int) -> int or None:
    now = int(datetime.datetime.now().timestamp())
    if not time or time > now:
        return now
    return time


def get_first_el(some_list):
    return some_list[0] if len(some_list) >= 1 else None


def get_count_all_text_items(items):
    more_items = {}
    for item in items:
        if not item['html_data']:
            continue
        for i in item['html_data']['items']:
            text_items = re.findall(
                '>([^<>]*?[а-яА-Я][^<>]+[a-zA-Zа-яА-Я]*?)<',
                i)
            if len(text_items) > 1:
                string_item = ''
                for i in text_items:
                    string_item += i
                text_items = [string_item]
            try:
                text_items = clean(
                    re.split('lol', re.sub('([^А-Я ]{3,}\.)([А-Я—0-9«][^\.].{50,})', r'\1lol\2', text_items[0])))
            except IndexError:
                continue
            if type(text_items) is str:
                text_items = [text_items]
            for text_item in text_items:
                try:
                    more_items[text_item] += 1
                except KeyError:
                    more_items[text_item] = 1
    return more_items


def get_count_all_pictures(items):
    more_pictures = {}
    for item in items:
        if not item['html_data']:
            continue
        for picture in item['html_data']['pictures']:
            try:
                more_pictures[picture] += 1
            except KeyError:
                more_pictures[picture] = 1
    return more_pictures


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


def up_buf(shm_name):
    while True:
        shm_b = shared_memory.SharedMemory(shm_name)
        if not shm_b.buf[0]:
            shm_b.buf[0] += 1
            return
        time.sleep(random.random())


async def get_data_rss_pid4(session, rss_link, headers=None, requestsF=False):
    ua = UserAgent()
    if not headers:
        headers = {'User-Agent': ua.chrome}
    timeout = aiohttp.ClientTimeout(total=600)
    rss_link = re.findall("http[^']+", rss_link)[0]
    try:
        async with session.get(rss_link, headers=headers, timeout=timeout, ssl=False) as response:
            try:
                response = await response.text()
                soup = BeautifulSoup(response, 'lxml')
            except UnicodeDecodeError:
                soup = BeautifulSoup(await response.read(), 'lxml')
            items = soup.find_all('item')
            if not items:
                items = soup.find_all('entry')
        return items
    except asyncio.exceptions.TimeoutError:
        return None


async def get_items_pid55(session, link, collect_elements):
    ua = UserAgent()
    headers = {'User-Agent': ua.chrome}
    timeout = aiohttp.ClientTimeout(total=600)
    try:
        async with session.get(link, headers=headers, timeout=timeout, ssl=False) as response:
            try:
                response = await response.text()
                soup = BeautifulSoup(response, 'lxml', multi_valued_attributes=None)
            except UnicodeDecodeError:
                soup = BeautifulSoup(await response.read(), 'lxml', multi_valued_attributes=None)
    except Exception as ex:
        # print(ex)
        return None
    items = []
    for el in collect_elements:
        # print(el)
        items.extend(get_items_recursive(el, [soup]))
    return items


async def get_collect_map(channel, session):
    collect_url = None
    if "collect_url" in channel:
        collect_url = channel['collect_url']
    collect_elements, collect_url, report, pattern, connect_error = await determinant_collect_element.run(channel,
                                                                                                          session,
                                                                                                          collect_url)
    if not connect_error:
        channel["collector_id"] = 55
        channel['collect_elements'] = collect_elements
        channel['collect_url'] = collect_url
        channel["link_pattern"] = pattern
    else:
        pass
    return channel, report, connect_error


async def create_docs_pid55(item, channel):
    link = None
    title = None
    pubdate = None
    protocol = re.findall("(https*):", channel["collect_url"])[0]
    all_text = item.get_text('|').split('|')
    try:
        title = clean(item.find(lambda el: re.fullmatch("h[0-9]+", el.name)).get_text(strip=True))
    except:
        for text_item in all_text:
            if re.findall("[А-Яа-яЁёa-zA-Z]", text_item):
                title = text_item
    for text_item in all_text:
        if text_item != title:
            try:
                pubdate = int(dateparser.parse(
                    text_item).timestamp())  # int(dateparser.search.search_dates(text_item)[0][1].timestamp())
                break
            except:
                pass
    links = [el.get('href') for el in item.find_all(lambda element: True if "href" in element.attrs else False)]
    if item.get("href"): links.insert(0, item.get("href"))
    if links:
        link = links[0]
        if not link.startswith('http'):
            link = f'{protocol}://{channel["url"]}/{link if not re.fullmatch(f"""(?:/|{channel["url"]})+.+""", link, flags=re.DOTALL) else str(get_first_el(re.findall(f"""(?:/|{channel["url"]})+(.+)""", link, flags=re.DOTALL)))}'
        link = re.sub("/{3,}", "//", link)
        item_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, re.sub("https*://", "", link)))
    # print(f'link {link}\ntitle {title}\npubdate ')
    if link and title and pubdate:
        collect_date = int(tm.mktime(datetime.datetime.now().timetuple()))
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
            "published_date": check_time(pubdate),
            "description": None,
            "imgF": False,
            "videoF": False,
            "main": channel['main'] if "main" in channel else False,
            "parser_id": channel['parser_id'],
            "news_element" if channel['parser_id'] not in [53, 54] else "news_elements": channel[
                'news_element'] if 'news_element' in channel else channel[
                'news_elements'] if 'news_elements' in channel else None,
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


async def create_docs_pid50(item, channel):
    try:
        title = clean(item.find('title').get_text())
    except:
        return None
    description = None
    if channel['url'].find('media.ru') != -1 or channel['url'].find('media.su') != -1:
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
        link = del_none([get_first_el(re.findall(r'http[^\r\n\t\]\["]+', text_item)) for text_item in
                         item.get_text("|").split('|')])
        if not link:
            link = del_none([get_first_el(re.findall(r'.*(/[^\r\n\t\]\["]+)', text_item)) for text_item in
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
        description = clean(item.find('description').get_text())
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
        "feed_id": channel['feed_id'],
        "user_id": channel['user_id'],
        "collect_date": collect_date,
        "published_date": check_time(pubdate),
        "description": description,
        "imgF": imgF,
        "videoF": False,
        "main": channel['main'],
        "parser_id": channel['parser_id'],
        "news_element" if channel['parser_id'] not in [53] else "news_elements": channel[
            'news_element'] if 'news_element' in channel else channel[
            'news_elements'] if 'news_elements' in channel else None,
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


class NewsCollector:
    def __init__(self, config_ini='src/config/config.ini', service_type='NewsCollector'):
        self.service_type = service_type
        self.config = ConfigParser()
        self.config.read(config_ini)
        self.rss_config_df = None
        self.config_df = None
        self.auto_config_df = None
        self.logger = logger
        self.arango = ArangoConnector()
        self.semaphore = asyncio.Semaphore(int(self.config[self.service_type]['semaphore']))
        self.channels = None

    async def find_rss(self, url, session, channel):
        ua = UserAgent()
        headers = {'User-Agent': ua.chrome}
        timeout = aiohttp.ClientTimeout(total=600)
        async with session.get(url, headers=headers, timeout=timeout, ssl=False) as response:
            try:
                response = await response.text()
                soup = BeautifulSoup(response, 'lxml')
            except UnicodeDecodeError:
                soup = BeautifulSoup(await response.read(), 'lxml')
            if "rss" not in url and "feed" not in url:
                links = [
                    f'{url}/{link if not re.fullmatch(f"""(?:/|{channel["url"]})+.+""", link, flags=re.DOTALL) else str(get_first_el(re.findall(f"""(?:/|{channel["url"]})+(.+)""", link, flags=re.DOTALL)))}' if not link.startswith(
                        'http') else link for link in [element.get("href") for element in soup.find_all(
                        lambda el: "rss" in str(el.get("href")) or "feed" in str(el.get("href")))]]
                rss_links = await asyncio.gather(*[self.find_rss(link, session, channel) for link in links])
                if not rss_links:
                    return {"url": url, "len": 0}
                best_link = {"best_url": None, "max_len": 0}
                for href in rss_links:
                    if href["len"] > best_link["max_len"]:
                        best_link["best_url"] = href["url"]
                        best_link["max_len"] = href["len"]
                return {"url": best_link["best_url"], "len": best_link["max_len"]}
            items = soup.find_all('item')
            if not items:
                items = soup.find_all('entry')
            items = del_none([await create_docs_pid50(item, channel) for item in items])
            return {"url": url, "len": len(items)}

    async def get_news_channels(self):
        self.channels = self.arango.get_news_channels()

    async def find_rss_process(self, session, channel):
        links = [f"http://{channel['url']}", f"http://{channel['url']}/feed", f"http://{channel['url']}/rss",
                 f"http://{channel['url']}/rss.xml",
                 f"https://{channel['url']}", f"https://{channel['url']}/feed", f"https://{channel['url']}/rss",
                 f"https://{channel['url']}/rss.xml"]
        rss_links = del_none(await asyncio.gather(*[self.find_rss(link, session, channel) for link in links]))
        if not rss_links:
            return None
        best_link = {"best_url": None, "max_len": 0}
        for href in rss_links:
            if href["len"] > best_link["max_len"]:
                best_link["best_url"] = href["url"]
                best_link["max_len"] = href["len"]
        return best_link["best_url"] if best_link["max_len"] > 4 else None

    async def collect_process(self, report, find_colect_element, channel, session, link):
        if find_colect_element:
            rss = await self.find_rss_process(session, channel)
            if rss:
                # print("best", rss)
                report["rss"] = True
                channel["rss_link"] = [rss]
                link = rss
            else:
                report["rss"] = False
                channel, report["collector"], connect_error = await get_collect_map(channel, session)
                if connect_error:
                    self.logger.warning(f'FAILED find collect_elements on {channel["url"]}')
                    report["failed_log"] = "FAILED find collect_elements"
                    report["status"] = 2
                    return channel, report, None
        if 'collector_id' in channel and channel['collector_id'] in [55]:
            items = await get_items_pid55(session, channel['collect_url'], channel['collect_elements'])
        else:
            items = await get_data_rss_pid4(session, link, headers=channel["headers"] if "headers" in channel else None)
        if not items:
            self.logger.warning(f'FAILED collect items on {channel["url"]}')
            report["failed_log"] = "FAILED collect items"
            report["status"] = 3
            return channel, report, None
        new_data = []
        all_links = []
        for item in items:
            if 'collector_id' in channel and channel['collector_id'] in [55]:
                data = await create_docs_pid55(item, channel)
            else:
                data = await create_docs_pid50(item, channel)
            if data:
                if data["link"] not in all_links and (
                        len(re.findall("/", re.sub("https*://", "", data["link"]))) == channel[
                            "link_pattern"] if "link_pattern" in channel and channel["link_pattern"] else True):
                    # print(channel["rss_link"], channel["link_pattern"] if "link_pattern" in channel and channel["link_pattern"] else None)
                    all_links.append(data["link"])
                    new_data.append(data)
        if len(new_data) < 5:
            self.logger.warning(f'FAILED collected news on {channel["url"]} {len(new_data)}')
            report["failed_log"] = f"FAILED collect news ({len(new_data)})"
            report["status"] = 3
            return channel, report, None
        return channel, report, new_data

    async def parser_process(self, session, new_data, report, channel):
        data = await asyncio.gather(
            *[determinant_news_element.fetch_all_elements(newdata, session) for newdata in new_data])
        # print(len(data))
        if (len(del_none(data)) * 2) < len(data) or len(del_none(data)) < 5:
            self.logger.warning(
                f"FAILED connect to news (all news = {len(data)}, successfully connection = {len(del_none(data))})")
            report[
                "failed_log"] = f"FAILED connect to news (all news = {len(data)}, successfully connection = {len(del_none(data))})"
            report["status"] = 4
            return channel, report
        data = [channel] + del_none(data)
        count_all_items = determinant_news_element.get_count_all_items(data)
        final_data_channel, report["parser"], res = await determinant_news_element.find_main_news_element(data,
                                                                                                          count_all_items,
                                                                                                          session)
        if not final_data_channel:
            self.logger.warning(f"FAILED find news_elements on {channel['url']}")
            report["failed_log"] = f"FAILED find news_elements"
            report["status"] = 5
            return channel, report
        if not res:
            self.logger.warning(f"FAILED find trash_text on {channel['url']}")
            report["failed_log"] = f"FAILED find trash_text"
            report["status"] = 6
            return channel, report
        self.logger.info(f"SUCCESSFULLY create map on {channel['url']}")
        report["status"] = 1
        return channel, report

    async def collect_news_pid50(self, channel, link, session, shm_alive_bar_name, find_colect_element=False):
        # ++++++ status code ++++++
        # 1 - SUCCESSFULLY
        # 2 - FAILED (не получилось найти целевые элементы для коллектора *в основном это связанно с ошибками коннекта)
        # 3 - FAILED (не получилось сколлектить целевые элементы)
        # 4 - FAILED (ошибки коннекта к сайту)
        # 5 - FAILED (не получилось найти целевой элемент для парсера)
        # 6 - FAILED (не получилось спарсить новости по целевым элементам)
        report = {"rss": True if "rss_link" in channel and channel["rss_link"] else False, "collector": None,
                  "parser": None, "failed_log": None, "status": None}
        self.logger.info(f'Start map assembly from {channel["url"]}')
        channel['parser_id'] = 55
        channel, report, new_data = await self.collect_process(report, find_colect_element, channel, session, link)
        if not new_data:
            if shm_alive_bar_name:
                up_buf(shm_alive_bar_name)
            return channel, report
        # print(len(new_data))
        if len(new_data) > 51:
            new_data = new_data[:50]
        # for doc in new_data:
        #     print(doc["link"])
        channel, report = await self.parser_process(session, new_data, report, channel)
        if shm_alive_bar_name:
            up_buf(shm_alive_bar_name)
        return channel, report
