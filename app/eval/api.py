from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import os
import threading
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.eval.judge import JudgeRouter
from app.eval.runner import EvaluationError, run_benchmark, run_evaluation, run_evaluation_job
from app.models import Alert, Dataset, DatasetSample, EvalResult, EvalRun, EvalRunStatus, Project, Trace
from app.security import (
    get_current_user_id,
    get_current_user_id_optional,
    get_project_id_from_api_key,
    get_project_id_from_api_key_optional,
    require_project_access,
)

logger = logging.getLogger(__name__)


DEFAULT_EVAL_PROVIDER = os.getenv("EVAL_DEFAULT_PROVIDER", "mock")
DEFAULT_EVAL_MODEL = os.getenv("EVAL_DEFAULT_MODEL", "mock")


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(minimum, value)


_EVAL_ASYNC_MIN_SAMPLES = _read_int_env("EVAL_ASYNC_MIN_SAMPLES", 25, minimum=1)


class EvalRequest(BaseModel):
    metrics: list[str] = Field(default_factory=list)
    provider: str = DEFAULT_EVAL_PROVIDER
    model: str = DEFAULT_EVAL_MODEL
    api_key: str | None = None
    project_id: str | None = None

    @field_validator("metrics", mode="before")
    @classmethod
    def _normalize_metrics(cls, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            value = [value]

        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                parts = item.split(",")
                normalized.extend(part.strip() for part in parts if part.strip())
            else:
                text = str(item).strip()
                if text:
                    normalized.append(text)

        return normalized


DEFAULT_BENCHMARK_METRICS = [
    "faithfulness",
    "relevance",
    "completeness",
    "context_precision",
    "context_recall",
    "groundedness",
    "retrieval_quality",
]


class EvalResponse(BaseModel):
    eval_run_id: str
    status: str
    summary: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None
    queued: bool = False
    provider: str
    model: str
    project_id: str | None = None


class BenchmarkVariant(BaseModel):
    name: str
    provider: str = DEFAULT_EVAL_PROVIDER
    model: str = DEFAULT_EVAL_MODEL
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class BenchmarkCompareRequest(BaseModel):
    dataset_id: str
    variants: list[BenchmarkVariant] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=lambda: list(DEFAULT_BENCHMARK_METRICS))
    project_id: str | None = None

    @field_validator("metrics", mode="before")
    @classmethod
    def _normalize_metrics(cls, value: Any) -> list[str]:
        return EvalRequest._normalize_metrics(value)


class BenchmarkCompareResponse(BaseModel):
    variants: dict[str, dict[str, float]]
    winner: str


class TraceEvalResponse(BaseModel):
    trace_id: str
    eval_run_id: str
    results: dict[str, float]
    project_id: str | None = None


class BatchTraceEvalRequest(BaseModel):
    trace_ids: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    provider: str = DEFAULT_EVAL_PROVIDER
    model: str = DEFAULT_EVAL_MODEL
    api_key: str | None = None
    project_id: str | None = None

    @field_validator("metrics", mode="before")
    @classmethod
    def _normalize_metrics(cls, value: Any) -> list[str]:
        return EvalRequest._normalize_metrics(value)


class BatchTraceEvalItem(BaseModel):
    trace_id: str
    eval_run_id: str
    results: dict[str, float]


class BatchTraceEvalResponse(BaseModel):
    results: list[BatchTraceEvalItem]


class EvalRunListItem(BaseModel):
    id: str
    project_id: str | None = None
    provider: str
    model: str
    status: EvalRunStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvalResultListItem(BaseModel):
    id: str
    project_id: str | None = None
    dataset_id: str
    eval_run_id: str
    metric_name: str
    score: float
    label: str
    judge_model: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EvalRunSampleMetric(BaseModel):
    metric_name: str
    score: float
    label: str
    reasoning: str | None = None
    judge_model: str

    model_config = ConfigDict(from_attributes=True)


class EvalRunDetailResponse(BaseModel):
    run: EvalRunListItem
    results_by_metric: dict[str, list[EvalRunSampleMetric]]


