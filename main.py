from __future__ import annotations
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import config
from database.db import Database
from handlers import user, admin, common, errors, discovery, admin_advanced
from services.security import GuardMiddleware
from services.admin_auth import hash_password
from utils.commands import set_user_commands

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger=logging.getLogger(__name__)

async def main():
    db=Database(config.database_path)
    await db.init(config.ceo_owner_id, hash_password(config.ceo_initial_password))
    bot=Bot(config.bot_token,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp=Dispatcher()
    dp['db']=db
    guard=GuardMiddleware(db)
    dp.message.middleware(guard)
    dp.callback_query.middleware(guard)
    dp.include_router(errors.router)
    dp.include_router(admin.router)
    dp.include_router(common.router)
    dp.include_router(user.router)
    dp.include_router(discovery.router)
    dp.include_router(admin_advanced.router)
    # Only public commands are visible by default. Admin commands are installed
    # for a chat after successful password authentication.
    await set_user_commands(bot)
    me=await bot.get_me()
    logger.info('Bot ishga tushdi: @%s',me.username)
    async def ban_cleanup_loop():
        while True:
            try:
                await db.cleanup()
            except Exception:
                logger.exception("Ban expiration cleanup failed")
            await asyncio.sleep(60)

    cleanup_task = asyncio.create_task(ban_cleanup_loop())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()

if __name__=='__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info('Bot stopped by user')
