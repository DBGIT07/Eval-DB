from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Dataset, DatasetSample, Project, Trace
from app.schemas import (
    DatasetCreate,
    DatasetFullResponse,
    DatasetResponse,
    DatasetSampleCreate,
    DatasetSampleResponse,
    DatasetSampleUpdate,
    DatasetSamplesFromTracesCreate,
    DatasetUpdate,
)
from app.security import (
    get_current_user_id,
    get_current_user_id_optional,
    get_project_id_from_api_key,
    get_project_id_from_api_key_optional,
    require_project_access,
)


router = APIRouter(tags=["dataset"])


def _sample_data_from_trace(trace: Trace) -> dict[str, object]:
    return {
        "query": trace.prompt,
        "answer": trace.response,
        "sources": trace.context or [],
        "metadata": {
            "trace_id": trace.id,
            "source": "trace",
        },
    }


def _create_sample_from_trace(dataset_id: str, trace: Trace) -> DatasetSample:
    return DatasetSample(
        dataset_id=dataset_id,
        input=trace.prompt,
        context=trace.context,
        tags=[],
        expected_output=trace.response,
        data=_sample_data_from_trace(trace),
    )


def _create_sample_from_payload(dataset_id: str, payload: DatasetSampleCreate) -> DatasetSample:
    return DatasetSample(
        dataset_id=dataset_id,
        input=payload.input,
        context=payload.context,
        tags=payload.tags,
        expected_output=payload.expected_output,
        data=payload.data,
    )


def _visible_dataset_query(db: Session, current_user_id: str | None, project_id: str | None = None):
    query = select(Dataset).order_by(Dataset.created_at.desc())

    if project_id is not None:
        require_project_access(db, project_id, current_user_id)
        return query.where(Dataset.project_id == project_id)

    if current_user_id is None:
        return query

    owned_project_ids = select(Project.id).where(Project.owner_id == current_user_id)
    return query.where(
        or_(
            Dataset.project_id.is_(None),
            Dataset.project_id.in_(owned_project_ids),
        )
    )


def _require_dataset_access(db: Session, dataset: Dataset, current_user_id: str | None) -> None:
    if dataset.project_id is None:
        return
    require_project_access(db, dataset.project_id, current_user_id)


def _resolve_effective_project_id(
    dataset: Dataset | None,
    current_user_id: str | None,
    project_id_from_api_key: str | None,
) -> str | None:
    if project_id_from_api_key is not None:
        return project_id_from_api_key
    if dataset is not None and dataset.project_id is not None:
        return dataset.project_id
    return None


@router.post("", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: DatasetCreate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id_from_api_key: str | None = Depends(get_project_id_from_api_key_optional),
) -> Dataset:
    effective_project_id = project_id_from_api_key or payload.project_id
    if effective_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization is required to create a dataset.",
        )

    if project_id_from_api_key is not None:
        if payload.project_id is not None and payload.project_id != project_id_from_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the requested project.",
            )
    else:
        require_project_access(db, effective_project_id, current_user_id)

    dataset = Dataset(name=payload.name, task_type=payload.task_type, project_id=effective_project_id)
    try:
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create dataset.",
        ) from exc
    return dataset


@router.get("", response_model=list[DatasetResponse])
def list_datasets(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[Dataset]:
    return list(db.scalars(_visible_dataset_query(db, current_user_id, project_id)))


@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
    )
    _require_dataset_access(db, dataset, current_user_id)
    return dataset


@router.get("/{dataset_id}/full", response_model=DatasetFullResponse)
def get_dataset_full(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> DatasetFullResponse:
    dataset = db.scalar(
        select(Dataset)
        .options(selectinload(Dataset.samples))
        .where(Dataset.id == dataset_id)
    )
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    _require_dataset_access(db, dataset, current_user_id)

    return DatasetFullResponse.model_validate(
        {
            "id": dataset.id,
            "project_id": dataset.project_id,
            "name": dataset.name,
            "task_type": dataset.task_type,
            "created_at": dataset.created_at,
            "samples": dataset.samples,
        }
    )


@router.patch("/{dataset_id}", response_model=DatasetResponse)
def update_dataset(
    dataset_id: str,
    payload: DatasetUpdate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    _require_dataset_access(db, dataset, current_user_id)

    if payload.name is not None:
        dataset.name = payload.name
    if payload.task_type is not None:
        dataset.task_type = payload.task_type
    if payload.project_id is not None:
        require_project_access(db, payload.project_id, current_user_id)
        dataset.project_id = payload.project_id

    try:
        db.commit()
        db.refresh(dataset)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update dataset.",
        ) from exc

    return dataset


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> None:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    _require_dataset_access(db, dataset, current_user_id)

    try:
        db.delete(dataset)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete dataset.",
        ) from exc