class EvalIssueMetric(BaseModel):
    metric_name: str
    score: float
    label: str
    reasoning: str | None = None


class EvalIssueSample(BaseModel):
    sample_id: str
    input: str
    response: str
    metric_scores: list[EvalIssueMetric]


class EvalRunComparisonMetric(BaseModel):
    run1: float
    run2: float
    diff: float


class EvalRunCompareResponse(BaseModel):
    run1: EvalRunListItem
    run2: EvalRunListItem
    comparison: dict[str, EvalRunComparisonMetric]


class DashboardTrendPoint(BaseModel):
    date: str
    score: float


class DashboardSummaryResponse(BaseModel):
    total_runs: int
    latest_scores: dict[str, float]
    trend: list[DashboardTrendPoint]


class DashboardAlertItem(BaseModel):
    id: str
    eval_run_id: str
    message: str
    severity: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardProjectResponse(BaseModel):
    total_traces: int
    total_datasets: int
    avg_scores: dict[str, float]
    recent_alerts: list[DashboardAlertItem]


router = APIRouter(prefix="/eval", tags=["eval"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])
benchmark_router = APIRouter(prefix="/benchmark", tags=["benchmark"])


def _require_dataset_access(
    db: Session,
    dataset: Dataset,
    current_user_id: str | None,
    project_id: str | None = None,
) -> None:
    effective_project_id = project_id if project_id is not None else dataset.project_id
    if effective_project_id is None:
        return
    require_project_access(db, effective_project_id, current_user_id)
    if dataset.project_id is not None and dataset.project_id != effective_project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dataset does not belong to the requested project.",
        )


def _require_trace_access(
    db: Session,
    trace: Trace,
    current_user_id: str | None,
    project_id: str | None = None,
) -> None:
    effective_project_id = project_id if project_id is not None else trace.project_id
    if effective_project_id is None:
        return
    require_project_access(db, effective_project_id, current_user_id)
    if trace.project_id is not None and trace.project_id != effective_project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Trace does not belong to the requested project.",
        )


def _resolve_eval_project_id(dataset: Dataset, project_id: str | None) -> str | None:
    return project_id or dataset.project_id


def _resolve_run_project_id(db: Session, run: EvalRun) -> str | None:
    if run.project_id is not None:
        return run.project_id

    dataset = db.scalar(select(Dataset).where(Dataset.id == run.dataset_id))
    if dataset is None:
        return None

    return dataset.project_id


def _require_eval_run_access(
    db: Session,
    run: EvalRun,
    current_user_id: str | None,
    project_id: str | None = None,
) -> None:
    effective_project_id = project_id if project_id is not None else _resolve_run_project_id(db, run)
    if effective_project_id is None:
        return
    require_project_access(db, effective_project_id, current_user_id)


def _require_project_dashboard_access(
    db: Session,
    project_id: str,
    current_user_id: str | None,
) -> None:
    require_project_access(db, project_id, current_user_id)


def _get_or_create_trace_dataset(db: Session, trace: Trace, project_id: str | None) -> Dataset:
    dataset_name = f"trace-eval:{trace.id}"
    dataset = db.scalar(
        select(Dataset).where(
            Dataset.name == dataset_name,
            Dataset.task_type == "trace_evaluation",
        )
    )
    if dataset is None:
        dataset = Dataset(name=dataset_name, task_type="trace_evaluation", project_id=project_id)
        db.add(dataset)
        db.flush()
    elif project_id is not None and dataset.project_id is None:
        dataset.project_id = project_id
    return dataset


def _sync_trace_sample(db: Session, dataset: Dataset, trace: Trace) -> DatasetSample:
    sample = db.scalar(
        select(DatasetSample)
        .where(DatasetSample.dataset_id == dataset.id)
        .order_by(DatasetSample.created_at.asc())
    )

    if sample is None:
        sample = DatasetSample(
            dataset_id=dataset.id,
            input=trace.prompt,
            context=trace.context,
            tags=[f"trace:{trace.id}", "synthetic"],
            expected_output=trace.response,
            data={
                "query": trace.prompt,
                "answer": trace.response,
                "sources": trace.context or [],
                "metadata": {
                    "trace_id": trace.id,
                    "source": "trace",
                },
            },
        )
        db.add(sample)
    else:
        sample.input = trace.prompt
        sample.context = trace.context
        sample.tags = [f"trace:{trace.id}", "synthetic"]
        sample.expected_output = trace.response
        sample.data = {
            "query": trace.prompt,
            "answer": trace.response,
            "sources": trace.context or [],
            "metadata": {
                "trace_id": trace.id,
                "source": "trace",
            },
        }

    db.flush()
    return sample


