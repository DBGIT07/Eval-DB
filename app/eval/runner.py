from __future__ import annotations

import os
import logging
import threading
import time
from dataclasses import dataclass, field
from statistics import mean, pvariance
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.eval.judge import Judge, MockJudge
from app.eval.metrics import METRICS, MetricResult
from app.models import Alert, Dataset, DatasetSample, EvalResult, EvalRun, EvalRunStatus

logger = logging.getLogger(__name__)


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(minimum, value)


_EVAL_CONCURRENCY_LIMIT = _read_int_env("EVAL_MAX_CONCURRENT_JOBS", 1, minimum=1)
_EVAL_CONCURRENCY_SEMAPHORE = threading.BoundedSemaphore(_EVAL_CONCURRENCY_LIMIT)
_EVAL_ASYNC_MIN_SAMPLES = _read_int_env("EVAL_ASYNC_MIN_SAMPLES", 25, minimum=1)


class EvaluationError(Exception):
    """Raised when evaluation cannot be completed."""


@dataclass(frozen=True)
class MetricSummary:
    metric_name: str
    average_score: float


@dataclass(frozen=True)
class EvaluationSummary:
    dataset_id: str
    metric_averages: dict[str, float] = field(default_factory=dict)


def _build_evaluator(metric_name: str, judge: Judge, provider: str, model: str) -> Any:
    evaluator_cls = METRICS.get(metric_name.lower())
    if evaluator_cls is None:
        raise EvaluationError(f"Unsupported metric: {metric_name}")
    return evaluator_cls(judge, provider, model)


def _compute_confidence(scores: list[float]) -> float:
    if not scores:
        return 0.0

    if len(scores) == 1:
        return 1.0

    variance = pvariance(scores)
    agreement = 1.0 - (max(scores) - min(scores))
    confidence = ((1.0 - min(1.0, variance)) + max(0.0, min(1.0, agreement))) / 2.0
    return max(0.0, min(1.0, confidence))


def _resolve_sample_payload(sample: DatasetSample) -> tuple[str, str, list[Any]]:
    payload = sample.data if isinstance(sample.data, dict) else None

    if payload is not None:
        prompt = payload.get("query")
        response = payload.get("answer")
        sources = payload.get("sources", [])

        resolved_prompt = (
            prompt
            if isinstance(prompt, str) and prompt.strip()
            else sample.input
        )
        resolved_response = (
            response
            if isinstance(response, str) and response.strip()
            else sample.expected_output
        )

        resolved_context: list[Any] = []
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict):
                    snippet = source.get("snippet")
                    if isinstance(snippet, str) and snippet.strip():
                        resolved_context.append(snippet)
                    elif snippet is not None:
                        resolved_context.append(str(snippet))
                elif source is not None:
                    resolved_context.append(str(source))

        if resolved_context:
            return resolved_prompt, resolved_response, resolved_context

        return resolved_prompt, resolved_response, sample.context or []

    return sample.input, sample.expected_output, sample.context or []


def _create_hallucination_alert(
    session: Session,
    eval_run: EvalRun,
    metric_averages: dict[str, float],
) -> Alert | None:
    hallucination_rate = float(metric_averages.get("hallucination", 0.0))
    if hallucination_rate <= 0.2:
        return None

    alert = Alert(
        eval_run_id=eval_run.id,
        severity="warning",
        message=(
            "Hallucination rate "
            f"{hallucination_rate:.3f} exceeded the alert threshold of 0.200."
        ),
    )
    session.add(alert)
    logger.warning(
        "Alert triggered for eval_run=%s hallucination_rate=%.3f threshold=0.200",
        eval_run.id,
        hallucination_rate,
    )
    return alert


