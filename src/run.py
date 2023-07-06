import asyncio
import os
import aiohttp
from aiohttp_socks import ProxyConnector
from aiohttp import client_exceptions
from asyncio import exceptions
from alive_progress import alive_bar
from component.news_collector.news_collector_class import NewsCollector
from component.arangoconnector.connector import ArangoConnector
from multiprocessing import Pool
from multiprocessing import shared_memory
import time
import random

RSS_PATHS = ['feed', 'rss']

HEADERS = {
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Saf'
}
bar = None


async def buf_proceses(cpu_id, shm_name):
    while True:
        shm = shared_memory.SharedMemory(shm_name)
        if shm.buf[0] == 0 or shm.buf[0] == cpu_id:
            shm.buf[0] = cpu_id
            time.sleep(random.random())
            if shm.buf[0] == cpu_id:
                np = NewsCollector()
                await np.get_news_channels()
                shm.buf[0] = 0
                return np
        time.sleep(random.random() * 2)


async def start_collector(cpu_id, shm_name, shm_alive_bar_name):
    async def collect(np, channel, shm_alive_bar_name):
        # connector = ProxyConnector.from_url('socks5://127.0.0.1:9050')
        connector = ProxyConnector.from_url('http://T5WZFf:MZKsVh@5.101.84.150:8000')
        async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as s:
            if "rss_link" in channel:
                for rss_link in channel['rss_link']:
                    channel, report = await np.collect_news_pid50(channel, rss_link, s, shm_alive_bar_name,
                                                                  find_colect_element=False)
                    if report:
                        np.arango.update_chanel(channel, report)
                        break
            else:
                channel, report = await np.collect_news_pid50(channel, None, s, shm_alive_bar_name,
                                                              find_colect_element=True)
                np.arango.update_chanel(channel, report)

    async def collect_news_with_rss(np, channel, shm_alive_bar_name):
        async with np.semaphore:
            task = asyncio.create_task(collect(np, channel, shm_alive_bar_name))
            try:
                await asyncio.wait_for(task, timeout=1000)
            except (client_exceptions.ClientConnectorError, client_exceptions.ServerDisconnectedError,
                    client_exceptions.ClientOSError, exceptions.TimeoutError) as ex:
                np.logger.exception(ex)
                np.logger.warning(f'Collecting news from {channel["url"]} [CONNECT ERROR]')
                report = {"collector": None, "parser": None, "failed_log": f"CONNECT ERROR: ({ex})"}
                np.arango.update_chanel(channel, report)
            except Exception as ex:
                if shm_alive_bar_name:
                    np.up_buf()
                np.logger.exception(ex)
                np.logger.warning(f'Collecting news from {channel["url"]} [FAILED BY TIMEOUT]')
                report = {"collector": None, "parser": None, "failed_log": f"FAILED BY TIMEOUT: ({ex})"}
                np.arango.update_chanel(channel, report)

    time.sleep(cpu_id)
    while True:
        np = await buf_proceses(cpu_id, shm_name)
        if not np.channels:
            break
        coros = []
        for i in range(len(np.channels)):
            coros.append(collect_news_with_rss(np, np.channels[i], shm_alive_bar_name))
        await asyncio.gather(*coros)
        await asyncio.sleep(2)


def alive_bar_process(shm_alive_bar_name):
    np = ArangoConnector()
    with alive_bar(total=np.count_channels[0], title='MAP ASSEMBLY process', theme='smooth') as bar:
        while True:
            time.sleep(random.random() * 2)
            shm_b = shared_memory.SharedMemory(shm_alive_bar_name)
            if shm_b.buf[0]:
                for _ in range(shm_b.buf[0]):
                    bar()
                shm_b.buf[0] = 0


def run(arrs):
    process_id, shm_name, shm_alive_bar_name = arrs
    if shm_alive_bar_name:
        if (os.cpu_count() - 2) > 1:
            if process_id == 1:
                alive_bar_process(shm_alive_bar_name)
    asyncio.run(start_collector(process_id, shm_name, shm_alive_bar_name))


def run_pool():
    shm = shared_memory.SharedMemory(create=True, size=1)
    buffer = shm.buf
    buffer[0] = 0
    shm_alive_bar = shared_memory.SharedMemory(create=True, size=1)
    buffer_alive_bar = shm_alive_bar.buf
    buffer_alive_bar[0] = 0
    # proceses = os.cpu_count() - 1
    proceses = 1
    alive_bar_name = None  # shm_alive_bar.name
    np = ArangoConnector()
    print(f"All channels = {np.count_channels[0]}")
    with Pool(proceses) as pool:
        pool.map(run, [(cpu_id, shm.name, alive_bar_name) for cpu_id in range(1, proceses + 1)])


if __name__ == "__main__":
    run_pool()
