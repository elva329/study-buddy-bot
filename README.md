# Study Buddy Bot

A cloud-deployed Telegram chatbot powered by an LLM, designed to assist students with study-related tasks. This project demonstrates cloud, DevOps, and containerization best practices.

## Features
- Telegram chatbot interface
- LLM-powered responses
- Cloud database logging
- Containerized with Docker
- CI/CD pipeline
- Monitoring and logging

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
   docker run --env-file config/.env -p 8000:8000 study-buddy-bot
   ```
3. Deploy to your chosen cloud provider (see deployment docs).

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
