import os
import sys
from bs4 import BeautifulSoup
import aiohttp
import asyncio
import re
import json
import pandas as pd
import pickle
from fake_useragent import UserAgent
sys.path.append(os.path.dirname(os.path.realpath(os.path.abspath(''))))
from component.news_parser.news_parser_class import NewsParser


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
            name, attrs = parent.split('|')
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
            if count_all_items[text_item]['count_text_items'] > 1 or \
                    count_all_items[text_item]['count_text_paterns'] > 1:
                continue
            navigable_item = soup.find(lambda tag: soup_clean(tag.text) == soup_clean(text_item) if str(tag.text).find(
                '<br/>') == -1 else text_item in divide_into_items_by_br_tags_div(tag.text))
            level = 0
            while navigable_item and navigable_item.parent:
                navigable_item = navigable_item.parent
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
    return int(structure_patern)


def average_values(attrs, name="pillar", count_valid_news=None):
    if name != "pillar":
        if erect_to_percent(count_valid_news, 20) >= attrs["found_in"] or \
                (attrs["global_count"] / attrs["found_in"]) > 1.5:
            return None
    average_attrs = {"count_text_items": [attrs["count_text_items"] / attrs["global_count"]],
                     "count_hyperlink": [attrs["count_hyperlink"] / attrs["global_count"]],
                     "count_media": [attrs["count_media"] / attrs["global_count"]]}
    if name == "pillar":
        average_attrs["percent_unique_structure_patern"] = attrs["percent_unique_structure_patern"] / \
                                                           attrs["global_count"]
        average_attrs["percent_unique_text_patern"] = attrs["percent_unique_text_patern"] / attrs["global_count"]
    else:
        average_attrs["percent_unique_structure_patern"] = [len(set(attrs["structure_patern"])) /
                                                            (len(attrs["structure_patern"]) / 100)]
        average_attrs["percent_unique_text_patern"] = [len(set(attrs["text_patern"])) /
                                                       (len(attrs["text_patern"]) / 100)]
    average_attrs["nesting_level"] = [attrs["nesting_level"] / attrs["global_count"]]
    average_attrs["name"] = name
    if name == "pillar":
        average_attrs["global_count"] = [attrs["global_count"]]
    else:
        average_attrs["global_count"] = [attrs["found_in"] / attrs["global_count"]]
    return average_attrs


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
            short_parent_name = f"{el.name}|{json.dumps(el.attrs)}"
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
    # print("len els", len(all_elements))
    for el in all_elements:
        # print(el, all_elements[el])
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
        return all_elements_average, all_indexes, pillar, False
    pillar = average_values(pillar)
    all_indexes = list(set(all_indexes))
    all_indexes.sort()
    return all_elements_average, all_indexes, pillar, True


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
        name, attrs = el["name"].split('|')
        attrs = json.loads(attrs)
        if not attrs:
            continue
        if el["nesting_level"][0] > max_nesting_level["nesting_level"]:
            max_nesting_level["nesting_level"] = el["nesting_level"][0]
            max_nesting_level["el"] = el
    if not max_nesting_level["el"]:
        return None
    name, attrs = max_nesting_level["el"]["name"].split('|')
    attrs = json.loads(attrs)
    item['news_elements'].append({
        "attrs": attrs,
        "name": name,
        'only_content': False
        # "metrixs": max_nesting_level["el"]
    })
    trash_sort = []
    for el in trash:
        try:
            name, attrs = el['name'].split('|')
        except:
            name = re.findall("(.+?)\|", el['name'], flags=re.DOTALL)[0]
            attrs = re.findall(".+?\|(.+)", el['name'], flags=re.DOTALL)[0]
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
    item['status'] = 1
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
            trash['trash_indexes'][item] = count_all_items[item]
    trash['trash_indexes']['count_news'] = count_news
    return trash


async def find_main_news_element(items, count_all_items, session):
    count_valid_news, all_parents, max_count_text_item = find_target_elements(items, count_all_items)
    all_interiors_els, all_indexes, pillar, traseback = get_interiors_els(max_count_text_item,
                                                                          [item["html_data"] for item in items[1:]],
                                                                          count_valid_news)
    if not traseback:
        result = {"count_valid_news": count_valid_news, "len_all_els": len(all_parents), "clear_els": None,
                  "trash_els": None, "channel_created": False}
        return None, result, False
    clear, trash = calculate_probability(all_interiors_els, all_indexes, pillar)
    channel = create_doc(clear, trash, items[0])
    result = {"count_valid_news": count_valid_news, "len_all_els": len(all_parents), "clear_els": len(clear),
              "trash_els": len(trash), "channel_created": True if channel else False}
    if channel:
        np = NewsParser()
        newdata = []
        for item in items[1:]:
            el = item["newdata"]
            el['trash_items'] = channel['trash_items']
            el['news_elements'] = channel['news_elements']
            el['parser_id'] = channel['parser_id']
            newdata.append(el)
        parsed_data = del_none(await asyncio.gather(*[np.parse_news_pid50(el, session) for el in newdata]))
        if not parsed_data:
            result = {"count_valid_news": count_valid_news, "len_all_els": len(all_parents), "clear_els": len(clear),
                      "trash_els": len(trash), "channel_created": True if channel else False}
            return channel, result, False
        all_text_items = get_count_raw_items(parsed_data)
        channel["trash_items"] = find_trash((count_valid_news, all_text_items), channel["trash_items"])
    return channel, result, True


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
        return 0
    return int(v_string)


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


async def fetch_all_elements(newdata, session):
    ua = UserAgent()
    headers = {'User-Agent': ua.chrome}
    timeout = aiohttp.ClientTimeout(total=600)
    try:
        async with session.get(newdata['link'], headers=headers, timeout=timeout, ssl=False) as response:
            response = await response.text()
            soup = BeautifulSoup(response, 'lxml', multi_valued_attributes=None)
            items = unpack_list(
                [i.text if str(i.text).find('<br/>') == -1 else divide_into_items_by_br_tags_div(i.text) for i in
                 soup.find_all(lambda el: True if len(re.findall('[а-яА-ЯёЁ]+', el.text)) > 1 else False)])
            return {'text_items': items, 'html_data': soup, 'newdata': newdata}
    except Exception as ex:
        return None