@router.post(
    "/{dataset_id}/samples",
    response_model=DatasetSampleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_sample(
    dataset_id: str,
    payload: DatasetSampleCreate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id_from_api_key: str | None = Depends(get_project_id_from_api_key_optional),
) -> DatasetSample:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    effective_project_id = _resolve_effective_project_id(dataset, current_user_id, project_id_from_api_key)
    if effective_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization is required to create dataset samples.",
        )

    if project_id_from_api_key is not None:
        if dataset.project_id is not None and dataset.project_id != project_id_from_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the dataset project.",
            )
    else:
        require_project_access(db, effective_project_id, current_user_id)
        if dataset.project_id is None:
            dataset.project_id = effective_project_id

    sample = _create_sample_from_payload(dataset_id, payload)

    try:
        db.add(sample)
        db.commit()
        db.refresh(sample)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create dataset sample.",
        ) from exc

    return sample


@router.post(
    "/{dataset_id}/bulk",
    response_model=list[DatasetSampleResponse],
    status_code=status.HTTP_201_CREATED,
)
def bulk_create_dataset_samples(
    dataset_id: str,
    payload: list[DatasetSampleCreate],
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id_from_api_key: str | None = Depends(get_project_id_from_api_key_optional),
) -> list[DatasetSample]:
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one sample must be provided.",
        )

    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    effective_project_id = _resolve_effective_project_id(dataset, current_user_id, project_id_from_api_key)
    if effective_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization is required to create dataset samples.",
        )

    if project_id_from_api_key is not None:
        if dataset.project_id is not None and dataset.project_id != project_id_from_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the dataset project.",
            )
    else:
        require_project_access(db, effective_project_id, current_user_id)
        if dataset.project_id is None:
            dataset.project_id = effective_project_id

    samples = [_create_sample_from_payload(dataset_id, item) for item in payload]

    try:
        db.add_all(samples)
        db.commit()
        for sample in samples:
            db.refresh(sample)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to bulk create dataset samples.",
        ) from exc

    return samples


@router.post(
    "/{dataset_id}/from-trace/{trace_id}",
    response_model=DatasetSampleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_sample_from_trace(
    dataset_id: str,
    trace_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id_from_api_key: str | None = Depends(get_project_id_from_api_key_optional),
) -> DatasetSample:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    effective_project_id = _resolve_effective_project_id(dataset, current_user_id, project_id_from_api_key)
    if effective_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization is required to create dataset samples.",
        )
    if project_id_from_api_key is not None:
        if dataset.project_id is not None and dataset.project_id != project_id_from_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the dataset project.",
            )
    else:
        require_project_access(db, effective_project_id, current_user_id)
        if dataset.project_id is None:
            dataset.project_id = effective_project_id

    trace = db.scalar(select(Trace).where(Trace.id == trace_id))
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace not found.",
        )
    if project_id_from_api_key is not None:
        if trace.project_id is not None and trace.project_id != project_id_from_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the trace project.",
            )
    else:
        require_project_access(db, effective_project_id, current_user_id)
        if trace.project_id is not None and trace.project_id != effective_project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trace does not belong to the requested project.",
            )

    sample = _create_sample_from_trace(dataset.id, trace)

    try:
        db.add(sample)
        db.commit()
        db.refresh(sample)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create dataset sample from trace.",
        ) from exc

    return sample


