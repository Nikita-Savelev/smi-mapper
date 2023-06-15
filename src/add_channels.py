import asyncio
import os
import sys
import vaex as vx
from loguru import logger
from component.arangoconnector.connector import ArangoConnector


async def run():
    arango = ArangoConnector()
    conf = vx.open('urls.csv')
    urls = conf.url.values.tolist()
    rss_link = conf.rss.values.tolist()

    docs = []

    for i in range(len(urls)):
        if rss_link[i] == '':
            docs.append({
                'url': urls[i],
                'active': True,
                'feed_id': i,
                'user_id': i,
                'main': False
            })
        else:
            docs.append({
                'url': urls[i],
                'rss_link': [rss_link[i]],
                'active': True,
                'feed_id': i,
                'user_id': i,
                'main': False
            })
        logger.info(docs[-1])

    arango.add_channels(docs)

if __name__ == "__main__":
    asyncio.run(run())
