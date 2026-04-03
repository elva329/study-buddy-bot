# Study Buddy Bot

A cloud-deployed Telegram chatbot powered by an LLM, designed to assist students with study-related tasks. This project demonstrates cloud, DevOps, and containerization best practices.

## Features
- Telegram chatbot interface
- LLM-powered responses
- Cloud database logging
- Containerized with Docker
- CI/CD pipeline
- Monitoring and logging

## Runtime Notes
- The production entrypoint is `python -m bot.main`.
- The bot expects `DATABASE_URL` from `.env` (recommended: managed cloud PostgreSQL such as AWS RDS).
- Local Postgres in Docker Compose is optional and only started with profile `localdb`.
- Monitoring endpoints are exposed on `HEALTH_PORT` (default `8081`):
   - `/health`
   - `/metrics`

## Project Structure
- `bot/` - Telegram bot source code
- `llm/` - LLM API integration
- `database/` - Database integration and models
- `config/` - Configuration files
- `logs/` - Log files
- `monitoring/` - Monitoring scripts/configs
- `.github/workflows/` - CI/CD pipeline configs

## Setup
1. Copy `config/config.example.ini` to `config/config.ini` and fill in your credentials.
2. Build and run with Docker:
   ```sh
   docker build -t study-buddy-bot .
   docker run --env-file .env -p 8081:8081 study-buddy-bot
   ```
   For local DB testing only:
   ```sh
   COMPOSE_PROFILES=localdb docker compose up -d --build
   ```
3. Deploy to your chosen cloud provider (see deployment docs).

## Cloud DB Migration Checklist
1. Provision PostgreSQL on cloud provider (for example AWS RDS).
2. Allow inbound `5432` from EC2 security group only (not `0.0.0.0/0`).
3. Set EC2 `.env`:
   ```sh
   DATABASE_URL=postgresql://<user>:<password>@<rds-endpoint>:5432/<database>
   TELEGRAM_BOT_TOKEN=<token>
   LLM_API_KEY=<key>
   LLM_BASE_URL=<provider-base-url>
   LLM_MODEL=<model>
   LLM_API_VER=<api-version>
   HEALTH_PORT=8081
   ```
4. Redeploy using GitHub Actions workflow.
5. Verify:
   ```sh
   curl http://localhost:8081/health
   curl http://localhost:8081/metrics
   ```

## Requirements
- Python 3.9+
- Docker
- Telegram Bot Token
- LLM API Key (OpenAI, HKBU, etc.)
- Cloud database credentials

## Monitoring
See `monitoring/` for setup instructions.

## License
MIT
