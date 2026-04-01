import random
from datetime import datetime
import json
from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
import re
import os
import sys
import logging
import requests
import configparser
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from database.db_client import log_message, log_quiz_score, get_quiz_stats, get_quiz_history, log_quiz_attempt_db, get_user_progress_db
from dotenv import load_dotenv
from bot.rag_utils import save_uploaded_file, list_uploaded_files
from bot.pdf_utils import extract_texts_from_all_pdfs, extract_text_from_pdf


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    files = list_uploaded_files()
    if not files:
        await update.message.reply_text("No uploaded notes found. Please upload PDF files first.")
        return
    await update.message.reply_text("Generating summaries for your uploaded notes...")
    global gpt
    for fname in files:
        if not fname.lower().endswith('.pdf'):
            continue
        pdf_path = os.path.join(UPLOAD_DIR, fname)
        try:
            text = extract_text_from_pdf(pdf_path)
            if not text.strip():
                await update.message.reply_text(f"Could not extract text from {fname}.")
                continue
            prompt = f"Summarize the following study material in 5 concise bullet points for university students.\n\nMaterial:\n{text[:3000]}"
            summary = gpt.submit(prompt)
            await update.message.reply_text(f"{fname}:\n{summary}")
        except Exception as e:
            await update.message.reply_text(f"Error summarizing {fname}: {e}")


# Helper to log quiz attempts


# Store quiz session metadata in DB (replaces JSON)
def log_quiz_attempt(user_id, num_questions):
    log_quiz_attempt_db(user_id, num_questions)

# Helper to get user progress


# Fetch quiz session metadata from DB (replaces JSON)
def get_user_progress(user_id):
    return get_user_progress_db(user_id)


# For batching PDF upload notifications
uploaded_files = []
upload_batch_timer = None

gpt = None

