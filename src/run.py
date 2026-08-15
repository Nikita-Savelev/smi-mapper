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

from configparser import ConfigParser
import sentry_sdk
from sentry_sdk import capture_message, capture_exception
import os
from dotenv import load_dotenv


load_dotenv()


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes")


DEBUG_MODE = _env_flag("DEBUG")

if not DEBUG_MODE:
    config = ConfigParser()
    config.read("src/config/config.ini")
    dsn = config["Sentry"]['dsn']
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=1.0,
        environment=os.getenv('ENVIRONMENT'),
    )

RSS_PATHS = ['feed', 'rss']

HEADERS = {
    'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Saf'
}
bar = None

def _is_connect_error(exc: BaseException, ex_traceback: str) -> bool:
    """Только реальные сетевые сбои — не маскировать логику/ML под CONNECT."""
    connect_types = (ConnectionError, TimeoutError, OSError)
    if isinstance(exc, connect_types):
        return True
    markers = (
        "Max retries exceeded",
        "ConnectionResetError",
        "Connection aborted",
        "ConnectTimeout",
        "Read timed out",
        "NameResolutionError",
        "ServerDisconnectedError",
        "ClientConnectorError",
        "ProxyConnectionError",
        "Failed to establish a new connection",
        "getaddrinfo failed",
    )
    return any(m in ex_traceback for m in markers)


def get_report(channel):
    # ++++++ status code ++++++
    # 1 - SUCCESSFULLY
    # 2 - FAILED (не получилось найти целевые элементы коллектора)
    # 3 - FAILED (не получилось сколлектить целевые элементы)
    # 4 - FAILED (сайт не вернул HTTP-ответ / сеть; не ошибка карты)
    # 5 - FAILED (не получилось найти целевой элемент для парсера)
    # 6 - FAILED (не получилось спарсить новости по целевым элементам)
    # unexpected exceptions → failed_log prefix MAP ASSEMBLY ERROR (status остаётся null, если не выставлен ниже)

    prev = channel.get("report")
    used = []
    if isinstance(prev, dict) and isinstance(prev.get("used_connections"), list):
        used = list(prev["used_connections"])
    report = {
        "rss": True if "rss_link" in channel and channel["rss_link"] else False,
        "collector": None,
        "parser": None,
        "failed_log": None,
        "status": None,
        "used_connections": used,
    }
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
                # Пустая очередь новых (null) → ретрай failed (map_assembly_status=3).
                # Раньше в DEBUG ретрай отключали; для ночных/локальных прогонов снова включён.
                if not channels:
                    channels = arango_conn.get_news_channels(failed_channels=True)
                    if channels:
                        logger.info(
                            f"[map_feed] step=queue retry_failed n={len(channels)} "
                            f"debug={int(DEBUG_MODE)}"
                        )
                proxy_pool = arango_conn.get_proxy_pool()
                shm.buf[0] = 0
                return channels, proxy_pool, arango_conn
        time.sleep(random.random() * 2)

def get_connection_mode(channel, proxy_pool):
    report = channel.get("report")
    if not isinstance(report, dict):
        return channel.get("connection_mode") or "default"
    report_connection = report.get("used_connections") or []
    if "connection_mode" in channel and channel["connection_mode"] not in report_connection:
        return channel["connection_mode"]
    try:
        proxy_pool_filter = set(proxy_pool).difference(set(report_connection))
    except Exception:
        report["used_connections"] = []
        channel["report"] = report
        proxy_pool_filter = proxy_pool
    return list(proxy_pool_filter)[0] if proxy_pool_filter else "default"

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
            t0 = time.perf_counter()
            try:
                channel, report, items_data = await create_map_for_collector(channel, collector_mapper, report)
                if items_data:
                    channel, report = await create_map_for_parser(channel, report, items_data, parser_mapper)
            except Exception as exc:
                import traceback
                ex_traceback = utils.get_exception()
                logger.warning(
                    f'Failed map assembly from {channel["url"]} ex_traceback = ({ex_traceback})'
                )
                logger.warning(
                    f'[map_feed] url={channel["url"]} step=exception_tb\n'
                    f'{traceback.format_exc()}'
                )
                report = channel.get("report") if isinstance(channel.get("report"), dict) else report
                if _is_connect_error(exc, ex_traceback):
                    report["failed_log"] = f"CONNECT ERROR: ({ex_traceback})"
                    if report.get("status") is None:
                        report["status"] = 4
                else:
                    report["failed_log"] = f"MAP ASSEMBLY ERROR: ({ex_traceback})"
                channel["report"] = report
            finally:
                duration_s = time.perf_counter() - t0
                report = channel.get("report") if isinstance(channel.get("report"), dict) else report
                logger.info(
                    f'[map_feed] url={channel["url"]} step=done '
                    f'status={report.get("status") if report else None} '
                    f'failed={report.get("failed_log") if report else None} '
                    f'rss={report.get("rss") if report else None} '
                    f'duration_s={duration_s:.1f}'
                )
                try:
                    arango_conn.update_chanel(channel, report)
                except Exception as ex:
                    # страховка: любая ошибка записи не должна ронять Pool-воркер
                    logger.warning(
                        f'[map_feed] url={channel["url"]} step=arango_update_failed '
                        f'{type(ex).__name__}: {ex}'
                    )
        await asyncio.sleep(2)

