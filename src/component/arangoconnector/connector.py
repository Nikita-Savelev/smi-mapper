import time as tm
from arango import ArangoClient
from configparser import ConfigParser


def get_plug():
    return {
        "active": True,
        "feed_id": None,
        "user_id": None,
        "url": None,
        "main": False,
        "debug": True,
        "div_white_list": [],
        "split_br_tags": True,
        "dont_get_header_img": False,
        "link_pattern": None,
        "parser_id": 55,
        "breaker_items": {
            "breaker_el_list": [],
            "breaker_re_strings": []
        },
        "trash_items": {
            "trash_elements": [
                {
                    "name": "div",
                    "attrs": {
                        "class": "some-element"
                    }
                },
            ],
            "trash_links": [
            ],
            "trash_text_items": []
        },
        "rss_links": [],
        "collector_id": 55,
        "get_all_iframe": False,
        "collect_elements": [
            {
                "name": "li",
                "attrs": {
                    "class": "relationships-news__item"
                },
                "next": False
            },
        ],
        "news_elements": [
            {
                "attrs": {
                    "class": "post-content",
                    "itemprop": "articleBody"
                },
                "name": "div",
                "only_content": False,
                "is_description_element": False,
                "is_header_img_element": False,
                "parent": None
            }
        ],
        "collect_url": "https://news.nashbryansk.ru"
    }

class ArangoConnector:
    def __init__(self, config_ini: str = 'src/config/config.ini', service_type='Arango'):

        self.config = ConfigParser()
        self.config.read(config_ini)
        self.service_type = service_type

        self.hostname = self.config[self.service_type]['arangoURL']
        self.db = self.config[self.service_type]['db_name']
        self.login = self.config[self.service_type]['username']
        self.password = self.config[self.service_type]['password']
        self.collection_channels_name = self.config[self.service_type]['collection_channels_name']
        self.collection_proxy_name = self.config[self.service_type]['collection_proxy_name']
        self.client = None
        self.aql = None
        self.collection_channels = None
        self.count_channels = None
        self.connect()

    def connect(self):
        self.client = ArangoClient(hosts=self.hostname)
        self.db = self.client.db(self.db, username=self.login, password=self.password)
        self.aql = self.db.aql
        self.collection_channels = self.db.collection(self.collection_channels_name)
        self.count_channels = self.get_count_channels()

    def aql_execute(self, aql_string: str, bind_vars=None):
        self.aql.validate(aql_string)
        cursor = self.aql.execute(aql_string, bind_vars=bind_vars)
        ret = [doc for doc in cursor]
        return ret

    def get_proxy_pool(self):
        return [doc["proxy"] for doc in self.aql_execute(f"FOR doc IN {self.collection_proxy_name} return doc")]

    def update_chanel(self, channel, report):
        if 'status' not in report or report["status"] != 1:
            channel["status"] = 3
            plug = get_plug()
            # if "trash_items" not in channel:
            #     channel["trash_items"] = plug['trash_items']
            # if "collect_elements" not in channel:
            #     channel["collect_elements"] = plug['collect_elements']
            # if "news_elements" not in channel:
            #     channel["news_elements"] = plug['news_elements']
        else:
            channel["status"] = 1
        channel["report"] = report
        self.collection_channels.update(channel)

    def get_count_channels(self):
        ret = self.aql_execute(f'FOR doc IN {self.collection_channels_name} '
                               f'FILTER doc.active '
                               f'AND doc.status == null '
                               f'AND doc.trash_items == null '
                               f'COLLECT WITH count INTO _lengh '
                               f'RETURN _lengh')
        return ret

    def get_news_channels(self, failed_channels=False):
        ret = self.aql_execute(f'LET arr = ((FOR doc IN {self.collection_channels_name} '
                               f'FILTER doc.active '
                               f'AND doc.status == {"null" if not failed_channels else 3} '
                               f'{"AND doc.trash_items == null " if not failed_channels else ""}'
                               f'LIMIT 4 '
                               f'RETURN doc)) '
                               f'FOR doc in arr '
                               'UPDATE doc WITH {"status": 2} IN '
                               f'{self.collection_channels_name} '
                               f'RETURN NEW')
        return ret
