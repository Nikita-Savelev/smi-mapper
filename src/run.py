import asyncio
import os
import sys
import aiohttp
from aiohttp import client_exceptions
from asyncio import exceptions

from alive_progress import alive_bar
sys.path.append(os.path.dirname(os.path.realpath(os.path.abspath(''))))

from component.news_collector.news_collector_class import NewsCollector
from component.news_parser.news_parser_class import NewsParser
from component.arangoconnector.connector import ArangoConnector

from multiprocessing import Pool
from multiprocessing import shared_memory
import time
import random
from aiohttp_socks import ProxyConnector
from common import utils
from loguru import logger
import uvicorn.server
import api
import subprocess

RSS_PATHS = ['feed', 'rss']

HEADERS = {
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Saf'
}
bar = None

def get_report(channel):
    # ++++++ status code ++++++
    # 1 - SUCCESSFULLY
    # 2 - FAILED (не получилось найти целевые элементы для коллектора *в основном это связанно с ошибками коннекта)
    # 3 - FAILED (не получилось сколлектить целевые элементы)
    # 4 - FAILED (ошибки коннекта к сайту)
    # 5 - FAILED (не получилось найти целевой элемент для парсера)
    # 6 - FAILED (не получилось спарсить новости по целевым элементам)

    report = {"rss": True if "rss_link" in channel and channel["rss_link"] else False, "collector": None,
              "parser": None, "failed_log": None, "status": None,
              "used_connections": [] if "report" not in channel else channel["report"]["used_connections"]
              if "used_connections" in channel["report"] else []}
    report["used_connections"].append(channel["connection_mode"])
    return report

async def buf_proceses(cpu_id, shm_name):
    while True:
        shm = shared_memory.SharedMemory(shm_name)
        if shm.buf[0] == 0 or shm.buf[0] == cpu_id:
            shm.buf[0] = cpu_id
            time.sleep(random.random())
            if shm.buf[0] == cpu_id:
                arango_conn = ArangoConnector()
                channels = arango_conn.get_news_channels()
                if not channels:
                    channels = arango_conn.get_news_channels(failed_channels=True)
                proxy_pool = arango_conn.get_proxy_pool()
                shm.buf[0] = 0
                return channels, proxy_pool, arango_conn
        time.sleep(random.random() * 2)

def get_connection_mode(channel, proxy_pool):
    report_connection = channel["report"]["used_connections"] if "report" in channel and "used_connections" in channel["report"] else []
    if "connection_mode" in channel and channel["connection_mode"] not in report_connection:
        return channel["connection_mode"]
    if not "report" in channel:
        return "default"
    try:
        proxy_pool_filter = set(proxy_pool).difference(set(channel["report"]["used_connections"]))
    except:
        channel["report"]["used_connections"] = []
        proxy_pool_filter = proxy_pool
    return list(proxy_pool_filter)[0] if proxy_pool_filter else "tor"

async def create_map_for_collector(channel, collector_mapper, report):
    channel['parser_id'] = 55
    items_data = None
    if "rss_link" in channel and channel["rss_link"]:
        for rss_link in channel['rss_link']:
            channel, report, items_data = await collector_mapper.start_collector_map_assembly_process(report, channel, rss_link)
            if items_data:
                break
    else:
        try:
            del channel["rss_link"]
        except:
            pass
        channel, report, items_data = await collector_mapper.start_collector_map_assembly_process(report, channel, None)
    return channel, report, items_data

async def create_map_for_parser(channel, report, items_data, parser_mapper):
    if len(items_data) > 51:
        items_data = items_data[:50]
    channel, report = await parser_mapper.start_parser_map_assembly_process(items_data, report, channel)
    return channel, report

async def main(cpu_id, shm_name):
    time.sleep(cpu_id)
    while True:
        logger.info(f'Get channels cpu_id={cpu_id}')
        channels, proxy_pool, arango_conn = await buf_proceses(cpu_id, shm_name)
        collector_mapper = NewsCollector()
        parser_mapper = NewsParser()
        for channel in channels:
            logger.info(f'Start map assembly from {channel["url"]}')
            channel["connection_mode"] = get_connection_mode(channel, proxy_pool)
            report = get_report(channel)
            channel["report"] = report
            try:
                channel, report, items_data = await create_map_for_collector(channel, collector_mapper, report)
                if items_data:
                    channel, report = await create_map_for_parser(channel, report, items_data, parser_mapper)
            except:
                ex_traceback = utils.get_exception()
                logger.warning(f'Failed map assembly from {channel["url"]} ex_traceback = ({ex_traceback})')
                report = {"collector": None, "parser": None, "failed_log": f"CONNECT ERROR: ({ex_traceback})",
                          "used_connections": []} if "report" not in channel else channel["report"]
                report["failed_log"] = f"CONNECT ERROR: ({ex_traceback})"
            finally:
                arango_conn.update_chanel(channel, report)
        await asyncio.sleep(2)

def run(arrs):
    process_id, shm_name = arrs
    asyncio.run(main(process_id, shm_name))


def api_startup():
    uvicorn.main.logger = logger
    uvicorn.server.logger = logger
    try:
        PORT = int(os.getenv("PORT"))
    except:
        PORT = 5035
    logger.info(f"Web application attempt start on {PORT} port")
    cmd = f"""cd src/; gunicorn --workers=2 -k uvicorn.workers.UvicornWorker --bind "0.0.0.0:{PORT}" api:app"""
    subprocess.Popen(cmd, shell=True)
    return True

if __name__ == "__main__":
    shm = shared_memory.SharedMemory(create=True, size=1)
    buffer = shm.buf
    buffer[0] = 0
    proceses = os.cpu_count() - 2
    np = ArangoConnector()
    api_startup()
    with Pool(proceses) as pool:
        pool.map(run, [(cpu_id, shm.name) for cpu_id in range(1, proceses + 1)])