from __future__ import annotations
import asyncio
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest, TelegramNetworkError

async def run_broadcast(
    bot: Bot,
    db,
    admin_id: int,
    source_chat_id: int,
    source_message_id: int | list[int],
    target: str,
    language: str | None = None,
    selected: list[int] | None = None,
) -> tuple[int,int,int]:
    rows = await db.users_for_broadcast(target, language, selected)
    ids = [int(r['telegram_id']) for r in rows]
    source_ids = source_message_id if isinstance(source_message_id, list) else [source_message_id]
    msg_type = 'album' if len(source_ids) > 1 else 'telegram_message'
    bid = await db.create_broadcast(admin_id, msg_type, target, ids)
    ok = failed = 0
    for uid in ids:
        try:
            for src in source_ids:
                await bot.copy_message(uid, source_chat_id, src)
            ok += 1
            await db.broadcast_target(bid, uid, 'sent')
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.2)
            try:
                for src in source_ids:
                    await bot.copy_message(uid, source_chat_id, src)
                ok += 1
                await db.broadcast_target(bid, uid, 'sent')
            except Exception as exc:
                failed += 1
                await db.broadcast_target(bid, uid, 'failed', str(exc)[:500])
        except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError) as exc:
            failed += 1
            await db.broadcast_target(bid, uid, 'failed', str(exc)[:500])
        except Exception as exc:
            failed += 1
            await db.broadcast_target(bid, uid, 'failed', str(exc)[:500])
        await asyncio.sleep(0.04)
    await db.finish_broadcast(bid, ok, failed)
    return ok, failed, len(ids)
