from __future__ import annotations
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from services.i18n import tr

async def required_channels(db):
    return [r for r in await db.channels() if int(r['active']) and int(r['required'])]

async def check_subscription(bot: Bot, user_id: int, db) -> tuple[bool, list[dict]]:
    missing = []
    for ch in await required_channels(db):
        target = ch['telegram_id'] if ch['telegram_id'] is not None else ch['username']
        if not target:
            continue
        try:
            member = await bot.get_chat_member(target, user_id)
            status = str(member.status)
            is_member = getattr(member, 'is_member', None)
            if status in {'member','administrator','creator'}:
                continue
            if status == 'restricted' and is_member is True:
                continue
            missing.append(ch)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError):
            # A channel we cannot verify safely remains blocking rather than granting access.
            missing.append(ch)
    return not missing, missing

def subscription_markup(lang: str, missing: list[dict], retry_data: str='subcheck') -> InlineKeyboardMarkup:
    rows=[]
    for ch in missing:
        url=ch['invite_link'] or (f"https://t.me/{str(ch['username']).lstrip('@')}" if ch['username'] else None)
        if url:
            rows.append([InlineKeyboardButton(text=f"📢 {str(ch['name'])[:36]}",url=url)])
    rows.append([InlineKeyboardButton(text=tr(lang,'check_subscription'),callback_data=retry_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def send_subscription_screen(bot: Bot, chat_id:int, user_id:int, db, lang:str, retry_data:str='subcheck') -> bool:
    ok, missing = await check_subscription(bot,user_id,db)
    if ok:
        return True
    await bot.send_message(chat_id,tr(lang,'sub_required'),reply_markup=subscription_markup(lang,missing,retry_data))
    return False
