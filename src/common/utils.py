import os
import pickle
from aiohttp_socks import ProxyConnector
import random
from fake_useragent import UserAgent
import sys
import linecache
import re

def mkdir(path: str):
    if not os.path.exists(path):
        os.makedirs(path)


def mkdirs(paths: list):
    for p in paths:
        mkdir(p)


def save_pkl(obj, filename):
    with open(filename, 'wb') as outp:
        pickle.dump(obj, outp, pickle.HIGHEST_PROTOCOL)


def load_pkl(filename):
    with open(filename, 'rb') as inp:
        return pickle.load(inp)

# Один UA на процесс: fake_useragent.chrome каждый вызов случайный (часто Android),
# сайты отдают другую вёрстку — карта с одного HTML, items с другого = 0 новостей.
_DESKTOP_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_CACHED_HTTP_HEADERS = None


def _stable_http_headers():
    global _CACHED_HTTP_HEADERS
    if _CACHED_HTTP_HEADERS is not None:
        return dict(_CACHED_HTTP_HEADERS)
    ua_str = None
    try:
        ua = UserAgent()
        for _ in range(8):
            cand = ua.chrome
            if cand and not re.search(r"Android|iPhone|iPad|Mobile", cand, re.I):
                ua_str = cand
                break
    except Exception:
        pass
    _CACHED_HTTP_HEADERS = {"User-Agent": ua_str or _DESKTOP_CHROME_UA}
    return dict(_CACHED_HTTP_HEADERS)


def http_user_agent():
    """UA, которым этот процесс mapper ходит на сайт (один на процесс)."""
    return _stable_http_headers().get("User-Agent")


def get_connection_options(connection_mode, response_type=ProxyConnector):
    headers = _stable_http_headers()
    if connection_mode == "default":
        connector = None
    # TOR отключён: socks5 127.0.0.1:9050 сейчас не работает как надо.
    # elif connection_mode == "tor":
    #     url = f"""socks5://{f'{str(random.randint(10000, 2147483647))}:passwrd'}@127.0.0.1:9050"""
    #     if response_type == ProxyConnector:
    #         connector = ProxyConnector.from_url(url)
    #     elif response_type == str:
    #         connector = url
    elif connection_mode == "tor":
        connector = None
    else:
        url = f'http://{connection_mode}'
        if response_type == ProxyConnector:
            connector = ProxyConnector.from_url(url)
        elif response_type == str:
            connector = url
    return connector, headers


def get_exception():
    """Full chain of frames (innermost last), not only the outer await line."""
    exc_type, exc_obj, tb = sys.exc_info()
    if tb is None:
        return f"EXCEPTION: {exc_obj}"
    frames = []
    cur = tb
    while cur is not None:
        f = cur.tb_frame
        lineno = cur.tb_lineno
        filename = f.f_code.co_filename
        linecache.checkcache(filename)
        line = linecache.getline(filename, lineno, f.f_globals).strip()
        frames.append(f'{filename}:{lineno} "{line}"')
        cur = cur.tb_next
    chain = " <- ".join(frames)
    return f"EXCEPTION IN ({chain}): {exc_obj}"


def get_first_el(some_list):
    return some_list[0] if len(some_list) >= 1 else None


def del_none(some_list):
    return [item for item in some_list if item]


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


def soup_clean(text):
    return re.sub('[^a-zA-Z0-9а-яА-Я]', '', clean(text))