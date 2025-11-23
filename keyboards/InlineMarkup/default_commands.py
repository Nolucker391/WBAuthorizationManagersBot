from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def start_kb():
    ikb = [
        [InlineKeyboardButton(text="🔐 Авторизоваться", callback_data='wb_cb')],
        [
            InlineKeyboardButton(text="🤳 Тех. Поддержка", url="https://t.me/Nolucker"),
            InlineKeyboardButton(text="⭐Канал⭐", url="https://t.me/mp_keshbek")
        ],
    ]
    keybord = InlineKeyboardMarkup(inline_keyboard=ikb)
    return keybord


def auth_user_markup():
    ikb = [
        [
            InlineKeyboardButton(text="Предоплата WB", callback_data="pred_pay_wb"),
            InlineKeyboardButton(text="Предоплата Ozon", callback_data="pred_pay_ozon")
        ],
        [InlineKeyboardButton(text="Предоплата YM", callback_data='pred_pay_ym')],
        [
            InlineKeyboardButton(text="🤳 Тех. Поддержка", url="https://t.me/Nolucker"),
            InlineKeyboardButton(text="⭐Канал⭐", url="https://t.me/mp_keshbek")
        ],
        [InlineKeyboardButton(text="🚪 Выйти из аккаунта", callback_data='quit_account_user')],
    ]
    keybord = InlineKeyboardMarkup(inline_keyboard=ikb)
    return keybord


def cancel():
    ikb = [
        [
            InlineKeyboardButton(text="🚫 Отменить", callback_data='cancel'),
            InlineKeyboardButton(text="✅ Подтвердить", callback_data='approve_data_get_true')
        ]
    ]
    keybord = InlineKeyboardMarkup(inline_keyboard=ikb)
    return keybord


def base_inline_kb_post_auth():
    ikb = [
        [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_main_menu")]
    ]

    keybord = InlineKeyboardMarkup(inline_keyboard=ikb)
    return keybord


def approve_quit():
    ikb = [
        [
            InlineKeyboardButton(text="🚫 Нет", callback_data='back_main_menu'),
            InlineKeyboardButton(text="✅ Да", callback_data='approve_quit_account')
        ]
    ]
    keybord = InlineKeyboardMarkup(inline_keyboard=ikb)
    return keybord
