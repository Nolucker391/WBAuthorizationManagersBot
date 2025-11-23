from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def confirm_auth_user_kb():
    ikb = [
        [InlineKeyboardButton(text="🔐 Перейти к авторизации", callback_data='back_main_menu')],
    ]
    keybord = InlineKeyboardMarkup(inline_keyboard=ikb)
    return keybord