@router.post(
    "/{dataset_id}/from-traces",
    response_model=list[DatasetSampleResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_samples_from_traces(
    dataset_id: str,
    payload: DatasetSamplesFromTracesCreate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id_optional),
    project_id_from_api_key: str | None = Depends(get_project_id_from_api_key_optional),
) -> list[DatasetSample]:
    if not payload.trace_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one trace_id must be provided.",
        )

    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    effective_project_id = _resolve_effective_project_id(dataset, current_user_id, project_id_from_api_key)
    if effective_project_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization is required to create dataset samples.",
        )
    if project_id_from_api_key is not None:
        if dataset.project_id is not None and dataset.project_id != project_id_from_api_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key project does not match the dataset project.",
            )
    else:
        require_project_access(db, effective_project_id, current_user_id)
        if dataset.project_id is None:
            dataset.project_id = effective_project_id

    trace_ids = list(dict.fromkeys(payload.trace_ids))
    traces = list(db.scalars(select(Trace).where(Trace.id.in_(trace_ids))))
    trace_map = {trace.id: trace for trace in traces}

    missing_trace_ids = [trace_id for trace_id in trace_ids if trace_id not in trace_map]
    if missing_trace_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace not found: {missing_trace_ids[0]}",
        )

    for trace in trace_map.values():
        if project_id_from_api_key is not None:
            if trace.project_id is not None and trace.project_id != project_id_from_api_key:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key project does not match the trace project.",
                )
        else:
            require_project_access(db, effective_project_id, current_user_id)
            if trace.project_id is not None and trace.project_id != effective_project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Trace does not belong to the requested project.",
                )

    samples = [_create_sample_from_trace(dataset.id, trace_map[trace_id]) for trace_id in trace_ids]

    try:
        db.add_all(samples)
        db.commit()
        for sample in samples:
            db.refresh(sample)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create dataset samples from traces.",
        ) from exc

    return samples


@router.get("/{dataset_id}/samples", response_model=list[DatasetSampleResponse])
def list_dataset_samples(
    dataset_id: str,
    tag: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> list[DatasetSample]:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )
    _require_dataset_access(db, dataset, current_user_id)

    query = (
        select(DatasetSample)
        .where(DatasetSample.dataset_id == dataset_id)
        .order_by(DatasetSample.created_at.desc())
    )
    if tag:
        query = query.where(
            text("EXISTS (SELECT 1 FROM json_each(dataset_samples.tags) WHERE json_each.value = :tag)")
        ).params(tag=tag)

    return list(
        db.scalars(query)
    )


@router.get("/samples/{sample_id}", response_model=DatasetSampleResponse)
def get_dataset_sample(
    sample_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> DatasetSample:
    sample = db.scalar(select(DatasetSample).where(DatasetSample.id == sample_id))
    if sample is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset sample not found.",
        )
    dataset = db.scalar(select(Dataset).where(Dataset.id == sample.dataset_id))
    if dataset is not None:
        _require_dataset_access(db, dataset, current_user_id)
    return sample


@router.patch("/samples/{sample_id}", response_model=DatasetSampleResponse)
def update_dataset_sample(
    sample_id: str,
    payload: DatasetSampleUpdate,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> DatasetSample:
    sample = db.scalar(select(DatasetSample).where(DatasetSample.id == sample_id))
    if sample is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset sample not found.",
        )
    dataset = db.scalar(select(Dataset).where(Dataset.id == sample.dataset_id))
    if dataset is not None:
        _require_dataset_access(db, dataset, current_user_id)

    if payload.input is not None:
        sample.input = payload.input
    if payload.context is not None:
        sample.context = payload.context
    if payload.tags is not None:
        sample.tags = payload.tags
    if payload.expected_output is not None:
        sample.expected_output = payload.expected_output
    if payload.data is not None:
        sample.data = payload.data

    try:
        db.commit()
        db.refresh(sample)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update dataset sample.",
        ) from exc

    return sample


@router.delete("/samples/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset_sample(
    sample_id: str,
    db: Session = Depends(get_db),
    current_user_id: str | None = Depends(get_current_user_id),
) -> None:
    sample = db.scalar(select(DatasetSample).where(DatasetSample.id == sample_id))
    if sample is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset sample not found.",
        )
    dataset = db.scalar(select(Dataset).where(Dataset.id == sample.dataset_id))
    if dataset is not None:
        _require_dataset_access(db, dataset, current_user_id)

    try:
        db.delete(sample)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete dataset sample.",
        ) from exc
