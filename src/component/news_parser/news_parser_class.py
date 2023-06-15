import aiohttp
import re
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import json
import dateparser
import datetime


def get_first_el(some_list):
    return some_list[0] if len(some_list) >= 1 else None


def shield(string):
    return re.sub("([\\|.\[\]{}()+*^])", r"\\\1", string)


def collect_br_tags(previous_el=None, next_el=None):
    if next_el and previous_el:
        return del_none([collect_br_tags(previous_el=previous_el), collect_br_tags(next_el=next_el)])
    if next_el and re.fullmatch(f'(?:img|iframe|a|span|i|article|script|None|b|u)', str(next_el.name)):
        text = re.sub(shield(clean(str(next_el)).strip()), "", collect_br_tags(next_el=next_el.next))
        text = text if text and text.startswith(" ") else " " + text
        return clean(str(next_el)).strip() + text
    if previous_el and re.fullmatch(f'(?:img|iframe|a|span|i|article|script|None|b|u)', str(previous_el.name)):
        text = re.sub(shield(clean(str(previous_el)).strip()), "", collect_br_tags(previous_el=previous_el.previous))
        text = text if text and text[-1] == " " else text + " "
        return text + clean(str(previous_el)).strip()
    # print("name", f"{previous_el.name} pre" if previous_el else f"{next_el.name} next" if next_el else None)
    return ''


def get_best_img(value_for_attr):
    if not value_for_attr:
        return None
    all_img = re.findall(
        '(?:[^ \'"<>,]+?/[^ \'"<>,]+?)(?:\.jpg|\.jpeg|\.jepeg|\.webp|\.png|\.JEPEG|\.JPEG|\.JPG)(?:[^ \'"<>,]+?)*',
        value_for_attr)
    max_permission = {'url': None, 'permission': 0}
    for picture in all_img:
        if re.fullmatch('.+-[0-9]+x[0-9]+.*', picture):
            perm_sum = int(re.findall('-([0-9]+)x[0-9]+', picture)[0]) + int(re.findall('-[0-9]+x([0-9]+)', picture)[0])
            if perm_sum > max_permission['permission']:
                max_permission = {'url': picture, 'permission': perm_sum}
        else:
            max_permission = {'url': picture, 'permission': 99999999}
            break
    if max_permission["url"]:
        return max_permission['url']


def check_repr(re_repr, string):
    try:
        return re.fullmatch(re_repr, string)
    except:
        return True if re_repr == string else False


def compare_el_with_attrs(news_attrs_list: [list, dict], el: [BeautifulSoup, dict], find_parents=False) -> bool:
    if type(news_attrs_list) is dict:
        news_attrs_list = [news_attrs_list]
    el_attrs = el['attrs'] if type(el) is dict else el.attrs
    el_name = el['name'] if type(el) is dict else el.name
    for news_attrs in news_attrs_list:
        if find_parents:
            if el.find_parents(news_attrs['name'], attrs=news_attrs["attrs"]):
                return True
        suitable_item = True
        for attr in news_attrs["attrs"]:
            if attr in el_attrs and news_attrs["attrs"][attr] == el_attrs[attr] and news_attrs['name'] == el_name:
                continue
            suitable_item = False
            break
        if suitable_item:
            return True
    return False


def del_none(some_list):
    return [item for item in some_list if item]


def check_time(time: int) -> int or None:
    now = int(datetime.datetime.now().timestamp())
    if not time or time > now:
        return now
    return time


def reconvert_date(date):
    if re.fullmatch('[0-9]{2}.[0-9]{2}.[0-9]{4} [0-9]{2}:[0-9]{2}', date):
        day, mon, year = re.findall('[0-9]{2,}', date)[0:3]
        date = re.sub('[0-9]{2}.[0-9]{2}.[0-9]{4}', f'{year}.{mon}.{day}', date)
        return date


def revise_break_patern_v2(text, re_strings):
    for re_string in re_strings:
        if re.fullmatch(re_string, text):
            return True


def get_bul(some_dict, key):
    if key in some_dict:
        if some_dict[key]:
            return True
    return False


def get_short_el_name(el, get_parents=False):
    if get_parents:
        res = []
        for parent in el.parents:
            el_name = parent.name
            el_attrs = parent.attrs
            res.append(f'{el_name}|{json.dumps(el_attrs)}')
        return res
    el_name = el.name
    el_attrs = el.attrs
    short_name = f'{el_name}|{json.dumps(el_attrs)}'
    return short_name


