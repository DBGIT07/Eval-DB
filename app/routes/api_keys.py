from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import APIKey
from app.schemas import APIKeyCreate, APIKeyCreateResponse
from app.security import get_current_user_id, require_project_access
from app.utils.security import generate_api_key, hash_api_key


router = APIRouter(prefix="/api-keys", tags=["api-keys"])

@router.post("", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: APIKeyCreate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> APIKeyCreateResponse:
    require_project_access(db, payload.project_id, current_user_id)

    raw_key = generate_api_key()
    api_key = APIKey(
        key_hash=hash_api_key(raw_key),
        name=payload.name.strip() if isinstance(payload.name, str) and payload.name.strip() else None,
        project_id=payload.project_id,
    )

    try:
        db.add(api_key)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Failed to create API key.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create API key.",
        ) from exc

    return APIKeyCreateResponse(api_key=raw_key, name=api_key.name)
