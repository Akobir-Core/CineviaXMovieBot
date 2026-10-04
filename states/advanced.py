from aiogram.fsm.state import State, StatesGroup

class CollectionCreateState(StatesGroup):
    title=State()
    description=State()

class CollectionItemState(StatesGroup):
    code=State()

class ReleaseAddState(StatesGroup):
    code=State()
    release_at=State()
    title=State()

class DiscoverFilterState(StatesGroup):
    type=State()
    genre=State()
    year=State()
    rating=State()
    confirm=State()