def revise_break_patern(text):
    if text == 'Читайте также:' or \
            text == 'Читать также:' or \
            text == 'Материалы рубрики' or \
            text == 'Похожие публикации:' or \
            text == 'на рассылку dostup1.ru' or \
            text == 'Читайте также' or \
            text == 'Оставить комментарий Отменить ответ' or \
            text == 'Поделись новостью:' or \
            text == 'СЛЕДУЮЩАЯ НОВОСТЬ ЧИТАТЬ' or \
            'Оставить комментарий' == text or \
            'Media.az' in text or \
            text == 'Источник:' or \
            text == 'Смотреть также' or \
            text == 'Смотреть также' or \
            'Опубликовано:' in text or \
            'Темы:' in text or \
            '🍎 Читайте также →' in text or \
            'По теме:' in text or \
            'Новости по теме' in text or \
            'Навигация по записям' in text or \
            'Честные новости в ОК' in text or \
            'Сюжет подготовили:' in text or \
            'ПОДЕЛИТЬСЯ НОВОСТЬЮ' in text or \
            'Похожие материалы' in text or \
            'Еще из этой рубрики:' in text or \
            'Поделиться ссылкой:' in text or \
            'Поделиться новостью:' == text or \
            'Вам может понравиться' == text or \
            'Подписывайтесь на наши каналы:' == text or \
            'Популярное в тему:' == text or \
            'Другие статьи на эту тему' == text or \
            'Жутко интересно' == text or \
            'Также интересно почитать' == text or \
            'ТЕМЫ' == text or \
            'Поделиться материалом:' == text or \
            'Интересно? Полезно? Хотите помочь редакции ?' == text or \
            'На нашем сайте читайте также:' == text or \
            'Популярные новости' == text or \
            'Рекомендуем наши новости' == text or \
            'Другие публикации по теме:' == text or \
            'Другие новости:' == text or \
            'Последние новости' == text or \
            'Публикации по теме' == text or \
            'ЧИТАЙТЕ ТАКЖЕ...' == text or \
            'ЧИТАЙТЕ ТАКЖЕ' == text or \
            'В тему:' == text or \
            '"Колос"' == text or \
            'Читать далее:' == text or \
            'Также Вам будет интересно:' == text or \
            'Похожее' == text or \
            'Материалы по теме' == text or \
            'Еще новости' == text or \
            'Читайте по теме:' == text or \
            'Назад' == text or \
            'Ранее:' == text or \
            'Ранее всюжете' == text or \
            "А еще:" == text or \
            'Это интересно:' == text or \
            'Все новости автора' == text or \
            'Предыдущий текст' == text or \
            'Еще по теме:' == text or \
            'Читайте также в блоге' == text or \
            'Вам также может быть интересно:' == text or \
            'Еще по теме' == text or \
            'Поделись с друзьями' == text or \
            'Твитнуть' == text or \
            'А еще у нас есть…' == text or \
            'Читать еще' == text or \
            'Статьи на эту тему' == text or \
            'Главное по теме' == text or \
            'Добавить комментарий' == text or \
            'Похожие публикации' == text or \
            'ССЫЛКИ ПО ТЕМЕ:' == text or \
            'Ещё по теме' == text or \
            'Другие темы' == text or \
            'Другие статьи раздела' == text or \
            'Сейчас читают:' == text or \
            'Похожие статьи' == text or \
            'вступай в группу ИА IrkutskMedia во "ВКонтакте"' in text or \
            'Из этой же рубрики' in text or \
            'Похожие записи' in text or \
            'Понравилась статья?' in text or \
            'Материалы по теме:' == text or \
            'МАТЕРИАЛЫ ПО ТЕМЕ' == text or \
            'Понравился материал?' == text or \
            text == 'Статьи по теме' or \
            'Также будет интересно:' == text or \
            'Актуальное по теме:' == text or \
            'Другие новости рубрики' == text or \
            'Вам также понравится' == text or \
            'Поделиться в социальных сетях' == text or \
            'Смотрите также:' == text or \
            'Похожие статьи:' == text or \
            'Другие интересные новости' == text or \
            text.startswith('Другие материалы рубрики') or \
            text.startswith('Следующая публикация') or \
            text.startswith('Предыдущая публикация') or \
            'КАК ВАМ НОВОСТЬ?' == text or \
            'Информационное агентство «Shraibikus News»,' == text or \
            'Подписывайтесь на наш Telegram – канал: https://t.me/interaffairs' == text or \
            'Больше новостей и интересных материалов в нашем Telegram-канале .' == text or \
            'Больше новостей, фото и видео в нашем Телеграм-канале !' == text or \
            'Подписывайтесь на канал «Взавтра.Net» в Яндекс Дзен,' == text or \
            'Чтобы сообщить об опечатке, выделите текст и нажмите Ctrl + Enter' == text or \
            'Больше новостей и ближе к сути? Заходите на ленту в Телеграм !' == text or \
            'Читайте наши новости также в "Одноклассниках" , "Вконтакте" и в телеграм-канале .' == text or \
            'Заинтересовал материал? Поделитесь в социальных сетях и оставьте комментарий ниже:' == text or \
            'Следить за новостями проще — Присоединяйся к нам в Одноклассниках.' == text or \
            'Насколько вероятно, что при случае вы порекомендуете Гастроном своим друзьям и знакомым?' == text or \
            'Хотите узнавать об интересных событиях первыми? Подпишитесь на нас в Яндекс.Новости , Google.Новости !' == text or \
            'Нашли ошибку или опечатку в тексте выше? Выделите слово или фразу с ошибкой и нажмите Shift + Enter или ' \
            'сюда.' == text or \
            text.startswith('Если вы нашли ошибку, пожалуйста, выделите фрагмент текста и нажмите') or \
            text.startswith('Понравился материал? Пожалуйста, расскажите об этом окружающим') or \
            text.startswith('Больше новостей читайте втелеграм-канале') or \
            text.startswith('Подписывайтесь на LIVE24.RU в Новостях') or \
            text.startswith('Подписывайтесь на RUSSKIE.ORG') or \
            text.startswith('Читайте также:') or \
            text.startswith('Читать также: ') or \
            text.startswith('Все новости по теме') or \
            text.startswith('Похожие статьи по теме:') or \
            'Редакция' == text or \
            'Теги:' == text or \
            'Читайте еще' == text or \
            re.fullmatch('Материал подготовила *[А-Яа-я]+ *[А-Яа-я]+ *', text) or \
            re.fullmatch('[0-9]+ комментариев', text) or \
            re.fullmatch('Публикации [0-9]+ года:', text) or \
            text.startswith('Метки:') or \
            text.startswith('Подпишитесь на наши каналы в ') or \
            text.startswith('Подписывайтесь на нашТелеграм-канал') or \
            text.startswith('*Экстремистские и террористические организации, запрещенные в Российской Федерации:') or \
            'Поделись новостью в социальных сетях' in text or \
            "Самое интересное:" in text:
        return True
    return False


def img_continuer(img: str):
    img = re.sub('(?:https://|http://)', '', img)
    if img[0] == '/':
        img = img[1:]
    if re.fullmatch('images/donation/cup-[0-9]+.png', img) or \
            re.fullmatch('.+main-version-without-useless-borders-[0-9].*', img) or \
            re.fullmatch('.+upimg/soc/.+png', img) or \
            len(re.findall('uploads/flag-[a-zA-Z0-9]+.png', img)) > 0 or \
            img.find('themes/mosvedomosti/images/telegram.png') != -1 or \
            img.find('moskvichmag/uploads/2022/03/zen-icon.png') != -1 or \
            img.find('wp-content/uploads/2021/06/d-yandex2.jpg') != -1 or \
            img.find('wp-content/uploads/2021/06/g-news.jpg') != -1 or \
            img.find('wp-content/uploads/2021/06/y-news.jpg') != -1 or \
            img.find('moskvichmag/uploads/2022/03/vk-icon.png') != -1 or \
            img.find('moskvichmag/assets/subscribe-youtube.png') != -1 or \
            img.find('media/img/0/01/756358467784010.jpg') != -1 or \
            img.find('moskvichmag/assets/subscribe-tg.png') != -1 or \
            img.find('img/Y-news.jpg') != -1 or \
            img.find('media/img/0/01/756358467784010.jpg') != -1 or \
            img.find('img/G-news.jpg') != -1:
        return False
    return True