def _run_evaluation_core(
    session: Session,
    eval_run: EvalRun,
    dataset_id: str,
    metrics: list,
    judge: Judge,
    provider: str,
    model: str,
    trace_id: str | None,
    project_id: str | None,
) -> dict[str, Any]:
    dataset = session.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise EvaluationError(f"Dataset not found: {dataset_id}")

    if project_id is not None and dataset.project_id is None:
        dataset.project_id = project_id

    eval_run.dataset_id = dataset_id
    eval_run.project_id = project_id or dataset.project_id
    eval_run.provider = provider
    eval_run.model = model
    eval_run.status = EvalRunStatus.RUNNING
    session.add(eval_run)
    session.flush()

    samples = list(
        session.scalars(
            select(DatasetSample)
            .where(DatasetSample.dataset_id == dataset_id)
            .order_by(DatasetSample.created_at.asc())
        )
    )

    metric_evaluators = {
        metric_name: _build_evaluator(metric_name, judge, provider, model)
        for metric_name in metrics
    }

    scores_by_metric: dict[str, list[float]] = {metric_name: [] for metric_name in metric_evaluators}
    sample_confidences: list[float] = []

    for sample in samples:
        sample_started_at = time.perf_counter()
        prompt, response, context = _resolve_sample_payload(sample)
        sample_results: list[MetricResult] = []
        logger.debug(
            "Eval sample start sample_id=%s dataset_id=%s metrics=%s prompt_chars=%s response_chars=%s context_items=%s context_chars=%s",
            sample.id,
            dataset_id,
            list(metric_evaluators.keys()),
            len(prompt or ""),
            len(response or ""),
            len(context or []),
            sum(len(str(item)) for item in (context or [])),
        )
        try:
            for metric_name, evaluator in metric_evaluators.items():
                metric_started_at = time.perf_counter()
                try:
                    result: MetricResult = evaluator.evaluate(
                        prompt=prompt,
                        response=response,
                        context=context,
                    )
                except Exception:
                    logger.exception(
                        "Eval metric failure sample_id=%s dataset_id=%s metric=%s provider=%s model=%s prompt_chars=%s response_chars=%s context_items=%s context_chars=%s",
                        sample.id,
                        dataset_id,
                        metric_name,
                        provider,
                        model,
                        len(prompt or ""),
                        len(response or ""),
                        len(context or []),
                        sum(len(str(item)) for item in (context or [])),
                    )
                    raise

                metric_elapsed = time.perf_counter() - metric_started_at
                logger.debug(
                    "Eval metric end sample_id=%s dataset_id=%s metric=%s score=%.3f label=%s elapsed_seconds=%.3f",
                    sample.id,
                    dataset_id,
                    metric_name,
                    result.score,
                    result.label,
                    metric_elapsed,
                )

                scores_by_metric[metric_name].append(result.score)
                sample_results.append(result)
        except Exception:
            sample_elapsed = time.perf_counter() - sample_started_at
            logger.error(
                "Eval sample failed sample_id=%s dataset_id=%s elapsed_seconds=%.3f metrics_completed=%s",
                sample.id,
                dataset_id,
                sample_elapsed,
                [result.metric_name for result in sample_results],
            )
            raise

        sample_confidence = _compute_confidence([result.score for result in sample_results])
        sample_confidences.append(sample_confidence)

        compact_results = ", ".join(
            f"{result.metric_name}={result.score:.3f}/{result.label}"
            for result in sample_results
        )
        logger.debug(
            "Eval sample end sample_id=%s dataset_id=%s confidence=%.3f elapsed_seconds=%.3f results=[%s]",
            sample.id,
            dataset_id,
            sample_confidence,
            time.perf_counter() - sample_started_at,
            compact_results,
        )

        for result in sample_results:
            eval_row = EvalResult(
                dataset_id=dataset_id,
                sample_id=sample.id,
                trace_id=trace_id,
                eval_run_id=eval_run.id,
                metric_name=result.metric_name,
                score=result.score,
                confidence=sample_confidence,
                label=result.label,
                reasoning=result.reasoning,
                judge_model=model,
            )
            session.add(eval_row)

    metric_averages = {
        metric_name: float(mean(scores)) if scores else 0.0
        for metric_name, scores in scores_by_metric.items()
    }
    average_confidence = float(mean(sample_confidences)) if sample_confidences else 0.0

    eval_run.status = EvalRunStatus.COMPLETED
    _create_hallucination_alert(session, eval_run, metric_averages)
    session.commit()

    return {
        "eval_run_id": eval_run.id,
        "summary": metric_averages,
        "confidence": average_confidence,
    }


