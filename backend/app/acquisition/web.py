"""The one place acquisition talks to the network.

Every catalogue search, token request and geocoder lookup goes through
:func:`request_json`, so a test replaces this single function and the whole
package runs offline.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app import USER_AGENT


class AcquisitionError(Exception):
    """Imagery could not be acquired.

    ``status`` is the :class:`~app.schemas.acquisition.AcquisitionReport`
    status the failure maps to, so the caller can tell "name a place" from
    "the catalogue is down".
    """

    def __init__(self, message: str, status: str = "failed") -> None:
        super().__init__(message)
        self.status = status


def request_json(
    url: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 60,
) -> Any:
    """GET ``url`` (or POST ``body`` as JSON) and return the decoded response."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    host = urllib.parse.urlsplit(url).netloc
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise AcquisitionError(
            f"{host} answered HTTP {error.code}; try again shortly."
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise AcquisitionError(f"{host} could not be reached ({reason}).") from error
    except ValueError as error:
        raise AcquisitionError(f"{host} returned a response that is not JSON.") from error


__all__ = ["AcquisitionError", "request_json"]
