import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import Base, engine
from app.routes.auth import router as auth_router
from app.eval.api import benchmark_router, dashboard_router, router as eval_router
from app.routes.api_keys import router as api_keys_router
from app.routes.dataset import router as dataset_router
from app.routes.project import router as project_router
from app.routes.ui import router as ui_router
from app.routes.trace import router as trace_router
from app.models import APIKey, Dataset, DatasetSample, EvalResult, Project, Trace, User  # noqa: F401


package_root = Path(__file__).resolve().parent

app = FastAPI(title="Trace API", version="1.0.0")
templates = Jinja2Templates(directory=str(package_root / "templates"))

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

static_dir = package_root / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    # Creates tables if they do not already exist.
    Base.metadata.create_all(bind=engine)


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                message = first.get("msg") or first.get("message")
                if isinstance(message, str) and message.strip():
                    return message
            return str(first)
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            message = first.get("msg") or first.get("message")
            if isinstance(message, str) and message.strip():
                return message
        return str(first)
    return "An unexpected error occurred."


def _filtered_headers(response) -> dict[str, str]:
    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers.pop("content-type", None)
    return headers


@app.middleware("http")
async def standardize_api_responses(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    path = request.url.path

    if (
        path.startswith("/ui/")
        or path in {"/openapi.json", "/docs", "/redoc"}
        or content_type.startswith("text/html")
    ):
        return response

    if response.status_code == 204:
        return JSONResponse(
            status_code=200,
            content={"status": "success", "data": None, "error": None},
        )

    if not content_type.startswith("application/json") and not content_type.startswith("application/problem+json"):
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    if not body:
        payload = None
    else:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return response

    if response.status_code >= 400:
        return JSONResponse(
            status_code=response.status_code,
            content={
                "status": "error",
                "data": None,
                "error": _extract_error_message(payload),
            },
            headers=_filtered_headers(response),
        )

    if isinstance(payload, dict) and set(payload.keys()) == {"status", "data", "error"}:
        return JSONResponse(
            status_code=response.status_code,
            content=payload,
            headers=_filtered_headers(response),
        )

    return JSONResponse(
        status_code=response.status_code,
        content={"status": "success", "data": payload, "error": None},
        headers=_filtered_headers(response),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "data": None,
            "error": _extract_error_message({"detail": exc.detail}),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = exc.errors()
    message = "Invalid request."
    if errors:
        first_error = errors[0]
        message = str(first_error.get("msg") or message)

    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "data": None,
            "error": message,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception for %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "data": None,
            "error": "An unexpected error occurred.",
        },
    )


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "message": "Trace API is running"}


app.include_router(trace_router)
app.include_router(auth_router)
app.include_router(api_keys_router)
app.include_router(project_router)
app.include_router(dataset_router, prefix="/dataset")
app.include_router(eval_router)
app.include_router(benchmark_router)
app.include_router(dashboard_router)
app.include_router(ui_router, prefix="/ui")
