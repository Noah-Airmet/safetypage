"""Search errors. Every message is written to be shown to an agent as the tool error."""

from __future__ import annotations

__all__ = [
    "ArmUnavailableError",
    "FilterError",
    "QuerySyntaxError",
    "SearchBusyError",
    "SearchError",
    "SearchTimeoutError",
]


class SearchError(Exception):
    """Base class: the request could not be answered, and the message says why."""


class QuerySyntaxError(SearchError, ValueError):
    """The query string cannot be read."""


class FilterError(SearchError, ValueError):
    """A filter, document or cursor names something that does not exist or is malformed."""


class ArmUnavailableError(SearchError, LookupError):
    """The requested retrieval arm is not built into this snapshot."""


class SearchBusyError(SearchError):
    """Too many searches are running; try again shortly."""


class SearchTimeoutError(SearchError, TimeoutError):
    """The query took longer than the per-query time limit."""
