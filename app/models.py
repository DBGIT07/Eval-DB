from datetime import datetime
from enum import Enum
from uuid import uuid4
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, JSON, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EvalRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True, default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    projects: Mapped[list["Project"]] = relationship(
        back_populates="owner",
        passive_deletes=True,
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    owner: Mapped["User"] = relationship(back_populates="projects")
    traces: Mapped[list["Trace"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )
    datasets: Mapped[list["Dataset"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )
    eval_runs: Mapped[list["EvalRun"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )
    api_keys: Mapped[list["APIKey"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )


class Trace(Base):
    __tablename__ = "traces"
    __table_args__ = (Index("ix_traces_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    context: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_feedback_rating: Mapped[str | None] = mapped_column(String(10), nullable=True)
    user_feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    project: Mapped["Project | None"] = relationship(back_populates="traces")
    eval_results: Mapped[list["EvalResult"]] = relationship(
        back_populates="trace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (Index("ix_datasets_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    samples: Mapped[list["DatasetSample"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    project: Mapped["Project | None"] = relationship(back_populates="datasets")
    eval_results: Mapped[list["EvalResult"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    eval_runs: Mapped[list["EvalRun"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DatasetSample(Base):
    __tablename__ = "dataset_samples"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    input: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="samples")
    eval_results: Mapped[list["EvalResult"]] = relationship(
        back_populates="sample",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def _data_payload(self) -> dict[str, Any] | None:
        return self.data if isinstance(self.data, dict) else None

    def resolved_input(self) -> str:
        if isinstance(self.input, str) and self.input.strip():
            return self.input

        payload = self._data_payload()
        if payload is not None:
            candidate = payload.get("query", payload.get("input"))
            if isinstance(candidate, str) and candidate.strip():
                return candidate
            if candidate is not None:
                return str(candidate)

        return ""

    def resolved_context(self) -> list[Any]:
        if self.context is not None:
            return self.context if isinstance(self.context, list) else [self.context]

        payload = self._data_payload()
        if payload is not None:
            candidate = payload.get("sources", payload.get("context"))
            if candidate is None:
                return []
            if isinstance(candidate, list):
                return candidate
            return [candidate]

        return []

    def resolved_expected_output(self) -> str:
        if isinstance(self.expected_output, str) and self.expected_output.strip():
            return self.expected_output

        payload = self._data_payload()
        if payload is not None:
            candidate = payload.get("answer", payload.get("expected_output"))
            if isinstance(candidate, str) and candidate.strip():
                return candidate
            if candidate is not None:
                return str(candidate)

        return ""


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("ix_eval_runs_dataset_id", "dataset_id"),
        Index("ix_eval_runs_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    experiment_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    variant: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    config: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[EvalRunStatus] = mapped_column(
        SAEnum(EvalRunStatus, name="eval_run_status", native_enum=False),
        default=EvalRunStatus.RUNNING,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="eval_runs")
    project: Mapped["Project | None"] = relationship(back_populates="eval_runs")
    eval_results: Mapped[list["EvalResult"]] = relationship(
        back_populates="eval_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="eval_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_eval_run_id", "eval_run_id"),
        Index("ix_alerts_severity", "severity"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    eval_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="warning")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    eval_run: Mapped["EvalRun"] = relationship(back_populates="alerts")


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )

    project: Mapped["Project"] = relationship(back_populates="api_keys")


class EvalResult(Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        Index("ix_eval_results_dataset_id", "dataset_id"),
        Index("ix_eval_results_eval_run_id", "eval_run_id"),
        Index("ix_eval_results_trace_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        unique=True,
        nullable=False,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    sample_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("dataset_samples.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    trace_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("traces.id", ondelete="CASCADE"),
        nullable=True,
    )
    eval_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    judge_model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="eval_results")
    sample: Mapped["DatasetSample | None"] = relationship(back_populates="eval_results")
    trace: Mapped["Trace | None"] = relationship(back_populates="eval_results")
    eval_run: Mapped["EvalRun"] = relationship(back_populates="eval_results")
