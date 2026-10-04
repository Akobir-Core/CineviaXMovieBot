from aiogram.fsm.state import StatesGroup, State


class AdminLoginState(StatesGroup):
    password = State()


class PasswordChangeState(StatesGroup):
    current = State()
    new = State()
    confirm = State()


class AdminResetState(StatesGroup):
    target = State()
    password = State()


class AdminAddPasswordState(StatesGroup):
    password = State()


class AdminBanState(StatesGroup):
    target_id = State()
    custom_minutes = State()
    reason = State()


class AdminContentSearchState(StatesGroup):
    query = State()
    page = State()