def _evaluate_trace_core(
    db: Session,
    trace: Trace,
    payload: EvalRequest,
    judge: Any,
    project_id: str | None,
) -> dict[str, object]:
    synthetic_dataset = _get_or_create_trace_dataset(db, trace, project_id)
    _sync_trace_sample(db, synthetic_dataset, trace)
    db.flush()

    summary = run_evaluation(
        dataset_id=synthetic_dataset.id,
        metrics=payload.metrics,
        db=db,
        judge=judge,
        provider=payload.provider,
        model=payload.model,
        trace_id=trace.id,
        project_id=project_id,
    )
    return summary


def _variant_to_payload(variant: BenchmarkVariant) -> dict[str, Any]:
    payload = variant.model_dump(exclude_none=True)
    config = dict(payload.pop("config", {}) or {})
    name = str(payload.pop("name", "") or "").strip()
    provider = str(payload.pop("provider", "mock") or "mock")
    model = str(payload.pop("model", "mock") or "mock")

    merged_config = {
        **config,
        **payload,
    }
    merged_config.setdefault("model", model)

    return {
        "name": name,
        "provider": provider,
        "model": model,
        "config": merged_config,
    }


def _count_dataset_samples(db: Session, dataset_id: str) -> int:
    return int(db.scalar(select(func.count(DatasetSample.id)).where(DatasetSample.dataset_id == dataset_id)) or 0)


def _run_dataset_evaluation_background(
    eval_run_id: str,
    dataset_id: str,
    metrics: list[str],
    *,
    provider: str,
    model: str,
    api_key: str | None,
    trace_id: str | None,
    project_id: str | None,
) -> None:
    try:
        judge = JudgeRouter(provider=provider, model=model, api_key=api_key)
        run_evaluation_job(
            eval_run_id=eval_run_id,
            dataset_id=dataset_id,
            metrics=metrics,
            provider=provider,
            model=model,
            judge=judge,
            trace_id=trace_id,
            project_id=project_id,
        )
    except Exception:
        logger.exception(
            "Background dataset evaluation failed for eval_run_id=%s dataset_id=%s",
            eval_run_id,
            dataset_id,
        )


def _launch_dataset_evaluation_job(
    *,
    eval_run_id: str,
    dataset_id: str,
    metrics: list[str],
    provider: str,
    model: str,
    api_key: str | None,
    trace_id: str | None,
    project_id: str | None,
) -> None:
    worker = threading.Thread(
        target=_run_dataset_evaluation_background,
        kwargs={
            "eval_run_id": eval_run_id,
            "dataset_id": dataset_id,
            "metrics": metrics,
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "trace_id": trace_id,
            "project_id": project_id,
        },
        daemon=True,
        name=f"eval-run-{eval_run_id}",
    )
    worker.start()


