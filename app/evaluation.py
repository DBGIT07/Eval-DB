from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.eval.judge import Judge, MockJudge
from app.models import Dataset, DatasetSample


class EvaluationError(Exception):
    """Raised when evaluation cannot be completed."""


@dataclass(frozen=True)
class SampleEvaluationResult:
    sample_id: str
    score: float
    label: str
    reasoning: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    dataset_id: str
    metric: str
    score: float
    sample_results: list[SampleEvaluationResult] = field(default_factory=list)


def run_evaluation(
    dataset_id: str,
    metric: str,
    *,
    db: Session | None = None,
    judge: Judge | None = None,
    provider: str = "mock",
    model: str = "mock",
) -> EvaluationResult:
    """
    Evaluate every sample in a dataset and return an aggregate score.

    Args:
        dataset_id: Dataset identifier.
        metric: Name of the evaluation metric to apply.
        db: Optional SQLAlchemy session. If omitted, a session is created.
        judge: Judge implementation used to score each sample.

    Returns:
        EvaluationResult containing per-sample scores and the average score.
    """
    owns_session = db is None
    session = db or SessionLocal()
    active_judge = judge or MockJudge()

    try:
        dataset = session.scalar(select(Dataset).where(Dataset.id == dataset_id))
        if dataset is None:
            raise EvaluationError(f"Dataset not found: {dataset_id}")

        samples = list(
            session.scalars(
                select(DatasetSample)
                .where(DatasetSample.dataset_id == dataset_id)
                .order_by(DatasetSample.created_at.asc())
            )
        )

        if not samples:
            return EvaluationResult(dataset_id=dataset_id, metric=metric, score=0.0, sample_results=[])

        sample_results: list[SampleEvaluationResult] = []
        for sample in samples:
            prompt = sample.resolved_input()
            response = sample.resolved_expected_output()
            context = sample.resolved_context()
            judge_result: dict[str, Any] = active_judge.evaluate(
                prompt=prompt,
                response=response,
                context=context,
                provider=provider,
                model=model,
            )
            sample_score = float(judge_result["score"])
            sample_results.append(
                SampleEvaluationResult(
                    sample_id=sample.id,
                    score=sample_score,
                    label=str(judge_result.get("label", "good")),
                    reasoning=judge_result.get("reasoning"),
                )
            )

        overall_score = float(mean(result.score for result in sample_results))
        return EvaluationResult(
            dataset_id=dataset_id,
            metric=metric,
            score=overall_score,
            sample_results=sample_results,
        )
    finally:
        if owns_session:
            session.close()
