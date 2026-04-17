from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Dataset, EvalRun, Project, Trace, User  # noqa: E402


LEGACY_PROJECT_NAME = "legacy-import"
SYSTEM_USER_EMAIL = "system@local"


def _get_or_create_user(db):
    user = db.scalar(select(User).order_by(User.created_at.asc()))
    if user is not None:
        if not user.email:
            user.email = SYSTEM_USER_EMAIL
        if not user.role:
            user.role = "system"
        return user

    user = User(
        email=SYSTEM_USER_EMAIL,
        password_hash=None,
        role="system",
    )
    db.add(user)
    db.flush()
    return user


def _get_or_create_user_by_email(db, email: str) -> User:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is not None:
        if not user.role:
            user.role = "system"
        return user

    user = User(
        email=normalized_email,
        password_hash=None,
        role="system",
    )
    db.add(user)
    db.flush()
    return user


def _get_or_create_project(db, owner: User, project_name: str) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.owner_id == owner.id,
            Project.name == project_name,
        )
    )
    if project is not None:
        return project

    project = Project(name=project_name, owner_id=owner.id)
    db.add(project)
    db.flush()
    return project


def _resolve_target_project(
    db,
    *,
    project_id: str | None,
    project_name: str | None,
    owner_email: str | None,
) -> Project:
    if project_id:
        project = db.scalar(select(Project).where(Project.id == project_id))
        if project is None:
            raise ValueError(f"Project not found: {project_id}")
        return project

    owner = _get_or_create_user_by_email(db, owner_email) if owner_email else _get_or_create_user(db)
    target_name = project_name or LEGACY_PROJECT_NAME
    return _get_or_create_project(db, owner, target_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill project_id for legacy Eval-DB rows.")
    parser.add_argument(
        "--project-id",
        default=None,
        help="Existing target project ID to assign records to.",
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="Create or reuse a target project by name when --project-id is not provided.",
    )
    parser.add_argument(
        "--owner-email",
        default=None,
        help="Owner email to associate with a created target project.",
    )
    parser.add_argument(
        "--all-records",
        action="store_true",
        help="Reassign records even if they already have a project_id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without writing any changes.",
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        project = _resolve_target_project(
            session,
            project_id=args.project_id,
            project_name=args.project_name,
            owner_email=args.owner_email,
        )

        trace_query = select(Trace)
        dataset_query = select(Dataset)
        eval_run_query = select(EvalRun)
        if not args.all_records:
            trace_query = trace_query.where(Trace.project_id.is_(None))
            dataset_query = dataset_query.where(Dataset.project_id.is_(None))
            eval_run_query = eval_run_query.where(EvalRun.project_id.is_(None))

        traces = list(session.scalars(trace_query))
        datasets = list(session.scalars(dataset_query))
        eval_runs = list(session.scalars(eval_run_query))

        print(
            f"Target project: {project.id} ({project.name}), owner: {project.owner_id}"
        )
        print(
            "Rows to backfill:",
            f"traces={len(traces)}",
            f"datasets={len(datasets)}",
            f"eval_runs={len(eval_runs)}",
        )

        if args.dry_run:
            print("Dry run only. No changes written.")
            return 0

        for trace in traces:
            trace.project_id = project.id

        for dataset in datasets:
            dataset.project_id = project.id

        for eval_run in eval_runs:
            eval_run.project_id = project.id

        session.commit()
        print("Backfill completed successfully.")
        return 0
    except Exception as exc:
        session.rollback()
        print(f"Backfill failed: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