def breaker_tag(text):
    if text == 'ВКОНТАКТЕ' \
            or text == 'Авторы' \
            or text == 'ПО ТЕМЕ' \
            or text == 'Вперёд' \
            or text == 'Share this...' \
            or text == 'Подписаться' \
            or text == 'Все новости' \
            or text == 'Статьи по теме' \
            or text == 'Что еще почитать' \
            or text == 'Предыдущая статья' \
            or text == 'Вам также может быть интересно' \
            or text == 'Новость предоставлена компанией' \
            or text == 'Вас может заинтересовать:':
        return True
    return False


def text_item_continuer(text, doc):
    if not text or text == '' or text == ' ' or \
            text == 'Почитать подробнее' or \
            text == 'ВКонтакте' or \
            text == 'Телеграм' or \
            text == 'Ссылка' or \
            text == 'LatgBa1H5' or \
            text == 'Источник: sibmama.ru' or \
            text == 'Происшествия' or \
            text == 'Реклама. beeline.ru. LatgBb1is' or \
            text == 'Источник: RG.RU .' or \
            text == 'Ознакомиться с материалами можно здесь .' or \
            text == 'Комментарии' or \
            text == 'ЧИТАЙТЕ ТАКЖЕ:' or \
            text == 'Facebook' or \
            text == 'Источник: asi.org.ru .' or \
            text == 'Источник: nia.eco' or \
            text == 'Реклама beeline.ru' or \
            text == 'вернуться к списку новостей | Архив' or \
            text == 'Версия для печати' or \
            text == 'Подробности' or \
            text == 'Twitter' or \
            text == 'Related posts:' or \
            text == 'По теме' or \
            text == 'МАТЕРИАЛ ПО ТЕМЕ' or \
            re.fullmatch('[0-9]', text) or \
            text.startswith('Фото и видео:') or \
            text.startswith('Автор:') or \
            text.startswith('Post category:') or \
            text.startswith('Следующая публикация') or \
            text.startswith('Читайте также :') or \
            text.startswith('Предыдущая публикация') or \
            text.startswith('Опубликовано в:') or \
            text.startswith('источник фото:') or \
            text.startswith('Добавлен:') or \
            text.startswith('Фото:') or \
            text.startswith('фото:') or \
            text.startswith('пїЅпїЅпїЅпїЅпїЅпїЅ') or \
            text.startswith('Видео:') or \
            text.startswith('Tags:') or \
            text.startswith('В тему: ') or \
            text.startswith('Запись опубликована:') or \
            text.startswith('Фотографии:') or \
            'Обложка:' in text or \
            'Место события на карте мира:' in text or \
            'Читайте также\n' in text or \
            'Опубликовано:' in text or \
            text == 'Главные новости прошедшего дня' or \
            'Новость по теме\n' in text or \
            'Статья по теме\n' in text or \
            'on Telegram' in text or \
            'Читать также:' in text or \
            "Сайт:" in text or \
            '{' in text or \
            "«Южного город» в соцсетях:" in text or \
            "Вк:" in text or \
            "Телеграм:" in text or \
            len(re.findall('[a-zA-ZА-Яа-я0-9]', text)) == 0 or \
            soup_clean(text) == soup_clean(doc['title']) or \
            text == 'Для просмотра видео включите поддержку javascript в браузере, или используйте браузер, который поддерживает HTML5 видео' or \
            re.fullmatch('[А-Яа-я]+ - [0-9]+ [А-Яа-я]+ [0-9]+, [0-9:]+ - [А-Яа-я ]+', text) or \
            re.fullmatch('от [А-Яа-я]+ [А-Яа-я]+ · [0-9]{2}\.[0-9]{2}\.[0-9]{4}', text) or \
            re.findall(', [0-9]+ Просмотров', text) or \
            re.findall('[0-9]+.[0-9]+.[0-9]+ [0-9]+:[0-9]+ .+', text) or \
            re.fullmatch('Фото, видео:.+5-tv.ru', text) or \
            re.fullmatch('Просмотры: [0-9]+  | .+  | .+', text) or \
            re.fullmatch('Комментарии /[0-9]+', text) or \
            re.fullmatch('Фото /[0-9]+', text) or \
            re.fullmatch('Видео /[0-9]+', text) or \
            re.fullmatch('Вчера, [0-9]+:[0-9]+', text) or \
            re.fullmatch('ФОТО [a-zA-ZА-Яа-я0-9]+', text) or \
            re.fullmatch('Сегодня, [0-9]+:[0-9]+', text) or \
            re.fullmatch('Прочтений: [0-9]+', text) or \
            re.fullmatch('Комментарии ([0-9]+)', text) or \
            re.fullmatch("[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", text) or \
            re.fullmatch("[0-9]+-[0-9]+-[0-9]+-, [0-9]+:[0-9]+", text) or \
            re.fullmatch('.[0-9]+° [0-9]+ мм рт. ст.', text) or \
            re.fullmatch('Количество просмотров: [0-9]+', text) or \
            re.fullmatch('[0-9]+%[0-9]+\.[0-9]+', text) or \
            re.fullmatch('.[0-9]+\.[0-9]+.+Гороскоп на [0-9]+ января для всех знаков зодиака', text) or \
            "Теги:" in text or \
            "Ютуб:" in text or \
            text == 'Подписаться':
        return True
    return False


def get_values(some_dict: dict, key):
    if key in some_dict:
        return some_dict[key]
    else:
        return None


