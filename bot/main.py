import random
import json
import re
import os
import sys
import logging
import requests
import configparser
import threading
from datetime import datetime, timezone
from io import BytesIO
from http.server import BaseHTTPRequestHandler, HTTPServer

import matplotlib
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

from bot.pdf_utils import extract_texts_from_all_pdfs, extract_text_from_pdf, extract_texts_with_metadata
from bot.rag_utils import save_uploaded_file, list_uploaded_files, retrieve_relevant_chunks, clear_uploads
from database.db_client import (
    log_event,
    log_message,
    log_quiz_score,
    get_db_overview,
    get_quiz_stats,
    get_quiz_history,
    log_quiz_attempt_db,
    get_user_progress_db,
)

matplotlib.use('Agg')


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    files = list_uploaded_files()
    log_event(user_id, 'summarize_requested', {'file_count': len(files)})

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
                log_event(user_id, 'summarize_empty_pdf', {'filename': fname})
                continue
            prompt = f"Summarize the following study material in 5 concise bullet points for university students.\n\nMaterial:\n{text[:3000]}"
            summary = gpt.submit(prompt)
            # Remove markdown formatting
            summary = strip_markdown(summary)
            await update.message.reply_text(f"{fname}:\n{summary}")
            log_event(user_id, 'summarize_completed', {
                'filename': fname,
                'summary_excerpt': db_excerpt(summary, 800),
            })
        except Exception as e:
            await update.message.reply_text(f"Error summarizing {fname}: {e}")
            log_event(user_id, 'summarize_failed', {
                      'filename': fname, 'error': str(e)})


# Helper to log quiz attempts


# Store quiz session metadata in DB (replaces JSON)
def log_quiz_attempt(user_id, num_questions):
    log_quiz_attempt_db(user_id, num_questions)


def db_excerpt(text, limit=500):
    if text is None:
        return None
    return " ".join(str(text).split())[:limit]


class MonitoringHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        uptime_seconds = int(
            (datetime.now(timezone.utc) - BOT_START_TIME).total_seconds())

        if self.path == '/health':
            self._send_json(200, {
                'status': 'ok',
                'uptime_seconds': uptime_seconds,
                'uploaded_files': len(list_uploaded_files()),
            })
            return

        if self.path == '/metrics':
            self._send_json(200, {
                'uptime_seconds': uptime_seconds,
                'database': get_db_overview(),
                'active_quiz_sessions': len(user_quiz_state),
                'active_ask_sessions': len(user_ask_mode),
            })
            return

        self._send_json(404, {'error': 'not found'})

    def log_message(self, format, *args):
        return


