# Inline and reply keyboard definitions for the bot

from telegram import KeyboardButton, ReplyKeyboardMarkup

# Example: Quiz answer keyboard


def quiz_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton(letter)] for letter in ['A', 'B', 'C', 'D']],
        one_time_keyboard=True,
        resize_keyboard=True
    )
