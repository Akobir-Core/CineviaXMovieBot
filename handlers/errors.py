from __future__ import annotations
import logging
from aiogram import Router
from aiogram.types import ErrorEvent
from database.db import Database
from services.i18n import tr

router=Router()
logger=logging.getLogger(__name__)

@router.error()
async def global_error(event: ErrorEvent, db: Database | None = None):
    logger.exception('Unhandled update error: %s', event.exception)
    try:
        user_id = None
        if getattr(event.update, 'message', None):
            user_id = event.update.message.from_user.id
        elif getattr(event.update, 'callback_query', None):
            user_id = event.update.callback_query.from_user.id
        lang = 'uz'
        if db and user_id:
            row = await db.user(user_id)
            if row:
                lang = row['language']
        if getattr(event.update, 'message', None):
            await event.update.message.answer(tr(lang, 'technical_error'))
        elif getattr(event.update, 'callback_query', None):
            await event.update.callback_query.answer(tr(lang, 'technical_error_short'), show_alert=True)
    except Exception:
        logger.exception('Failed to send user-facing technical error message')
