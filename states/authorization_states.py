from aiogram.fsm.state import State, StatesGroup


class StateEmail(StatesGroup):
    email_state = State()


class StatePhone(StatesGroup):
    phone_state = State()


class StateCaptcha(StatesGroup):
    sms_state = State()
    captcha_state = State()


class StateApprove(StatesGroup):
    approve = State()
    approve_true = State()
    approve_quit_account_state = State()

    phone = State()
    email = State()

