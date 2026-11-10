"""openterm-sdk: read-only pandas access to a locally running OpenTerm. No orders, no writes, no keys."""

from .client import BacktestRun, OpenTerm
from .errors import (
    BackendDown,
    BadRequest,
    KeyRequired,
    LoginRequired,
    NoData,
    OpenTermError,
    ProviderDown,
    StaleData,
)

__all__ = [
    "BackendDown",
    "BacktestRun",
    "BadRequest",
    "KeyRequired",
    "LoginRequired",
    "NoData",
    "OpenTerm",
    "OpenTermError",
    "ProviderDown",
    "StaleData",
]
__version__ = "0.1.0"