@router.post("/{dataset_id}", response_model=EvalResponse)
def evaluate_dataset(
    dataset_id: str,
    payload: EvalRequest,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id: str | None = Depends(get_project_id_from_api_key_optional),
) -> dict[str, object]:
    if not payload.metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one metric must be provided.",
        )

    dataset: Dataset | None = None
    eval_run: EvalRun | None = None

    try:
        dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        if dataset is None:
            raise EvaluationError(f"Dataset not found: {dataset_id}")

        effective_project_id = project_id or payload.project_id or dataset.project_id
        if effective_project_id is None:
            if current_user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authorization is required to evaluate a dataset.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A project_id is required to evaluate a dataset.",
            )

        if project_id is not None:
            if payload.project_id is not None and payload.project_id != project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key project does not match the requested project.",
                )
            if dataset.project_id is not None and dataset.project_id != project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key project does not match the dataset project.",
                )
        else:
            require_project_access(db, effective_project_id, current_user_id)
            if payload.project_id is not None and payload.project_id != effective_project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Project does not match the requested project.",
                )
            if dataset.project_id is not None and dataset.project_id != effective_project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Dataset does not belong to the requested project.",
                )

        sample_count = _count_dataset_samples(db, dataset_id)

        eval_run = EvalRun(
            dataset_id=dataset_id,
            project_id=effective_project_id,
            name=f"evaluation-{dataset_id}",
            provider=payload.provider,
            model=payload.model,
            status=EvalRunStatus.RUNNING,
        )
        db.add(eval_run)
        db.commit()
        db.refresh(eval_run)

        logger.info(
            "Dataset evaluation requested dataset_id=%s samples=%s provider=%s model=%s queued_threshold=%s",
            dataset_id,
            sample_count,
            payload.provider,
            payload.model,
            _EVAL_ASYNC_MIN_SAMPLES,
        )

        if sample_count >= _EVAL_ASYNC_MIN_SAMPLES:
            _launch_dataset_evaluation_job(
                eval_run_id=eval_run.id,
                dataset_id=dataset_id,
                metrics=list(payload.metrics),
                provider=payload.provider,
                model=payload.model,
                api_key=payload.api_key,
                trace_id=None,
                project_id=effective_project_id,
            )
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "eval_run_id": eval_run.id,
                    "status": EvalRunStatus.RUNNING.value,
                    "summary": {},
                    "confidence": None,
                    "queued": True,
                    "provider": payload.provider,
                    "model": payload.model,
                    "project_id": effective_project_id,
                },
            )

        judge = JudgeRouter(provider=payload.provider, model=payload.model, api_key=payload.api_key)
        summary = run_evaluation_job(
            eval_run_id=eval_run.id,
            dataset_id=dataset_id,
            metrics=payload.metrics,
            provider=payload.provider,
            model=payload.model,
            judge=judge,
            trace_id=None,
            project_id=effective_project_id,
        )
    except EvaluationError as exc:
        message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Unexpected dataset evaluation failure dataset_id=%s eval_run_id=%s provider=%s model=%s",
            dataset_id,
            getattr(eval_run, "id", None),
            payload.provider,
            payload.model,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Evaluation failed unexpectedly. Check server logs for details.",
        ) from exc

    return {
        "eval_run_id": str(summary["eval_run_id"]),
        "status": EvalRunStatus.COMPLETED.value,
        "summary": dict(summary["summary"]),
        "confidence": summary.get("confidence"),
        "queued": False,
        "provider": payload.provider,
        "model": payload.model,
        "project_id": effective_project_id,
    }


@benchmark_router.post("/compare", response_model=BenchmarkCompareResponse)
def compare_benchmark(
    payload: BenchmarkCompareRequest,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> dict[str, Any]:
    if not payload.dataset_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset_id is required.",
        )
    if not payload.variants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one variant must be provided.",
        )

    dataset = db.scalar(select(Dataset).where(Dataset.id == payload.dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset not found: {payload.dataset_id}",
        )

    effective_project_id = _resolve_eval_project_id(dataset, payload.project_id)
    _require_dataset_access(db, dataset, current_user_id, effective_project_id)

    benchmark_variants = [_variant_to_payload(variant) for variant in payload.variants]

    try:
        results = run_benchmark(
            dataset_id=payload.dataset_id,
            variants=benchmark_variants,
            db=db,
            metrics=payload.metrics,
            project_id=effective_project_id,
        )
    except EvaluationError as exc:
        message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compare benchmarks.",
        ) from exc

    variants_output: dict[str, dict[str, float]] = {}
    winner_name = ""
    winner_score = float("-inf")

    for item in results:
        variant_name = str(item.get("variant") or item.get("eval_run_id") or "").strip()
        summary = dict(item.get("summary", {}))
        variants_output[variant_name] = summary

        if summary:
            aggregate_score = sum(summary.values()) / len(summary)
        else:
            aggregate_score = 0.0

        if aggregate_score > winner_score:
            winner_score = aggregate_score
            winner_name = variant_name

    return {
        "variants": variants_output,
        "winner": winner_name,
    }


