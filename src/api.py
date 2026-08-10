import os
import sys
from loguru import logger
from fastapi import APIRouter, Response, Request, Header
from fastapi import FastAPI
sys.path.append(os.path.dirname(os.path.realpath(os.path.abspath(''))))
from aioprometheus.asgi.starlette import metrics
from component.arangoconnector.connector import ArangoConnector
from component.metrics.middleware import CustomMetricsMiddleware
import component.metrics
import socket
import asyncio

app = FastAPI()

router = APIRouter(prefix="/api/health", tags=["/api/health"])


async def is_connected_network():
    try:
        host = socket.gethostbyname("www.google.com")
        await asyncio.sleep(0.1)
        s = socket.create_connection((host, 80), 2)
        await asyncio.sleep(0.1)
        return True
    except Exception as ex:
        logger.exception(ex)
    return False


async def is_connected_arango():
    try:
        # проверка доступности
        arangodb = ArangoConnector()
        await asyncio.sleep(0.1)
        ret = arangodb.liveness()
        await asyncio.sleep(0.1)
    except Exception as ex:
        logger.exception(ex)
        return False

    if not ret:
        logger.error('No answer from arango')
        return False

    return True

async def is_connected():
    network = await is_connected_network()
    arangodb = await is_connected_arango()
    if network and arangodb:
        logger.info('NETWORK IS TRUE')
        return True
    logger.error('NETWORK IS FALSE')
    return False


@router.get("/live")
async def liveness_probe():
    return "Healthy"


@router.get("/readiness")
async def readiness_probe(response: Response):
    try:
        # проверка доступности
        arangodb = ArangoConnector(config_ini='config/config.ini')
        ret = arangodb.liveness()
    except Exception as ex:
        logger.exception(ex)
        response.status_code = 503
        return "ArangoUnhealthy"

    if not ret:
        logger.error('No answer from arango')
        response.status_code = 503
        return "ArangoUnhealthy"

    if await is_connected_network():
        return "Healthy"
    else:
        return "NetworkUnhealthy"

@router.get("/inc_successfully")
async def inc_successfully(request: Request):
    # метрики пока не собираем; endpoint оставлен no-op для старых клиентов
    return True


app.add_middleware(CustomMetricsMiddleware)
app.add_route("/metrics", metrics)
app.include_router(router)