def create_items_pid50(doc, html_data):
    if 'trash_items' not in doc:
        doc['trash_items'] = False
    count_text_items = 0
    for item in html_data['content']:
        if 'text' in item and item['tag'] not in ['a', 'span']:
            item_text = item['text']
            if doc['trash_items'] and item_text in doc['trash_items']['trash_text_items']:
                continue
            if type(item_text) is not list:
                item_text = [item['text']]
            for text in item_text:
                text = re.sub('(?:[0-9]+ *Новости на Блoкнoт-Шахты|СЛЕДУЮЩАЯ НОВОСТЬ ЧИТАТЬ)', '', text)
                if not text_item_continuer(text, doc):
                    count_text_items += 1
    if doc["parser_id"] == 100:
        doc[
            'description'] = "НАСТОЯЩИЙ МАТЕРИАЛ (ИНФОРМАЦИЯ) ПРОИЗВЕДЕН, РАСПРОСТРАНЕН И (ИЛИ) " \
                             "НАПРАВЛЕН ИНОСТРАННЫМ " \
                             "АГЕНТОМ ООО ТЕЛЕКАНАЛ ДОЖДЬ ЛИБО КАСАЕТСЯ ДЕЯТЕЛЬНОСТИ ИНОСТРАННОГО АГЕНТА ООО " \
                             "ТЕЛЕКАНАЛ ДОЖДЬ"
    debug = doc['debug'] if 'debug' in doc else False
    link = doc['link']
    count = -1
    breaker = False
    items_start = False
    doc['telegramF'] = False
    all_text_items = []
    breaker_re_strings = doc['breaker_items']['breaker_re_strings'] if 'breaker_items' in doc and doc[
        'breaker_items'] else []
    all_img = []
    for item in html_data['content']:
        if breaker:
            break
        count += 1
        if count == 0 and doc['imgF']:
            if html_data['img']:
                if type(html_data['img']) is list:
                    html_data['img'] = html_data['img'][0]
                if not html_data['img'].startswith('http'):
                    if html_data['img'].find(re.findall("https*://(.+?)/", doc["link"])[0]) == -1:
                        html_data[
                            'img'] = f'{re.findall("(https*://.+?)/", doc["link"])[0]}{html_data["img"] if html_data["img"][0] == "/" else "/" + html_data["img"]}'
                    else:
                        html_data[
                            'img'] = f'{re.findall("https*://", doc["link"])[0]}{html_data["img"] if html_data["img"][0] == "/" else "/" + html_data["img"]}'
                    html_data['img'] = re.sub('(?:////|///)', '//', html_data['img'])
                if len(re.findall('https*://', html_data['img'])) > 1:
                    html_data['img'] = re.findall('.+(https*://.+)', html_data['img'])[0]
                if html_data['img'].find('logo') != -1 or html_data['img'].find('Logo') != -1 or \
                        html_data['img'].find('/images/social/tg') != -1 or \
                        html_data['img'].find('/images/social/vk') != -1 or \
                        html_data['img'].find('/images/social/twitter') != -1 or \
                        html_data['img'].find('/images/social/ok') != -1 or \
                        html_data['img'].find('/images/social/whatsapp') != -1 or \
                        doc['trash_items'] and del_none(
                    [check_repr(re_repr, str(html_data['img'])) for re_repr in doc['trash_items']['trash_links']]):
                    pass
                else:
                    all_img.append(html_data['img'])
                    news_item = {
                        'type': 2,
                        'image': html_data['img']}
                    if debug:
                        news_item['short_el_name'] = item['short_el_name']
                        news_item['short_parents_el_name'] = item['short_parents_el_name']
                    doc['raw_items'].append(news_item)
        elif count == 1 and doc['videoF']:
            video = html_data['video'] if type(html_data['video']) is not list else html_data['video'][0]
            video = None if doc['trash_items'] and del_none(
                [check_repr(re_repr, video) for re_repr in doc['trash_items']['trash_links']]) else video
            if video:
                news_item = {
                    'type': 6,
                    'original_url': video if video[0] == 'h' else 'https:' + video
                }
                if debug:
                    news_item['short_el_name'] = item['short_el_name']
                    news_item['short_parents_el_name'] = item['short_parents_el_name']
                doc['raw_items'].append(news_item)
        pass_site = ['live24.ru', 'iz.ru', "www.5-tv.ru", "www.bashinform.ru"]
        if item['tag'] == 'a' or item['tag'] == 'span':
            if doc['site'] not in pass_site:
                if breaker_tag(item['text']):
                    break
            continue
        if item['tag'] == 'tg_post':
            news_item = {
                "type": 4,
                "url": item['link'],
                "title": item['text']
            }
            if debug:
                news_item['short_el_name'] = item['short_el_name']
                news_item['short_parents_el_name'] = item['short_parents_el_name']
            doc['raw_items'].append(news_item)
            doc['telegramF'] = True
            continue
        if item['tag'] == 'iframe':
            if not item['video'].startswith('http'):
                if item['video'].startswith('//'):
                    item['video'] = f'{re.findall("(https*:)//", doc["link"])[0]}{item["video"]}'
                else:
                    item[
                        'video'] = f'{re.findall("(https*://.+?)/", doc["link"])[0]}{item["video"] if item["video"][0] == "/" else "/" + item["video"]}'
                item['video'] = re.sub('(?:////|///)', '//', item['video'])
            news_item = {
                'type': 6,
                'original_url': item['video']
            }
            if debug:
                news_item['short_el_name'] = item['short_el_name']
                news_item['short_parents_el_name'] = item['short_parents_el_name']
            doc['raw_items'].append(news_item)
            doc['videoF'] = True
            count = 2
            continue
        if item['tag'] == 'img':
            if doc['trash_items'] and del_none(
                    [check_repr(re_repr, item['img']) for re_repr in doc['trash_items']['trash_links']]):
                continue
            if item['img'][0] != 'http':
                if item['img'].startswith('//'):
                    item['img'] = f'{re.findall("(https*:)//", doc["link"])[0]}{item["img"]}'
                else:
                    item[
                        'img'] = f'{re.findall("(https*://.+?)/", doc["link"])[0]}{item["img"] if item["img"][0] == "/" else "/" + item["img"]}'
                    if item['img'].find(re.findall("https*://(.+?)/", doc["link"])[0]) == -1:
                        item[
                            'img'] = f'{re.findall("(https*://.+?)/", doc["link"])[0]}{item["img"] if item["img"][0] == "/" else "/" + item["img"]}'
                    else:
                        item[
                            'img'] = f'{re.findall("https*://", doc["link"])[0]}{item["img"] if item["img"][0] == "/" else "/" + item["img"]}'
                item['img'] = re.sub('(?:////|///)', '//', item['img'])
            if len(re.findall('https*://', item['img'])) > 1:
                item['img'] = re.findall('.+(https*://.+)', item['img'])[0]
            if item['img'].find('logo') != -1 or item['img'].find('Logo') != -1 or \
                    item['img'].find('/images/social/tg') != -1 or \
                    item['img'].find('/images/social/vk') != -1 or \
                    item['img'].find('/images/social/twitter') != -1 or \
                    item['img'].find('/images/social/ok') != -1 or \
                    item['img'].find('/images/social/whatsapp') != -1 or \
                    doc['trash_items'] and del_none(
                [check_repr(re_repr, item['img']) for re_repr in doc['trash_items']['trash_links']]):
                continue
            if html_data['img'] == item['img'] or len(doc['raw_items']) == 1 or len(doc['raw_items']) == 2 and \
                    doc['raw_items'][1]['type'] == 6:
                try:
                    all_img[0] = item['img']
                except:
                    all_img.append(item['img'])
                news_item = {
                    'type': 2,
                    'image': item['img']
                }
                if debug:
                    news_item['short_el_name'] = item['short_el_name']
                    news_item['short_parents_el_name'] = item['short_parents_el_name']
                try:
                    doc['raw_items'][0] = news_item
                except:
                    doc['raw_items'].append(news_item)
                continue
            if not doc['raw_items'] or doc['raw_items'][0]['type'] != 2 or not doc['raw_items'][0]['image']:
                all_img.append(item['img'])
                news_item = {
                    'type': 2,
                    'image': item['img']
                }
                if debug:
                    news_item['short_el_name'] = item['short_el_name']
                    news_item['short_parents_el_name'] = item['short_parents_el_name']
                doc['raw_items'].insert(0, news_item)
                doc['imgF'] = True
                continue
            else:
                if item['img'] not in all_img:
                    all_img.append(item['img'])
                    news_item = {
                        'type': 2,
                        'image': item['img']
                    }
                    if debug:
                        news_item['short_el_name'] = item['short_el_name']
                        news_item['short_parents_el_name'] = item['short_parents_el_name']
                    doc['raw_items'].append(news_item)
                continue
        item_text = item['text']
        if doc['trash_items'] and item_text in doc['trash_items']['trash_text_items']:
            continue
        if type(item_text) is not list:
            item_text = [item['text']]
        for text in item_text:
            text = re.sub('(?:[0-9]+ *Новости на Блoкнoт-Шахты|СЛЕДУЮЩАЯ НОВОСТЬ ЧИТАТЬ)', '', text)
            if soup_clean(text) == soup_clean(doc['title']):
                continue
            if text_item_continuer(text, doc):
                continue
            if doc['parser_id'] < 53:
                if revise_break_patern(text):
                    breaker = True
                    break
            else:
                if revise_break_patern_v2(text, breaker_re_strings):
                    breaker = True
                    break
            if not items_start:
                if len(re.findall('[а-яА-ЯЁёa-zA-Z]+', text)) >= 2:
                    items_start = True
                else:
                    continue
            if not doc['description']:
                if count_text_items == 1:
                    doc['description'] = get_first_el(re.findall('.+?[\.?!:]', text))
                    doc['description'] = doc['description'] if doc['description'] else text
                    text = text.replace(doc['description'], '').strip() if text != doc['description'] else None
                    if text:
                        text = re.sub("(.+?)(\w.+)", r"\2", text, flags=re.DOTALL) if re.fullmatch("[\.?!:]",
                                                                                                   get_first_el(
                                                                                                       text)) else text
                        text = text[0].upper() + text[1:]
                    if text and len(text) < 100:
                        doc['description'] += text
                        continue
                    if text:
                        news_item = {
                            'type': 1,
                            'text': text
                        }
                        if debug:
                            news_item['short_el_name'] = item['short_el_name']
                            news_item['short_parents_el_name'] = item['short_parents_el_name']
                        doc['raw_items'].append(news_item)
                    if doc['description'].startswith(doc['title']):
                        doc['description'] = doc['description'].replace(doc['title'], '')
                    continue
                else:
                    doc['description'] = text
                    if doc['description'].startswith(doc['title']):
                        doc['description'] = doc['description'].replace(doc['title'], '')
                        if doc['description'].startswith('. '):
                            doc['description'] = doc['description'][2:]
                    continue
            if text.startswith(doc['description']):
                text = text.replace(doc['description'], '')
                if text.startswith('. '):
                    text = text[2:]
            if soup_clean(text) == soup_clean(doc['description']):
                continue
            if not text:
                continue
            if text not in all_text_items:
                all_text_items.append(text)
            else:
                continue
            if re.fullmatch('h[0-9]', item['tag']):
                if not re.fullmatch('[А-Яё][а-яё]+ [А-Яё][а-яё]+', text):
                    news_item = {
                        'type': 0,
                        'size': 3,
                        'text': text
                    }
                    if debug:
                        news_item['short_el_name'] = item['short_el_name']
                        news_item['short_parents_el_name'] = item['short_parents_el_name']
                    doc['raw_items'].append(news_item)
                    continue
                else:
                    news_item = {
                        'type': 1,
                        'text': text
                    }
                    if debug:
                        news_item['short_el_name'] = item['short_el_name']
                        news_item['short_parents_el_name'] = item['short_parents_el_name']
                    doc['raw_items'].append(news_item)
            else:
                if item['tag'] == 'blockquote':
                    news_item = {
                        'type': 3,
                        'text': text
                    }
                    if debug:
                        news_item['short_el_name'] = item['short_el_name']
                        news_item['short_parents_el_name'] = item['short_parents_el_name']
                    doc['raw_items'].append(news_item)
                    continue
                if text[:1] == '«' or text[:1] == '"' or text[:1] == '“':
                    if text[:1] == '«':
                        text_item = re.findall('«(.+?)»', text)
                    elif text[:1] == '"':
                        text_item = re.findall('"(.+?)"', text)
                    else:
                        text_item = re.findall('“(.+?)“', text)
                    if len(text_item) > 1:
                        news_item = {
                            'type': 1,
                            'text': text
                        }
                        if debug:
                            news_item['short_el_name'] = item['short_el_name']
                            news_item['short_parents_el_name'] = item['short_parents_el_name']
                        doc['raw_items'].append(news_item)
                        continue
                    else:
                        if text_item:
                            if len(text_item[0]) < 45:
                                news_item = {
                                    'type': 1,
                                    'text': text
                                }
                                if debug:
                                    news_item['short_el_name'] = item['short_el_name']
                                    news_item['short_parents_el_name'] = item['short_parents_el_name']
                                doc['raw_items'].append(news_item)
                                continue
                    if len(re.findall('(?:"|«|“|»)', text)) % 2 > 0:
                        news_item = {
                            'type': 1,
                            'text': text
                        }
                        if debug:
                            news_item['short_el_name'] = item['short_el_name']
                            news_item['short_parents_el_name'] = item['short_parents_el_name']
                        doc['raw_items'].append(news_item)
                        continue
                    news_item = {
                        'type': 3,
                        'text': text
                    }
                    if debug:
                        news_item['short_el_name'] = item['short_el_name']
                        news_item['short_parents_el_name'] = item['short_parents_el_name']
                    doc['raw_items'].append(news_item)
                else:
                    news_item = {
                        'type': 1,
                        'text': text
                    }
                    if debug:
                        news_item['short_el_name'] = item['short_el_name']
                        news_item['short_parents_el_name'] = item['short_parents_el_name']
                    doc['raw_items'].append(news_item)
    if not all_img:
        doc['imgF'] = False
    doc['published_date'] = check_time(doc['published_date'])
    try:
        if doc['raw_items'][-1]['type'] == 0:
            del doc['raw_items'][-1]['size']
            doc['raw_items'][-1]['type'] = 1
    except:
        pass
    doc['raw_items'].append({
        "type": 4,
        "url": link,
        'title': 'Источник'
    })
    try:
        if doc["rss_data"]["add_block"]:
            doc['raw_items'].append({
                'type': 0,
                'size': 3,
                'text': "Читайте в источнике"
            })
            for add in doc["rss_data"]["add_block"]:
                doc['raw_items'].extend(add)
    except:
        pass
    if not doc['imgF'] and not doc['videoF']:
        doc['done'] = True
        doc['items'] = doc['raw_items']
    return doc


