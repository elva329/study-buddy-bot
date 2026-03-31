import os
import sys
import logging
import requests
import configparser
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from database.db_client import log_message
from dotenv import load_dotenv

gpt = None

# Always load .env from project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
sys.path.append(PROJECT_ROOT)

# Load config from project root
config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config', 'config.ini'))

# --- ChatGPT REST API Client ---


class ChatGPT:
    def __init__(self, config):
        # Try config first, then .env
        api_key = config['CHATGPT'].get(
            'API_KEY') if 'CHATGPT' in config and 'API_KEY' in config['CHATGPT'] else os.getenv('LLM_API_KEY')
        base_url = config['CHATGPT'].get(
            'BASE_URL') if 'CHATGPT' in config and 'BASE_URL' in config['CHATGPT'] else os.getenv('LLM_BASE_URL')
        model = config['CHATGPT'].get(
            'MODEL') if 'CHATGPT' in config and 'MODEL' in config['CHATGPT'] else os.getenv('LLM_MODEL')
        api_ver = config['CHATGPT'].get(
            'API_VER') if 'CHATGPT' in config and 'API_VER' in config['CHATGPT'] else os.getenv('LLM_API_VER')
        self.url = f'{base_url}/deployments/{model}/chat/completions?api-version={api_ver}'
        self.headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "api-key": api_key,
        }
        self.system_message = (
            'You are a helper! Your users are university students. '
            'Your replies should be conversational, informative, use simple words, and be straightforward.'
        )

    def submit(self, user_message: str):
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": user_message},
        ]
        payload = {
            "messages": messages,
            "temperature": 1,
            "max_tokens": 150,
            "top_p": 1,
            "stream": False
        }
        response = requests.post(self.url, json=payload, headers=self.headers)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']
        else:
            return "Error: " + response.text

# --- Telegram Bot Logic ---


def get_telegram_token():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if token:
        return token
    if 'telegram' in config and 'bot_token' in config['telegram']:
        return config['telegram']['bot_token']
    raise RuntimeError(
        'Telegram bot token not found in .env or config/config.ini ([telegram] section)')


TELEGRAM_TOKEN = get_telegram_token()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler(os.path.join(
        PROJECT_ROOT, 'logs', 'bot.log')), logging.StreamHandler()]
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hello! I am your Study Buddy Bot. How can I help you today?')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    log_message(user_id, user_message, sender='user')
    global gpt
    response = gpt.submit(user_message)
    log_message(user_id, response, sender='bot')
    await update.message.reply_text(response)


def main():
    global gpt
    gpt = ChatGPT(config)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == '__main__':
    main()
