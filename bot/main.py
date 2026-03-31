# For batching PDF upload notifications
from bot.pdf_utils import extract_texts_from_all_pdfs
from bot.rag_utils import save_uploaded_file
from dotenv import load_dotenv
from database.db_client import log_message
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update
import configparser
import requests
import logging
import sys
import os
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
uploaded_files = []
upload_batch_timer = None

gpt = None

# Always load .env from project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
sys.path.append(PROJECT_ROOT)

# Load config from project root
config = configparser.ConfigParser()
config.read(os.path.join(PROJECT_ROOT, 'config', 'config.ini'))

# Define UPLOAD_DIR
UPLOAD_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'uploads'))

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
    # RAG: extract all PDF text and prepend to prompt
    pdf_texts = extract_texts_from_all_pdfs(UPLOAD_DIR)
    context_text = '\n'.join(pdf_texts)
    if context_text.strip():
        prompt = f"Context from your uploaded PDFs:\n{context_text}\n\nQuestion: {user_message}"
    else:
        prompt = user_message
    response = gpt.submit(prompt)
    log_message(user_id, response, sender='bot')
    await update.message.reply_text(response)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if document.mime_type == 'application/pdf':
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        file_path = save_uploaded_file(file_bytes, document.file_name)
        global uploaded_files, upload_batch_timer
        uploaded_files.append(document.file_name)
        import asyncio
        # Cancel previous timer if running
        if upload_batch_timer is not None and not upload_batch_timer.done():
            upload_batch_timer.cancel()
        # Only send a message after a short delay (batch window)

        async def send_batch():
            await asyncio.sleep(1.5)
            if uploaded_files:
                files_str = ', '.join(uploaded_files)
                await update.message.reply_text(f"PDFs {files_str} uploaded and saved.")
                uploaded_files.clear()
        upload_batch_timer = asyncio.create_task(send_batch())
    else:
        await update.message.reply_text("Only PDF files are supported at this time.")


# Store user quiz preferences in memory (simple dict for demo; use DB for production)
user_quiz_prefs = {}


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    # Step 1: Ask for quiz format if not set
    if user_id not in user_quiz_prefs:
        await update.message.reply_text(
            "What quiz format do you prefer?\n1. Multiple Choice\n2. Short Answer\n3. Mixed\n(Reply with 1, 2, 3, or the format name)"
        )
        user_quiz_prefs[user_id] = {"step": "format"}
        return
    # Step 2: Handle format selection
    if user_quiz_prefs[user_id]["step"] == "format":
        format_choice = update.message.text.strip()
        # Accept both text and number replies
        format_map = {
            "1": "Multiple Choice",
            "2": "Short Answer",
            "3": "Mixed",
            "Multiple Choice": "Multiple Choice",
            "Short Answer": "Short Answer",
            "Mixed": "Mixed"
        }
        if format_choice not in format_map:
            await update.message.reply_text(
                "Please choose a valid format: 1. Multiple Choice, 2. Short Answer, 3. Mixed."
            )
            return
        user_quiz_prefs[user_id]["format"] = format_map[format_choice]
        user_quiz_prefs[user_id]["step"] = "amount"
        await update.message.reply_text(
            "How many questions do you want? (Enter a number between 3 and 15)",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    # Step 3: Handle amount selection
    if user_quiz_prefs[user_id]["step"] == "amount":
        try:
            num_questions = int(update.message.text.strip())
            if not (3 <= num_questions <= 15):
                raise ValueError
        except Exception:
            await update.message.reply_text("Please enter a valid number between 3 and 15.")
            return
        user_quiz_prefs[user_id]["amount"] = num_questions
        user_quiz_prefs[user_id]["step"] = "ready"
        await update.message.reply_text("Generating your quiz... Please wait.")
        # Now generate the quiz
        pdf_texts = extract_texts_from_all_pdfs(UPLOAD_DIR)
        context_text = '\n'.join(pdf_texts)
        if not context_text.strip():
            await update.message.reply_text("No PDF content found. Please upload a PDF first.")
            user_quiz_prefs.pop(user_id, None)
            return
        format_choice = user_quiz_prefs[user_id]["format"]
        num_questions = user_quiz_prefs[user_id]["amount"]
        if format_choice == "Multiple Choice":
            prompt = (
                f"You are a study assistant. Based on the following course material, generate {num_questions} multiple choice questions. "
                "For each question, provide 4 options labeled A-D, and give the answer immediately after the question. "
                "Format: Q1: ...\nA. ...\nB. ...\nC. ...\nD. ...\nAnswer: ...\n\nMaterial:\n" + context_text
            )
        elif format_choice == "Short Answer":
            prompt = (
                f"You are a study assistant. Based on the following course material, generate {num_questions} short answer questions. "
                "For each question, provide the answer immediately after the question. "
                "Format: Q1: ...\nAnswer: ...\n\nMaterial:\n" + context_text
            )
        else:  # Mixed
            prompt = (
                f"You are a study assistant. Based on the following course material, generate a quiz with {num_questions} questions. "
                "Mix multiple choice and short answer questions. For multiple choice, provide 4 options labeled A-D. "
                "For each question, provide the answer immediately after the question. "
                "Format: Q1 (Multiple Choice): ...\nA. ...\nB. ...\nC. ...\nD. ...\nAnswer: ...\nQ2 (Short Answer): ...\nAnswer: ...\n\nMaterial:\n" + context_text
            )
        global gpt
        quiz_text = gpt.submit(prompt)
        await update.message.reply_text(quiz_text)
        user_quiz_prefs.pop(user_id, None)
        return


def main():
    global gpt
    gpt = ChatGPT(config)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    # Accept both /quiz command and text replies for quiz flow
    app.add_handler(CommandHandler('quiz', quiz))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(
        '^(Multiple Choice|Short Answer|Mixed|[0-9]+)$'), quiz))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.run_polling()


if __name__ == '__main__':
    main()
