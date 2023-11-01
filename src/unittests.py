import unittest
import sys, os

sys.path.append(os.path.dirname(os.path.realpath(os.path.abspath(''))))
from component.news_collector.news_collector_class import NewsCollector
from component.news_parser.news_parser_class import NewsParser
from component.arangoconnector.connector import ArangoConnector
import asyncio

channel = {
        "active": True,
        "url": "iz.ru",
        "feed_id": 677,
        "user_id": 1195,
        "main": False,
        "connection_mode": "default",
        "parser_id": 55
    }

report = {"rss": False, "collector": None,
          "parser": None, "failed_log": None, "status": None,
          "used_connections": []}

async def create_map():
    nc = NewsCollector()
    new_channel, new_report, new_data = await nc.start_collector_map_assembly_process(report, channel, None)
    np = NewsParser()
    return await np.start_parser_map_assembly_process(new_data, new_report, new_channel, unittest=True)



class TestSmiMapper(unittest.TestCase):

    def test_create_map(self):
        self.assertEqual(asyncio.run(create_map()), True)

    def test_arangoconnector(self):
        conn = ArangoConnector()
        self.assertEqual(conn.liveness(), True)



if __name__ == "__main__":
  unittest.main()