def clean(item):
    if not item:
        return item
    if type(item) is list:
        string = []
        for i in item:
            if type(i) is str:
                string.append(re.sub('\\xad|\\xa0|\u200f|\u202f|&[a-zA-Z]+;| {2,}', ' ', re.sub(r'&ldquo;', '"', re.sub(
                    '(?:\]\]>|\u200b|\ufeff|\u2063|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\"|\\n|\\t)+', '', i))).strip())
        return string
    return re.sub('\\xad|\\xa0|\u200f|\u202f|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub(
        '(?:\]\]>|\u200b|\ufeff|\u2063|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\n|\\t)+', '', item))).strip()


def soup_clean(text):
    resub = re.sub('[^a-zA-Z0-9а-яА-Я]', '', clean(text))
    return resub if resub else 'lol&|&|&'


def soup_sample1(tag):
    return re.findall('(?:p|li|h[0-9]|ul|img)', tag.name) and len(tag.name) <= 3


def soup_sample2(tag):
    return re.fullmatch('(?:p|li|h[0-9]|ul|img|blockquote|iframe|a|pre|span|source)', tag.name)


def divide_into_items_by_br_tags(item):
    items = [clean(i) for i in item.split('<br/>') if len(re.findall('[а-яА-Я]', i)) > 1]
    return items