@router.post("/trace/{trace_id}", response_model=TraceEvalResponse)
def evaluate_trace(
    trace_id: str,
    payload: EvalRequest,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id: str | None = Depends(get_project_id_from_api_key_optional),
) -> dict[str, object]:
    if not payload.metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one metric must be provided.",
        )

    trace = db.scalar(select(Trace).where(Trace.id == trace_id))
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace not found.",
        )

    effective_project_id = project_id or payload.project_id or trace.project_id
    if effective_project_id is None:
        if current_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization is required to evaluate a trace.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A project_id is required to evaluate a trace.",
        )

    if project_id is not None:
        if payload.project_id is not None and payload.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the requested project.",
            )
        if trace.project_id is not None and trace.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the trace project.",
            )
    else:
        require_project_access(db, effective_project_id, current_user_id)
        if payload.project_id is not None and payload.project_id != effective_project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project does not match the requested project.",
            )
        if trace.project_id is not None and trace.project_id != effective_project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trace does not belong to the requested project.",
            )

    try:
        judge = JudgeRouter(provider=payload.provider, model=payload.model, api_key=payload.api_key)
        summary = _evaluate_trace_core(db, trace, payload, judge, effective_project_id)
    except EvaluationError as exc:
        db.rollback()
        message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    except RuntimeError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to evaluate trace.",
        ) from exc

    return {
        "trace_id": trace.id,
        "eval_run_id": str(summary["eval_run_id"]),
        "results": dict(summary["summary"]),
        "project_id": effective_project_id,
    }


@router.post("/traces", response_model=BatchTraceEvalResponse)
def evaluate_traces(
    payload: BatchTraceEvalRequest,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id: str | None = Depends(get_project_id_from_api_key_optional),
) -> dict[str, object]:
    if not payload.trace_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one trace_id must be provided.",
        )
    if not payload.metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one metric must be provided.",
        )

    judge = JudgeRouter(provider=payload.provider, model=payload.model, api_key=payload.api_key)
    batch_results: list[BatchTraceEvalItem] = []

    try:
        for trace_id in payload.trace_ids:
            trace = db.scalar(select(Trace).where(Trace.id == trace_id))
            if trace is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Trace not found: {trace_id}",
                )
            effective_project_id = project_id or payload.project_id or trace.project_id
            if effective_project_id is None:
                if current_user_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Authorization is required to evaluate traces.",
                    )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A project_id is required to evaluate traces.",
                )

            if project_id is not None:
                if payload.project_id is not None and payload.project_id != project_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="API key project does not match the requested project.",
                    )
                if trace.project_id is not None and trace.project_id != project_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="API key project does not match the trace project.",
                    )
            else:
                require_project_access(db, effective_project_id, current_user_id)
                if payload.project_id is not None and payload.project_id != effective_project_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Project does not match the requested project.",
                    )
                if trace.project_id is not None and trace.project_id != effective_project_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Trace does not belong to the requested project.",
                    )

            summary = _evaluate_trace_core(
                db,
                trace,
                EvalRequest(
                    metrics=payload.metrics,
                    provider=payload.provider,
                    model=payload.model,
                    api_key=payload.api_key,
                    project_id=effective_project_id,
                ),
                judge,
                effective_project_id,
            )
            batch_results.append(
                BatchTraceEvalItem(
                    trace_id=trace.id,
                    eval_run_id=str(summary["eval_run_id"]),
                    results=dict(summary["summary"]),
                )
            )
    except EvaluationError as exc:
        db.rollback()
        message = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to evaluate traces.",
        ) from exc

    return {"results": batch_results}


