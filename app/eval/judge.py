from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import json
import os
import random
import re
import time
from pathlib import Path
from statistics import pvariance
from typing import Any

logger = logging.getLogger(__name__)


def _load_dotenv_files() -> None:
    """
    Load local .env files without introducing an external dependency.
    Existing environment variables always win.
    """
    candidate_paths = (
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[1] / ".env",
    )

    for env_path in candidate_paths:
        if not env_path.exists():
            continue

        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not os.environ.get(key):
                    os.environ[key] = value
        except OSError:
            # Ignore unreadable .env files and fall back to process env.
            continue


_load_dotenv_files()


def _resolve_api_key(provider_name: str, explicit_key: str | None, env_var: str) -> str:
    api_key = explicit_key or os.getenv(env_var)
    if not api_key:
        raise RuntimeError(
            f"{provider_name} API key is missing. Set {env_var} or pass api_key to JudgeRouter."
        )
    return api_key


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(minimum, value)


def _read_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return max(minimum, value)


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


_JUDGE_MAX_PROMPT_CHARS = _read_int_env("EVAL_JUDGE_MAX_PROMPT_CHARS", 4000, minimum=200)
_JUDGE_MAX_RESPONSE_CHARS = _read_int_env("EVAL_JUDGE_MAX_RESPONSE_CHARS", 4000, minimum=200)
_JUDGE_MAX_CONTEXT_ITEMS = _read_int_env("EVAL_JUDGE_MAX_CONTEXT_ITEMS", 12, minimum=1)
_JUDGE_MAX_CONTEXT_ITEM_CHARS = _read_int_env(
    "EVAL_JUDGE_MAX_CONTEXT_ITEM_CHARS",
    2000,
    minimum=50,
)
_JUDGE_MAX_CONTEXT_CHARS = _read_int_env("EVAL_JUDGE_MAX_CONTEXT_CHARS", 12000, minimum=1000)


def _truncate_text(value: Any, max_chars: int) -> str:
    text = "" if value is None else str(value).strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text

    suffix = f"... [truncated {len(text) - max_chars} chars]"
    head_length = max(0, max_chars - len(suffix))
    return f"{text[:head_length].rstrip()}{suffix}"


