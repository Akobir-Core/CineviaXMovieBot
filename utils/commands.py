from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

USER_COMMANDS = [
    BotCommand(command="start", description="Start CineviaXMovieBot"),
    BotCommand(command="help", description="Help"),
    BotCommand(command="cancel", description="Cancel current action"),
]

ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin", description="Private admin panel"),
    BotCommand(command="sdd", description="Private admin access"),
    BotCommand(command="add", description="Add content"),
    BotCommand(command="edit", description="Edit content"),
    BotCommand(command="delete", description="Delete content"),
    BotCommand(command="add_channel", description="Add required channel"),
    BotCommand(command="channels", description="Manage channels"),
    BotCommand(command="users", description="User management"),
    BotCommand(command="stats", description="Statistics"),
    BotCommand(command="broadcast", description="Broadcast"),
]

async def set_user_commands(bot: Bot, user_id: int | None = None) -> None:
    # Default users only see public commands. When user_id is supplied, replace any
    # previous per-chat admin scope with the public command set.
    if user_id is None:
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    else:
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeChat(chat_id=user_id))

async def set_admin_commands(bot: Bot, user_id: int) -> None:
    await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=user_id))