@router.get("/runs/{dataset_id}", response_model=list[EvalRunListItem])
def list_eval_runs(
    dataset_id: str,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[EvalRunListItem]:
    try:
        dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset not found: {dataset_id}",
            )
        effective_project_id = _resolve_eval_project_id(dataset, project_id)
        _require_dataset_access(db, dataset, current_user_id, effective_project_id)

        runs = list(
            db.scalars(
                select(EvalRun)
                .where(EvalRun.dataset_id == dataset_id)
                .order_by(EvalRun.created_at.desc())
            )
        )

        if not runs:
            return []

        response: list[EvalRunListItem] = []
        for run in runs:
            response.append(
                EvalRunListItem(
                    id=run.id,
                    project_id=_resolve_run_project_id(db, run),
                    provider=str(getattr(run, "provider", "unknown") or "unknown"),
                    model=str(getattr(run, "model", "unknown") or "unknown"),
                    status=run.status,
                    created_at=run.created_at,
                )
            )

        return response
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load evaluation runs.",
        ) from exc


@router.get("/project/{project_id}/results", response_model=list[EvalResultListItem])
def list_project_eval_results(
    project_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[EvalResultListItem]:
    try:
        _require_project_dashboard_access(db, project_id, current_user_id)

        results = list(
            db.scalars(
                select(EvalResult)
                .join(EvalRun, EvalRun.id == EvalResult.eval_run_id)
                .where(EvalRun.project_id == project_id)
                .order_by(EvalResult.created_at.desc())
            )
        )

        return [
            EvalResultListItem(
                id=result.id,
                project_id=project_id,
                dataset_id=result.dataset_id,
                eval_run_id=result.eval_run_id,
                metric_name=result.metric_name,
                score=result.score,
                label=result.label,
                judge_model=result.judge_model,
                created_at=result.created_at,
            )
            for result in results
        ]
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load project evaluation results.",
        ) from exc


@router.get("/project/{project_id}/runs", response_model=list[EvalRunListItem])
def list_project_eval_runs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[EvalRunListItem]:
    try:
        _require_project_dashboard_access(db, project_id, current_user_id)

        runs = list(
            db.scalars(
                select(EvalRun)
                .where(EvalRun.project_id == project_id)
                .order_by(EvalRun.created_at.desc())
            )
        )
        if not runs:
            return []

        return [
            EvalRunListItem(
                id=run.id,
                project_id=_resolve_run_project_id(db, run),
                provider=str(getattr(run, "provider", "unknown") or "unknown"),
                model=str(getattr(run, "model", "unknown") or "unknown"),
                status=run.status,
                created_at=run.created_at,
            )
            for run in runs
        ]
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load project evaluation runs.",
        ) from exc


@router.get("/run/{eval_run_id}", response_model=EvalRunDetailResponse)
def get_eval_run(
    eval_run_id: str,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> EvalRunDetailResponse:
    try:
        run = db.scalar(select(EvalRun).where(EvalRun.id == eval_run_id))
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation run not found: {eval_run_id}",
            )
        _require_eval_run_access(db, run, current_user_id, project_id)

        eval_results = list(
            db.scalars(
                select(EvalResult)
                .where(EvalResult.eval_run_id == eval_run_id)
                .order_by(EvalResult.created_at.asc())
            )
        )

        summary_by_metric: dict[str, list[float]] = defaultdict(list)
        results_by_metric: dict[str, list[EvalRunSampleMetric]] = defaultdict(list)
        for result in eval_results:
            summary_by_metric[result.metric_name].append(result.score)
            results_by_metric[result.metric_name].append(
                EvalRunSampleMetric(
                    metric_name=result.metric_name,
                    score=result.score,
                    label=result.label,
                    reasoning=result.reasoning,
                    judge_model=result.judge_model,
                )
            )

        metrics_summary = {
            metric_name: sum(scores) / len(scores) if scores else 0.0
            for metric_name, scores in summary_by_metric.items()
        }

        run_info = EvalRunListItem(
            id=run.id,
            project_id=_resolve_run_project_id(db, run),
            provider=str(getattr(run, "provider", "unknown") or "unknown"),
            model=str(getattr(run, "model", "unknown") or "unknown"),
            status=run.status,
            created_at=run.created_at,
        )

        return EvalRunDetailResponse(
            run=run_info,
            results_by_metric=dict(results_by_metric),
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load evaluation run details.",
        ) from exc


