from aioprometheus import Gauge, Counter

all_successfully_maps = Counter('count_successfully_map_assembly', 'Number of successfully created maps')
health_checker = Gauge("mapper_healthcheck", "HealthChecker")
events_counter_metrics = Gauge("newsparser_events", "Number of events [LAST 24 HOURS].")