def divide_into_items_by_br_tags_div(item):
    items = [clean(i) for i in re.split('(?:<br/>|<blockquote/*>|<p/*>)', item) if len(re.findall('[а-яА-Я]', i)) > 1]
    return items


def clear_dubl_content(items):
    a_text: list[str] = []
    pop_index = []
    for index in range(0, len(items)):
        if index >= len(items):
            break
        if items[index]['tag'] == 'a':
            a_text.append(soup_clean(items[index]['text']))
            continue
        if items[index - 1]['tag'] == 'span' or items[index]['tag'] == 'span' \
                or items[index - 1]['tag'] == 'img' or items[index]['tag'] == 'img' \
                or items[index - 1]['tag'] == 'iframe' or items[index]['tag'] == 'iframe' \
                or items[index - 1]['tag'] == 'a':
            continue
        if index:
            if items[index - 1]['text'] and items[index]['text']:
                if soup_clean(items[index - 1]['text']).startswith(soup_clean(items[index]['text'])):
                    pop_index.append(index - 1)

    for index in range(0, len(items)):
        if index >= len(items):
            break
        if items[index]['tag'] == 'img' \
                or items[index]['tag'] == 'iframe' \
                or items[index]['tag'] == 'span' \
                or items[index]['tag'] == 'h3' \
                or items[index]['tag'] == 'a':
            continue
        if soup_clean(items[index]['text']) in a_text:
            pop_index.append(index)
    pop_index.sort(reverse=True)
    for index in pop_index:
        items.pop(index)

    return items


