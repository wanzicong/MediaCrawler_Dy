# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.


class DouyinError(RuntimeError):
    """Base error for Douyin crawling failures."""


class DataFetchError(DouyinError):
    """The Douyin API returned an invalid or rejected response."""


class CDPConnectionError(DouyinError):
    """A CDP browser could not be launched or connected."""


class LoginError(DouyinError):
    """The selected login flow did not complete."""