def _stringify_context_item(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
        except TypeError:
            text = str(value)
    else:
        text = str(value)

    return _truncate_text(text, _JUDGE_MAX_CONTEXT_ITEM_CHARS)


def _serialize_context(context: list) -> str:
    if not context:
        return "[]"

    rendered_items: list[str] = []
    total_chars = 2  # account for wrapping brackets in the rendered payload

    for index, item in enumerate(context):
        if index >= _JUDGE_MAX_CONTEXT_ITEMS:
            break

        item_text = _stringify_context_item(item)
        line = f"{index + 1}. {item_text}"
        projected_length = total_chars + len(line) + (1 if rendered_items else 0)
        if projected_length > _JUDGE_MAX_CONTEXT_CHARS:
            break

        rendered_items.append(line)
        total_chars = projected_length

    omitted_items = len(context) - len(rendered_items)
    if omitted_items > 0:
        summary_line = f"{len(rendered_items) + 1}. [truncated {omitted_items} additional context item(s)]"
        projected_length = total_chars + len(summary_line) + (1 if rendered_items else 0)
        if projected_length <= _JUDGE_MAX_CONTEXT_CHARS:
            rendered_items.append(summary_line)

    if not rendered_items:
        return "[truncated context]"

    return "\n".join(rendered_items)


def _build_evaluation_prompt(prompt: str, response: str, context: list) -> str:
    prompt_text = _truncate_text(prompt, _JUDGE_MAX_PROMPT_CHARS)
    response_text = _truncate_text(response, _JUDGE_MAX_RESPONSE_CHARS)
    context_text = _serialize_context(context)
    return (
        f"Given:\n"
        f"Question: {prompt_text}\n"
        f"Context: {context_text}\n"
        f"Answer: {response_text}\n\n"
        f"Evaluate separately:\n\n"
        f"1. Faithfulness:\n"
        f"- Is answer fully supported by context?\n"
        f"- Score 0-1\n\n"
        f"2. Relevance:\n"
        f"- Does it answer the question?\n"
        f"- Score 0-1\n\n"
        f"3. Completeness:\n"
        f"- Does it miss important info?\n"
        f"- Score 0-1\n\n"
        f"Return STRICT JSON:\n"
        f"{{\n"
        f'  "faithfulness": float,\n'
        f'  "relevance": float,\n'
        f'  "completeness": float,\n'
        f'  "final_score": float,\n'
        f'  "reasoning": "short explanation"\n'
        f"}}"
    )


def _http_status_code(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    return None


def _is_retryable_error(error: Exception) -> bool:
    status_code = _http_status_code(error)
    if status_code is not None:
        if status_code == 429:
            return True
        if 400 <= status_code < 500:
            return False
        return True

    message = str(error).lower()
    non_retryable_markers = (
        "context length",
        "maximum context",
        "prompt too long",
        "input too large",
        "payload too large",
        "unprocessable entity",
        "invalid request",
        "bad request",
        "invalid json",
        "schema",
    )
    return not any(marker in message for marker in non_retryable_markers)


def _build_consensus_result(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        raise RuntimeError("Judge evaluation failed for all attempts.")

    scores = [float(result.get("final_score", result.get("score", 0.0))) for result in results]
    scores = [max(0.0, min(1.0, score)) for score in scores]
    final_score = sum(scores) / len(scores)
    variance = pvariance(scores) if len(scores) > 1 else 0.0

    reasoning_parts = [
        str(result.get("reasoning") or "").strip()
        for result in results
        if str(result.get("reasoning") or "").strip()
    ]
    reasoning = " | ".join(reasoning_parts) if reasoning_parts else "Combined consensus evaluation."

    base_result = dict(results[0])
    base_result["label"] = "good" if final_score >= 0.5 else "bad"
    base_result.update(
        {
            "score": final_score,
            "final_score": final_score,
            "variance": variance,
            "reasoning": reasoning,
        }
    )
    return base_result


def _extract_retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    if response is None:
        return None

    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    retry_after = None
    if hasattr(headers, "get"):
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
    elif isinstance(headers, dict):
        retry_after = headers.get("retry-after") or headers.get("Retry-After")

    if retry_after is None:
        return None

    try:
        return max(0.0, float(retry_after))
    except (TypeError, ValueError):
        return None


class Judge(ABC):
    @abstractmethod
    def evaluate(
        self,
        prompt: str,
        response: str,
        context: list,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        """
        Evaluate a model response against the prompt and optional context.

        Returns:
            {
                "score": float,
                "label": "good" | "bad",
                "reasoning": str
            }
        """
        raise NotImplementedError


class MockJudge(Judge):
    """
    Placeholder judge implementation for future OpenAI integration.
    """

    def evaluate(
        self,
        prompt: str,
        response: str,
        context: list,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        attempts = []
        for _ in range(3):
            final_score = round(random.uniform(0.7, 0.95), 4)
            attempts.append(
                {
                    "faithfulness": final_score,
                    "relevance": final_score,
                    "completeness": final_score,
                    "final_score": final_score,
                    "score": final_score,
                    "label": "good",
                    "reasoning": "Mock evaluation",
                }
            )
        return _build_consensus_result(attempts)


class OpenAIJudge(Judge):
    """
    OpenAI-backed judge implementation.
    """

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        self._api_key = api_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("The openai package is required to use OpenAIJudge.") from exc

        api_key = _resolve_api_key("OpenAI", self._api_key, "OPENAI_API_KEY")
        self._client = OpenAI(api_key=api_key)
        return self._client

    @staticmethod
    def _serialize_context(context: list) -> str:
        try:
            return json.dumps(context, ensure_ascii=False, default=str, indent=2)
        except TypeError:
            return str(context)

    @staticmethod
    def _extract_json_payload(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass

        raise ValueError("OpenAIJudge response did not contain valid JSON.")

    @staticmethod
    def _normalize_result(payload: dict[str, Any]) -> dict[str, Any]:
        def _coerce_score(value: Any) -> float:
            try:
                coerced = float(value)
            except (TypeError, ValueError):
                coerced = 0.0
            return max(0.0, min(1.0, coerced))

        faithfulness = _coerce_score(payload.get("faithfulness"))
        relevance = _coerce_score(payload.get("relevance"))
        completeness = _coerce_score(payload.get("completeness"))
        score = _coerce_score(payload.get("final_score", payload.get("score", 0.0)))

        label = payload.get("label")
        if not isinstance(label, str) or not label.strip():
            label = "good" if score >= 0.5 else "bad"

        reasoning = payload.get("reasoning")
        if reasoning is None:
            reasoning = ""

        return {
            "faithfulness": faithfulness,
            "relevance": relevance,
            "completeness": completeness,
            "final_score": score,
            "score": score,
            "label": label,
            "reasoning": str(reasoning),
        }

    def _evaluate_once(
        self,
        client: Any,
        prompt: str,
        response: str,
        context: list,
        model: str,
    ) -> dict[str, Any]:
        evaluation_prompt = _build_evaluation_prompt(prompt, response, context)

        completion = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict evaluation engine. "
                        "Return only valid JSON with keys faithfulness, relevance, completeness, final_score, and reasoning."
                    ),
                },
                {"role": "user", "content": evaluation_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        payload = self._extract_json_payload(content)
        normalized = self._normalize_result(payload)
        logger.debug(
            "OpenAIJudge raw payload=%s normalized=%s model=%s",
            payload,
            normalized,
            model,
        )
        return normalized

    def evaluate(
        self,
        prompt: str,
        response: str,
        context: list,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        if provider.lower() != "openai":
            raise ValueError(f"OpenAIJudge only supports provider='openai', got {provider!r}.")

        client = self._get_client()
        try:
            attempts: list[dict[str, Any]] = []
            for _ in range(3):
                try:
                    attempts.append(self._evaluate_once(client, prompt, response, context, model))
                except Exception as exc:
                    if not _is_retryable_error(exc):
                        raise
                    continue
            if not attempts:
                raise RuntimeError("OpenAIJudge evaluation failed for all attempts.")
            return _build_consensus_result(attempts)
        except Exception as exc:
            raise RuntimeError(f"OpenAIJudge evaluation failed: {exc}") from exc


class ClaudeJudge(Judge):
    """
    Anthropic Claude-backed judge implementation.
    """

    def __init__(self, api_key: str | None = None, client: Any | None = None) -> None:
        self._api_key = api_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from anthropic import Anthropic
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("The anthropic package is required to use ClaudeJudge.") from exc

        api_key = _resolve_api_key("Anthropic", self._api_key, "ANTHROPIC_API_KEY")
        self._client = Anthropic(api_key=api_key)
        return self._client

    @staticmethod
    def _serialize_context(context: list) -> str:
        try:
            return json.dumps(context, ensure_ascii=False, default=str, indent=2)
        except TypeError:
            return str(context)

    @staticmethod
    def _extract_json_payload(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass

        raise ValueError("ClaudeJudge response did not contain valid JSON.")

    @staticmethod
    def _normalize_result(payload: dict[str, Any]) -> dict[str, Any]:
        def _coerce_score(value: Any) -> float:
            try:
                coerced = float(value)
            except (TypeError, ValueError):
                coerced = 0.0
            return max(0.0, min(1.0, coerced))

        try:
            score = _coerce_score(payload.get("final_score", payload.get("score", 0.0)))
        except Exception:
            score = 0.0

        label = payload.get("label")
        if not isinstance(label, str) or not label.strip():
            label = "good" if score >= 0.5 else "bad"

        faithfulness = _coerce_score(payload.get("faithfulness"))
        relevance = _coerce_score(payload.get("relevance"))
        completeness = _coerce_score(payload.get("completeness"))

        reasoning = payload.get("reasoning")
        if reasoning is None:
            reasoning = ""

        return {
            "faithfulness": faithfulness,
            "relevance": relevance,
            "completeness": completeness,
            "final_score": score,
            "score": score,
            "label": label,
            "reasoning": str(reasoning),
        }

    def _evaluate_once(
        self,
        client: Any,
        prompt: str,
        response: str,
        context: list,
        model: str,
    ) -> dict[str, Any]:
        evaluation_prompt = _build_evaluation_prompt(prompt, response, context)

        completion = client.messages.create(
            model=model,
            temperature=0,
            max_tokens=1024,
            system=(
                "You are a strict evaluation engine. "
                "Return only valid JSON with keys faithfulness, relevance, completeness, final_score, and reasoning."
            ),
            messages=[
                {
                    "role": "user",
                    "content": evaluation_prompt,
                }
            ],
        )

        content = ""
        for block in getattr(completion, "content", []):
            text = getattr(block, "text", None)
            if text:
                content += text

        payload = self._extract_json_payload(content or "{}")
        normalized = self._normalize_result(payload)
        logger.debug(
            "ClaudeJudge raw payload=%s normalized=%s model=%s",
            payload,
            normalized,
            model,
        )
        return normalized

    def evaluate(
        self,
        prompt: str,
        response: str,
        context: list,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        if provider.lower() not in {"claude", "anthropic"}:
            raise ValueError(
                f"ClaudeJudge only supports provider='claude' or provider='anthropic', got {provider!r}."
            )

        client = self._get_client()
        try:
            attempts: list[dict[str, Any]] = []
            for _ in range(3):
                try:
                    attempts.append(self._evaluate_once(client, prompt, response, context, model))
                except Exception as exc:
                    if not _is_retryable_error(exc):
                        raise
                    continue
            if not attempts:
                raise RuntimeError("ClaudeJudge evaluation failed for all attempts.")
            return _build_consensus_result(attempts)
        except Exception as exc:
            raise RuntimeError(f"ClaudeJudge evaluation failed: {exc}") from exc


class GroqJudge(Judge):
    """
    Groq-backed judge implementation using the Groq OpenAI-compatible chat API.
    """

    def __init__(
        self,
        api_key: str | None = None,
        client: Any | None = None,
        max_attempts: int | None = None,
        retry_base_delay_seconds: float | None = None,
        retry_backoff_multiplier: float | None = None,
        retry_max_delay_seconds: float | None = None,
        timeout_seconds: float | None = None,
        sdk_max_retries: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._max_attempts = max_attempts or _read_int_env("GROQ_JUDGE_MAX_ATTEMPTS", 1, minimum=1)
        self._retry_base_delay_seconds = (
            retry_base_delay_seconds
            if retry_base_delay_seconds is not None
            else _read_float_env("GROQ_JUDGE_RETRY_BASE_DELAY_SECONDS", 1.5, minimum=0.0)
        )
        self._retry_backoff_multiplier = (
            retry_backoff_multiplier
            if retry_backoff_multiplier is not None
            else _read_float_env("GROQ_JUDGE_RETRY_BACKOFF_MULTIPLIER", 2.0, minimum=1.0)
        )
        self._retry_max_delay_seconds = (
            retry_max_delay_seconds
            if retry_max_delay_seconds is not None
            else _read_float_env("GROQ_JUDGE_RETRY_MAX_DELAY_SECONDS", 8.0, minimum=0.0)
        )
        self._timeout_seconds = timeout_seconds if timeout_seconds is not None else _read_float_env(
            "GROQ_JUDGE_TIMEOUT_SECONDS",
            30.0,
            minimum=0.1,
        )
        self._sdk_max_retries = sdk_max_retries if sdk_max_retries is not None else _read_int_env(
            "GROQ_JUDGE_SDK_MAX_RETRIES",
            0,
            minimum=0,
        )
        self._respect_retry_after = _read_bool_env("EVAL_RESPECT_RETRY_AFTER", True)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from groq import Groq
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("The groq package is required to use GroqJudge.") from exc

        api_key = _resolve_api_key("Groq", self._api_key, "GROQ_API_KEY")
        self._client = Groq(
            api_key=api_key,
            timeout=self._timeout_seconds,
            max_retries=self._sdk_max_retries,
        )
        return self._client

    @staticmethod
    def _serialize_context(context: list) -> str:
        try:
            return json.dumps(context, ensure_ascii=False, default=str, indent=2)
        except TypeError:
            return str(context)

    @staticmethod
    def _extract_json_payload(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                pass

        raise ValueError("GroqJudge response did not contain valid JSON.")

    @staticmethod
    def _normalize_result(payload: dict[str, Any]) -> dict[str, Any]:
        def _coerce_score(value: Any) -> float:
            try:
                coerced = float(value)
            except (TypeError, ValueError):
                coerced = 0.0
            return max(0.0, min(1.0, coerced))

        faithfulness = _coerce_score(payload.get("faithfulness"))
        relevance = _coerce_score(payload.get("relevance"))
        completeness = _coerce_score(payload.get("completeness"))
        score = _coerce_score(payload.get("final_score", payload.get("score", 0.0)))

        label = payload.get("label")
        if not isinstance(label, str) or not label.strip():
            label = "good" if score >= 0.5 else "bad"

        reasoning = payload.get("reasoning")
        if reasoning is None:
            reasoning = ""

        return {
            "faithfulness": faithfulness,
            "relevance": relevance,
            "completeness": completeness,
            "final_score": score,
            "score": score,
            "label": label,
            "reasoning": str(reasoning),
        }

    def _evaluate_once(
        self,
        client: Any,
        prompt: str,
        response: str,
        context: list,
        model: str,
    ) -> dict[str, Any]:
        evaluation_prompt = _build_evaluation_prompt(prompt, response, context)

        completion = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict evaluation engine. "
                        "Return only valid JSON with keys faithfulness, relevance, completeness, final_score, and reasoning."
                    ),
                },
                {"role": "user", "content": evaluation_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        payload = self._extract_json_payload(content)
        normalized = self._normalize_result(payload)
        logger.debug(
            "GroqJudge raw payload=%s normalized=%s model=%s",
            payload,
            normalized,
            model,
        )
        return normalized

    def evaluate(
        self,
        prompt: str,
        response: str,
        context: list,
        provider: str,
        model: str,
    ) -> dict[str, Any]:
        if provider.lower() not in {"groq"}:
            raise ValueError(f"GroqJudge only supports provider='groq', got {provider!r}.")

        client = self._get_client()
        try:
            attempts: list[dict[str, Any]] = []
            last_error: Exception | None = None
            for attempt_index in range(self._max_attempts):
                try:
                    attempts.append(self._evaluate_once(client, prompt, response, context, model))
                except Exception as exc:
                    last_error = exc
                    if not _is_retryable_error(exc):
                        raise
                    if attempt_index + 1 < self._max_attempts:
                        delay = _extract_retry_after_seconds(exc) if self._respect_retry_after else None
                        if delay is None:
                            delay = self._retry_base_delay_seconds * (
                                self._retry_backoff_multiplier ** attempt_index
                            )
                        delay = min(delay, self._retry_max_delay_seconds)
                        if delay > 0:
                            time.sleep(delay)
                    continue
            if not attempts:
                if last_error is not None:
                    raise RuntimeError(f"GroqJudge evaluation failed for all attempts: {last_error}") from last_error
                raise RuntimeError("GroqJudge evaluation failed for all attempts.")
            return _build_consensus_result(attempts)
        except Exception as exc:
            raise RuntimeError(f"GroqJudge evaluation failed: {exc}") from exc


def JudgeRouter(provider: str, model: str, api_key: str | None = None, **kwargs: Any) -> Judge:
    """
    Factory for returning the correct Judge implementation for a provider.

    Args:
        provider: Provider name such as "openai" or "claude".
        model: Target model name. Accepted for API compatibility and future extension.
        **kwargs: Optional constructor kwargs forwarded to the concrete judge.

    Returns:
        A Judge instance matching the requested provider.
    """
    provider_key = provider.lower().strip()

    registry: dict[str, type[Judge]] = {
        "mock": MockJudge,
        "openai": OpenAIJudge,
        "claude": ClaudeJudge,
        "anthropic": ClaudeJudge,
        "groq": GroqJudge,
    }

    judge_cls = registry.get(provider_key)
    if judge_cls is None:
        raise ValueError(f"Unsupported provider: {provider!r}")

    if judge_cls is MockJudge:
        return judge_cls()

    return judge_cls(api_key=api_key, **kwargs)
