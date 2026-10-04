from __future__ import annotations
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from database.db import Database
from services.i18n import tr

router=Router()

@router.message(Command('cancel'))
async def cancel(message:Message,state:FSMContext,db:Database):
    row=await db.user(message.from_user.id)
    await state.clear()
    lang=row['language'] if row else 'uz'
    await message.answer(tr(lang,'cancelled'))
