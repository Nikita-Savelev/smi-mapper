from bs4 import BeautifulSoup
import aiohttp
import asyncio
import re
from fake_useragent import UserAgent
import json
import pandas as pd
import pickle
import subprocess
from asyncio import exceptions
import uuid
import aiofiles
from PIL import Image
import os
from common.utils import get_connection_options


def del_none(some_list):
    return [item for item in some_list if item]


with open("src/model/pickle_model.pkl", 'rb') as file:
    pickle_model = pickle.load(file)


def get_first_el(some_list):
    return some_list[0] if len(some_list) >= 1 else None


def soup_clean(text):
    return re.sub('[^a-zA-Z0-9а-яА-Я]', '', clean(text))


def erect_to_percent(num, percent):
    return num / 100 * percent


def find_max_count_text_items(all_parents, items):
    biggest_count = 0
    biggest_el = None
    for item in items:
        soup = item["html_data"]
        for parent in all_parents:
            name = re.findall("(.+?)\|.+", parent)[0]
            attrs = re.findall(".+?\|(\{.+)", parent)[0]
            attrs = json.loads(attrs)
            if "global_count" not in all_parents[parent]:
                all_parents[parent]["global_count"] = len(soup.find_all(name, attrs=attrs))
            all_parents[parent]["global_count"] += len(soup.find_all(name, attrs=attrs))
    for short_parent_name in all_parents:
        if (all_parents[short_parent_name]["global_count"] / all_parents[short_parent_name]["found_in"]) > 1:
            continue
        count = all_parents[short_parent_name]['count_text_items']
        if count > biggest_count:
            biggest_count = count
            biggest_el = short_parent_name
    return biggest_el


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


def find_target_elements(items, count_all_items):
    all_parents = {}
    first = True
    count_valid_news = len(items) - 1
    for item in items:
        if first:
            first = False
            continue
        soup = item['html_data']
        all_short_parent_name = []
        for text_item in item['text_items']:
            if len(text_item) > 2000:
                continue
            if count_all_items[text_item]['count_text_items'] > 1 or count_all_items[text_item][
                'count_text_paterns'] > 1:
                continue
            navigable_item = soup.find(lambda tag: soup_clean(tag.text) == soup_clean(text_item) if str(tag.text).find(
                '<br/>') == -1 else text_item in divide_into_items_by_br_tags_div(tag.text))
            level = 0
            for navigable_item in navigable_item.find_parents():
                if navigable_item.name in ["html", "body", "[document]"]:
                    continue
                level += 1
                short_parent_name = f"{navigable_item.name}|{json.dumps(navigable_item.attrs)}"
                if short_parent_name not in all_parents:
                    all_parents[short_parent_name] = {'count_text_items': 0, 'found_in': 0}
                all_parents[short_parent_name]['count_text_items'] += 1
                if short_parent_name not in all_short_parent_name:
                    all_parents[short_parent_name]['found_in'] += 1
                    all_short_parent_name.append(short_parent_name)
    max_count_text_item = find_max_count_text_items(all_parents, items[1:])
    return count_valid_news, all_parents, max_count_text_item


def collect_structure_patern(structures):
    vector_name = {"lol": "01", "p": '02', 'li': '03', 'h': '04', "ul": '05', "blockquote": '06', "span": '07',
                   "i": '08', "br": '09', "a": "10", "b": "11"}
    if not structures:
        structures = ["lol"]
    structure_patern = ''
    for name in structures:
        structure_patern += vector_name[name]
    # Строковый отпечаток: раньше был int(), на Python 3.12 падает при >4300 цифр.
    # Значение используется только как ключ уникальности (set), не как числовой признак ML.
    return structure_patern


