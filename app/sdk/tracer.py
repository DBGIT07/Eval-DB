from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

import requests

from app.sdk.client import send_trace


def _normalize_context(context: list[Any] | None) -> list[str]:
    """Reduce RAG context items to a compact list of text snippets."""
    if not context:
        return []

    normalized: list[str] = []
    for document in context:
        if isinstance(document, str):
            text = document
        elif isinstance(document, Mapping):
            text = document.get("text", "")
        else:
            text = getattr(document, "text", "")

        if text:
            normalized.append(str(text).strip())

    return normalized


def _auto_evaluate_trace(
    trace_id: str,
    *,
    metrics: list[str] | None,
    provider: str,
    model: str,
    project_id: str | None,
    api_key: str | None,
) -> None:
    """Kick off trace evaluation without blocking the caller."""
    if not metrics:
        return

    payload = {
        "metrics": metrics,
        "provider": provider,
        "model": model,
        "project_id": project_id,
    }

    try:
        headers = {}
        if api_key:
            headers["X-API-Key"] = api_key

        requests.post(
            f"http://localhost:8000/eval/trace/{trace_id}",
            json=payload,
            headers=headers or None,
            timeout=10.0,
        )
    except Exception:
        # Auto-eval is best-effort only.
        pass


def track_llm(
    prompt: str,
    response: str,
    model: str,
    context: list[Any] | None,
    latency_ms: int,
    task_type: str = "chat",
    auto_eval: bool = False,
    metrics: list[str] | None = None,
    provider: str = "mock",
    project_id: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Build a trace payload for an LLM call and send it to the trace API.

    Args:
        prompt: The input prompt.
        response: The model output.
        model: The model name.
        context: Optional contextual data for the trace.
        latency_ms: Request latency in milliseconds.
        task_type: Task type for the trace, defaults to "chat".
        auto_eval: If True, trigger best-effort trace evaluation in the background.
        metrics: Metrics to use for auto evaluation.
        provider: Evaluation provider to use for auto evaluation.
        api_key: Optional API key used for project-scoped API requests.

    Returns:
        The response from the trace API.
    """
    trace = {
        "prompt": prompt,
        "response": response,
        "model": model,
        "task_type": task_type,
        "context": _normalize_context(context),
        "latency_ms": latency_ms,
        "project_id": project_id,
    }
    result = send_trace(trace, api_key=api_key)

    if auto_eval:
        trace_id = result.get("trace_id") or result.get("id")
        if trace_id:
            threading.Thread(
                target=_auto_evaluate_trace,
                kwargs={
                    "trace_id": str(trace_id),
                    "metrics": metrics,
                    "provider": provider,
                    "model": model,
                    "project_id": project_id,
                    "api_key": api_key,
                },
                daemon=True,
            ).start()

    return result
