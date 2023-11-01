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


    async def find_rss(self, url, connection_mode, channel):
        timeout = aiohttp.ClientTimeout(total=60)
        proxy, headers = get_connection_options(connection_mode, response_type=str)
        try:
            async with aiohttp.request("get", url, headers=headers, timeout=timeout, proxy=proxy) as response:
                try:
                    response = await response.text()
                    soup = BeautifulSoup(response, 'lxml')
                except UnicodeDecodeError:
                    soup = BeautifulSoup(await response.read(), 'lxml')
                if "rss" not in url and "feed" not in url:
                    links = [f'{url}/{link if not re.fullmatch(f"""(?:/|{channel["url"]})+.+""", link, flags=re.DOTALL) else str(utils.get_first_el(re.findall(f"""(?:/|{channel["url"]})+(.+)""", link, flags=re.DOTALL)))}' if not link.startswith('http') else link for link in [element.get("href") for element in soup.find_all(lambda el: "rss" in str(el.get("href")) or "feed" in str(el.get("href")))]]
                    rss_links = await asyncio.gather(*[self.find_rss(link, connection_mode, channel) for link in links])
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
                items = utils.del_none([await self.create_docs_pid50(item, channel) for item in items])
                return {"url": url, "len": len(items)}
        except Exception as ex:
            self.logger.warning(utils.get_exception())
            return None


    async def get_data_rss_pid4(self, connection_mode, rss_link, headers=None, return_rss_link=False):
        ua = UserAgent()
        if not headers:
            headers = {'User-Agent': ua.chrome}
        proxy, _ = get_connection_options(connection_mode, response_type=str)
        timeout = aiohttp.ClientTimeout(total=60)
        rss_link = re.findall("http[^']+", rss_link)[0]
        items = None
        try:
            async with aiohttp.request("get", rss_link, headers=headers, timeout=timeout, proxy=proxy) as response:
                try:
                    response = await response.text()
                    soup = BeautifulSoup(response, 'lxml')
                except UnicodeDecodeError:
                    soup = BeautifulSoup(await response.read(), 'lxml')
                items = soup.find_all('item')
                if not items:
                    items = soup.find_all('entry')
                if not items:
                    if rss_link.startswith("https"):
                        new_rss_link = re.sub("https://", "http://", rss_link)
                    elif rss_link.startswith("http://"):
                        new_rss_link = re.sub("http://", "https://", rss_link)
                    items = await self.get_data_rss_pid4(connection_mode, new_rss_link)
                    if items:
                        rss_link = new_rss_link
        except Exception:
            utils.get_exception()
        finally:
            if return_rss_link: return items, rss_link
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
        links = [f"http://{channel['url']}", f"http://{channel['url']}/feed", f"http://{channel['url']}/rss", f"http://{channel['url']}/rss.xml",
                 f"https://{channel['url']}", f"https://{channel['url']}/feed", f"https://{channel['url']}/rss", f"https://{channel['url']}/rss.xml"]
        rss_links = utils.del_none(await asyncio.gather(*[self.find_rss(link, connection_mode, channel) for link in links]))
        if not rss_links:
            return None
        best_link = {"best_url": None, "max_len": 0}
        for href in rss_links:
            if href["len"] > best_link["max_len"]:
                best_link["best_url"] = href["url"]
                best_link["max_len"] = href["len"]
        return best_link["best_url"] if best_link["max_len"] > 4 else None


    async def start_collector_map_assembly_process(self, report, channel, link, unittest=False):
        if not link:
            rss = await self.find_rss_process(channel["connection_mode"], channel)
            if rss:
                report["rss"] = True
                channel["rss_link"] = [rss]
                link = rss
            else:
                report["rss"] = False
                channel, report["collector"], connect_error = await self.get_collect_map(channel, channel["connection_mode"])
                if connect_error:
                    if unittest:
                        return False
                    self.logger.warning(f'FAILED find collect_elements on {channel["url"]}')
                    report["failed_log"] = "FAILED find collect_elements"
                    report["status"] = 2
                    return channel, report, None
        if 'collector_id' in channel and channel['collector_id'] in [55]:
            if "collect_url" in channel and channel['collect_url']:
                items = await self.get_items_pid55(channel["connection_mode"], channel['collect_url'], channel['collect_elements'])
            else:
                if unittest:
                    return False
                self.logger.warning(f'FAILED find collect_url {channel["url"]}')
                report["failed_log"] = "FAILED find collect_url"
                report["status"] = 3
                return channel, report, None
        else:
            items, rss_link = await self.get_data_rss_pid4(channel["connection_mode"], link, headers=channel["headers"] if "headers" in channel else None, return_rss_link=True)
            channel["rss_link"] = [rss_link]
        if not items:
            if unittest:
                return False
            self.logger.warning(f'FAILED collect items on {channel["url"]}')
            report["failed_log"] = "FAILED collect items"
            report["status"] = 3
            return channel, report, None
        new_data = []
        all_links = []
        for item in items:
            if 'collector_id' in channel and channel['collector_id'] in [55]:
                data = await self.create_docs_pid55(item, channel)
            else:
                data = await self.create_docs_pid50(item, channel)
            if data:
                if data["link"] not in all_links and (len(re.findall("/", re.sub("(?:https*://|//)", "", data["link"]))) == channel["link_pattern"] if "link_pattern" in channel and channel["link_pattern"] else True):
                    all_links.append(data["link"])
                    new_data.append(data)
        if len(new_data) < 5:
            if unittest:
                return False
            self.logger.warning(f'FAILED collected news on {channel["url"]} {len(new_data)}')
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
            "feed_id": channel['feed_id'],
            "user_id": channel['user_id'],
            "collect_date": collect_date,
            "published_date": check_time(pubdate),
            "description": description,
            "imgF": imgF,
            "videoF": False,
            "main": channel['main'],
            "parser_id": channel['parser_id'],
            "news_element" if channel['parser_id'] not in [53] else "news_elements": channel['news_element'] if 'news_element' in channel else channel['news_elements'] if 'news_elements' in channel else None,
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