# Always load .env from project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PROGRESS_LOG = os.path.join(PROJECT_ROOT, 'user_progress.json')
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
            'You are a helpful assistant that creates multiple-choice quiz questions for university students.'
        )

    def submit(self, user_message: str):
        messages = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": user_message},
        ]
        payload = {
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 500,
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
    await update.message.reply_text(
        'Hello! I am your Study Buddy Bot. 📚\n\n'
        'I can help you study by:\n'
        '• Uploading PDF files for context\n'
        '• Creating multiple-choice quizzes from your materials\n'
        '• Answering questions about your study materials\n\n'
        'Use /quiz to start a quiz!\n'
        'Use /progress to see your quiz history'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    log_message(user_id, user_message, sender='user')
    global gpt

    # Check if user is in new upload mode
    if user_id in user_new_upload_mode and user_id in user_new_upload_files and user_new_upload_files[user_id]:
        # Use only new uploads for context
        pdf_texts = []
        for fname in user_new_upload_files[user_id]:
            pdf_path = os.path.join(UPLOAD_DIR, fname)
            if os.path.exists(pdf_path):
                pdf_texts.append(extract_text_from_pdf(pdf_path))
        context_text = '\n'.join(pdf_texts)
    else:
        # Use all PDFs (default behavior)
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
    user_id = update.message.from_user.id

    if document.mime_type == 'application/pdf':
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        file_path = save_uploaded_file(file_bytes, document.file_name)
        global uploaded_files, upload_batch_timer
        uploaded_files.append(document.file_name)

        # If user is in new upload mode, track their new uploads
        if user_id in user_new_upload_mode:
            if user_id not in user_new_upload_files:
                user_new_upload_files[user_id] = []
            user_new_upload_files[user_id].append(document.file_name)

        import asyncio
        # Cancel previous timer if running
        if upload_batch_timer is not None and not upload_batch_timer.done():
            upload_batch_timer.cancel()
        # Only send a message after a short delay (batch window)

        async def send_batch():
            await asyncio.sleep(1.5)
            if uploaded_files:
                files_str = ', '.join(uploaded_files)
                await update.message.reply_text(f"✅ PDFs {files_str} uploaded and saved!")
                uploaded_files.clear()
        upload_batch_timer = asyncio.create_task(send_batch())
    else:
        await update.message.reply_text("Only PDF files are supported at this time.")

# Store user quiz and preferences in memory
user_quiz_prefs = {}
user_quiz_state = {}

# --- New upload mode state ---
user_new_upload_mode = set()
user_new_upload_files = {}


def parse_mcq_question(raw_text):
    """Parse a multiple choice question from LLM response"""
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]

    question_data = {
        'question': None,
        'options': [],
        'answer': None,
        'explanation': None
    }

    # Find the question line
    question_line = None
    for i, line in enumerate(lines):
        if line and not re.match(r'^[A-D]\)', line) and not line.startswith('Answer:') and not line.startswith('Explanation:'):
            # This is likely the question
            question_line = line
            break

    if question_line:
        # Clean up question
        question_data['question'] = re.sub(
            r'^Q\d*:?\s*', '', question_line).strip()

    # Find options (lines starting with A), B), etc.)
    option_pattern = re.compile(r'^([A-D])[\.\):]\s*(.*)')
    for line in lines:
        match = option_pattern.match(line)
        if match:
            question_data['options'].append(match.group(2).strip())

    # Find answer
    for line in lines:
        if line.startswith('Answer:'):
            answer_text = re.sub(r'^Answer:\s*', '', line).strip()
            # Extract the letter if present
            letter_match = re.match(r'^([A-D])', answer_text, re.IGNORECASE)
            if letter_match:
                question_data['answer'] = letter_match.group(1).upper()
            else:
                question_data['answer'] = answer_text
            break

    # Find explanation
    for line in lines:
        if line.startswith('Explanation:'):
            question_data['explanation'] = re.sub(
                r'^Explanation:\s*', '', line).strip()
            break

    # Validate we have all required parts
    if (question_data['question'] and len(question_data['options']) == 4 and question_data['answer']):
        return question_data
    return None


async def generate_mcq_question(update, context, user_id, question_num, total_questions, context_text):
    """Generate a single multiple-choice question"""
    prompt = (
        f"Based on the following course material, create a multiple-choice quiz question (#{question_num} of {total_questions}).\n\n"
        f"Material:\n{context_text}\n\n"
        f"Instructions:\n"
        f"1. Create ONE multiple-choice question with 4 options (A, B, C, D)\n"
        f"2. Format EXACTLY like this example:\n"
        f"Q: What is the main component of a GAN?\n"
        f"A) Encoder\n"
        f"B) Decoder\n"
        f"C) Generator\n"
        f"D) Classifier\n"
        f"Answer: C\n"
        f"Explanation: GANs consist of a Generator and Discriminator, with the Generator creating fake data.\n\n"
        f"ONLY output the question in this exact format. Do not add any extra text."
    )

    global gpt
    max_retries = 3

    for attempt in range(max_retries):
        response = gpt.submit(prompt)
        print(f"LLM Response (attempt {attempt + 1}):\n{response}\n")

        question_data = parse_mcq_question(response)
        if question_data:
            return question_data

    return None


async def generate_and_send_next_question(update, context, user_id):
    state = user_quiz_state.get(user_id)
    if not state:
        return

    qnum = state['current'] + 1
    total = state['amount']
    context_text = state['context_text']

    # Send "generating" message
    thinking_msg = await update.message.reply_text(f"🤔 Generating question {qnum}/{total}...")

    # Generate the question
    question_data = await generate_mcq_question(update, context, user_id, qnum, total, context_text)

    if not question_data:
        await thinking_msg.edit_text("❌ Sorry, I couldn't generate a valid question. Please try again.")
        await finish_quiz(update, context, user_id)
        return

    # Store the question
    state['last_question'] = question_data

    # Format the message
    msg = f"Question {qnum}/{total}\n\n{question_data['question']}\n\n"
    for i, opt in enumerate(question_data['options']):
        msg += f"{chr(65+i)}) {opt}\n"

    # Create keyboard with letter buttons
    keyboard = [[KeyboardButton(f"{chr(65+i)}")] for i in range(4)]

    await thinking_msg.delete()
    await update.message.reply_text(
        msg,
        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
    )


async def finish_quiz(update, context, user_id):
    state = user_quiz_state.get(user_id)
    if not state:
        await update.message.reply_text("Quiz state lost. Please start again with /quiz.")
        user_quiz_prefs.pop(user_id, None)
        user_quiz_state.pop(user_id, None)
        return

    score = state.get('score', 0)
    total = state.get('amount', 0)
    percent = int(100 * score / total) if total > 0 else 0

    # Create simple review - just questions with correct answers
    review = "Quiz Review\n\n"

    for i, ans in enumerate(state.get('answers', [])):
        q = ans['q']
        correct_answer_letter = q['answer']
        correct_answer_text = q['options'][ord(
            correct_answer_letter) - ord('A')]

        # Show the question and correct answer
        review += f"Q{i+1}: {q['question']}\n"
        review += f"Correct answer: {correct_answer_letter}) {correct_answer_text}\n\n"

        # Split into multiple messages if too long
        if len(review) > 3500 and i < total - 1:
            await update.message.reply_text(review)
            review = "Quiz Review (continued)\n\n"

    # Send final review message
    await update.message.reply_text(
        f"Quiz Complete!\n\n"
        f"Your Score: {score}/{total} ({percent}%)\n\n"
        f"{review}",
        reply_markup=ReplyKeyboardRemove()
    )

    # Clear new upload mode after quiz completion if it was used
    if user_id in user_new_upload_mode:
        user_new_upload_mode.discard(user_id)
        if user_id in user_new_upload_files:
            user_new_upload_files[user_id] = []
        await update.message.reply_text(
            "New upload mode cleared. Your new documents have been added to your study materials."
        )

    user_quiz_prefs.pop(user_id, None)
    user_quiz_state.pop(user_id, None)


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    # Determine which PDFs to use based on upload mode
    use_new_uploads = False
    pdf_texts = []

    # Check if user is in new upload mode
    if user_id in user_new_upload_mode:
        if user_id in user_new_upload_files and user_new_upload_files[user_id]:
            # Use only new uploads
            use_new_uploads = True
            for fname in user_new_upload_files[user_id]:
                pdf_path = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(pdf_path):
                    pdf_texts.append(extract_text_from_pdf(pdf_path))
        else:
            # User is in new upload mode but hasn't uploaded any files yet
            await update.message.reply_text(
                "No files uploaded yet!\n\n"
                "You're in new upload mode but haven't uploaded any documents.\n\n"
                "Please upload your PDF files first, then try /quiz again."
            )
            return
    else:
        # Use all available PDFs (default behavior)
        pdf_texts = extract_texts_from_all_pdfs(UPLOAD_DIR)

    # If user is already in a quiz session
    if user_id in user_quiz_prefs:
        prefs = user_quiz_prefs[user_id]

        # Step 1: Asking for number of questions
        if prefs.get("step") == "asking_amount":
            try:
                num_questions = int(text)
                if num_questions <= 0 or num_questions > 20:
                    await update.message.reply_text("Please enter a number between 1 and 20.")
                    return
                prefs["amount"] = num_questions
                prefs["step"] = "in_progress"

                # Use the SAME pdf_texts that was determined at the start of this function
                # This ensures consistency throughout the entire quiz session
                context_text = '\n'.join(pdf_texts)

                if not context_text.strip():
                    await update.message.reply_text(
                        "⚠️ No study materials found!\n\n"
                        "Please upload some PDF files first by sending them to me, then try /quiz again."
                    )
                    user_quiz_prefs.pop(user_id, None)
                    # Clear new upload mode if it was active
                    if use_new_uploads:
                        user_new_upload_mode.discard(user_id)
                        if user_id in user_new_upload_files:
                            user_new_upload_files[user_id] = []
                    return

                user_quiz_state[user_id] = {
                    "amount": num_questions,
                    "current": 0,
                    "score": 0,
                    "answers": [],
                    "context_text": context_text,
                    "last_question": None
                }

                await generate_and_send_next_question(update, context, user_id)
                return
            except ValueError:
                await update.message.reply_text("Please enter a valid number (1-20).")
                return

        # Step 2: Handling answer to current question
        elif prefs.get("step") == "in_progress":
            state = user_quiz_state.get(user_id)
            if not state or 'last_question' not in state or state['last_question'] is None:
                await update.message.reply_text("Quiz state lost. Please start again with /quiz.")
                user_quiz_prefs.pop(user_id, None)
                user_quiz_state.pop(user_id, None)
                return

            question = state['last_question']
            user_answer = update.message.text.strip().upper()

            # Validate answer
            if user_answer not in ['A', 'B', 'C', 'D']:
                await update.message.reply_text("❌ Please answer with A, B, C, or D.")
                return

            # Check if correct
            correct = (user_answer == question['answer'])
            correct_option_text = question['options'][ord(
                question['answer']) - ord('A')]
            user_option_text = question['options'][ord(user_answer) - ord('A')]

            if correct:
                state['score'] += 1
                feedback = f"Correct!\n\n"
                feedback += f"Your answer: {user_answer}) {user_option_text}\n\n"
            else:
                feedback = f"Wrong!\n\n"
                feedback += f"Your answer: {user_answer}) {user_option_text}\n"
                feedback += f"Correct answer: {question['answer']}) {correct_option_text}\n\n"

            if question.get('explanation'):
                feedback += f"Explanation: {question['explanation']}"

            # Store answer
            state['answers'].append({
                'user': user_answer,
                'correct': correct,
                'q': question
            })
            state['current'] += 1

            # Send feedback
            await update.message.reply_text(feedback)

            # Send next question or finish
            if state['current'] < state['amount']:
                await generate_and_send_next_question(update, context, user_id)
            else:
                await finish_quiz(update, context, user_id)
            return

    # New quiz session
    else:
        if not pdf_texts:
            if use_new_uploads:
                # User is in new upload mode but no files were found
                await update.message.reply_text(
                    "No files in new upload session!\n\n"
                    "Please upload PDF documents first, then try /quiz again."
                )
            else:
                # Default mode - no files exist at all
                await update.message.reply_text(
                    "No study materials found!\n\n"
                    "Please upload PDF files first by sending them to me, then try /quiz again."
                )
            return

        user_quiz_prefs[user_id] = {
            "step": "asking_amount",
            "use_new_uploads": use_new_uploads
        }
        await update.message.reply_text(
            "How many questions would you like to answer?\n\n"
            "Please enter a number between 1 and 20:"
        )

    # After quiz completion, clear new upload mode if it was used
    # Note: This is also handled in finish_quiz
    if use_new_uploads and user_id not in user_quiz_state:
        user_new_upload_mode.discard(user_id)
        if user_id in user_new_upload_files:
            user_new_upload_files[user_id] = []


# --- Progress Command ---


async def newupload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to indicate user wants to upload new documents for a new course"""
    user_id = update.message.from_user.id

    # Clear any previous new upload session and start fresh
    user_new_upload_files[user_id] = []
    user_new_upload_mode.add(user_id)

    await update.message.reply_text(
        "📂 <b>New Upload Mode Activated!</b>\n\n"
        "Please upload your PDF documents for this new category.\n"
        "These documents will be used <b>exclusively</b> for your next quiz.\n\n"
        "📍 Files uploaded here will NOT be mixed with previously uploaded files.\n"
        "📍 After your quiz, this mode will close automatically.\n\n"
        "To cancel: use /cancel_upload",
        parse_mode='HTML'
    )


async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel new upload mode"""
    user_id = update.message.from_user.id
    user_new_upload_mode.discard(user_id)
    if user_id in user_new_upload_files:
        user_new_upload_files[user_id] = []
    await update.message.reply_text(
        "✅ New upload mode cancelled. Future quizzes will use all available documents.",
        parse_mode='HTML'
    )


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    total_quizzes, avg_score, best_score, weak_topics = get_quiz_stats(user_id)
    quiz_history = get_quiz_history(user_id, limit=5)
    if total_quizzes == 0:
        await update.message.reply_text(
            "📊 No quiz history found yet.\n\n"
            "Take a quiz with /quiz to start tracking your progress!"
        )
        return

    # Placeholder for worst topic name (since topic tracking is not implemented)
    worst_topic = 'N/A'
    msg = f"📊 Quiz History\n\n"
    msg += f"📝 Total Quizzes Taken: {total_quizzes}\n"
    msg += f"📈 Average Score: {avg_score}%\n"
    msg += f"🏆 Best Score: {best_score}%\n"
    msg += f"⚠️ Worst Score: {worst_topic}\n\n"
    msg += f"You have completed {total_quizzes} quiz sessions.\n\n"
    msg += "🕓 Recent attempts:\n"
    for i, (ts, total) in enumerate(quiz_history, 1):
        dt = ts.split('T')[0] if 'T' in ts else str(ts)[:10]
        msg += f"{i}. {dt}: {total} questions\n"
    await update.message.reply_text(msg)


def main():
    global gpt
    gpt = ChatGPT(config)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('quiz', quiz))
    app.add_handler(CommandHandler('progress', progress))
    app.add_handler(CommandHandler('summarize', summarize))
    app.add_handler(CommandHandler('newupload', newupload))
    app.add_handler(CommandHandler('cancel_upload', cancel_upload))

    # Route all text to a dispatcher that checks quiz state
    async def text_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.from_user.id
        if user_id in user_quiz_prefs:
            await quiz(update, context)
        else:
            await handle_message(update, context)

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, text_dispatcher))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.run_polling()


if __name__ == '__main__':
    main()
