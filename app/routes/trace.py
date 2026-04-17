from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, Trace
from app.schemas import (
    TraceCreate,
    TraceFeedbackCreate,
    TraceListItem,
    TraceRead,
    TraceResponse,
    TraceUpdate,
)
from app.security import get_current_user_id, get_project_id_from_api_key, require_project_access


router = APIRouter(tags=["trace"])


def _visible_trace_query(db: Session, current_user_id: str | None, project_id: str | None = None):
    query = select(Trace).order_by(Trace.created_at.desc())

    if project_id is not None:
        require_project_access(db, project_id, current_user_id)
        return query.where(Trace.project_id == project_id)

    if current_user_id is None:
        return query

    owned_project_ids = select(Project.id).where(Project.owner_id == current_user_id)
    return query.where(
        or_(
            Trace.project_id.is_(None),
            Trace.project_id.in_(owned_project_ids),
        )
    )


def _require_trace_access(db: Session, trace: Trace, current_user_id: str | None) -> None:
    if trace.project_id is None:
        return
    require_project_access(db, trace.project_id, current_user_id)


@router.post("/trace", response_model=TraceResponse, status_code=status.HTTP_201_CREATED)
def create_trace(
    payload: TraceCreate,
    db: Session = Depends(get_db),
    project_id: str = Depends(get_project_id_from_api_key),
) -> Trace:
    if payload.project_id is not None and payload.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key project does not match the requested project.",
        )
    trace = Trace(
        project_id=project_id,
        prompt=payload.prompt,
        response=payload.response,
        model=payload.model,
        context=payload.context,
        latency_ms=payload.latency_ms,
    )

    try:
        db.add(trace)
        db.commit()
        db.refresh(trace)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save trace.",
        ) from exc

    return trace


@router.get("/trace", response_model=list[TraceRead])
def list_traces(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[Trace]:
    return list(db.scalars(_visible_trace_query(db, current_user_id, project_id)))


@router.get("/traces", response_model=list[TraceListItem])
def list_traces_paginated(
    limit: int = 50,
    offset: int = 0,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[Trace]:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    try:
        query = _visible_trace_query(db, current_user_id, project_id).limit(limit).offset(offset)
        return list(db.scalars(query))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load traces.",
        ) from exc


@router.get("/trace/{trace_id}", response_model=TraceRead)
def get_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> Trace:
    trace = db.scalar(select(Trace).where(Trace.id == trace_id))
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace not found.",
        )
    _require_trace_access(db, trace, current_user_id)
    return trace


@router.patch("/trace/{trace_id}", response_model=TraceRead)
def update_trace(
    trace_id: str,
    payload: TraceUpdate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> Trace:
    trace = db.scalar(select(Trace).where(Trace.id == trace_id))
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace not found.",
        )
    _require_trace_access(db, trace, current_user_id)

    if payload.project_id is not None:
        require_project_access(db, payload.project_id, current_user_id)
        trace.project_id = payload.project_id
    if payload.prompt is not None:
        trace.prompt = payload.prompt
    if payload.response is not None:
        trace.response = payload.response
    if payload.model is not None:
        trace.model = payload.model
    if payload.context is not None:
        trace.context = payload.context
    if payload.latency_ms is not None:
        trace.latency_ms = payload.latency_ms

    db.commit()
    db.refresh(trace)
    return trace


@router.delete("/trace/{trace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trace(
    trace_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> None:
    trace = db.scalar(select(Trace).where(Trace.id == trace_id))
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace not found.",
        )
    _require_trace_access(db, trace, current_user_id)

    db.delete(trace)
    db.commit()


@router.post("/trace/{trace_id}/feedback", response_model=TraceResponse)
def add_trace_feedback(
    trace_id: str,
    payload: TraceFeedbackCreate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> Trace:
    trace = db.scalar(select(Trace).where(Trace.id == trace_id))
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace not found.",
        )
    _require_trace_access(db, trace, current_user_id)

    trace.user_feedback_rating = payload.rating
    trace.user_feedback_comment = payload.comment

    try:
        db.commit()
        db.refresh(trace)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save feedback.",
        ) from exc

    return trace