def average_values(attrs, name="pillar", count_valid_news=None):
    if name != "pillar":
        if erect_to_percent(count_valid_news, 20) >= attrs["found_in"] or (
                attrs["global_count"] / attrs["found_in"]) > 1.5:
            return None
    average_attrs = {}
    average_attrs["count_text_items"] = [attrs["count_text_items"] / attrs["global_count"]]
    average_attrs["count_hyperlink"] = [attrs["count_hyperlink"] / attrs["global_count"]]
    average_attrs["count_media"] = [attrs["count_media"] / attrs["global_count"]]
    if name == "pillar":
        average_attrs["percent_unique_structure_patern"] = attrs["percent_unique_structure_patern"] / attrs[
            "global_count"]
        average_attrs["percent_unique_text_patern"] = attrs["percent_unique_text_patern"] / attrs["global_count"]
    else:
        average_attrs["percent_unique_structure_patern"] = [
            len(set(attrs["structure_patern"])) / (len(attrs["structure_patern"]) / 100)]
        average_attrs["percent_unique_text_patern"] = [
            len(set(attrs["text_patern"])) / (len(attrs["text_patern"]) / 100)]
    average_attrs["nesting_level"] = [attrs["nesting_level"] / attrs["global_count"]]
    average_attrs["name"] = name
    if name == "pillar":
        average_attrs["global_count"] = [attrs["global_count"]]
    else:
        average_attrs["global_count"] = [attrs["found_in"] / attrs["global_count"]]
    return average_attrs


def get_xpath_pattern(element: BeautifulSoup):
    xpath_name = ""
    for parent in element.find_parents():
        parent_full_name = f"""①{parent.name}"""
        for attr_name in parent.attrs:
            parent_full_name += f"""②{attr_name}"""
        xpath_name += parent_full_name
    return xpath_name


def get_interiors_els(max_count_text_item, all_news, count_valid_news):
    name, attrs = (None, None)
    # if max_count_text_item:
    #     name, attrs = max_count_text_item.split('|')
    #     attrs = json.loads(attrs)
    all_elements = {}
    for news in all_news:
        els_news = []
        if name and attrs:
            soup = BeautifulSoup(str(news.find(name, attrs=attrs)), 'lxml', multi_valued_attributes=None)
        else:
            soup = news
        for el in soup.find_all(lambda tag: len(
                tag.find_all(lambda el: re.fullmatch('(?:p|li|h[0-9]|ul|img|blockquote|a|span|br)', el.name))) > 2):
            if el.name in ["html", "body"]:
                continue
            short_parent_name = f"{el.name}╬{json.dumps(el.attrs)}╬{get_xpath_pattern(el)}"
            if short_parent_name not in all_elements:
                all_elements[short_parent_name] = {"count_text_items": 0, "count_hyperlink": 0, "count_media": 0,
                                                   "structure_patern": [], "text_patern": [], "global_count": 0,
                                                   "nesting_level": 0, "found_in": 0}
            if short_parent_name not in els_news:
                els_news.append(short_parent_name)
                all_elements[short_parent_name]["found_in"] += 1
            all_elements[short_parent_name]["count_text_items"] += len(
                el.find_all(lambda tag: re.fullmatch('(?:p|li|h[0-9]|ul|blockquote|br)', tag.name)))
            all_elements[short_parent_name]["count_hyperlink"] += len(el.find_all("a"))
            all_elements[short_parent_name]["count_media"] += len(el.find_all("img"))
            all_elements[short_parent_name]["structure_patern"].append(collect_structure_patern(
                [re.sub("[0-9]", "", i.name) for i in
                 el.find_all(lambda tag: re.fullmatch('(?:p|li|h[0-9]|ul|blockquote|span|i|br)', tag.name))]))
            all_elements[short_parent_name]["text_patern"].append(vectoriser(el.text))
            all_elements[short_parent_name]["global_count"] += 1
            all_elements[short_parent_name]["nesting_level"] += len(el.find_parents())
    all_elements_average = {}
    all_indexes = []
    pillar = {"count_text_items": 0, "count_hyperlink": 0, "count_media": 0, "percent_unique_structure_patern": 0,
              "percent_unique_text_patern": 0, "global_count": 0, "nesting_level": 0}
    count_all_els = len(all_elements)
    for el in all_elements:
        average = average_values(all_elements[el], el, count_valid_news)
        if average:
            if average["nesting_level"][0] not in all_elements_average:
                all_elements_average[average["nesting_level"][0]] = []
            all_elements_average[average["nesting_level"][0]].append(average)
            all_indexes.append(average["nesting_level"][0])
            pillar["count_text_items"] += average["count_text_items"][0]
            pillar["count_hyperlink"] += average["count_hyperlink"][0]
            pillar["count_media"] += average["count_media"][0]
            pillar["percent_unique_structure_patern"] += average["percent_unique_structure_patern"][0]
            pillar["percent_unique_text_patern"] += average["percent_unique_text_patern"][0]
            pillar["global_count"] += 1
            pillar["nesting_level"] += average["nesting_level"][0]
    if not pillar["global_count"]:
        return all_elements_average, all_indexes, pillar, False, count_all_els
    pillar = average_values(pillar)
    all_indexes = list(set(all_indexes))
    all_indexes.sort()
    return all_elements_average, all_indexes, pillar, True, count_all_els