def _finalize_failed_eval_run(session: Session, eval_run_id: str, message: str | None = None) -> None:
    eval_run = session.scalar(select(EvalRun).where(EvalRun.id == eval_run_id))
    if eval_run is None:
        return

    eval_run.status = EvalRunStatus.FAILED
    session.add(eval_run)
    session.commit()
    if message:
        logger.error("Evaluation run %s failed: %s", eval_run_id, message)


def run_evaluation_job(
    eval_run_id: str,
    dataset_id: str,
    metrics: list,
    *,
    provider: str = "mock",
    model: str = "mock",
    judge: Judge | None = None,
    trace_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    with _EVAL_CONCURRENCY_SEMAPHORE:
        session = SessionLocal()
        active_judge = judge or MockJudge()

        try:
            eval_run = session.scalar(select(EvalRun).where(EvalRun.id == eval_run_id))
            if eval_run is None:
                raise EvaluationError(f"Eval run not found: {eval_run_id}")

            return _run_evaluation_core(
                session=session,
                eval_run=eval_run,
                dataset_id=dataset_id,
                metrics=metrics,
                judge=active_judge,
                provider=provider,
                model=model,
                trace_id=trace_id,
                project_id=project_id,
            )
        except Exception:
            session.rollback()
            try:
                _finalize_failed_eval_run(session, eval_run_id)
            except Exception:
                session.rollback()
            raise
        finally:
            session.close()


def run_evaluation(
    dataset_id: str,
    metrics: list,
    *,
    db: Session | None = None,
    judge: Judge | None = None,
    provider: str = "mock",
    model: str = "mock",
    trace_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Evaluate a dataset with one or more metric evaluators.

    For each sample:
    - run each metric evaluator
    - persist an EvalResult row

    Returns:
        A dictionary containing the eval_run_id and per-metric summary averages.
    """
    with _EVAL_CONCURRENCY_SEMAPHORE:
        owns_session = db is None
        session = db or SessionLocal()
        active_judge = judge or MockJudge()
        eval_run = EvalRun(
            dataset_id=dataset_id,
            project_id=project_id,
            name=f"evaluation-{dataset_id}",
            provider=provider,
            model=model,
            status=EvalRunStatus.RUNNING,
        )

        try:
            session.add(eval_run)
            session.flush()
            result = _run_evaluation_core(
                session=session,
                eval_run=eval_run,
                dataset_id=dataset_id,
                metrics=metrics,
                judge=active_judge,
                provider=provider,
                model=model,
                trace_id=trace_id,
                project_id=project_id,
            )
            return result
        except Exception:
            session.rollback()
            try:
                _finalize_failed_eval_run(session, eval_run.id)
            except Exception:
                session.rollback()
            raise
        finally:
            if owns_session:
                session.close()


def run_benchmark(
    dataset_id: str,
    variants: list[dict[str, Any]],
    *,
    db: Session | None = None,
    metrics: list[str] | None = None,
    judge: Judge | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Run the same dataset against multiple benchmark variants.

    Each variant may include:
    - name
    - provider
    - model
    - top_k
    - prompt_version
    - any other config fields
    """
    if not variants:
        return []

    owns_session = db is None
    session = db or SessionLocal()
    results: list[dict[str, Any]] = []

    try:
        for variant in variants:
            variant_name = str(variant.get("name") or "").strip()
            provider = str(variant.get("provider") or "mock")
            model = str(variant.get("model") or "mock")

            config = dict(variant)
            config.setdefault("model", model)

            summary = run_evaluation(
                dataset_id=dataset_id,
                metrics=metrics or [],
                db=session,
                judge=judge,
                provider=provider,
                model=model,
                project_id=project_id,
            )

            eval_run_id = str(summary.get("eval_run_id") or "")
            if eval_run_id:
                eval_run = session.scalar(select(EvalRun).where(EvalRun.id == eval_run_id))
                if eval_run is not None:
                    eval_run.experiment_name = str(variant.get("experiment_name") or variant_name or None)
                    eval_run.variant = variant_name or None
                    eval_run.config = config
                    session.commit()

            results.append(
                {
                    "variant": variant_name or None,
                    "eval_run_id": eval_run_id,
                    "summary": dict(summary.get("summary", {})),
                    "confidence": summary.get("confidence", 0.0),
                }
            )

        return results
    finally:
        if owns_session:
            session.close()