class NewsParser:
    async def parse_news_pid50(self, newdata, session):
        newdata['parsed_date'] = int(datetime.datetime.now().timestamp())
        newdata['raw_items'] = []
        newdata, html_data = await self.parse_pid54(newdata, session)
        if not newdata or not html_data:
            return None
        newdata = create_items_pid50(newdata, html_data)
        if len(newdata['raw_items']) < 2 and not newdata['description']:
            return None
        return newdata

    async def parse_pid54(self, newdata, session):
        ua = UserAgent()
        headers = {'User-Agent': ua.chrome}
        timeout = aiohttp.ClientTimeout(total=600)
        videoF = False
        async with session.get(newdata['link'], headers=headers, timeout=timeout, ssl=False) as response:
            try:
                response = await response.text()
                soup = BeautifulSoup(response, 'lxml', multi_valued_attributes=None)
            except:
                soup = BeautifulSoup(await response.read(), 'lxml', multi_valued_attributes=None)
            news_elements = newdata['news_elements']
            only_content_elements = [news_element for news_element in news_elements if
                                     get_bul(news_element, 'only_content')]
            all_news_element = [BeautifulSoup(str(element), 'lxml', multi_valued_attributes=None) for element in
                                soup.find_all(lambda element: compare_el_with_attrs(news_elements, element))]
            if not all_news_element:
                return newdata, None
            items: list[dict] = []
            all_img: list[str] = []
            all_video: list[str] = []
            all_blockquote: list[str] = []
            html_data = {}
            breaker = False
            for title_class in all_news_element:
                if breaker:
                    break
                try:
                    only_contentF = True if del_none([compare_el_with_attrs(only_content_elements, el) for el in
                                                      title_class.find('body').find_all(recursive=False)]) else False
                except:
                    only_contentF = False
                debug = newdata['debug']
                split_br_tags = newdata['split_br_tags']
                breaker_el_list = newdata['breaker_items']['breaker_el_list']
                breaker_re_strings = newdata['breaker_items']['breaker_re_strings']
                trash_elements = del_none(
                    [item if not compare_el_with_attrs(newdata['news_elements'], item) else None for item in
                     newdata['trash_items']['trash_elements']])
                div_white_list = newdata['div_white_list'] if newdata['div_white_list'] else []
                get_all_iframe = newdata['get_all_iframe'] if "get_all_iframe" in newdata else False
                if only_contentF:
                    for trash_el in trash_elements:
                        for el in title_class.find_all(trash_el['name'], attrs=trash_el['attrs']):
                            el.extract()
                for item in [
                    {'elements': collect_br_tags(previous_el=item.previous, next_el=item.next), 'tag': 'br',
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if item.name == "br" else  # br tags
                    {'tg_post_link': f"https://t.me/{item['data-telegram-post']}",
                     'tg_post_text': f"См. пост в telegram от {re.sub('/.+', '', item['data-telegram-post'])}",
                     'tag': 'tg_post', "short_el_name": get_short_el_name(item),
                     "short_parents_el_name": get_short_el_name(item,
                                                                get_parents=True) if debug else None} if "src" in item.attrs and re.fullmatch(
                        "https://telegram\.org/js/telegram-widget\.js\?[0-9]*",
                        item.attrs["src"]) else  # telegram posts
                    {'elements': divide_into_items_by_br_tags_div(str(item)), 'tag': 'only_content',
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if only_contentF else  # only_content elements
                    {'elements': divide_into_items_by_br_tags_div(str(item)), 'tag': 'break_list_el',
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if item.name in [
                        'div', 'article'] and compare_el_with_attrs(breaker_el_list, item,
                                                                    find_parents=True) else  # div break_list elements
                    {'elements': divide_into_items_by_br_tags_div(str(item)), 'tag': 'white_list_el',
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if compare_el_with_attrs(
                        div_white_list, item) else  # white_list elements
                    {'elements': divide_into_items_by_br_tags_div(str(item)), 'tag': 'childless_div',
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if item.name in [
                        'div'] and not del_none([child.name for child in item.find_all() if
                                                 not re.fullmatch('(?:a|span|em|b|i|s|br|small|mark|strong)',
                                                                  child.name)]) and not item.attrs else  # div childless elements
                    {'video': [value if re.findall('(?:\.mp4|\.youtube|vk\.com|video)', str(value)) else None for
                               key, value in item.attrs.items()], 'special_attrs': [item.get('src')], 'tag': 'iframe',
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if item.name == 'iframe' or item.name == 'source' else  # video
                    {'elements': [item.get_text('|', strip=True)], 'tag': item.name,
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if item.name == 'blockquote' else  # blockquote elements
                    {'img': [value if re.findall('(?:\.jpg|\.jpeg|\.jepeg|\.webp|\.png)', str(value)) else None for
                             key, value in item.attrs.items()],
                     'special_attrs': del_none([get_values(item.attrs, 'data-srcset'), get_values(item.attrs, 'src')]),
                     'tag': item.name, 'attrs': item.attrs, 'parents_noscript': del_none(item.find_parents('noscript')),
                     "short_el_name": get_short_el_name(item), "short_parents_el_name": get_short_el_name(item,
                                                                                                          get_parents=True) if debug else None} if item.name == 'img' else  # img
                    {'elements': [clean(item.get_text(' ', strip=True))], 'tag': item.name, 'attrs': item.attrs,
                     "short_el_name": get_short_el_name(item),
                     "short_parents_el_name": get_short_el_name(item, get_parents=True) if debug else None} if str(
                        item).find('<br/>') == -1 or not split_br_tags else {
                        'elements': divide_into_items_by_br_tags(str(item)), 'tag': item.name,
                        "short_el_name": get_short_el_name(item),
                        "short_parents_el_name": get_short_el_name(item, get_parents=True) if debug else None}
                    # rest text items
                    for item in title_class.find_all(lambda item: True if re.fullmatch(
                        f'(?:p|li|h[0-9]|ul|img|blockquote|iframe|a|pre|span|source|div|i|article|script{"|br)" if newdata["parser_id"] > 54 else ")"}',
                        item.name) and
                                                                          not compare_el_with_attrs(trash_elements,
                                                                                                    item,
                                                                                                    find_parents=True) or
                                                                          compare_el_with_attrs(div_white_list,
                                                                                                item) else False)] if not only_contentF else [
                    title_class]:
                    if item['tag'] == 'break_list_el':
                        breaker = True
                        break
                    if only_contentF and item['tag'] not in ["white_list_el", "iframe", "img", "only_content"]:
                        continue
                    if item['tag'] == 'iframe':
                        try:
                            video = [
                                {'video':
                                     re.findall('(?:[^ "<>,]+?)(?:\.mp4|\.youtube|vk\.com|video)(?:[^ "<>,]+?)*',
                                                video)[0].strip(),
                                 'tag': item['tag'], "short_el_name": item['short_el_name'],
                                 "short_parents_el_name": item['short_parents_el_name']} for video in item['video']
                                if video and re.findall(
                                    '(?:[^ "<>,]+?)(?:\.mp4|\.youtube|vk\.com|video)(?:[^ "<>,]+?)*', video)]
                        except IndexError:
                            pass
                        if get_all_iframe:
                            if not video:
                                if del_none(item['special_attrs']):
                                    video = [{'video': get_first_el(del_none(item['special_attrs'])).strip(),
                                              'tag': item['tag'],
                                              "short_el_name": item['short_el_name'],
                                              "short_parents_el_name": item['short_parents_el_name']}]
                        if video and video[0]['video'] not in all_video:
                            all_video.append(video[0]['video'])
                            items.append(video[0])
                            newdata['videoF'] = False
                            videoF = True
                            html_data['videoF'] = newdata['videoF']
                        continue
                    if item['tag'] == "tg_post":
                        items.append(
                            {'text': item["tg_post_text"], 'link': item["tg_post_link"], 'tag': item['tag'],
                             "short_el_name": item['short_el_name'],
                             "short_parents_el_name": item['short_parents_el_name']})
                        continue
                    if item['tag'] != 'img':
                        if not item['elements']:
                            continue
                        if item['tag'] in ['div', 'article', 'script']:
                            continue
                        if revise_break_patern_v2(clean(str(item['elements'][0])), breaker_re_strings):
                            breaker = True
                            break
                        if item['tag'] == 'blockquote':
                            for i in item['elements']:
                                all_blockquote.extend([soup_clean(el) for el in i.split('|')])
                                i = re.sub('\|', ' ', i)
                                all_blockquote.append(soup_clean(i))
                                items.append(
                                    {'text': clean(i), 'tag': item['tag'], "short_el_name": item['short_el_name'],
                                     "short_parents_el_name": item['short_parents_el_name']})
                        items.extend([{'text': clean(element), 'tag': item['tag'],
                                       "short_el_name": item['short_el_name'],
                                       "short_parents_el_name": item['short_parents_el_name']} for element in
                                      item['elements'] if
                                      element and soup_clean(element) not in all_blockquote or item[
                                          'tag'] == 'a' and element])
                    else:
                        if item['parents_noscript']:
                            continue
                        if item['special_attrs']:
                            while item['special_attrs']:
                                picture = get_best_img(item['special_attrs'].pop(0))
                                if picture:
                                    picture = picture.strip()
                                    break
                            if picture:
                                img = {'img': picture, 'tag': item['tag'],
                                       "short_el_name": item['short_el_name'],
                                       "short_parents_el_name": item['short_parents_el_name']}
                                if len(str(img[
                                               "img"])) < 2500 and "R0lGODlhAQABAIAAAAAAAP//yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" not in str(
                                    img["img"]):
                                    if re.sub('[-_][0-9]+x[0-9]+', '', picture) not in all_img:
                                        all_img.append(
                                            re.sub('[-_][0-9]+x[0-9]+', '', picture))
                                        items.append(img)
                        continue
            # print(items)
            if len(items) >= 2:
                items = clear_dubl_content(items)
            html_data['video'] = []
            if not videoF:
                video = re.findall('([https:]*//www.youtube.com/embed/.+?)[ ;"]', str(title_class))
                video.extend(re.findall('http.+?mp4', str(title_class)))
                video.extend(re.findall('"([^ "]+?\.mp4).*?"', str(title_class)))
                video.extend(re.findall('(https://vk.com/video_ext.php.+?)["; ]', str(title_class)))
                video.insert(0, soup.find('meta', property='og:video').get('content')) if soup.find('meta',
                                                                                                    property='og:video') else video
                html_data['video'] = video
            if not get_bul(newdata, 'dont_get_header_img'):
                if newdata['site'] not in ['polit-expert.ru', "www.malls.ru", "kaliningradfirst.ru",
                                           "astrakhanfm.ru", "news.1777.ru"]:
                    picture = soup.find('meta', property="og:image").get('content') if soup.find('meta',
                                                                                                 property="og:image") else None
                    if not picture:
                        picture = soup.find('meta', property='og:image').get('src') if soup.find('meta',
                                                                                                 property='og:image') else None
                        if not picture:
                            picture = soup.find('link', rel="image_src").get('href') if soup.find('link',
                                                                                                  rel="image_src") else None
                            if not picture:
                                picture = soup.find('meta', property="og:image:secure_url").get(
                                    'content') if soup.find('meta', property="og:image:secure_url") else None
                    if picture and picture.find('логотип') == -1 and picture.find('logo') == -1 and picture.find(
                            'Logo') == -1:
                        all_img.insert(0, picture)
            if newdata['parser_id'] >= 55:
                pubdate = int(dateparser.parse(
                    soup.find('meta', property="article:published_time").get('content')).timestamp()) if soup.find(
                    'meta', property="article:published_time") else \
                    int(dateparser.parse(
                        soup.find('meta', itemprop="datePublished").get('content')).timestamp()) if soup.find('meta',
                                                                                                              itemprop="datePublished") else \
                        int(dateparser.parse(soup.find('meta', attrs={"name": "mediator_published_time"}).get(
                            'content')).timestamp()) if soup.find('meta',
                                                                  attrs={"name": "mediator_published_time"}) else None
                if pubdate:
                    newdata['published_date'] = pubdate
            html_data['content'] = items
            newdata['videoF'] = True if html_data['video'] else False
            html_data['videoF'] = newdata['videoF']
            newdata['img'] = all_img if all_img else None
            newdata['imgF'] = True if all_img else False
            html_data['img'] = newdata['img']
            return newdata, html_data
