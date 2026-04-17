from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TraceBase(BaseModel):
    project_id: str | None = None
    prompt: str
    response: str
    model: str = Field(..., max_length=255)
    context: Any | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class TraceCreate(TraceBase):
    pass


class TraceUpdate(BaseModel):
    prompt: str | None = None
    response: str | None = None
    model: str | None = Field(default=None, max_length=255)
    context: Any | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class TraceRead(TraceBase):
    id: str
    user_feedback_rating: str | None = None
    user_feedback_comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TraceListItem(BaseModel):
    id: str
    project_id: str | None = None
    prompt: str
    response: str
    model: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TraceResponse(TraceRead):
    pass


class TraceFeedbackCreate(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = None


class DatasetCreate(BaseModel):
    name: str
    task_type: str
    project_id: str | None = None


class DatasetUpdate(BaseModel):
    name: str | None = None
    task_type: str | None = None
    project_id: str | None = None


class DatasetResponse(BaseModel):
    id: str
    project_id: str | None = None
    name: str
    task_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DatasetFullResponse(DatasetResponse):
    samples: list["DatasetSampleResponse"] = Field(default_factory=list)


class DatasetSampleCreate(BaseModel):
    input: str | None = None
    context: list | None = None
    tags: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize_flexible_payload(self) -> "DatasetSampleCreate":
        payload = self.data if isinstance(self.data, dict) else None

        if self.input is None and payload is not None:
            candidate = payload.get("query", payload.get("input"))
            if isinstance(candidate, str) and candidate.strip():
                self.input = candidate

        if self.context is None and payload is not None:
            candidate = payload.get("sources", payload.get("context"))
            if candidate is not None:
                if isinstance(candidate, list):
                    self.context = candidate
                else:
                    self.context = [candidate]

        if self.expected_output is None and payload is not None:
            candidate = payload.get("answer", payload.get("expected_output"))
            if isinstance(candidate, str) and candidate.strip():
                self.expected_output = candidate

        if not self.tags and payload is not None:
            candidate = payload.get("tags")
            if isinstance(candidate, list):
                self.tags = [str(item) for item in candidate if str(item).strip()]

        if self.input is None or self.context is None or self.expected_output is None:
            raise ValueError(
                "Dataset sample requires either input/context/expected_output or a data payload with query/sources/answer."
            )

        return self


class DatasetSamplesFromTracesCreate(BaseModel):
    trace_ids: list[str] = Field(default_factory=list)


class DatasetSampleUpdate(BaseModel):
    input: str | None = None
    context: list | None = None
    tags: list[str] | None = None
    expected_output: str | None = None
    data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _normalize_flexible_payload(self) -> "DatasetSampleUpdate":
        payload = self.data if isinstance(self.data, dict) else None

        if self.input is None and payload is not None:
            candidate = payload.get("query", payload.get("input"))
            if isinstance(candidate, str) and candidate.strip():
                self.input = candidate

        if self.context is None and payload is not None:
            candidate = payload.get("sources", payload.get("context"))
            if candidate is not None:
                if isinstance(candidate, list):
                    self.context = candidate
                else:
                    self.context = [candidate]

        if self.expected_output is None and payload is not None:
            candidate = payload.get("answer", payload.get("expected_output"))
            if isinstance(candidate, str) and candidate.strip():
                self.expected_output = candidate

        if self.tags is None and payload is not None:
            candidate = payload.get("tags")
            if isinstance(candidate, list):
                self.tags = [str(item) for item in candidate if str(item).strip()]

        return self


class DatasetSampleResponse(BaseModel):
    id: str
    dataset_id: str
    input: str
    context: Any | None
    tags: list[str] | None = None
    expected_output: str
    data: Any | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default="user", max_length=50)

    @model_validator(mode="before")
    @classmethod
    def _normalize_email(cls, values: Any) -> Any:
        if isinstance(values, dict) and "email" in values:
            values = dict(values)
            values["email"] = str(values["email"] or "").strip().lower()
        return values


class UserLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)

    @model_validator(mode="before")
    @classmethod
    def _normalize_email(cls, values: Any) -> Any:
        if isinstance(values, dict) and "email" in values:
            values = dict(values)
            values["email"] = str(values["email"] or "").strip().lower()
        return values


class UserRead(BaseModel):
    id: str
    email: str | None = None
    role: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class APIKeyCreate(BaseModel):
    project_id: str
    name: str | None = Field(default=None, max_length=255)


class APIKeyCreateResponse(BaseModel):
    api_key: str
    name: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class ProjectRead(BaseModel):
    id: str
    name: str
    owner_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