def start_monitoring_server():
    port = int(os.getenv('HEALTH_PORT', '8081'))
    try:
        server = HTTPServer(('0.0.0.0', port), MonitoringHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logging.getLogger(__name__).info(
            "Monitoring server started on port %s", port)
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Monitoring server unavailable on port %s: %s", port, exc)

# Helper to get user progress


# Fetch quiz session metadata from DB (replaces JSON)
def get_user_progress(user_id):
    return get_user_progress_db(user_id)


# For batching PDF upload notifications
uploaded_files = []
upload_batch_timer = None

gpt = None
BOT_START_TIME = datetime.now(timezone.utc)

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

    def submit(self, user_message: str, system_message: str = None):
        if system_message is None:
            system_message = self.system_message
        messages = [
            {"role": "system", "content": system_message},
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

# --- Helper Functions ---


def strip_markdown(text: str) -> str:
    """Remove all markdown formatting from text"""
    # Remove ** bold
    text = text.replace("**", "")
    # Remove __ bold
    text = text.replace("__", "")
    # Remove * and _ italic
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    # Remove ### headers (keep content)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    # Remove ``` code blocks
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    # Remove inline code
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Remove [text](url) links, keep text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove --- horizontal rules
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    return text.strip()


def format_study_plan_table(plan_text: str) -> str:
    """Format study plan into a table-like structure for Telegram"""
    # Strip markdown first
    plan_text = strip_markdown(plan_text)

    # Split by lines and reconstruct in ASCII table format
    lines = [line.strip() for line in plan_text.split('\n') if line.strip()]

    # Create formatted output
    formatted = "Weekly Study Plan"
    # formatted += "=" * 50 + "\n\n"

    current_day = None
    for line in lines:
        # Detect day headers
        if 'Day' in line and ':' in line:
            if current_day is not None:
                formatted += "\n"
            current_day = line
            formatted += f"📅 {line}\n"
            formatted += "-" * 50 + "\n"
        else:
            # Add other content with proper indentation
            if line:
                formatted += f"  {line}\n"

    formatted += "=" * 50 + "\n"
    return formatted


def generate_study_plan_image(plan_text: str) -> BytesIO:
    """Generate a professional weekly study plan timetable using matplotlib"""
    try:
        # Strip markdown
        plan_text = strip_markdown(plan_text)

        # Helper function to wrap text for table cells
        def wrap_text(text, max_width=12):
            """Wrap text to fit in table cells with proper line breaks"""
            if not text:
                return ''
            words = text.split()
            lines = []
            current_line = []

            for word in words:
                # If adding this word would exceed max_width, start a new line
                if sum(len(w) for w in current_line) + len(word) + len(current_line) > max_width:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    current_line.append(word)

            if current_line:
                lines.append(' '.join(current_line))

            return '\n'.join(lines)

        # Parse the timetable format
        # Expected format with Time, Monday, Tuesday, Wednesday, Thursday, Friday columns
        lines = [line.strip()
                 for line in plan_text.split('\n') if line.strip()]

        # Identify header row (should contain days of week)
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
        table_data = []
        header_found = False

        for line in lines:
            # Check if this is a header line
            if any(day in line for day in days):
                header_found = True
                # Parse header - split by common delimiters
                parts = [p.strip() for p in line.replace('\t', '|').split('|')]
                table_data.append(parts)
            elif header_found and line:
                # Parse data rows
                parts = [p.strip() for p in line.replace('\t', '|').split('|')]
                if len(parts) >= 2:  # Make sure we have meaningful data
                    # Pre-filter: remove rows with only empty cells, "--", or whitespace
                    cleaned_parts = []
                    for p in parts:
                        p_clean = p.strip()
                        # Skip empty, "--", or whitespace-only content
                        if p_clean and p_clean != '--':
                            cleaned_parts.append(wrap_text(p))
                        else:
                            cleaned_parts.append('')

                    # Only add row if time slot exists AND at least 2 other cells have content
                    # (time column + at least one topic)
                    content_count = sum(
                        1 for p in cleaned_parts[1:] if p and p.strip())
                    if content_count >= 1 and cleaned_parts[0] and cleaned_parts[0].strip():
                        table_data.append(cleaned_parts)

        # Normalize the final slot so it always shows a wrap-up / planning block
        for row in table_data:
            if not row:
                continue
            time_label = row[0].strip().replace(' ', '').lower()
            if time_label in ('17:45-18:00', '5:45-6:00'):
                for j in range(1, len(row)):
                    row[j] = 'Wrap-up & Plan'

        # If parsing failed, create a default timetable structure
        if not table_data or len(table_data) < 2:
            # Fallback: create a simple structured format from the text
            table_data = [
                ['Time', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
                ['10:00-11:30', 'Study', 'Study', 'Study', 'Study', 'Study'],
                ['11:30-12:00', 'Break', 'Break', 'Break', 'Break', 'Break'],
                ['12:00-1:30', 'Study', 'Study', 'Study', 'Study', 'Study'],
                ['1:30-2:30', 'Lunch', 'Lunch', 'Lunch', 'Lunch', 'Lunch'],
                ['2:30-4:00', 'Study', 'Study', 'Study', 'Study', 'Review'],
                ['4:00-4:15', 'Break', 'Break', 'Break', 'Break', 'Break'],
                ['4:15-5:45', 'Practice', 'Practice',
                    'Practice', 'Practice', 'Review'],
                ['5:45-6:00', 'Wrap-up & Plan', 'Wrap-up & Plan',
                    'Wrap-up & Plan', 'Wrap-up & Plan', 'Wrap-up & Plan']
            ]

        # Final pass: remove any rows where all non-time cells are empty
        if len(table_data) > 1:
            filtered_table = [table_data[0]]  # Keep header
            for row in table_data[1:]:
                # Check if row has any real content besides the time slot
                has_content = any(row[j].strip()
                                  for j in range(1, len(row)) if row[j])
                if has_content:
                    filtered_table.append(row)
            table_data = filtered_table if len(
                filtered_table) > 1 else table_data

        # Create figure with proper size for a timetable
        num_rows = len(table_data)
        fig, ax = plt.subplots(figsize=(16, 3.6 + num_rows * 1.25))
        ax.axis('off')

        # Title - centered horizontally and vertically in the top band
        fig.text(0.5, 0.975, 'Weekly Study Plan (Weekdays: 10:00 AM – 6:00 PM)',
                 ha='center', va='center', fontsize=18, fontweight='bold')

        # Create table in a bounded area so the title and table stay close together
        table = ax.table(
            cellText=table_data,
            cellLoc='left',
            loc='center',
            bbox=[0.0, 0.0, 1.0, 0.960],
            colWidths=[0.12, 0.176, 0.176, 0.176, 0.176, 0.176]  # 6 columns
        )

        # Style the table
        table.auto_set_font_size(False)
        table.set_fontsize(18)

        row_units = [1]
        for row in table_data[1:]:
            max_lines = 1
            for cell_text in row:
                if cell_text:
                    max_lines = max(max_lines, cell_text.count('\n') + 1)
            row_units.append(max_lines)

        total_units = sum(row_units)
        usable_height = 0.960

        # Format header row (first row)
        for i in range(len(table_data[0])):
            cell = table[(0, i)]
            cell.set_facecolor('#2E7D32')  # Darker green
            cell.set_text_props(weight='bold', color='white',
                                fontsize=18, ha='center', va='center')
            cell.set_height(usable_height * row_units[0] / total_units * 1.15)
            cell.PAD = 0.035

        # Format data rows with alternating colors
        for i in range(1, len(table_data)):
            for j in range(len(table_data[0])):
                cell = table[(i, j)]

                # Alternate row colors
                if i % 2 == 0:
                    cell.set_facecolor('#E8F5E9')  # Light green
                else:
                    cell.set_facecolor('#F1F8E9')  # Very light green

                # Time column styling
                if j == 0:
                    cell.set_text_props(
                        weight='bold', fontsize=18, ha='center', va='top')
                else:
                    cell.set_text_props(
                        fontsize=18, ha='left', va='top', wrap=True)

                # Increase cell height to show wrapped lines based on row content
                cell.set_height(
                    usable_height * row_units[i] / total_units * 1.15)
                cell.PAD = 0.06

        # Save to BytesIO
        buffer = BytesIO()
        plt.tight_layout(rect=[0, 0, 1, 0.995])
        plt.savefig(buffer, format='png', dpi=120, bbox_inches='tight')
        buffer.seek(0)
        plt.close(fig)

        return buffer

    except Exception as e:
        print(f"[Image Generation Error] {e}")
        return None


def get_telegram_token():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if token:
        return token
    if 'telegram' in config and 'bot_token' in config['telegram']:
        return config['telegram']['bot_token']
    raise RuntimeError(
        'Telegram bot token not found in .env or config/config.ini ([telegram] section)')


TELEGRAM_TOKEN = get_telegram_token()

LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
LOG_PATH = os.path.join(LOG_DIR, 'bot.log')

os.makedirs(LOG_DIR, exist_ok=True)

handlers = [logging.StreamHandler()]
try:
    handlers.insert(0, logging.FileHandler(LOG_PATH))
except OSError as exc:
    print(f'[Logging Warning] File logging disabled: {exc}')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=handlers
)


def reset_user_session(user_id):
    global uploaded_files, upload_batch_timer

    if upload_batch_timer is not None and not upload_batch_timer.done():
        upload_batch_timer.cancel()
    upload_batch_timer = None
    uploaded_files.clear()

    user_quiz_prefs.pop(user_id, None)
    user_quiz_state.pop(user_id, None)
    user_ask_mode.pop(user_id, None)
    user_ask_context.pop(user_id, None)

    clear_uploads()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    files_before_clear = list_uploaded_files()
    log_event(user_id, 'session_start_requested', {
        'uploaded_files_before_clear': files_before_clear,
    })

    try:
        reset_user_session(user_id)
        log_event(user_id, 'session_start_completed', {
            'cleared_file_count': len(files_before_clear),
        })
    except Exception as e:
        await update.message.reply_text(f"Error starting new session: {e}")
        log_event(user_id, 'session_start_failed', {'error': str(e)})
        return

    await update.message.reply_text(
        'Hello! I am your Study Buddy Bot.\n\n'
        'A new session has been started. Previous uploaded documents were cleared.\n\n'
        'I can help you study by:\n'
        '• Uploading PDF files for context\n'
        '• Creating multiple-choice quizzes from your materials\n'
        '• Answering questions about your study materials\n\n'
        'Available commands:\n'
        '/quiz - Start a quiz session\n'
        '/ask - Ask a question about your notes\n'
        '/plan - Generate a weekly study plan\n'
        '/progress - See your quiz history\n'
        '/summarize - Summarize your documents\n'
        '/endsession - Clear documents and start a new session'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    log_message(user_id, user_message, sender='user')
    log_event(user_id, 'message_received', {
              'message_excerpt': db_excerpt(user_message, 300)})
    global gpt

    # Use all PDFs for context
    pdf_texts = extract_texts_from_all_pdfs(UPLOAD_DIR)
    context_text = '\n'.join(pdf_texts)

    if context_text.strip():
        prompt = f"Context from your uploaded PDFs:\n{context_text}\n\nQuestion: {user_message}"
    else:
        prompt = user_message
    response = gpt.submit(prompt)
    # Remove markdown formatting
    response = strip_markdown(response)
    log_message(user_id, response, sender='bot')
    log_event(user_id, 'message_replied', {
        'response_excerpt': db_excerpt(response, 500),
        'used_pdf_context': bool(context_text.strip()),
    })
    await update.message.reply_text(response)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    user_id = update.message.from_user.id

    if document.mime_type == 'application/pdf':
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        file_path = save_uploaded_file(file_bytes, document.file_name)
        log_event(user_id, 'pdf_uploaded', {
            'filename': document.file_name,
            'saved_path': os.path.basename(file_path),
        })
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
                await update.message.reply_text(f"PDFs {files_str} uploaded and saved!")
                uploaded_files.clear()
        upload_batch_timer = asyncio.create_task(send_batch())
    else:
        await update.message.reply_text("Only PDF files are supported at this time.")

# Store user quiz and preferences in memory
user_quiz_prefs = {}
user_quiz_state = {}

# Store user Q&A conversation context
user_ask_context = {}
user_ask_mode = {}


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
    log_quiz_score(user_id, score, total, percent)
    log_event(user_id, 'quiz_completed', {
        'score': score,
        'total': total,
        'percent': percent,
    })

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
    # (No longer needed - user can type /endsession to clear)

    user_quiz_prefs.pop(user_id, None)
    user_quiz_state.pop(user_id, None)


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    # Get all available PDFs
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
                log_quiz_attempt(user_id, num_questions)
                log_event(user_id, 'quiz_started', {
                          'num_questions': num_questions})

                # Use the SAME pdf_texts that was determined at the start of this function
                # This ensures consistency throughout the entire quiz session
                context_text = '\n'.join(pdf_texts)

                if not context_text.strip():
                    await update.message.reply_text(
                        "No study materials found!\n\n"
                        "Please upload some PDF files first by sending them to me, then try /quiz again."
                    )
                    user_quiz_prefs.pop(user_id, None)
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
            log_event(user_id, 'quiz_answer_submitted', {
                'question_index': state['current'],
                'user_answer': user_answer,
                'correct': correct,
            })

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
            await update.message.reply_text(
                "No study materials found!\n\n"
                "Please upload PDF files first by sending them to me, then try /quiz again."
            )
            return

        user_quiz_prefs[user_id] = {
            "step": "asking_amount"
        }
        await update.message.reply_text(
            "How many questions would you like to answer?\n\n"
            "Please enter a number between 1 and 20:"
        )


# --- Session Management Command ---


async def endsession(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all uploaded documents to start a new session"""
    user_id = update.message.from_user.id
    files_before_clear = list_uploaded_files()
    log_event(user_id, 'session_end_requested', {
        'uploaded_files_before_clear': files_before_clear,
    })

    try:
        reset_user_session(user_id)
        log_event(user_id, 'session_end_completed', {
            'cleared_file_count': len(files_before_clear),
        })
        await update.message.reply_text(
            "Session ended. All uploaded documents have been cleared.\n\n"
            "You can now upload new documents for your next session."
        )
    except Exception as e:
        await update.message.reply_text(f"Error clearing documents: {e}")


# --- Progress Command ---

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    log_event(user_id, 'progress_requested', None)
    try:
        total_quizzes, avg_score, best_score, worst_score, weak_topics = get_quiz_stats(
            user_id)
        quiz_history = get_quiz_history(user_id, limit=5)
        if total_quizzes == 0:
            await update.message.reply_text(
                "No quiz history found yet.\n\n"
                "Take a quiz with /quiz to start tracking your progress!"
            )
            return

        # Format worst score display
        worst_score_text = f"{worst_score}%"
        if weak_topics and weak_topics != 'N/A':
            worst_score_text = f"{worst_score}% (Topic: {weak_topics})"

        msg = f"📊 Quiz History\n\n"
        msg += f"📖 Total Quizzes Taken: {total_quizzes}\n"
        msg += f"🎯 Average Score: {avg_score}%\n"
        msg += f"🏆 Best Score: {best_score}%\n"
        msg += f"📉 Worst Performance: {worst_score_text}\n\n"
        msg += f"You have completed {total_quizzes} quiz sessions.\n\n"
        msg += "Recent attempts:\n"
        for i, (ts, total) in enumerate(quiz_history, 1):
            ts_text = ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
            dt = ts_text.split('T')[0].split(' ')[0]
            msg += f"{i}. {dt}: {total} questions\n"

        await update.message.reply_text(msg)
    except Exception as e:
        log_event(user_id, 'progress_failed', {'error': str(e)})
        await update.message.reply_text(
            "I couldn't fetch your progress right now. Please try again in a moment."
        )


# --- Q&A Command with RAG ---

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Q&A session - ask user to provide their question"""
    user_id = update.message.from_user.id

    # Set user in ask mode
    user_ask_mode[user_id] = True
    log_event(user_id, 'ask_started', None)
    await update.message.reply_text(
        "Please provide your question. You can continue asking follow-up questions in this mode."
    )


async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a weekly study plan based on uploaded documents"""
    user_id = update.message.from_user.id
    log_event(user_id, 'plan_requested', None)

    try:
        # Extract all text from uploaded PDFs
        pdf_texts = extract_texts_from_all_pdfs(UPLOAD_DIR)

        if not pdf_texts:
            await update.message.reply_text(
                "No study materials found!\n\n"
                "Please upload PDF files first to generate a study plan."
            )
            return

        # Send status message
        status_msg = await update.message.reply_text("⏳ Generating your study plan...")

        context_text = '\n'.join(pdf_texts)

        # Generate study plan using LLM
        global gpt
        qa_system_message = "You are a helpful study planning assistant. Create clear, actionable weekly study plans formatted as timetables."
        prompt = (
            f"Based on the following study materials, create a professional weekly study timetable for a university student.\n\n"
            f"Study Materials:\n{context_text[:2000]}\n\n"
            f"Generate a structured timetable with:\n"
            f"- Time slots (e.g., 10:00-11:30, 11:30-12:00, etc.)\n"
            f"- Days of the week (Monday through Friday)\n"
            f"- Include specific study topics/subjects based on the materials\n"
            f"- Include break times and lunch breaks\n"
            f"- Format as a table with headers: Time | Monday | Tuesday | Wednesday | Thursday | Friday\n\n"
            f"Example format:\n"
            f"Time | Monday | Tuesday | Wednesday | Thursday | Friday\n"
            f"10:00-11:30 | Topic A | Topic B | Topic A | Topic B | Topic A\n"
            f"11:30-12:00 | Break | Break | Break | Break | Break\n"
            f"17:45-18:00 | Wrap-up & Plan | Wrap-up & Plan | Wrap-up & Plan | Wrap-up & Plan | Wrap-up & Plan\n"
            f"[continue with more rows covering 10 AM to 6 PM]\n\n"
            f"Make sure to:\n"
            f"1. Cover all major topics from the materials\n"
            f"2. Distribute topics effectively across the week\n"
            f"3. Include appropriate breaks\n"
            f"4. Keep time slots to 1.5-2 hours for study, 15-30 minutes for breaks\n\n"
            f"Format ONLY as the table above, with no other text."
        )

        plan_content = gpt.submit(prompt, system_message=qa_system_message)

        # Try to generate image version
        image_buffer = generate_study_plan_image(plan_content)

        if image_buffer:
            # Delete status message and send image
            await status_msg.delete()
            # Send as image
            await update.message.reply_photo(
                photo=image_buffer,
                caption=""
            )
            log_event(user_id, 'plan_completed', {'format': 'image'})
        else:
            # Fallback to text format
            formatted_plan = format_study_plan_table(plan_content)
            await status_msg.edit_text("✅ Study plan generated!")
            await update.message.reply_text(formatted_plan)
            log_event(user_id, 'plan_completed', {
                'format': 'text',
                'plan_excerpt': db_excerpt(formatted_plan, 800),
            })

    except Exception as e:
        await update.message.reply_text(f"Error generating study plan: {e}")


def search_internet(query: str) -> str:
    """Generate an answer using LLM without document context"""
    try:
        global gpt
        qa_system_message = "You are a helpful study assistant that answers questions based on general knowledge. Provide clear and concise answers suitable for university students."
        prompt = (
            f"Please provide a clear and informative answer to the following question:\n\n"
            f"Question: {query}\n\n"
            f"Provide a comprehensive but concise answer based on general knowledge. "
            f"If this is a specialized topic, explain it in simple terms that students can understand."
        )

        answer = gpt.submit(prompt, system_message=qa_system_message)
        # Remove markdown formatting
        answer = strip_markdown(answer)
        return answer

    except Exception as e:
        print(f"[Internet Search Error] {e}")
        # Return a basic response
        return f"Unable to generate an answer for this question at the moment. Please try again later."


async def process_ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the user's question in Q&A mode"""
    user_id = update.message.from_user.id
    question = update.message.text.strip()
    log_message(user_id, question, sender='user')
    log_event(user_id, 'ask_question_received', {
              'question_excerpt': db_excerpt(question, 300)})

    try:
        # Extract chunks with metadata from all uploaded PDFs
        chunks = extract_texts_with_metadata(UPLOAD_DIR)
        relevant_chunks = []

        # Try to find relevant chunks if documents exist
        if chunks:
            relevant_chunks = retrieve_relevant_chunks(
                question, chunks, top_k=3)

        # If relevant chunks found, use LLM with document context
        if relevant_chunks:
            # Format context from retrieved chunks
            context_text = "\n\n".join([
                f"[From {chunk['filename']}, Page {chunk['page_num']}]\n{chunk['text'][:500]}"
                for chunk in relevant_chunks
            ])

            # Generate answer using LLM with context
            global gpt
            qa_system_message = "You are a helpful study assistant that answers questions based on provided study materials. Provide clear and concise answers."
            prompt = (
                f"Based on the following study materials, please answer this question:\n\n"
                f"Question: {question}\n\n"
                f"Study Materials:\n{context_text}\n\n"
                f"Please provide a clear and concise answer based on the materials. "
                f"If the materials don't contain relevant information, respond with: 'The provided materials do not contain information to answer this question.'"
            )

            answer = gpt.submit(prompt, system_message=qa_system_message)
            # Remove markdown formatting
            answer = strip_markdown(answer)

            # Check if answer indicates no relevant information found
            no_answer_indicators = [
                "do not contain information",
                "does not contain information",
                "not mentioned in",
                "not discussed in",
                "no information about",
                "no mention of",
                "materials do not"
            ]

            answer_lower = answer.lower()
            has_answer = not any(
                indicator in answer_lower for indicator in no_answer_indicators)

            if has_answer:
                # Format response with source information
                response = f"Answer: {answer}\n\n"
                response += "Source information:\n"
                for i, chunk in enumerate(relevant_chunks, 1):
                    response += f"{i}. {chunk['filename']} (Page {chunk['page_num']})\n"

                await update.message.reply_text(response)
                log_message(user_id, response, sender='bot')
                log_event(user_id, 'ask_answered_from_docs', {
                    'source_count': len(relevant_chunks),
                    'answer_excerpt': db_excerpt(answer, 500),
                })

                # Store context for follow-up questions
                user_ask_context[user_id] = {
                    'last_question': question,
                    'last_answer': answer,
                    'chunks': relevant_chunks
                }
                return

        # No relevant chunks or document says no answer - search internet
        internet_result = search_internet(question)

        response = f"Could not find related answers from your uploaded docs.\n\nHere is the answer from internet search\n\n{internet_result}"
        await update.message.reply_text(response)
        log_message(user_id, response, sender='bot')
        log_event(user_id, 'ask_answered_from_internet', {
            'answer_excerpt': db_excerpt(internet_result, 500),
        })

    except Exception as e:
        await update.message.reply_text(f"Error processing your question: {e}")


def main():
    global gpt
    gpt = ChatGPT(config)
    start_monitoring_server()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('quiz', quiz))
    app.add_handler(CommandHandler('progress', progress))
    app.add_handler(CommandHandler('summarize', summarize))
    app.add_handler(CommandHandler('endsession', endsession))
    app.add_handler(CommandHandler('ask', ask))
    app.add_handler(CommandHandler('plan', plan))

    # Route all text to a dispatcher that checks quiz and ask states
    async def text_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.from_user.id
        if user_id in user_ask_mode:
            await process_ask_question(update, context)
        elif user_id in user_quiz_prefs:
            await quiz(update, context)
        else:
            await handle_message(update, context)

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, text_dispatcher))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.run_polling()


if __name__ == '__main__':
    main()
