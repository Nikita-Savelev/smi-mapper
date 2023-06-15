from arango import ArangoClient
from configparser import ConfigParser
from loguru import logger


class ArangoConnector:
    def __init__(self, config_ini: str = 'src/config/config.ini', service_type='Arango'):

        self.config = ConfigParser()
        self.config.read(config_ini)
        self.service_type = service_type
        self.logger = logger
        self.hostname = self.config[self.service_type]['arangoURL']
        self.db = self.config[self.service_type]['db_name']
        self.login = self.config[self.service_type]['username']
        self.password = self.config[self.service_type]['password']
        self.collection_channels_name = self.config[self.service_type]['collection_channels_name']
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
        max_try = 0
        ret = None
        while max_try < 5:
            try:
                if not self.client:
                    self.connect()
                self.aql.validate(aql_string)
                cursor = self.aql.execute(aql_string, bind_vars=bind_vars)
                ret = [doc for doc in cursor]
                break
            except Exception as ex:
                self.logger.exception(ex)
                max_try += 1
        return ret

    def update_chanel(self, channel, report):
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

    def get_news_channels(self):
        ret = self.aql_execute(f'LET arr = ((FOR doc IN {self.collection_channels_name} '
                               f'FILTER doc.active '
                               f'AND doc.status == null '
                               f'AND doc.trash_items == null '
                               f'LIMIT 4 '
                               f'RETURN doc)) '
                               f'FOR doc in arr '
                               'UPDATE doc WITH {"status": 2} IN '
                               f'{self.collection_channels_name} '
                               f'RETURN NEW')
        return ret

    def add_channels(self, docs):
        if not docs:
            return
        self.collection_channels.insert_many(docs)
