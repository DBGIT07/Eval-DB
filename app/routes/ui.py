from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Dataset, EvalResult, EvalRun, Trace

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

router = APIRouter(tags=["ui"])


@router.get("/traces")
def traces_page(request: Request, db: Session = Depends(get_db)):
    traces = list(db.scalars(select(Trace).order_by(Trace.created_at.desc())))
    return templates.TemplateResponse(
        request,
        "traces.html",
        {"traces": traces},
    )


@router.get("/datasets")
def datasets_page(request: Request, db: Session = Depends(get_db)):
    datasets = list(db.scalars(select(Dataset).order_by(Dataset.created_at.desc())))
    return templates.TemplateResponse(
        request,
        "datasets.html",
        {"datasets": datasets},
    )


@router.get("/evals")
def evals_page(
    request: Request,
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = select(EvalResult)
    if project_id:
        query = query.join(EvalRun, EvalRun.id == EvalResult.eval_run_id).where(EvalRun.project_id == project_id)

    results = list(db.scalars(query.order_by(EvalResult.created_at.desc())))
    return templates.TemplateResponse(
        request,
        "evals.html",
        {"results": results, "project_id": project_id},
    )


@router.get("/benchmark")
def benchmark_page(request: Request):
    return templates.TemplateResponse(
        request,
        "benchmark.html",
        {},
    )