def calculate_probability(all_interiors_els, all_indexes, pillar):
    trash = []
    clear = []
    for index in all_indexes:
        for el in all_interiors_els[index]:
            name = el["name"]
            for key in pillar:
                el["pillar_" + key] = pillar[key]
            del el["name"], el["pillar_name"]
            df = pd.DataFrame(el)
            el["name"] = name
            if pickle_model.predict(df):
                clear.append(el)
            else:
                trash.append(el)
    return clear, trash


def create_doc(clear, trash, item):
    item['news_elements'] = []
    max_nesting_level = {"nesting_level": 0, "el": None}
    for el in clear:
        attrs = re.findall(".+?╬(\{.+)╬", el["name"])[0]
        attrs = json.loads(attrs)
        if not attrs:
            continue
        if el["nesting_level"][0] > max_nesting_level["nesting_level"]:
            max_nesting_level["nesting_level"] = el["nesting_level"][0]
            max_nesting_level["el"] = el
    if not max_nesting_level["el"]:
        return None
    name, attrs, xpath = max_nesting_level["el"]["name"].split('╬')
    attrs = json.loads(attrs)
    item['news_elements'].append({
        "attrs": attrs,
        "name": name,
        "custom_xpath": xpath,
        'only_content': False,
        "is_description_element": False,
        "is_header_img_element": False,
        "parent": None
        # "metrixs": max_nesting_level["el"]
    })
    trash_sort = []
    for el in trash:
        name, attrs, xpath = el['name'].split('╬')
        attrs = json.loads(attrs)
        if attrs:
            trash_sort.append({"name": name, "attrs": attrs})  # , "metrixs": el})
    item['trash_items'] = {
        'trash_elements': trash_sort,
        'trash_links': [],
        'trash_text_items': [],
        'trash_indexes': {}
    }
    item['parser_id'] = 55
    item['map_assembly_status'] = 1
    item['dont_get_header_img'] = False
    item['split_br_tags'] = True
    item['breaker_items'] = {'breaker_el_list': [], 'breaker_re_strings': []}
    item['div_white_list'] = []
    item['debug'] = True
    item['get_all_iframe'] = False
    return item


def get_count_raw_items(all_news):
    all_text_items = {}

    for news in all_news:
        for item in news['raw_items']:
            item = item['image'] if 'image' in item else \
                item['text'] if 'text' in item else \
                    item['url'] if 'url' in item else \
                        item['original_url']
            if item not in all_text_items:
                all_text_items[item] = 0
            all_text_items[item] += 1
    return all_text_items


def find_trash(trash_text, trash):
    count_news, count_all_items = trash_text
    for item in count_all_items:
        if erect_to_percent(count_news, 50) < count_all_items[item]:
            if re.fullmatch('http.+', item, flags=re.DOTALL) or \
                    re.fullmatch('(?:[^ "<>,]+?/[^ "<>,]+?)(?:\.jpg|\.jpeg|\.jepeg|\.webp|\.png)(?:[^ "<>,]+?)*', item):
                trash['trash_links'].append(item)
            else:
                trash['trash_text_items'].append(item)
    return trash


def is_author_el(el):
    return el.get_text(strip=True) and del_none([attr for attr in el.attrs if "author" in el.attrs[attr]])


def find_author_el(items):
    author_element = None
    all_author_short_name = {}
    for item in items:
        all_author_els = item["html_data"].find_all(is_author_el)
        for author_el in all_author_els:
            # if author_el.find_all(is_author_el):
            #     continue
            short_author_el_name = f"{author_el.name}╬{json.dumps(author_el.attrs)}╬{get_xpath_pattern(author_el)}"
            if short_author_el_name not in all_author_short_name:
                all_author_short_name[short_author_el_name] = 0
            all_author_short_name[short_author_el_name] += 1
    best_author_el = {"short_name": None, "count": 0}
    for author_el_name, author_el_count in all_author_short_name.items():
        if len(items) >= author_el_count > best_author_el["count"]:
            best_author_el["short_name"] = author_el_name
            best_author_el["count"] = author_el_count
    if best_author_el["short_name"]:
        name, attrs, xpath = re.split("╬", best_author_el["short_name"])
        attrs = json.loads(attrs)
        author_element = {"attrs": attrs,
                     "name": name,
                     "custom_xpath": xpath,
                     'only_content': False,
                     "is_description_element": False,
                     "is_header_img_element": False,
                     "is_author_element": True,
                     "parent": None
                     }
    return author_element


