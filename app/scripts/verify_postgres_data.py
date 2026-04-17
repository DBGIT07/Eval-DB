from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Alert,
    APIKey,
    Dataset,
    DatasetSample,
    EvalResult,
    EvalRun,
    Project,
    Trace,
    User,
)


MODELS = [
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


def _default_source_url() -> str:
    root = Path(__file__).resolve().parents[2]
    return f"sqlite:///{(root / 'ai_eval.db').as_posix()}"


def _default_database_url() -> str:
    return "postgresql+psycopg2://evaldb:evaldb@localhost:5432/evaldb"


def _count_rows(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print table counts for a PostgreSQL Eval-DB database.")
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--source", default=_default_source_url())
    args = parser.parse_args()

    source_engine = create_engine(args.source, future=True)
    engine = create_engine(args.database_url, future=True)
    SourceSession = sessionmaker(bind=source_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    source_session = SourceSession()
    session = SessionLocal()
    try:
        source_counts = {model.__tablename__: _count_rows(source_session, model) for model in MODELS}
        target_counts = {model.__tablename__: _count_rows(session, model) for model in MODELS}
        print("SQLite counts:", source_counts)
        print("Postgres counts:", target_counts)
        if source_counts != target_counts:
            print("Counts do not match.")
            return 1
        return 0
    except Exception as exc:
        print(f"Verification failed: {exc}")
        return 1
    finally:
        source_session.close()
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
