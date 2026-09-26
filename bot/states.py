from aiogram.fsm.state import State, StatesGroup


class SearchStates(StatesGroup):
    waiting_for_query = State()
    waiting_for_limit = State()
    waiting_for_custom_limit = State()