async def get_img_resp(connection_mode, url):
    proxy, headers = get_connection_options(connection_mode, response_type=str)
    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.request(method="GET", url=url, headers=headers, timeout=timeout, proxy=proxy) as resp:
            return (await resp.read(), resp, url)
    except:
        return None


def refactor_img(img, link):
    if not img.startswith('http'):
        if img.startswith('//'):
            img = f'{re.findall("(https*:)//", link)[0]}{img}'
        else:
            if img.find(re.findall("https*://(.+?)/", link)[0]) == -1:
                img = f'{re.findall("(https*://.+?)/", link)[0]}{img if img[0] == "/" else "/" + img}'
            else:
                img = f'{re.findall("https*://", link)[0]}{img if img[0] == "/" else "/" + img}'
        img = re.sub('(?:////|///)', '//', img)
    return img


async def get_size_img(urls, connection_mode, news_link):
    all_img = await asyncio.gather(*[get_img_resp(connection_mode, refactor_img(url, news_link)) for url in urls])
    count_img = 0
    averaged_size = 0
    for data in all_img:
        if not data:
            continue
        data_img, data_img_obj, url = data
        if data_img_obj.status == 200:
            image_name = str(uuid.uuid5(uuid.NAMESPACE_DNS, re.sub("https*://", "", url)))
            extension = re.findall("\.([^\./]+)", url)
            path = f'src/component/news_parser/images/{image_name}.{extension[-1] if extension else "jpg"}'
            retry = 0
            compleat = False
            while retry <= 3:
                try:
                    async with aiofiles.open(path, 'wb') as f:
                        await f.write(data_img)
                        compleat = True
                        break
                except:
                    retry += 1
            if not compleat:
                return False
            im = Image.open(path)
            width, height = im.size
            os.remove(path)
            averaged_size += width * height
            count_img += 1
    if count_img and averaged_size:
        return averaged_size / count_img
    return False

async def find_header_img_el(items, connection_mode):
    header_img_element = None
    all_header_img_els = {}
    first = True
    for item in items:
        if "divided_body" not in item:
            item["divided_body"] = {"previous_zone": item["html_data"]}
            continue
        if first:
            first = False
        for header_img_el in item["divided_body"]["previous_zone"].find_all(lambda el: len(el.find_all("img")) == 1):
            if not header_img_el.attrs:
                continue
            short_header_img_el_name = f"{header_img_el.name}╬{json.dumps(header_img_el.attrs)}╬{get_xpath_pattern(header_img_el)}"
            if short_header_img_el_name not in all_header_img_els:
                all_header_img_els[short_header_img_el_name] = {"count": 0, "src": [], "item_link": item["newdata"]["link"]}
            all_header_img_els[short_header_img_el_name]["count"] += 1
            all_header_img_els[short_header_img_el_name]["src"].append(header_img_el.find("img").get("src"))
    # for el in all_header_img_els:
    #     print(el, all_header_img_els[el])
    best_header_img_el = {"short_name": None, "count": 0}
    for header_img_el_name, header_img_value in all_header_img_els.items():
        if len(items) >= header_img_value["count"] > best_header_img_el["count"]:
            if erect_to_percent(len(items), 30) <= header_img_value["count"]:
                if len(header_img_value["src"]) == len(set(header_img_value["src"])):
                    average_size = await get_size_img(header_img_value["src"], connection_mode, header_img_value["item_link"])
                    if average_size and average_size >= 50000:
                        best_header_img_el["short_name"] = header_img_el_name
                        best_header_img_el["count"] = header_img_value["count"]
    if best_header_img_el["short_name"]:
        name, attrs, xpath = re.split("╬", best_header_img_el["short_name"])
        attrs = json.loads(attrs)
        header_img_element = {"attrs": attrs,
                              "name": name,
                              "custom_xpath": xpath,
                              'only_content': False,
                              "is_description_element": False,
                              "is_header_img_element": True,
                              "is_author_element": False,
                              "parent": None
                              }
    return header_img_element