@router.get("/run/{eval_run_id}/issues", response_model=list[EvalIssueSample])
def get_eval_run_issues(
    eval_run_id: str,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[EvalIssueSample]:
    try:
        run = db.scalar(select(EvalRun).where(EvalRun.id == eval_run_id))
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation run not found: {eval_run_id}",
            )
        _require_eval_run_access(db, run, current_user_id, project_id)

        issue_filter = or_(
            and_(EvalResult.metric_name == "hallucination", EvalResult.label == "high"),
            EvalResult.score < 0.5,
        )
        issue_results = list(
            db.scalars(
                select(EvalResult)
                .where(EvalResult.eval_run_id == eval_run_id)
                .where(issue_filter)
                .order_by(EvalResult.sample_id.asc(), EvalResult.created_at.asc())
            )
        )

        if not issue_results:
            return []

        sample_ids = [result.sample_id for result in issue_results]
        samples = {
            sample.id: sample
            for sample in db.scalars(
                select(DatasetSample).where(DatasetSample.id.in_(sample_ids))
            )
        }

        grouped: dict[str, list[EvalIssueMetric]] = defaultdict(list)
        for result in issue_results:
            grouped[result.sample_id].append(
                EvalIssueMetric(
                    metric_name=result.metric_name,
                    score=result.score,
                    label=result.label,
                    reasoning=result.reasoning,
                )
            )

        issues: list[EvalIssueSample] = []
        for sample_id in dict.fromkeys(sample_ids):
            sample = samples.get(sample_id)
            if sample is None:
                continue
            issues.append(
                EvalIssueSample(
                    sample_id=sample.id,
                    input=sample.resolved_input(),
                    response=sample.resolved_expected_output(),
                    metric_scores=grouped.get(sample_id, []),
                )
            )

        return issues
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load evaluation issues.",
        ) from exc


@router.get("/compare", response_model=EvalRunCompareResponse)
def compare_eval_runs(
    run1: str,
    run2: str,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> EvalRunCompareResponse:
    try:
        runs = list(
            db.scalars(
                select(EvalRun).where(EvalRun.id.in_([run1, run2]))
            )
        )
        run_map = {run.id: run for run in runs}

        missing_run_ids = [run_id for run_id in (run1, run2) if run_id not in run_map]
        if missing_run_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Evaluation run not found: {missing_run_ids[0]}",
            )
        for run in runs:
            _require_eval_run_access(db, run, current_user_id, project_id)

        metric_rows = db.execute(
            select(
                EvalResult.eval_run_id,
                EvalResult.metric_name,
                func.avg(EvalResult.score),
            )
            .where(EvalResult.eval_run_id.in_([run1, run2]))
            .group_by(EvalResult.eval_run_id, EvalResult.metric_name)
        ).all()

        scores_by_run: dict[str, dict[str, float]] = defaultdict(dict)
        for eval_run_id, metric_name, avg_score in metric_rows:
            scores_by_run[eval_run_id][metric_name] = float(avg_score or 0.0)

        metric_names = set(scores_by_run.get(run1, {})) | set(scores_by_run.get(run2, {}))
        comparison: dict[str, EvalRunComparisonMetric] = {}
        for metric_name in sorted(metric_names):
            run1_score = float(scores_by_run.get(run1, {}).get(metric_name, 0.0))
            run2_score = float(scores_by_run.get(run2, {}).get(metric_name, 0.0))
            comparison[metric_name] = EvalRunComparisonMetric(
                run1=run1_score,
                run2=run2_score,
                diff=run2_score - run1_score,
            )

        return EvalRunCompareResponse(
            run1=EvalRunListItem(
                id=run_map[run1].id,
                project_id=_resolve_run_project_id(db, run_map[run1]),
                provider=str(getattr(run_map[run1], "provider", "unknown") or "unknown"),
                model=str(getattr(run_map[run1], "model", "unknown") or "unknown"),
                status=run_map[run1].status,
                created_at=run_map[run1].created_at,
            ),
            run2=EvalRunListItem(
                id=run_map[run2].id,
                project_id=_resolve_run_project_id(db, run_map[run2]),
                provider=str(getattr(run_map[run2], "provider", "unknown") or "unknown"),
                model=str(getattr(run_map[run2], "model", "unknown") or "unknown"),
                status=run_map[run2].status,
                created_at=run_map[run2].created_at,
            ),
            comparison=comparison,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compare evaluation runs.",
        ) from exc


