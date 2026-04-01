# Command and message handlers for the Telegram bot

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from src.services.llm_service import LLMService
from src.services.pdf_service import extract_texts_from_all_pdfs, extract_text_from_pdf
from src.services.rag_service import save_uploaded_file, list_uploaded_files
from src.services.quiz_service import parse_mcq_question
from src.config import config
from src.utils.logger import logger
import os
import asyncio

# --- State (to be replaced with DB-backed logic) ---
user_quiz_prefs = {}
user_quiz_state = {}
uploaded_files = []
upload_batch_timer = None
UPLOAD_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../uploads'))

# Make sure upload directory exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

llm = LLMService(config)


def debug_log(msg):
    print(f"[DEBUG] {msg}")
    logger.info(f"[DEBUG] {msg}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debug_log(f"/start called by user {update.message.from_user.id}")
    await update.message.reply_text(
        'Hello! I am your Study Buddy Bot. 📚\n\n'
        'I can help you study by:\n'
        '• Uploading PDF files for context\n'
        '• Creating multiple-choice quizzes from your materials\n'
        '• Answering questions about your study materials\n\n'
        'Commands:\n'
        '/quiz - Start a quiz\n'
        '/plan - Generate a weekly study plan\n'
        '/summarize - Get summaries of your uploaded PDFs\n'
        '/progress - View your quiz history'
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debug_log(f"handle_message called by user {update.message.from_user.id}")
    user_message = update.message.text
    user_id = update.message.from_user.id

    # Use all PDFs for context
    pdf_texts = extract_texts_from_all_pdfs(UPLOAD_DIR)
    context_text = '\n'.join(pdf_texts)

    if context_text.strip():
        prompt = f"Context from your uploaded PDFs:\n{context_text}\n\nQuestion: {user_message}"
    else:
        prompt = user_message
    response = llm.submit(prompt)
    await update.message.reply_text(response)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debug_log(f"handle_document called by user {update.message.from_user.id}")
    document = update.message.document
    user_id = update.message.from_user.id

    if document.mime_type == 'application/pdf':
        file = await context.bot.get_file(document.file_id)
        file_bytes = await file.download_as_bytearray()
        file_path = save_uploaded_file(file_bytes, document.file_name)

        global uploaded_files, upload_batch_timer
        uploaded_files.append(document.file_name)

        # Cancel previous timer if running
        if upload_batch_timer is not None and not upload_batch_timer.done():
            upload_batch_timer.cancel()

        async def send_batch():
            await asyncio.sleep(1.5)
            if uploaded_files:
                files_str = ', '.join(uploaded_files)
                await update.message.reply_text(f"✅ PDFs {files_str} uploaded and saved!")
                uploaded_files.clear()
        upload_batch_timer = asyncio.create_task(send_batch())
    else:
        await update.message.reply_text("Only PDF files are supported at this time.")


async def summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debug_log(f"/summarize called by user {update.message.from_user.id}")
    user_id = update.message.from_user.id
    files = list_uploaded_files()
    if not files:
        await update.message.reply_text("No uploaded notes found. Please upload PDF files first.")
        return

    await update.message.reply_text("Generating summaries for your uploaded notes...")
    for fname in files:
        if not fname.lower().endswith('.pdf'):
            continue
        pdf_path = os.path.join(UPLOAD_DIR, fname)
        try:
            text = extract_text_from_pdf(pdf_path)
            if not text.strip():
                await update.message.reply_text(f"❌ Could not extract text from {fname}.")
                continue
            prompt = f"Summarize the following study material in 5 concise bullet points for university students.\n\nMaterial:\n{text[:3000]}"
            summary = llm.submit(prompt)
            await update.message.reply_text(f"📄 {fname}\n{summary}")
        except Exception as e:
            await update.message.reply_text(f"Error summarizing {fname}: {e}")


async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debug_log(f"/quiz called by user {update.message.from_user.id}")
    user_id = update.message.from_user.id
    text = update.message.text.strip()

    # Use all PDFs for quiz
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

                context_text = '\n'.join(pdf_texts)
                if not context_text.strip():
                    await update.message.reply_text(
                        "⚠️ No study materials found!\n\n"
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
                feedback = f"✅ Correct!\n\nYour answer: {user_answer}) {user_option_text}\n\n"
            else:
                feedback = f"❌ Wrong!\n\nYour answer: {user_answer}) {user_option_text}\nCorrect answer: {question['answer']}) {correct_option_text}\n\n"

            if question.get('explanation'):
                feedback += f"📚 Explanation: {question['explanation']}"

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
            await update.message.reply_text(
                "📚 To start a quiz, please upload some study materials first!\n\n"
                "1. Send me PDF files of your study materials\n"
                "2. Then use /quiz to test your knowledge\n\n"
                "I'll create multiple-choice questions based on your uploaded materials."
            )
            return

        user_quiz_prefs[user_id] = {
            "step": "asking_amount"
        }
        await update.message.reply_text(
            "📝 How many questions would you like to answer?\n\nPlease enter a number between 1 and 20:"
        )


async def generate_mcq_question(update, context, user_id, question_num, total_questions, context_text):
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
    max_retries = 3
    for attempt in range(max_retries):
        response = llm.submit(prompt)
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

    thinking_msg = await update.message.reply_text(f"🤔 Generating question {qnum}/{total}...")
    question_data = await generate_mcq_question(update, context, user_id, qnum, total, context_text)

    if not question_data:
        await thinking_msg.edit_text("❌ Sorry, I couldn't generate a valid question. Please try again.")
        await finish_quiz(update, context, user_id)
        return

    state['last_question'] = question_data
    msg = f"📝 Question {qnum}/{total}\n\n{question_data['question']}\n\n"
    for i, opt in enumerate(question_data['options']):
        msg += f"{chr(65+i)}) {opt}\n"

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

    review = "📋 Quiz Review\n\n"
    for i, ans in enumerate(state.get('answers', [])):
        q = ans['q']
        correct_answer_letter = q['answer']
        correct_answer_text = q['options'][ord(
            correct_answer_letter) - ord('A')]
        review += f"Q{i+1}: {q['question']}\n"
        review += f"✓ Correct answer: {correct_answer_letter}) {correct_answer_text}\n\n"

        if len(review) > 3500 and i < total - 1:
            await update.message.reply_text(review)
            review = "📋 Quiz Review (continued)\n\n"

    await update.message.reply_text(
        f"🎉 Quiz Complete!\n\nYour Score: {score}/{total} ({percent}%)\n\n{review}",
        reply_markup=ReplyKeyboardRemove()
    )

    user_quiz_prefs.pop(user_id, None)
    user_quiz_state.pop(user_id, None)


async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debug_log(f"/progress called by user {update.message.from_user.id}")
    user_id = update.message.from_user.id
    # Placeholder for progress tracking
    await update.message.reply_text(
        "📊 Progress tracking is coming soon!\n\n"
        "Check back later for detailed statistics about your quiz performance."
    )


async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    debug_log(f"/plan called by user {update.message.from_user.id}")
    user_id = update.message.from_user.id

    try:
        # Extract all text from uploaded PDFs
        pdf_texts = extract_texts_from_all_pdfs(UPLOAD_DIR)

        if not pdf_texts:
            await update.message.reply_text(
                "No study materials found!\n\n"
                "Please upload PDF files first to generate a study plan."
            )
            return

        context_text = '\n'.join(pdf_texts)

        # Generate study plan using LLM
        prompt = (
            f"Based on the following study materials, create a detailed weekly study plan for a university student.\n\n"
            f"Study Materials:\n{context_text[:2000]}\n\n"
            f"Please generate a structured 7-day study plan that:\n"
            f"1. Covers all major topics from the materials\n"
            f"2. Distributes topics across the week\n"
            f"3. Includes suggested daily study duration\n"
            f"4. Provides specific learning objectives for each day\n\n"
            f"Format the plan as a clear, structured schedule with days and topics."
        )

        plan_content = llm.submit(prompt)

        # Format as a nicely structured message
        response = "Weekly Study Plan\n"
        # response += "=" * 40 + "\n\n"
        response += plan_content
        response += "\n\n" + "=" * 40

        await update.message.reply_text(response)

    except Exception as e:
        await update.message.reply_text(f"Error generating study plan: {e}")