def check_parents_recursive(el_parent_attrs: dict, el: BeautifulSoup) -> bool:
    parent = get_first_el(el.find_parents(el_parent_attrs['name'], attrs=el_parent_attrs["attrs"]))
    if parent:
        if "parent" in el_parent_attrs:
            return check_parents_recursive(el_parent_attrs["parent"], parent)
        return True
    else:
        return False


def compare_el_with_attrs(news_attrs_list: [list, dict], el: [BeautifulSoup, dict], find_parents=False,
                          compare_parents=True, check_xpath=False) -> [bool, str, tuple]:
    if type(news_attrs_list) is dict:
        news_attrs_list = [news_attrs_list]
    if repr(type(news_attrs_list)) == "<class 'bs4.element.Tag'>":
        news_attrs_list = [{"attrs": news_attrs_list.attrs, "name": news_attrs_list.name}]
    el_attrs = el['attrs'] if type(el) is dict else el.attrs
    el_name = el['name'] if type(el) is dict else el.name
    for news_attrs in news_attrs_list:
        if find_parents:
            if el.find_parents(news_attrs['name'], attrs=news_attrs["attrs"]):
                return True
        if news_attrs['name'] == el_name:
            suitable_item = True
            for attr in news_attrs["attrs"]:
                if attr in el_attrs and news_attrs["attrs"][attr] == el_attrs[attr]:
                    continue
                suitable_item = False
                break
            if suitable_item:
                if "parent" in news_attrs and news_attrs["parent"] and compare_parents:
                    if not check_parents_recursive(news_attrs["parent"], el):
                        continue
                if check_xpath:
                    if "custom_xpath" in news_attrs and news_attrs["custom_xpath"]:
                        return (news_attrs["custom_xpath"], get_xpath_pattern(el),
                                f"{news_attrs['name']}|{json.dumps(news_attrs['attrs'])}")
                    else:
                        return None
                return True
    return False


def compare_el_xpath(pillar_xpath, el_xpath):
    pillar_xpath, el_xpath = re.split("①", pillar_xpath), re.split("①", el_xpath)
    pillar_xpath.reverse()
    el_xpath.reverse()
    overlap = 0
    for index in range(0, len(el_xpath)):
        try:
            if pillar_xpath[index] == el_xpath[index]:
                overlap += 1
        except:
            break
    return overlap


def find_news_zone(soup, news_el):
    all_news_elements = []
    overlaps = {}
    for element in soup.find_all(lambda element: compare_el_with_attrs(news_el, element)):
        xpath_res = compare_el_with_attrs(news_el, element, compare_parents=False, check_xpath=True)
        overlap, short_el_name = None, None
        if xpath_res:
            xpath, el_xpath, short_el_name = xpath_res
            overlap = compare_el_xpath(xpath, el_xpath)
            if short_el_name in overlaps:
                if overlap > overlaps[short_el_name]["overlap"]:
                    overlaps[short_el_name]["overlap"] = overlap
                    overlaps[short_el_name]["bigest"] = True
            else:
                overlaps[short_el_name] = {"overlap": overlap, "bigest": False}
        all_news_elements.append({"overlap": overlap, "short_name": short_el_name,
                                  "html_data": BeautifulSoup(
                                      re.sub("<!.+?>", "", str(element), flags=re.DOTALL), 'lxml',
                                      multi_valued_attributes=None)})
    for short_el_name in overlaps:
        if not overlaps[short_el_name]["bigest"]:
            continue
        for index in range(len(all_news_elements) - 1, -1, -1):
            try:
                if all_news_elements[index]["short_el_name"] == short_el_name:
                    if overlap != overlaps[short_el_name]["overlap"]:
                        all_news_elements.pop(index)
            except:
                pass
    return all_news_elements


def find_previous_and_next_zone(html_data, news_el):
    next_zone = []
    first = True
    while news_el.parent:
        navigate_el = news_el.parent
        extract = False
        for el in [item for item in list(navigate_el.children) if str(item).strip()]:
            if extract:
                next_zone.append(el.extract())
            else:
                if type(el) is str:
                    continue
                if compare_el_with_attrs(el, news_el):
                    extract = True
                    if first:
                        first = False
        news_el = navigate_el
    return html_data, next_zone

