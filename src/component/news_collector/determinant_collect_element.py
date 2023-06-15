from bs4 import BeautifulSoup
import aiohttp
import re
from fake_useragent import UserAgent
import json
import dateparser


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
            string.append(re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub(
                '(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\"|\\n|\\t)+', '', i))).strip())
        return string
    return re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"',
                                                   re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\n|\\t)+',
                                                          '', item))).strip()


async def get_page(session, link):
    ua = UserAgent()
    headers = {'User-Agent': ua.chrome}
    timeout = aiohttp.ClientTimeout(total=600)
    async with session.get(link, headers=headers, timeout=timeout, ssl=False) as response:
        status = response.status
        try:
            response = await response.text()
            soup = BeautifulSoup(response, 'lxml', multi_valued_attributes=None)
        except:
            soup = BeautifulSoup(await response.read(), 'lxml', multi_valued_attributes=None)
        return soup, status


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
    for link in [re.sub("[0-9]+", "[0-9]+", re.sub("(.+/)(.+)", r"\1.+?", re.sub("([\\\|\[\]{}()+*^])", r"\\\1",
                                                                                 el.get("href") if el.get("href")[
                                                                                                       -1] != "/" else el.get(
                                                                                         "href")[:-1]),
                                                   flags=re.DOTALL)) + "/*" for el in
                 page.find_all(lambda el: "href" in el.attrs) if el.get("href")]:
        if link not in all_links:
            all_links[link] = 1
        all_links[link] += 1
        if all_links[link] > best_pattern["count"]:
            best_pattern = {"pattern": link, "count": all_links[link]}
    return page.find_all(
        lambda el: "href" in el.attrs and re.fullmatch(best_pattern["pattern"], el.get("href"), flags=re.DOTALL)), \
    best_pattern["pattern"]


def find_collector_element(page, site, status):
    all_elements = {}
    all_date_elements = page.find_all(required_parameters)
    all_patterns = {}
    pattern = None
    if not all_date_elements:
        optimum_elements, pattern = find_optimum_elements(page)
    else:
        optimum_elements = all_date_elements
    unical_els = {}
    for el in optimum_elements:
        el_name = get_short_el_name(el)
        if el_name not in unical_els:
            unical_els[el_name] = {"count": 1, "text_in_el": 0, "href_in_el": 0}
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
                if len(re.findall("[А-Яа-яЁёa-zA-Z]+", parent.get_text())) > 2:
                    unical_els[el_name]["text_in_el"] += 1
                    href = parent.find_all(lambda element: "href" in element.attrs and (len(re.findall("/", re.sub(
                        "https*://", "", element.get("href")))) == pattern if pattern else True))
                    if href:
                        # print(href)
                        len_options = len(re.findall("/", re.sub("https*://", "", href[0].get("href"))))
                        if len_options not in all_patterns:
                            all_patterns[len_options] = 0
                        all_patterns[len_options] += 1
                        unical_els[el_name]["href_in_el"] += 1
                        if short_el_name not in all_elements:
                            all_elements[short_el_name] = {"count": 1, "parents": {}}
                        all_elements[short_el_name]['count'] += 1
                        element_found = short_el_name
            else:
                if level not in all_elements[element_found]["parents"]:
                    all_elements[element_found]["parents"][level] = [short_el_name]
                if short_el_name not in all_elements[element_found]["parents"][level]:
                    all_elements[element_found]["parents"][level].append(short_el_name)
                level += 1
            parent = parent.parent
    maps = []
    for el in all_elements:
        name, attrs = el.split('|')
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
            lmap = {"name": name, "attrs": attrs, "next": False}
            maps.append(lmap)
            continue
    res = {"response_code": status, "all_date_elements": len(all_date_elements), "fit_elements": len(all_elements),
           "map_els": len(maps)}
    best_patern = {"len_options": None, "count": 0}
    for pat in all_patterns:
        if all_patterns[pat] > best_patern["count"]:
            best_patern["len_options"] = pat
            best_patern["count"] = all_patterns[pat]
    pattern = best_patern["len_options"]
    # print("pat", pattern, res, site)
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


async def run(newdata, session, collect_url):
    possible_links = [f"https://{newdata['url']}", f"http://{newdata['url']}", f"https://{newdata['url']}/news",
                      f"http://{newdata['url']}/news", f"https://{newdata['url']}/articles",
                      f"http://{newdata['url']}/articles"] if not collect_url else [collect_url]
    report = None
    connect_error = False
    for link in possible_links:
        page, status = await get_page(session, link)
        report = {"response_code": status}
        if page:
            # print(page)
            collector_elements, report, pattern = find_collector_element(page, newdata['url'], status)
            if collector_elements:
                return collector_elements, link, report, pattern, connect_error
        else:
            connect_error = True
    return None, None, report, None, connect_error
