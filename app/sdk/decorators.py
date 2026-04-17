from __future__ import annotations

import functools
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from .tracer import track_llm

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def trace(name: str) -> Callable[[F], F]:
    """
    Decorate a function so its prompt, context, response, and latency are traced.

    The wrapped function is expected to accept `prompt` and `context` arguments.
    """

    def decorator(func: F) -> F:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind_partial(*args, **kwargs)
            prompt = bound.arguments.get("prompt")
            context = bound.arguments.get("context", [])

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception:
                latency_ms = int((time.perf_counter() - start) * 1000)
                logger.exception("Trace failed for %s", name)
                try:
                    track_llm(
                        prompt=str(prompt) if prompt is not None else "",
                        response="",
                        model=name,
                        context=context if isinstance(context, list) else [context],
                        latency_ms=latency_ms,
                    )
                except Exception:
                    logger.exception("Failed to send trace for %s after exception", name)
                raise

            latency_ms = int((time.perf_counter() - start) * 1000)
            try:
                track_llm(
                    prompt=str(prompt) if prompt is not None else "",
                    response=str(result),
                    model=name,
                    context=context if isinstance(context, list) else [context],
                    latency_ms=latency_ms,
                )
            except Exception:
                logger.exception("Failed to send trace for %s", name)

            return result

        return wrapper  # type: ignore[return-value]

    return decorator
