# Monitoring Setup

This folder is for monitoring and cost-control notes for Study Buddy Bot deployments.

## Runtime Endpoints
- `GET /health`: bot liveness, uptime, and uploaded file count.
- `GET /metrics`: uptime, DB table counts, active sessions, and LLM token usage.

## Cost and Abuse Guardrails
Configure these in `.env`:
- `MAX_DAILY_TOKENS` (default: `120000`)
- `REQUEST_WINDOW_SECONDS` (default: `60`)
- `MAX_REQUESTS_PER_WINDOW` (default: `20`)

When daily token budget is exhausted, LLM requests return a budget-limit message.
When per-user request rate is exceeded, requests are rejected temporarily.

## Recommended Cloud Alerts
- Alert when `/health` is unavailable for 2+ minutes.
- Alert when `/metrics.llm_usage.total_tokens` is above 80% of daily budget.
- Alert when DB connection errors increase.
- Alert when container restarts exceed threshold.