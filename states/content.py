from aiogram.fsm.state import StatesGroup, State
class ContentAddState(StatesGroup):
    title=State(); code=State(); ctype=State(); cartoon_mode=State(); alternative=State(); description=State(); poster=State(); media=State(); genre=State(); country=State(); year=State(); language=State(); translation=State(); rating=State(); confirm=State()
class SeriesAddState(StatesGroup):
    title=State(); code=State(); alternative=State(); description=State(); poster=State(); genre=State(); country=State(); year=State(); language=State(); translation=State(); rating=State(); confirm=State()
class EpisodeAddState(StatesGroup):
    series_code=State(); season=State(); episode=State(); title=State(); description=State(); code=State(); media=State(); confirm=State()
class EditState(StatesGroup): code=State(); field=State(); value=State(); confirm=State()
class DeleteState(StatesGroup): code=State(); confirm=State()
class ChannelState(StatesGroup): add=State(); edit=State()
class GenreState(StatesGroup): add=State(); rename=State()
class AdminAddState(StatesGroup): telegram_id=State(); role=State()
class TicketReplyState(StatesGroup): ticket_id=State(); answer=State()
class QAReplyState(StatesGroup): question_id=State(); answer=State()
class SettingsState(StatesGroup): value=State(); key=State()


class SeasonAddState(StatesGroup):
    series_id = State()
    season_number = State()
    title = State()

class SeasonEditState(StatesGroup):
    season_id = State()
    field = State()
    value = State()

class SeasonDeleteState(StatesGroup):
    season_id = State()
    confirm = State()

class ChannelDeleteState(StatesGroup):
    channel_id = State()
    confirm = State()

class GenreDeleteState(StatesGroup):
    genre_id = State()
    confirm = State()


class EpisodeEditState(StatesGroup):
    code = State()
    field = State()
    value = State()

class EpisodeDeleteState(StatesGroup):
    code = State()
    confirm = State()