@dashboard_router.get("/summary/{dataset_id}", response_model=DashboardSummaryResponse)
def get_dashboard_summary(
    dataset_id: str,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> DashboardSummaryResponse:
    try:
        dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
        if dataset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset not found: {dataset_id}",
            )
        effective_project_id = _resolve_eval_project_id(dataset, project_id)
        _require_dataset_access(db, dataset, current_user_id, effective_project_id)

        total_runs = db.scalar(
            select(func.count(EvalRun.id)).where(EvalRun.dataset_id == dataset_id)
        ) or 0

        latest_run = db.scalar(
            select(EvalRun)
            .where(EvalRun.dataset_id == dataset_id)
            .order_by(EvalRun.created_at.desc())
        )

        latest_scores = {
            "faithfulness": 0.0,
            "relevance": 0.0,
            "completeness": 0.0,
            "hallucination": 0.0,
        }
        if latest_run is not None:
            metric_rows = db.execute(
                select(
                    EvalResult.metric_name,
                    func.avg(EvalResult.score),
                )
                .where(EvalResult.eval_run_id == latest_run.id)
                .group_by(EvalResult.metric_name)
            ).all()
            for metric_name, avg_score in metric_rows:
                if metric_name in latest_scores:
                    latest_scores[metric_name] = float(avg_score or 0.0)

        trend_rows = db.execute(
            select(
                EvalRun.created_at,
                func.avg(EvalResult.score),
            )
            .join(EvalResult, EvalResult.eval_run_id == EvalRun.id)
            .where(EvalRun.dataset_id == dataset_id)
            .group_by(EvalRun.id, EvalRun.created_at)
            .order_by(EvalRun.created_at.asc())
        ).all()

        trend = [
            DashboardTrendPoint(
                date=created_at.date().isoformat() if hasattr(created_at, "date") else str(created_at),
                score=float(avg_score or 0.0),
            )
            for created_at, avg_score in trend_rows
        ]

        return DashboardSummaryResponse(
            total_runs=int(total_runs),
            latest_scores=latest_scores,
            trend=trend,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load dashboard summary.",
        ) from exc


@dashboard_router.get("/project/{project_id}", response_model=DashboardProjectResponse)
def get_project_dashboard(
    project_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> DashboardProjectResponse:
    try:
        _require_project_dashboard_access(db, project_id, current_user_id)

        counts_row = db.execute(
            select(
                select(func.count(Trace.id))
                .where(Trace.project_id == project_id)
                .scalar_subquery()
                .label("total_traces"),
                select(func.count(Dataset.id))
                .where(Dataset.project_id == project_id)
                .scalar_subquery()
                .label("total_datasets"),
            )
        ).one()

        avg_score_rows = db.execute(
            select(
                EvalResult.metric_name,
                func.avg(EvalResult.score).label("avg_score"),
            )
            .join(EvalRun, EvalRun.id == EvalResult.eval_run_id)
            .where(EvalRun.project_id == project_id)
            .group_by(EvalResult.metric_name)
            .order_by(EvalResult.metric_name.asc())
        ).all()

        recent_alert_rows = db.scalars(
            select(Alert)
            .join(EvalRun, EvalRun.id == Alert.eval_run_id)
            .where(EvalRun.project_id == project_id)
            .order_by(Alert.created_at.desc())
            .limit(10)
        ).all()

        avg_scores = {
            str(metric_name): float(avg_score or 0.0)
            for metric_name, avg_score in avg_score_rows
        }

        recent_alerts = [
            DashboardAlertItem.model_validate(alert)
            for alert in recent_alert_rows
        ]

        return DashboardProjectResponse(
            total_traces=int(counts_row.total_traces or 0),
            total_datasets=int(counts_row.total_datasets or 0),
            avg_scores=avg_scores,
            recent_alerts=recent_alerts,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load project dashboard.",
        ) from exc
