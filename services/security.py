from __future__ import annotations
import logging
import time
from collections import defaultdict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from services.i18n import tr
from services.subscriptions import check_subscription, subscription_markup

logger = logging.getLogger(__name__)

class GuardMiddleware(BaseMiddleware):
    def __init__(self, db):
        self.db = db
        self.burst = defaultdict(list)

    async def __call__(self, handler, event, data):
        user = getattr(event, 'from_user', None)
        if not user:
            return await handler(event, data)
        now=time.monotonic(); arr=self.burst[user.id]
        while arr and now-arr[0] > 8: arr.pop(0)
        if len(arr) >= 18:
            row=await self.db.user(user.id); lang=row['language'] if row else 'uz'
            if isinstance(event, Message): await event.answer(tr(lang,'rate_limited'))
            else: await event.answer(tr(lang,'rate_limited'),show_alert=True)
            return
        arr.append(now)

        row=await self.db.user(user.id)
        lang=row['language'] if row else 'uz'
        admin=await self.db.admin(user.id)

        # Active admin accounts keep access to their private management surface.
        ban=await self.db.active_ban(user.id)
        if ban and not admin:
            expires=ban.get('ban_expires_at')
            when=expires[:19].replace('T',' ') if expires else tr(lang,'ban_permanent')
            text=tr(lang,'user_banned',reason=ban.get('ban_reason') or '—',expires=when)
            if isinstance(event, Message): await event.answer(text)
            else: await event.answer(text,show_alert=True)
            return

        # New-user language selection and subscription retry are intentionally allowed.
        if isinstance(event, CallbackQuery):
            data_value=event.data or ''
            if data_value.startswith('lang:') or data_value.startswith('subcheck:') or data_value=='subcheck':
                return await handler(event,data)
        if isinstance(event, Message):
            txt=(event.text or '').strip()
            if txt.startswith('/start'):
                return await handler(event,data)

        if admin:
            return await handler(event,data)

        # Normal users must stay behind the live required-channel gate.
        bot=data.get('bot')
        if bot is not None:
            ok,missing=await check_subscription(bot,user.id,self.db)
            if not ok:
                markup=subscription_markup(lang,missing,'subcheck')
                if isinstance(event, Message):
                    await event.answer(tr(lang,'sub_required'),reply_markup=markup)
                else:
                    await event.answer(tr(lang,'sub_no'),show_alert=True)
                    try:
                        await event.message.answer(tr(lang,'sub_required'),reply_markup=markup)
                    except Exception:
                        logger.debug('Failed to send subscription screen to callback message', exc_info=True)
                return

        maintenance=(await self.db.setting('maintenance_mode','0'))=='1'
        if maintenance:
            if isinstance(event,Message): await event.answer(tr(lang,'maintenance'))
            else: await event.answer(tr(lang,'maintenance'),show_alert=True)
            return
        return await handler(event,data)
