from __future__ import annotations

import logging
from typing import Any

import requests

DEFAULT_TRACE_URL = "http://localhost:8000/trace"

logger = logging.getLogger(__name__)


class TraceClientError(Exception):
    """Raised when a trace cannot be sent successfully."""


def send_trace(
    data: dict[str, Any],
    *,
    api_key: str | None = None,
    timeout: float | tuple[float, float] = 10.0,
    url: str = DEFAULT_TRACE_URL,
) -> dict[str, Any]:
    """
    Send trace data to the local trace API.

    Args:
        data: JSON-serializable trace payload.
        timeout: Requests timeout in seconds. May be a single float or (connect, read).
        url: Trace API endpoint.
        api_key: Optional API key used for project-scoped authentication.

    Returns:
        The JSON response from the API, or an empty dict if the response has no body.

    Raises:
        TraceClientError: If the request fails or the API returns a bad status.
    """
    try:
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key

        response = requests.post(url, json=data, headers=headers or None, timeout=timeout)
        response.raise_for_status()
    except requests.Timeout as exc:
        logger.exception("Trace request timed out when posting to %s", url)
        raise TraceClientError(f"Trace request timed out after {timeout} seconds") from exc
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        body = exc.response.text if exc.response is not None else ""
        logger.error(
            "Trace API returned HTTP %s for %s: %s",
            status_code,
            url,
            body,
        )
        raise TraceClientError(
            f"Trace API returned HTTP {status_code}"
        ) from exc
    except requests.RequestException as exc:
        logger.exception("Failed to send trace to %s", url)
        raise TraceClientError(f"Failed to send trace to {url}") from exc

    if not response.content:
        return {}

    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("Trace API returned a non-JSON response from %s", url)
        raise TraceClientError("Trace API returned a non-JSON response") from exc

    if isinstance(payload, dict):
        return payload

    return {"data": payload}
