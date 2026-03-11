"""Exception hierarchy for the trader platform."""


class TraderError(Exception):
    """Base exception for all trader platform errors."""
    pass


class ConfigError(TraderError):
    """Raised when required configuration is missing or invalid."""
    pass


class APIError(TraderError):
    """Base exception for exchange API errors."""
    pass


class KrakenAPIError(APIError):
    """Raised on Kraken REST API errors."""
    pass


class KrakenAuthError(APIError):
    """Raised on Kraken authentication or signing errors."""
    pass


class OandaAPIError(APIError):
    """Raised on OANDA API errors."""
    pass


class RiskError(TraderError):
    """Raised when a risk limit is breached."""
    pass


class DataError(TraderError):
    """Raised on data loading, storage, or integrity issues."""
    pass
