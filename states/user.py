from aiogram.fsm.state import StatesGroup, State
class SearchState(StatesGroup):
    search=State()
    results=State()
class SupportState(StatesGroup): category=State(); message=State()
class QAState(StatesGroup): question=State(); confirm=State()
class BroadcastState(StatesGroup): message=State(); target=State(); selected=State()
class AdminUserState(StatesGroup): search=State()


class UserTicketReplyState(StatesGroup):
    ticket_id = State()


class UserQAReplyState(StatesGroup):
    question_id = State()


class CompareState(StatesGroup):
    second_code = State()

class ReportState(StatesGroup):
    report_type = State()
    message = State()
