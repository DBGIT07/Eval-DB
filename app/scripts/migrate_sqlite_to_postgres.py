from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    Alert,
    APIKey,
    Dataset,
    DatasetSample,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    Project,
    Trace,
    User,
)


COPY_ORDER = [
    User,
    Project,
    Trace,
    Dataset,
    DatasetSample,
    EvalRun,
    EvalResult,
    Alert,
    APIKey,
]

DELETE_ORDER = list(reversed(COPY_ORDER))


def _default_source_url() -> str:
    root = Path(__file__).resolve().parents[2]
    return f"sqlite:///{(root / 'ai_eval.db').as_posix()}"


def _default_target_url() -> str:
    return "postgresql+psycopg2://evaldb:evaldb@localhost:5432/evaldb"


def _row_data(source_obj: Any, model: type) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for column in model.__table__.columns:  # type: ignore[attr-defined]
        value = getattr(source_obj, column.name)
        if column.name == "status" and isinstance(value, str):
            value = EvalRunStatus(value)
        if model is EvalRun:
            if column.name == "provider" and not value:
                value = "mock"
            if column.name == "model" and not value:
                value = "mock"
        data[column.name] = value
    return data


def _count_rows(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy Eval-DB data from SQLite into PostgreSQL.")
    parser.add_argument("--source", default=_default_source_url(), help="SQLite source database URL.")
    parser.add_argument(
        "--target",
        default=_default_target_url(),
        help="Target PostgreSQL database URL.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete existing rows in the target database before copying.",
    )
    args = parser.parse_args()

    source_engine = create_engine(args.source, future=True)
    target_engine = create_engine(args.target, future=True)

    SourceSession = sessionmaker(bind=source_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    TargetSession = sessionmaker(bind=target_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    Base.metadata.create_all(bind=target_engine)

    source_session = SourceSession()
    target_session = TargetSession()

    try:
        source_counts = {model.__tablename__: _count_rows(source_session, model) for model in COPY_ORDER}
        target_counts = {model.__tablename__: _count_rows(target_session, model) for model in COPY_ORDER}

        if any(count > 0 for count in target_counts.values()) and not args.overwrite:
            print("Target database already contains data. Re-run with --overwrite to replace it.")
            print("Target counts:", target_counts)
            return 1

        if args.overwrite:
            for model in DELETE_ORDER:
                target_session.execute(delete(model))
            target_session.commit()

        copied_counts: dict[str, int] = {}
        for model in COPY_ORDER:
            rows = list(source_session.scalars(select(model)))
            for row in rows:
                target_session.add(model(**_row_data(row, model)))
            copied_counts[model.__tablename__] = len(rows)
            target_session.flush()

        target_session.commit()
        print("Migration completed successfully.")
        print("Source counts:", source_counts)
        print("Copied counts:", copied_counts)
        return 0
    except Exception as exc:
        target_session.rollback()
        print(f"Migration failed: {exc}")
        return 1
    finally:
        source_session.close()
        target_session.close()


if __name__ == "__main__":
    raise SystemExit(main())
