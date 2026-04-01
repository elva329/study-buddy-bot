# Entry point for Study Buddy Bot

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from src.bot.handlers import start, handle_message, handle_document, summarize, quiz, progress, endsession, ask, plan
from src.config import config


def main():
    # You may want to load config and initialize services here
    app = ApplicationBuilder().token(
        config['telegram']['bot_token']).build()  # Replace with config usage
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('quiz', quiz))
    app.add_handler(CommandHandler('progress', progress))
    app.add_handler(CommandHandler('summarize', summarize))
    app.add_handler(CommandHandler('endsession', endsession))
    app.add_handler(CommandHandler('ask', ask))
    app.add_handler(CommandHandler('plan', plan))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    app.run_polling()


if __name__ == '__main__':
    main()