def divide_pages(news_el, items):
    for item in items:
        soup = BeautifulSoup(str(BeautifulSoup(re.sub("<!--.+?-->", "", str(item["html_data"])), "html5lib")), 'lxml',
                             multi_valued_attributes=None)
        body = {"previous_zone": None, "news_zone": None, "next_zone": None}
        news_zone = get_first_el(find_news_zone(soup, news_el))
        if news_zone:
            body['news_zone'] = news_zone["html_data"]
        if not body['news_zone']:
            continue
        body['previous_zone'], body['next_zone'] = find_previous_and_next_zone(item["html_data"], body['news_zone'])
        item["divided_body"] = body
    return items


async def find_main_news_element(items, count_all_items, connection_mode):
    # count_valid_news, all_parents, max_count_text_item = find_target_elements(items, count_all_items)
    newdata = []
    count_valid_news = len(items) - 1
    max_count_text_item = None
    all_interiors_els, all_indexes, pillar, traseback, count_all_els = get_interiors_els(max_count_text_item,
                                                                                         [item["html_data"] for item in
                                                                                          items[1:]], count_valid_news)
    if not traseback:
        result = {"count_valid_news": count_valid_news, "len_all_els": count_all_els, "clear_els": None,
                  "trash_els": None, "channel_created": False}
        return None, result, False, newdata, count_valid_news
    clear, trash = calculate_probability(all_interiors_els, all_indexes, pillar)
    channel = create_doc(clear, trash, items[0])
    result = {"count_valid_news": count_valid_news, "len_all_els": count_all_els, "clear_els": len(clear),
              "trash_els": len(trash), "channel_created": True if channel else False}
    if channel:
        items = divide_pages(channel["news_elements"][0], items[1:])
        author_el = find_author_el(items)
        channel["author_el"] = author_el
        header_img_el = await find_header_img_el(items, connection_mode)
        if header_img_el:
            channel["news_elements"].append(header_img_el)
        newdata = []
        for item in items[1:]:
            el = item["newdata"]
            el['trash_items'] = channel['trash_items']
            el['news_elements'] = channel['news_elements']
            el['parser_id'] = channel['parser_id']
            newdata.append(el)
    return channel, result, True, newdata, count_valid_news


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


def vectoriser(string):
    v_string = re.sub("[^0-9]", "4",
                      re.sub("~~~~", "1", re.sub("\s+", "3", re.sub("\w+", "2", re.sub("\d+", "~~~~", string)))))
    if not v_string:
        return "0"
    # Строковый отпечаток вместо int(): иначе ValueError int_max_str_digits на длинных статьях (Py3.12+).
    # Используется как ключ уникальности / dict key, не как арифметическое число.
    return v_string


def get_count_all_items(items):
    text_patterns = {}
    first = True
    for item in items:
        if first:
            first = False
            continue
        if item['text_items']:
            for text_item in item['text_items']:
                if vectoriser(text_item) in text_patterns:
                    text_patterns[vectoriser(text_item)] += 1
                else:
                    text_patterns[vectoriser(text_item)] = 1
    more_items = {}
    first = True
    for item in items:
        if first:
            first = False
            continue
        if item['text_items']:
            for text_item in item['text_items']:
                if text_item in more_items:
                    more_items[text_item]["count_text_items"] += 1
                else:
                    more_items[text_item] = {"count_text_items": 1,
                                             "count_text_paterns": text_patterns[vectoriser(text_item)]}
    return more_items


def divide_into_items_by_br_tags_div(item):
    items = [clean(i) for i in re.split('(?:<br/>|<blockquote/*>|<p/*>)', item) if len(re.findall('[а-яА-Я]', i)) > 1]
    return items


def unpack_list(some_list):
    unpack = []
    for el in some_list:
        if type(el) is list:
            unpack.extend(el)
        else:
            unpack.append(el)
    return unpack


async def fetch_all_elements(newdata, connection_mode, try_count):
    if try_count > 3:
        return
    proxy, headers = get_connection_options(connection_mode, response_type=str)
    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.request("get", newdata['link'], headers=headers, timeout=timeout, proxy=proxy) as response:
            response = await response.text()
            soup = BeautifulSoup(response, 'lxml', multi_valued_attributes=None)
            items = unpack_list(
                [i.text if str(i.text).find('<br/>') == -1 else divide_into_items_by_br_tags_div(i.text) for i in
                 soup.find_all(lambda el: True if len(re.findall('[а-яА-ЯёЁ]+', el.text)) > 1 else False)])
            return {'text_items': items, 'html_data': soup, 'newdata': newdata}
    except:
        try_count += 1
        return await fetch_all_elements(newdata, connection_mode, try_count)
