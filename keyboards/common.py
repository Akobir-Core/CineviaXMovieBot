from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from services.i18n import tr

LANGS = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data='lang:uz'),
        InlineKeyboardButton(text='🇷🇺 Русский', callback_data='lang:ru'),
    ],
    [
        InlineKeyboardButton(text='🇬🇧 English', callback_data='lang:en'),
    ],
])

def language_prompt() -> str:
    return (
        "🇺🇿 O'zingizga qulay tilni tanlang\n"
        "🇷🇺 Выберите удобный язык\n"
        "🇬🇧 Choose your preferred language"
    )

def back_home(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang,'back'),callback_data='nav:back'), InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]
    ])

def confirm_cancel(lang,prefix='generic'):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'confirm'),callback_data=f'{prefix}:confirm'),InlineKeyboardButton(text=tr(lang,'cancel'),callback_data=f'{prefix}:cancel')]])


def pager(lang, action, page, total):
    row=[]
    if page>0:
        row.append(InlineKeyboardButton(text='⬅️',callback_data=f'{action}:{page-1}'))
    row.append(InlineKeyboardButton(text=tr(lang,'page',current=page+1,total=max(1,total)),callback_data='noop'))
    if page<max(0,total-1):
        row.append(InlineKeyboardButton(text='➡️',callback_data=f'{action}:{page+1}'))
    return [row]

def user_menu(lang):
    """Primary user navigation. Core areas stay visible; secondary tools are grouped below them."""
    rows = [
        [tr(lang, 'movies'), tr(lang, 'series')],
        [tr(lang, 'anime'), tr(lang, 'cartoons')],
        [tr(lang, 'search'), tr(lang, 'discover')],
        [tr(lang, 'my_cinema'), tr(lang, 'questions')],
        [tr(lang, 'support'), tr(lang, 'profile')],
        [tr(lang, 'settings')],
    ]
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


def settings_menu(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🌐 ' + tr(lang, 'language'), callback_data='menu:language')],
        [InlineKeyboardButton(text='🔔 ' + tr(lang, 'notifications'), callback_data='mycin:notifications')],
        [InlineKeyboardButton(text='ℹ️ ' + tr(lang, 'about'), callback_data='menu:about')],
        [InlineKeyboardButton(text=tr(lang, 'back'), callback_data='nav:home')],
    ])
