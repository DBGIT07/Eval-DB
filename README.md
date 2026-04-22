# Eval-DB

## Docker Setup

This project ships with Docker support for the FastAPI app, the React UI, and Postgres.

### Quick Start

1. Copy `.env.example` to `.env`
1. Fill in any API keys or local overrides you want to use.
1. Start the stack:

```bash
docker compose up --build
```

Open the UI at `http://localhost:4173`.

On Windows Command Prompt, you can also run:

```bat
setup.bat
```

### Environment Variables

The app reads configuration from `.env` through Docker Compose.

When you run via Docker Compose, the app container points at the Postgres
service automatically. The `DATABASE_URL` value in `.env` is also required for
running host-side scripts.

Required variables:

- `DATABASE_URL`
- `JWT_SECRET_KEY`

The application no longer falls back to SQLite. If `DATABASE_URL` is missing,
startup will fail.

Optional app/runtime variables:

- `JWT_ALGORITHM`
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`
- `EVAL_DEFAULT_PROVIDER`
- `EVAL_DEFAULT_MODEL`
- `EVAL_FALLBACK_PROVIDER`
- `EVAL_MAX_CONCURRENT_JOBS`
- `EVAL_RESPECT_RETRY_AFTER`
- `EVAL_ASYNC_MIN_SAMPLES`
- `UI_DEFAULT_PROVIDER`
- `UI_DEFAULT_MODEL`
- `UI_SHOW_PROVIDER_SELECTOR`
- `EVAL_JUDGE_MAX_PROMPT_CHARS`
- `EVAL_JUDGE_MAX_RESPONSE_CHARS`
- `EVAL_JUDGE_MAX_CONTEXT_ITEMS`
- `EVAL_JUDGE_MAX_CONTEXT_ITEM_CHARS`
- `EVAL_JUDGE_MAX_CONTEXT_CHARS`
- `GROQ_JUDGE_MAX_ATTEMPTS`
- `GROQ_JUDGE_RETRY_BASE_DELAY_SECONDS`
- `GROQ_JUDGE_RETRY_BACKOFF_MULTIPLIER`
- `GROQ_JUDGE_RETRY_MAX_DELAY_SECONDS`
- `GROQ_JUDGE_TIMEOUT_SECONDS`
- `GROQ_JUDGE_SDK_MAX_RETRIES`

### Commands

Build and start the UI, app, and Postgres:

```bash
docker compose up --build
```

Stop everything:

```bash
docker compose down
```

View logs:

```bash
docker compose logs -f
```

If you prefer `make`, the same commands are available:

```bash
make up
make down
make logs
```

### Migrating Existing Data

If you already have data in the root `ai_eval.db` SQLite file, migrate it into
Postgres once after the database container is up:

```bash
docker compose up -d db
python -m app.scripts.migrate_sqlite_to_postgres --target postgresql+psycopg2://evaldb:evaldb@localhost:5432/evaldb
```

If the target database already has rows, re-run with `--overwrite` to replace
them.

To confirm the data landed in Postgres, run:

```bash
python -m app.scripts.verify_postgres_data
```

### Authentication

Register and login through:

- `POST /auth/register`
- `POST /auth/login`

Use the returned token as:

```bash
Authorization: Bearer <access_token>
```

In Swagger UI, use the `HTTPBearer` authorization button to paste the raw JWT
access token directly for user-authenticated endpoints. `POST /auth/login`
still expects JSON `{"email": "...", "password": "..."}`.

The `X-API-Key` header is only for trace ingestion on `POST /trace`.

### Ports

- React UI: `4173`
- FastAPI app: `8000`
- Postgres: `5432`