def run(arrs):
    process_id, shm_name = arrs
    try:
        asyncio.run(main(process_id, shm_name))
    except Exception as ex:
        # не отдаём сырой ArangoServerError в Pool (pickle ломает _handle_results)
        logger.error(f'Worker {process_id} crashed: {type(ex).__name__}: {ex}')


def _read_mapper_config() -> ConfigParser:
    config = ConfigParser()
    config.read("src/config/config.ini")
    return config


def api_startup(api_workers: int = 2):
    uvicorn.main.logger = logger
    uvicorn.server.logger = logger
    try:
        PORT = int(os.getenv("PORT"))
    except:
        PORT = 5035
    api_workers = max(1, api_workers)
    gunicorn_bin = os.path.join(os.path.dirname(sys.executable), "gunicorn")
    if not os.path.isfile(gunicorn_bin):
        gunicorn_bin = "gunicorn"
    logger.info(f"Web application attempt start on {PORT} port (gunicorn workers={api_workers})")
    cmd = f"""cd src/; "{gunicorn_bin}" --workers={api_workers} -k uvicorn.workers.UvicornWorker --bind "0.0.0.0:{PORT}" api:app"""
    subprocess.Popen(cmd, shell=True)
    return True


def resolve_pool_size(config: ConfigParser) -> int:
    """Число multiprocessing-воркеров.

    Приоритет: env MAPPER_WORKERS → config [Workers] workers → auto (cpu_count - 2).
    Локально в config.ini обычно workers = 1.
    """
    raw = os.getenv("MAPPER_WORKERS")
    if not raw and config.has_option("Workers", "workers"):
        raw = config.get("Workers", "workers").strip()
    if raw and raw.lower() != "auto":
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning(f"Invalid workers={raw!r}, fallback to auto")
    return max(1, (os.cpu_count() or 2) - 2)


def resolve_api_workers(config: ConfigParser) -> int:
    """Число gunicorn workers. Приоритет: env MAPPER_API_WORKERS → config → 2."""
    raw = os.getenv("MAPPER_API_WORKERS")
    if not raw and config.has_option("Workers", "api_workers"):
        raw = config.get("Workers", "api_workers").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning(f"Invalid api_workers={raw!r}, fallback to 2")
    return 2


if __name__ == "__main__":
    shm = shared_memory.SharedMemory(create=True, size=1)
    buffer = shm.buf
    buffer[0] = 0
    config = _read_mapper_config()
    proceses = resolve_pool_size(config)
    api_workers = resolve_api_workers(config)
    logger.info(
        f"Starting mapper pool with {proceses} worker(s), api_workers={api_workers} "
        f"debug={int(DEBUG_MODE)}"
    )
    np = ArangoConnector()
    api_startup(api_workers=api_workers)
    # 1 воркер: без Pool — иначе ArangoServerError при unpickle роняет _handle_results и прогон зависает
    if proceses <= 1:
        run((1, shm.name))
    else:
        with Pool(proceses) as pool:
            pool.map(run, [(cpu_id, shm.name) for cpu_id in range(1, proceses + 1)])
