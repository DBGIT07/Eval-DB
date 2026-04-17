from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project
from app.schemas import ProjectCreate, ProjectRead
from app.security import get_current_user_id


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
def list_projects(
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[Project]:
    return list(
        db.query(Project)
        .filter(Project.owner_id == current_user_id)
        .order_by(Project.created_at.desc())
        .all()
    )


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> Project:
    project = Project(name=payload.name.strip(), owner_id=current_user_id)
    try:
        db.add(project)
        db.commit()
        db.refresh(project)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Failed to create project.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create project.",
        ) from exc
    return project

