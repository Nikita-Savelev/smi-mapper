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

def get_connection_options(connection_mode, response_type=ProxyConnector):
    ua = UserAgent()
    headers = {'User-Agent': ua.chrome}
    if connection_mode == "default":
        connector = None
    elif connection_mode == "tor":
        url = f"""socks5://{f'{str(random.randint(10000, 2147483647))}:passwrd'}@127.0.0.1:9050"""
        if response_type == ProxyConnector:
            connector = ProxyConnector.from_url(url)
        elif response_type == str:
            connector = url
    else:
        url = f'http://{connection_mode}'
        if response_type == ProxyConnector:
            connector = ProxyConnector.from_url(url)
        elif response_type == str:
            connector = url
    return connector, headers


def get_exception():
    exc_type, exc_obj, tb = sys.exc_info()
    f = tb.tb_frame
    lineno = tb.tb_lineno
    filename = f.f_code.co_filename
    linecache.checkcache(filename)
    line = linecache.getline(filename, lineno, f.f_globals)
    return 'EXCEPTION IN ({}, LINE {} "{}"): {}'.format(filename, lineno, line.strip(), exc_obj)


def get_first_el(some_list):
    return some_list[0] if len(some_list) >= 1 else None


def del_none(some_list):
    return [item for item in some_list if item]


def clean(item):
    if type(item) is list:
        string = []
        for i in item:
            string.append(re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\"|\\n|\\t)+', '', i))).strip())
        return string
    return re.sub('\\xa0|&[a-zA-Z]+;', ' ', re.sub(r'&ldquo;', '"', re.sub('(?:\]\]>|\u200b|<!\[CDATA\[|\\r|<.+?>|&#[0-9]+;|\\n|\\t)+', '', item))).strip()


def soup_clean(text):
    return re.sub('[^a-zA-Z0-9а-яА-Я]', '', clean(text))