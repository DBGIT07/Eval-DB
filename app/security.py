from __future__ import annotations

from collections.abc import Iterable

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import bearer_scheme, get_current_user as _auth_get_current_user
from app.database import get_db
from app.models import APIKey, Project, User
from app.utils.security import hash_api_key


api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, description="Project API key used for trace ingestion.")


def get_current_user_id(user: User = Depends(_auth_get_current_user)) -> str:
    return user.id


def get_current_user_id_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> str | None:
    if credentials is None or not credentials.credentials.strip():
        return None

    user = _auth_get_current_user(credentials=credentials, db=db)
    return user.id


def get_current_user(user: User = Depends(_auth_get_current_user)) -> User:
    return user


def require_authenticated_user(user: User = Depends(_auth_get_current_user)) -> User:
    return user


def require_project_access(
    db: Session,
    project_id: str | None,
    user_id: str | None,
) -> Project | None:
    if project_id is None:
        return None

    project = db.scalar(select(Project).where(Project.id == project_id))
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization is required for project-scoped requests.",
        )

    if project.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project.",
        )

    return project


def require_project_owner(
    db: Session,
    project_id: str | None,
    user_id: str | None,
) -> Project | None:
    return require_project_access(db, project_id, user_id)


def visible_project_ids(db: Session, user_id: str | None) -> Iterable[str]:
    if user_id is None:
        return ()

    rows = db.scalars(select(Project.id).where(Project.owner_id == user_id))
    return list(rows)


def get_project_id_from_api_key(
    x_api_key: str | None = Security(api_key_scheme),
    db: Session = Depends(get_db),
) -> str:
    if x_api_key is None or not x_api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    key_hash = hash_api_key(x_api_key.strip())
    api_key = db.scalar(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.revoked.is_(False),
        )
    )
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )

    return api_key.project_id


def get_project_id_from_api_key_optional(
    x_api_key: str | None = Security(api_key_scheme),
    db: Session = Depends(get_db),
) -> str | None:
    if x_api_key is None or not x_api_key.strip():
        return None

    return get_project_id_from_api_key(x_api_key=x_api_key, db=db)
