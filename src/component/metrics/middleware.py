from typing import Any, Awaitable, Callable, Dict, Sequence

from aioprometheus import REGISTRY, Counter, Registry, MetricsMiddleware
from aioprometheus.mypy_types import LabelsType

# From aioprometheus MetricsMiddleware
Scope = Dict[str, Any]
Message = Dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGICallable = Callable[[Scope, Receive, Send], Awaitable[None]]

EXCLUDE_PATHS = (
    "/metrics",
    "/metrics/",
    "/docs",
    "/openapi.json",
    "/docs/oauth2-redirect",
    "/redoc",
    "/favicon.ico",
    "/inc_successfully"
)


# end

class CustomMetricsMiddleware(MetricsMiddleware):
    """класс для того чтобы переназвать метрики по умолчанию переопределить функцию create_metrics"""

    def __init__(self, app: ASGICallable,
                 registry: Registry = REGISTRY,
                 exclude_paths: Sequence[str] = EXCLUDE_PATHS,
                 use_template_urls: bool = True,
                 group_status_codes: bool = False,
                 const_labels: LabelsType = None, ) -> None:
        super().__init__(app, registry, exclude_paths, use_template_urls, group_status_codes, const_labels)
        self.status_codes_counter = None
        self.exceptions_counter = None
        self.responses_counter = None
        self.requests_counter = None

    def create_metrics(self):
        """Create middleware metrics"""

        self.requests_counter = (  # pylint: disable=attribute-defined-outside-init
            Counter(
                "newsparser_requests_total_counter",
                "Total number of requests received",
                const_labels=self.const_labels,
                registry=self.registry,
            )
        )

        self.responses_counter = (  # pylint: disable=attribute-defined-outside-init
            Counter(
                "newsparser_responses_total_counter",
                "Total number of responses sent",
                const_labels=self.const_labels,
                registry=self.registry,
            )
        )

        self.exceptions_counter = (  # pylint: disable=attribute-defined-outside-init
            Counter(
                "newsparser_exceptions_total_counter",
                "Total number of requested which generated an exception",
                const_labels=self.const_labels,
                registry=self.registry,
            )
        )

        self.status_codes_counter = (  # pylint: disable=attribute-defined-outside-init
            Counter(
                "newsparser_status_codes_counter",
                "Total number of response status codes",
                const_labels=self.const_labels,
                registry=self.registry,
            )
        )

        self.metrics_created = True
