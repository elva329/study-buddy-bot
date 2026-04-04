# Study Buddy Bot

Cloud-deployed Telegram chatbot powered by HKBU OpenAI LLM for study support (PDF Q&A, quiz, summaries, and study planning), with Docker + CI/CD + monitoring.

## Implemented Features
- Telegram bot commands:
  - `/start`
  - `/ask`
  - `/quiz`
  - `/progress`
  - `/summarize`
  - `/plan`
  - `/endsession`
- LLM integration via REST API
- PDF upload and retrieval-augmented Q&A
- Database logging for messages, events, and quiz records
- Monitoring endpoints (`/health`, `/metrics`)
- Cost/abuse guardrails:
  - per-user request rate limiting
  - daily LLM token budget tracking
- Dockerized runtime + GitHub Actions test/build/deploy

## Project Structure
- `bot/`: production Telegram bot runtime (`python -m bot.main`)
- `src/`: alternate implementation tree kept for reference
- `database/`: DB client and persistence helpers
- `llm/`: LLM client modules
- `monitoring/`: monitoring notes and alert guidance
- `tests/`: pytest suite
- `.github/workflows/`: CI/CD workflow

## Environment Variables
Required in `.env`:
- `TELEGRAM_BOT_TOKEN`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_VER`

Database configuration (supported patterns):
1. Preferred single URL:
   - `DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<db>`
2. Backward-compatible components:
   - `DB_HOST` (either hostname or full URL)
   - `DB_USER`
   - `DB_PASSWORD`
   - `DB_NAME`
   - `DB_PORT` (optional, default `5432`)

Runtime/monitoring controls:
- `HEALTH_PORT` (default `8081`)
- `MAX_DAILY_TOKENS` (default `120000`)
- `REQUEST_WINDOW_SECONDS` (default `60`)
- `MAX_REQUESTS_PER_WINDOW` (default `20`)
- `REQUIRE_CLOUD_DB` (default `true` in Docker Compose)

## Quick Start (Local)
1. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```
2. Configure `.env` with bot, LLM, and DB credentials.
3. Run with Docker Compose (cloud DB):
   ```sh
   docker compose up -d --build bot
   ```
4. Optional local Postgres only for development:
   ```sh
   COMPOSE_PROFILES=localdb docker compose up -d --build
   ```

## Cloud Deployment (EC2 + GitHub Actions)
- Workflow file: `.github/workflows/ci.yml`
- On push to `main`/`master`:
  - install dependencies
  - run database smoke check
  - run `pytest -q`
  - build Docker image
  - deploy to EC2 over SSH

Important:
- Keep EC2 `.env` with cloud DB credentials.
- Do not open DB port `5432` to `0.0.0.0/0`; allow EC2 security group only.

## Monitoring and Validation
Health check:
```sh
curl http://localhost:8081/health
```

Metrics check:
```sh
curl http://localhost:8081/metrics
```

Database counters check:
```sh
sudo docker compose exec -T bot python - <<'PY'
from database.db_client import get_db_overview, DB_URL
print('DB URL scheme:', DB_URL.split(':', 1)[0])
print(get_db_overview())
PY
```

## Tests
Run locally:
```sh
pytest -q
```
