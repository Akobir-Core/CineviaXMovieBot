from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.db import Database, utcnow
from keyboards.admin import admin_panel, content_menu, roles_keyboard, dashboard_menu, users_menu, inquiries_menu, settings_menu
from services.broadcast import run_broadcast
from services.i18n import tr
from services.admin_auth import hash_password, verify_password, validate_password
from services.permissions import ALL_PERMISSIONS, PERMISSION_LABELS, has_permission, role_has, effective_permissions
from states.content import (
    AdminAddState,
    ChannelState,
    ChannelDeleteState, GenreDeleteState,
    ContentAddState,
    DeleteState,
    EditState,
    EpisodeAddState,
    EpisodeEditState,
    EpisodeDeleteState,
    GenreState,
    QAReplyState,
    SeriesAddState,
    SettingsState,
    TicketReplyState,
    SeasonAddState, SeasonEditState, SeasonDeleteState,
)
from states.user import AdminUserState, BroadcastState
from utils.commands import set_admin_commands, set_user_commands
from utils.helpers import extract_media
from states.admin import AdminLoginState, PasswordChangeState, AdminResetState, AdminAddPasswordState, AdminBanState, AdminContentSearchState
from keyboards.common import user_menu

router = Router()
ALBUM_TASKS: dict[tuple[int,str], asyncio.Task] = {}


ROLE_LABEL_KEYS = {
    "ceo": "role_ceo_label",
    "senior_admin": "role_senior_admin_label",
    "admin": "role_admin_label",
}

async def admin_context(event: Message | CallbackQuery, db: Database):
    row = await db.user(event.from_user.id)
    if not row:
        row, _ = await db.ensure_user(event.from_user)
    admin = await db.authenticated_admin(event.from_user.id)
    return row, admin

async def raw_admin(event: Message | CallbackQuery, db: Database):
    row = await db.user(event.from_user.id)
    if not row:
        row, _ = await db.ensure_user(event.from_user)
    return row, await db.admin_any(event.from_user.id)

async def admin_locked_message(db: Database, admin) -> int:
    state = await db.login_state(int(admin["telegram_id"]))
    if not state or not state["locked_until"]:
        return 0
    try:
        expires = datetime.fromisoformat(str(state["locked_until"]))
    except ValueError:
        return 0
    remaining = int(max(0, (expires - datetime.now(timezone.utc)).total_seconds()))
    return (remaining + 59) // 60


async def deny(event: Message | CallbackQuery, lang: str) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(tr(lang, "unauthorized"), show_alert=True)
    else:
        await event.answer(tr(lang, "unauthorized"))


async def section_access(db,admin,section:str)->bool:
    required={
        'dashboard':('statistics.view','users.view','reports.view','health.view'),
        'channels':('channels.manage',), 'users':('users.view',), 'tickets':('feedback.view',), 'qa':('qa.view',),
        'broadcast':('broadcast.send',), 'stats':('statistics.view',), 'settings':(), 'security':(),
        'admins':('admins.view','admins.manage','admins.create_junior','admins.manage_junior'), 'genres':('movies.edit','series.edit','anime.edit','cartoons.edit'), 'inbox':('feedback.view','qa.view','reports.view'),
        'content':('movies.view','series.view','anime.view','cartoons.view','episodes.view'),
    }
    req=required.get(section)
    if not req: return True
    for perm in req:
        if await has_permission(db,admin,perm): return True
    return False

async def _content_perm(db, admin, content_kind: str, action: str) -> bool:
    mapping = {
        "movie": f"movies.{action}",
        "series": f"series.{action}",
        "anime": f"anime.{action}",
        "cartoon": f"cartoons.{action}",
        "episode": f"episodes.{action}",
    }
    permission = mapping.get(content_kind)
    return bool(permission) and await has_permission(db, admin, permission)

async def _any_content_perm(db, admin, action: str) -> bool:
    for kind in ("movie", "series", "anime", "cartoon"):
        if await _content_perm(db, admin, kind, action):
            return True
    return False

async def _season_manage_perm(db, admin) -> bool:
    return await has_permission(db, admin, "series.edit") or await has_permission(db, admin, "episodes.view")


async def _content_type_keyboard(db: Database, admin, lang: str) -> InlineKeyboardMarkup:
    rows=[]
    options=[
        ("movie", "movies.create", "admin_type_movie"),
        ("series", "series.create", "admin_type_series"),
        ("anime", "anime.create", "admin_type_anime"),
        ("cartoon", "cartoons.create", "admin_type_cartoon"),
    ]
    current=[]
    for kind, perm, label_key in options:
        if await has_permission(db, admin, perm):
            current.append(InlineKeyboardButton(text=tr(lang,label_key), callback_data=f"ctype:{kind}"))
            if len(current)==2:
                rows.append(current); current=[]
    if current: rows.append(current)
    rows.append([InlineKeyboardButton(text=tr(lang,'cancel'), callback_data='nav:home')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def send_panel(event: Message | CallbackQuery, db: Database, bot: Bot) -> None:
    row, admin = await admin_context(event, db)
    lang = row["language"]
    if not admin:
        await deny(event, lang)
        return
    await set_admin_commands(bot, int(admin["telegram_id"]))
    markup = admin_panel(lang, admin['role'], await effective_permissions(db,admin))
    if isinstance(event, Message):
        await event.answer(tr(lang, "admin_panel"), reply_markup=markup)
    else:
        await event.message.answer(tr(lang, "admin_panel"), reply_markup=markup)
        await event.answer()




@router.message(Command("add"))
async def add_cmd(message: Message, db: Database, state: FSMContext):
    row, admin = await admin_context(message, db)
    if not admin or not await _any_content_perm(db, admin, "create"):
        await deny(message, row["language"])
        return
    await state.clear()
    await message.answer(tr(row["language"], "choose_content_type"), reply_markup=await _content_type_keyboard(db, admin, row["language"]))
    await state.set_state(ContentAddState.ctype)

@router.message(Command("edit"))
async def edit_cmd(message: Message, db: Database, state: FSMContext):
    row, admin = await admin_context(message, db)
    if not admin or not await _any_content_perm(db, admin, "edit"):
        await deny(message, row["language"])
        return
    await state.clear()
    await message.answer(tr(row["language"], "enter_code"))
    await state.set_state(EditState.code)

@router.message(Command("delete"))
async def delete_cmd(message: Message, db: Database, state: FSMContext):
    row, admin = await admin_context(message, db)
    if not admin or not await _any_content_perm(db, admin, "delete"):
        await deny(message, row["language"])
        return
    await state.clear()
    await message.answer(tr(row["language"], "enter_code"))
    await state.set_state(DeleteState.code)

@router.message(Command(commands=["admin", "sdd"]))
async def admin_cmd(message: Message, db: Database, bot: Bot, state: FSMContext):
    row, admin = await raw_admin(message, db)
    lang = row["language"]
    if not admin or not int(admin["active"]):
        await deny(message, lang)
        return
    locked = await admin_locked_message(db, admin)
    if locked:
        await message.answer(tr(lang, "password_locked", minutes=locked))
        return
    if await db.admin_session_valid(message.from_user.id):
        await send_panel(message, db, bot)
        return
    role = tr(lang, ROLE_LABEL_KEYS.get(admin["role"], "role_admin_label"))
    await message.answer(tr(lang, "admin_login_prompt", role=role))
    await state.clear()
    await state.set_state(AdminLoginState.password)

@router.message(AdminLoginState.password)
async def admin_login_password(message: Message, db: Database, bot: Bot, state: FSMContext):
    row, admin = await raw_admin(message, db)
    lang = row["language"]
    if not admin or not int(admin["active"]):
        await state.clear()
        await deny(message, lang)
        return
    locked = await admin_locked_message(db, admin)
    if locked:
        await state.clear()
        await message.answer(tr(lang, "password_locked", minutes=locked))
        return
    password = (message.text or "").strip()
    state_row = await db.login_state(int(admin["telegram_id"]))
    max_attempts = int(await db.setting("admin_login_max_attempts", "5"))
    if verify_password(password, admin["password_hash"]):
        minutes = int(await db.setting("admin_session_minutes", "720"))
        await db.login_success(int(admin["telegram_id"]))
        await db.set_admin_session(int(admin["telegram_id"]), minutes)
        await state.clear()
        await set_admin_commands(bot, int(admin["telegram_id"]))
        await db.log_admin(int(admin["telegram_id"]), "admin_login")
        await message.answer(tr(lang, "login_ok"))
        await send_panel(message, db, bot)
        return
    failed = int(state_row["failed_attempts"] or 0) + 1 if state_row else 1
    if failed >= max_attempts:
        lock_minutes = int(await db.setting("admin_login_lock_minutes", "15"))
        expires=(datetime.now(timezone.utc)+timedelta(minutes=lock_minutes)).isoformat()
        await db.login_failure(int(admin["telegram_id"]), expires)
        await state.clear()
        await db.log_admin(int(admin["telegram_id"]), "admin_login_locked")
        await message.answer(tr(lang, "password_locked", minutes=lock_minutes))
        return
    await db.login_failure(int(admin["telegram_id"]), None)
    left=max(0,max_attempts-failed)
    await message.answer(tr(lang, "wrong_password") + "\n" + tr(lang, "login_attempts_left", count=left))

@router.callback_query(F.data == "adm:home")
async def admin_home(cb: CallbackQuery, db: Database, bot: Bot):
    await send_panel(cb, db, bot)


@router.callback_query(F.data == "adm:close")
async def admin_close(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin:
        await deny(cb, row["language"])
        return
    await cb.message.answer(tr(row["language"], "panel_closed"), reply_markup=user_menu(row["language"]))
    await cb.answer()

@router.callback_query(F.data == "adm:logout")
async def admin_logout(cb: CallbackQuery, db: Database, bot: Bot, state: FSMContext):
    row, admin = await admin_context(cb, db)
    if not admin:
        await deny(cb, row["language"])
        return
    await db.invalidate_admin_session(int(admin["telegram_id"]))
    await state.clear()
    await set_user_commands(bot, int(admin["telegram_id"]))
    await db.log_admin(int(admin["telegram_id"]), "admin_logout")
    await cb.message.answer(tr(row["language"], "panel_closed"), reply_markup=user_menu(row["language"]))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:"))
async def admin_section(cb: CallbackQuery, db: Database, bot: Bot):
    row, admin = await admin_context(cb, db)
    lang = row["language"]
    if not admin:
        await deny(cb, lang)
        return
    section = cb.data.split(":", 1)[1]
    if not await section_access(db, admin, section):
        await deny(cb, lang)
        return
    permissions = await effective_permissions(db, admin)

    if section == "dashboard":
        await show_dashboard(cb, db, lang, permissions)
    elif section == "content":
        await cb.message.edit_text(tr(lang, "content_management"), reply_markup=content_menu(lang, admin["role"], permissions))
    elif section == "channels":
        await show_channels(cb, db, lang)
    elif section == "users":
        await show_users(cb, lang, permissions)
    elif section == "moderation":
        buttons = []
        if "users.view" in permissions:
            buttons.append([InlineKeyboardButton(text=tr(lang, "users"), callback_data="adm:users")])
        if "users.ban" in permissions:
            buttons.append([InlineKeyboardButton(text=tr(lang, "banned_users"), callback_data="users:list:banned")])
        if "reports.view" in permissions:
            buttons.append([InlineKeyboardButton(text=tr(lang, "report"), callback_data="adv:reports")])
        if "qa.view" in permissions:
            buttons.append([InlineKeyboardButton(text=tr(lang, "qa_manage"), callback_data="adm:qa")])
        if "feedback.view" in permissions:
            buttons.append([InlineKeyboardButton(text=tr(lang, "tickets"), callback_data="adm:tickets")])
        buttons.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:dashboard")])
        await cb.message.edit_text(tr(lang, "moderation"), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    elif section == "health":
        from handlers.admin_advanced import health_admin
        await health_admin(cb, db, bot)
        return
    elif section == "tickets":
        await show_tickets(cb, db, lang)
    elif section == "qa":
        await show_questions(cb, db, lang)
    elif section == "broadcast":
        await show_broadcast(cb, lang)
    elif section == "stats":
        await show_stats(cb, db, lang)
    elif section == "settings":
        await show_settings(cb, db, lang, permissions)
    elif section == "logs":
        await show_logs(cb, db, lang)
    elif section == "genres":
        await show_genres(cb, db, lang)
    elif section == "admins":
        await show_admins(cb, db, lang)
    elif section == "security":
        await show_security(cb, db, lang)
    elif section == "inbox":
        await show_inbox(cb, db, lang)
    await cb.answer()


async def show_dashboard(cb: CallbackQuery, db: Database, lang: str, permissions: set[str]):
    stats = await db.stats() if "statistics.view" in permissions else {}
    text = tr(lang, "dashboard_title")
    if stats:
        text += "\n\n" + tr(lang, "stats_text", **stats)
    await cb.message.edit_text(text, reply_markup=dashboard_menu(lang, permissions))


# --------------------------- season / episode management ---------------------------
async def _content_series_rows(db, limit=50):
    return await db.fetchall("SELECT id,title,code,content_type FROM series WHERE active=1 ORDER BY created_at DESC LIMIT ?", (limit,))

async def start_season_management(cb: CallbackQuery, db: Database, lang: str):
    rows=await _content_series_rows(db)
    buttons=[[InlineKeyboardButton(text=f"📺 {r['title'][:34]} · {r['content_type']}",callback_data=f'admseason:series:{r["id"]}')] for r in rows]
    buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:content')])
    await cb.message.edit_text(tr(lang,'season_manage'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def show_season_manager(target_message, db: Database, lang: str, series_id:int):
    series=await db.series_by_id(series_id)
    if not series:
        await target_message.answer(tr(lang,'not_found')); return
    seasons=await db.seasons(series_id)
    buttons=[[InlineKeyboardButton(text=f"📀 {x['season_number']} · {x['episode_count']}",callback_data=f'admseason:view:{series_id}:{x["season_number"]}'), InlineKeyboardButton(text='✏️',callback_data=f'admseason:edit:{x["id"]}'), InlineKeyboardButton(text='🗑',callback_data=f'admseason:delete:{x["id"]}')] for x in seasons]
    buttons.append([InlineKeyboardButton(text=tr(lang,'season_add'),callback_data=f'admseason:add:{series_id}')])
    buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='content:season_manage')])
    await target_message.answer(f"📺 {series['title']}\n\n{tr(lang,'season_manage')}",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def start_episode_management(cb: CallbackQuery, db: Database, lang: str):
    rows=await _content_series_rows(db)
    buttons=[[InlineKeyboardButton(text=f"📺 {r['title'][:34]} · {r['content_type']}",callback_data=f'admeps:series:{r["id"]}')] for r in rows]
    buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:content')])
    await cb.message.edit_text(tr(lang,'episode_manage'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith('admseason:series:'))
async def admseason_series(cb:CallbackQuery, db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.edit'):
        await deny(cb,lang); return
    await show_season_manager(cb.message,db,lang,int(cb.data.split(':')[-1])); await cb.answer()

@router.callback_query(F.data.startswith('admseason:add:'))
async def admseason_add(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.edit'):
        await deny(cb,lang); return
    await state.clear(); await state.update_data(series_id=int(cb.data.split(':')[-1]))
    await cb.message.answer(tr(lang,'season_number_prompt')); await state.set_state(SeasonAddState.season_number); await cb.answer()

@router.message(SeasonAddState.season_number)
async def admseason_add_number(message:Message,state:FSMContext,db:Database):
    row,admin=await admin_context(message,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.edit'):
        await state.clear(); await deny(message,lang); return
    try: number=int((message.text or '').strip())
    except ValueError: await message.answer(tr(lang,'invalid_number')); return
    if number<1:
        await message.answer(tr(lang,'invalid_number')); return
    data=await state.get_data()
    if await db.season(int(data['series_id']),number):
        await message.answer(tr(lang,'invalid')+' / duplicate season'); return
    await state.update_data(season_number=number); await message.answer(tr(lang,'season_title_prompt')); await state.set_state(SeasonAddState.title)

@router.message(SeasonAddState.title)
async def admseason_add_title(message:Message,state:FSMContext,db:Database):
    row,admin=await admin_context(message,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.edit'):
        await state.clear(); await deny(message,lang); return
    data=await state.get_data(); title=(message.text or '').strip(); title=None if title=='-' else title
    sid=await db.add_season(int(data['series_id']),int(data['season_number']),title)
    await db.log_admin(int(admin['telegram_id']),'add_season',str(sid),str(data['season_number']))
    await state.clear(); await message.answer(tr(lang,'season_saved'))

@router.callback_query(F.data.startswith('admseason:view:'))
async def admseason_view(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'episodes.view'):
        await deny(cb,lang); return
    _,_,series_id,season_no=cb.data.split(':')
    season=await db.season(int(series_id),int(season_no))
    if not season: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await show_episode_manager(cb.message,db,lang,int(series_id),int(season_no)); await cb.answer()

@router.callback_query(F.data.startswith('admseason:edit:'))
async def admseason_edit_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.edit'):
        await deny(cb,lang); return
    sid=int(cb.data.split(':')[-1]); season=await db.season_by_id(sid)
    if not season: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await state.clear(); await state.update_data(season_id=sid,series_id=int(season['series_id']))
    await cb.message.answer(tr(lang,'season_title_prompt')); await state.set_state(SeasonEditState.value); await cb.answer()

@router.message(SeasonEditState.value)
async def admseason_edit_save(message:Message,state:FSMContext,db:Database):
    row,admin=await admin_context(message,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.edit'):
        await state.clear(); await deny(message,lang); return
    data=await state.get_data(); title=(message.text or '').strip(); title=None if title=='-' else title
    await db.update_season(int(data['season_id']),title=title)
    await db.log_admin(int(admin['telegram_id']),'edit_season',str(data['season_id']))
    await state.clear(); await message.answer(tr(lang,'season_saved'))

@router.callback_query(F.data.startswith('admseason:delete:'))
async def admseason_delete_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.delete'):
        await deny(cb,lang); return
    sid=int(cb.data.split(':')[-1]); season=await db.season_by_id(sid)
    if not season: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await state.clear(); await state.update_data(season_id=sid)
    await cb.message.answer(f"⚠️ Season {season['season_number']}\n{tr(lang,'confirm')}",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'confirm'),callback_data='admseason:delete_yes')],[InlineKeyboardButton(text=tr(lang,'cancel'),callback_data='admseason:delete_no')]]))
    await state.set_state(SeasonDeleteState.confirm); await cb.answer()

@router.callback_query(SeasonDeleteState.confirm,F.data=='admseason:delete_yes')
async def admseason_delete_yes(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'series.delete'):
        await state.clear(); await deny(cb,lang); return
    sid=int((await state.get_data())['season_id']); await db.delete_season(sid); await db.log_admin(int(admin['telegram_id']),'delete_season',str(sid)); await state.clear(); await cb.message.answer(tr(lang,'season_deleted')); await cb.answer()

@router.callback_query(SeasonDeleteState.confirm,F.data=='admseason:delete_no')
async def admseason_delete_no(cb:CallbackQuery,state:FSMContext,db:Database):
    row,_=await admin_context(cb,db); await state.clear(); await cb.message.answer(tr(row['language'],'cancelled')); await cb.answer()

async def show_episode_manager(target_message,db:Database,lang:str,series_id:int,season_no:int):
    season=await db.season(series_id,season_no)
    if not season: await target_message.answer(tr(lang,'not_found')); return
    eps=await db.episodes(int(season['id']),50,0)
    buttons=[]
    for e in eps:
        buttons.append([InlineKeyboardButton(text=f"E{e['episode_number']} · {(e['title'] or '')[:22]}",callback_data='noop'), InlineKeyboardButton(text='⬆️',callback_data=f'epmove:up:{e["id"]}'), InlineKeyboardButton(text='⬇️',callback_data=f'epmove:down:{e["id"]}'), InlineKeyboardButton(text='✏️',callback_data=f'epmanage:edit:{e["id"]}'), InlineKeyboardButton(text='🗑',callback_data=f'epmanage:delete:{e["id"]}')])
    buttons.append([InlineKeyboardButton(text=tr(lang,'episode_add'),callback_data='content:add_episode')])
    buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data=f'admseason:series:{series_id}')])
    await target_message.answer(f"📀 {season_no}\n{tr(lang,'episode_manage')}",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith('admeps:series:'))
async def admeps_series(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'episodes.view'):
        await deny(cb,lang); return
    series_id=int(cb.data.split(':')[-1]); seasons=await db.seasons(series_id)
    buttons=[[InlineKeyboardButton(text=f"📀 {x['season_number']} · {x['episode_count']}",callback_data=f'admseason:view:{series_id}:{x["season_number"]}')] for x in seasons]
    buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='content:episode_manage')])
    await cb.message.edit_text(tr(lang,'episode_manage'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await cb.answer()

@router.callback_query(F.data.startswith('epmove:'))
async def epmove(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'episodes.edit'):
        await deny(cb,lang); return
    _,direction,eid=cb.data.split(':'); changed=await db.move_episode(int(eid),direction); e=await db.episode_by_id(int(eid))
    await cb.answer('✅' if changed else tr(lang,'invalid_number'),show_alert=not changed)
    if e: await show_episode_manager(cb.message,db,lang,int(e['series_id']),int(e['season_number']))

@router.callback_query(F.data.startswith('epmanage:edit:'))
async def epmanage_edit(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'episodes.edit'):
        await deny(cb,lang); return
    e=await db.episode_by_id(int(cb.data.split(':')[-1]))
    if not e: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await state.clear(); await state.update_data(episode_id=int(e['id']),code=e['code'])
    buttons=[[InlineKeyboardButton(text=tr(lang,'episode_number_edit'),callback_data='epedit:episode_number'),InlineKeyboardButton(text=tr(lang,'episode_title_edit'),callback_data='epedit:title')],[InlineKeyboardButton(text=tr(lang,'episode_media_edit'),callback_data='epedit:media'),InlineKeyboardButton(text=tr(lang,'episode_description_edit'),callback_data='epedit:description')],[InlineKeyboardButton(text=tr(lang,'back'),callback_data='admseason:view:%s:%s'%(e['series_id'],e['season_number']))]]
    await cb.message.answer(tr(lang,'episode_field_prompt'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await state.set_state(EpisodeEditState.field); await cb.answer()

@router.callback_query(F.data.startswith('epmanage:delete:'))
async def epmanage_delete(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'episodes.delete'):
        await deny(cb,lang); return
    eid=int(cb.data.split(':')[-1]); e=await db.episode_by_id(eid)
    if not e: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await state.clear(); await state.update_data(episode_id=eid,code=e['code'])
    await cb.message.answer(f"⚠️ {e['series_title']} · S{e['season_number']}E{e['episode_number']}\n{tr(lang,'confirm')}",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'confirm'),callback_data='epdelete:yes')],[InlineKeyboardButton(text=tr(lang,'cancel'),callback_data='epdelete:no')]])); await state.set_state(EpisodeDeleteState.confirm); await cb.answer()

# --------------------------- content add ---------------------------
@router.callback_query(F.data.startswith("content:"))
async def content_action(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    lang = row["language"]
    if not admin:
        await deny(cb, lang)
        return
    action = cb.data.split(":", 1)[1]
    permission_by_action = {
        "add": lambda: _any_content_perm(db, admin, "create"),
        "add_series": lambda: _content_perm(db, admin, "series", "create"),
        "add_anime": lambda: _content_perm(db, admin, "anime", "create"),
        "add_cartoon_series": lambda: _content_perm(db, admin, "cartoon", "create"),
        "add_episode": lambda: _content_perm(db, admin, "episode", "create"),
        "season_manage": lambda: _season_manage_perm(db, admin),
        "episode_manage": lambda: _content_perm(db, admin, "episode", "view"),
        "edit_episode": lambda: _content_perm(db, admin, "episode", "edit"),
        "delete_episode": lambda: _content_perm(db, admin, "episode", "delete"),
        "edit": lambda: _any_content_perm(db, admin, "edit"),
        "delete": lambda: _any_content_perm(db, admin, "delete"),
        "list": lambda: _any_content_perm(db, admin, "view"),
        "search": lambda: _any_content_perm(db, admin, "view"),
    }
    checker = permission_by_action.get(action)
    if checker and not await checker():
        await deny(cb, lang)
        return
    await state.clear()

    if action == "add":
        markup = await _content_type_keyboard(db, admin, lang)
        if len(markup.inline_keyboard) <= 1:
            await cb.answer(tr(lang, "unauthorized"), show_alert=True)
            return
        await cb.message.answer(tr(lang, "choose_content_type"), reply_markup=markup)
        await state.set_state(ContentAddState.ctype)
    elif action in {"add_series", "add_anime", "add_cartoon_series"}:
        content_type = 'anime' if action == 'add_anime' else 'cartoon' if action == 'add_cartoon_series' else 'series'
        await state.update_data(content_type=content_type)
        prompt_key = 'anime_add_title_prompt' if action == 'add_anime' else 'series_add_title_prompt'
        await cb.message.answer(tr(lang, prompt_key))
        await state.set_state(SeriesAddState.title)
    elif action == "add_episode":
        await cb.message.answer(tr(lang, "episode_series_code_prompt"))
        await state.set_state(EpisodeAddState.series_code)
    elif action == "season_manage":
        await start_season_management(cb, db, lang)
    elif action == "episode_manage":
        await start_episode_management(cb, db, lang)
    elif action == "edit_episode":
        await cb.message.answer(tr(lang, "episode_edit_prompt"))
        await state.set_state(EpisodeEditState.code)
    elif action == "delete_episode":
        await cb.message.answer(tr(lang, "episode_delete_prompt"))
        await state.set_state(EpisodeDeleteState.code)
    elif action == "edit":
        await cb.message.answer(tr(lang, "enter_code"))
        await state.set_state(EditState.code)
    elif action == "delete":
        await cb.message.answer(tr(lang, "enter_code"))
        await state.set_state(DeleteState.code)
    elif action == "list":
        await content_list_message(cb.message, db, lang)
    elif action == "search":
        await cb.message.edit_text(tr(lang, "content_admin_search_prompt"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:content")]]))
        await state.set_state(AdminContentSearchState.query)
    await cb.answer()


@router.message(ContentAddState.title)
async def add_title(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(title=message.text.strip())
    await message.answer(tr(row["language"], "add_code"))
    await state.set_state(ContentAddState.code)


@router.message(ContentAddState.code)
async def add_code(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    lang=row["language"]
    code = (message.text or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,31}", code):
        await message.answer(tr(lang, "invalid"))
        return
    if not await db.unique_code(code):
        await message.answer(tr(lang, "content_duplicate"))
        return
    data=await state.get_data()
    await state.update_data(code=code)
    # Type is selected at the beginning; do not ask for it again.
    if data.get("content_type") == "movie":
        await message.answer(tr(lang, "add_alt")); await state.set_state(ContentAddState.alternative); return
    if data.get("content_type") == "cartoon":
        await message.answer(tr(lang, "add_alt")); await state.set_state(ContentAddState.alternative); return
    await message.answer(tr(lang, "add_alt")); await state.set_state(ContentAddState.alternative)


@router.callback_query(ContentAddState.ctype, F.data.startswith("ctype:"))
async def add_content_type(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    lang = row["language"]
    content_type = cb.data.split(":", 1)[1]
    if content_type not in {"movie", "series", "anime", "cartoon"} or not admin:
        await deny(cb, lang); return
    permission_map = {"movie": "movies.create", "series": "series.create", "anime": "anime.create", "cartoon": "cartoons.create"}
    permission = permission_map[content_type]
    if not await has_permission(db, admin, permission):
        await deny(cb, lang); return
    if content_type == "cartoon":
        await state.update_data(content_type="cartoon")
        await cb.message.answer(tr(lang, "cartoon_mode_prompt"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang,"cartoon_single"), callback_data="cartoonmode:single")],
            [InlineKeyboardButton(text=tr(lang,"cartoon_series"), callback_data="cartoonmode:series")],
            [InlineKeyboardButton(text=tr(lang,"cancel"), callback_data="nav:home")],
        ]))
        await state.set_state(ContentAddState.cartoon_mode)
    elif content_type in {"series", "anime"}:
        await state.update_data(content_type=content_type)
        await cb.message.answer(tr(lang, "anime_add_title_prompt" if content_type == "anime" else "series_add_title_prompt"))
        await state.set_state(SeriesAddState.title)
    else:
        await state.update_data(content_type="movie")
        await cb.message.answer(tr(lang, "add_title"))
        await state.set_state(ContentAddState.title)
    await cb.answer()

@router.callback_query(ContentAddState.cartoon_mode, F.data.startswith("cartoonmode:"))
async def cartoon_mode_select(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db); lang = row["language"]
    if not admin or not await has_permission(db, admin, "cartoons.create"):
        await deny(cb, lang); return
    mode = cb.data.split(":",1)[1]
    if mode not in {"single","series"}:
        await cb.answer(tr(lang,"invalid"), show_alert=True); return
    await state.update_data(content_type="cartoon")
    if mode == "series":
        await cb.message.answer(tr(lang,"cartoon_series_title_prompt"))
        await state.set_state(SeriesAddState.title)
    else:
        await cb.message.answer(tr(lang,"cartoon_single_title_prompt"))
        await state.set_state(ContentAddState.title)
    await cb.answer()


@router.message(ContentAddState.alternative)
async def add_alt(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    value = message.text.strip()
    await state.update_data(alternative_title=None if value == "-" else value)
    await message.answer(tr(row["language"], "add_description"))
    await state.set_state(ContentAddState.description)


@router.message(ContentAddState.description)
async def add_desc(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    value = message.text.strip()
    await state.update_data(description=None if value == "-" else value)
    await message.answer(tr(row["language"], "add_poster"))
    await state.set_state(ContentAddState.poster)


@router.message(ContentAddState.poster, Command("skip"))
async def add_no_poster(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(poster_file_id=None)
    await message.answer(tr(row["language"], "add_media"))
    await state.set_state(ContentAddState.media)


@router.message(ContentAddState.poster)
async def add_poster(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    file_id, _ = extract_media(message)
    if not file_id:
        await message.answer(tr(row["language"], "invalid"))
        return
    await state.update_data(poster_file_id=file_id)
    await message.answer(tr(row["language"], "add_media"))
    await state.set_state(ContentAddState.media)


@router.message(ContentAddState.media)
async def add_media(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    file_id, media_type = extract_media(message)
    if not file_id:
        await message.answer(tr(row["language"], "invalid"))
        return
    duration = None
    media = message.video or message.audio or message.animation
    if media is not None:
        duration = getattr(media, 'duration', None)
    await state.update_data(media_file_id=file_id, media_type=media_type, duration=duration)
    await message.answer(tr(row["language"], "add_genre"))
    await state.set_state(ContentAddState.genre)


@router.message(ContentAddState.genre)
async def add_genre(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    genre = await db.genre(message.text.strip())
    if not genre:
        await message.answer(tr(row["language"], "genre_not_found"))
        return
    await state.update_data(genre_id=genre["id"])
    await message.answer(tr(row["language"], "add_country"))
    await state.set_state(ContentAddState.country)


@router.message(ContentAddState.country)
async def add_country(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    country = await db.country(message.text.strip())
    if not country:
        await message.answer(tr(row["language"], "country_not_found"))
        return
    await state.update_data(country_id=country["id"])
    await message.answer(tr(row["language"], "add_year"))
    await state.set_state(ContentAddState.year)


@router.message(ContentAddState.year)
async def add_year(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    try:
        year = int(message.text.strip())
    except ValueError:
        await message.answer(tr(row["language"], "invalid_year"))
        return
    if not 1888 <= year <= 2100:
        await message.answer(tr(row["language"], "invalid_year"))
        return
    await state.update_data(release_year=year)
    await message.answer(tr(row["language"], "add_language"))
    await state.set_state(ContentAddState.language)


@router.message(ContentAddState.language)
async def add_language(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(language=message.text.strip())
    await message.answer(tr(row["language"], "add_translation"))
    await state.set_state(ContentAddState.translation)


@router.message(ContentAddState.translation)
async def add_translation(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(translation_type=message.text.strip())
    await message.answer(tr(row["language"], "add_rating"))
    await state.set_state(ContentAddState.rating)


@router.message(ContentAddState.rating)
async def add_rating(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    try:
        rating = float(message.text.strip())
    except ValueError:
        await message.answer(tr(row["language"], "invalid_rating"))
        return
    if not 0 <= rating <= 10:
        await message.answer(tr(row["language"], "invalid_rating"))
        return
    await state.update_data(rating=rating)
    data = await state.get_data()
    genre = await db.genre(str(data.get('genre_id'))) if data.get('genre_id') else None
    country = await db.country(str(data.get('country_id'))) if data.get('country_id') else None
    genre_name = (genre[f'name_{row["language"]}'] if genre else '—')
    country_name = (country[f'name_{row["language"]}'] if country else '—')
    type_label = tr(row["language"], {'movie':'content_type_movie','anime':'content_type_anime','cartoon':'content_type_cartoon'}.get(data['content_type'],'content_type_movie'))
    preview = (f"🎬 {data['title']}\n🔐 {data['code']}\n\n"
               f"📂 {type_label}\n📅 {data.get('release_year','—')}\n🌍 {country_name}\n🎭 {genre_name}\n"
               f"🔊 {data.get('language') or '—'}\n🗣 {data.get('translation_type') or '—'}\n⭐ {rating}\n\n"
               f"📝 {data.get('description') or '—'}")
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(row["language"], "confirm"), callback_data="content_save:yes")],
            [InlineKeyboardButton(text=tr(row["language"], "cancel"), callback_data="content_save:no")],
        ]
    )
    await message.answer(tr(row["language"], "content_preview", preview=preview), reply_markup=markup)
    await state.set_state(ContentAddState.confirm)


@router.callback_query(ContentAddState.confirm, F.data == "content_save:yes")
async def save_movie(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    data = await state.get_data()
    content_type = data.get("content_type", "movie")
    perm_kind = content_type if content_type in {"anime", "cartoon"} else "movie"
    if not admin or not await _content_perm(db, admin, perm_kind, "create"):
        await state.clear(); await deny(cb, row["language"]); return
    try:
        content_id = await db.add_movie(data)
    except sqlite3.IntegrityError:
        await cb.answer(tr(row["language"], "content_duplicate"), show_alert=True)
        return
    except ValueError:
        await cb.answer(tr(row["language"], "invalid"), show_alert=True)
        return
    await db.log_admin(int(admin["telegram_id"]), "add_content", str(content_id), data["title"])
    await state.clear()
    await cb.message.answer(tr(row["language"], "content_saved"))
    await cb.answer()


@router.callback_query(ContentAddState.confirm, F.data == "content_save:no")
async def cancel_movie(cb: CallbackQuery, state: FSMContext, db: Database):
    row, _ = await admin_context(cb, db)
    await state.clear()
    await cb.message.answer(tr(row["language"], "cancelled"))
    await cb.answer()



async def _notify_episode_followers(bot: Bot, db: Database, series_id: int, episode_id: int) -> None:
    series = await db.series_by_id(series_id)
    episode = await db.episode_by_id(episode_id)
    if not series or not episode:
        return
    for u in await db.followers_of(series_id):
        if not await db.notifications_enabled(int(u['id']), 'new_episodes'):
            continue
        lang = u['language']
        text = f"🆕 {tr(lang, 'next_episode')}\n\n📺 {series['title']}\nS{episode['season_number']}E{episode['episode_number']}"
        try:
            await bot.send_message(int(u['telegram_id']), text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'watch'), callback_data=f"open:episode:{episode_id}")]]))
        except TelegramAPIError:
            continue

# --------------------------- series + episodes ---------------------------
@router.message(SeriesAddState.title)
async def series_title(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(title=message.text.strip())
    await message.answer(tr(row["language"], "series_add_code_prompt"))
    await state.set_state(SeriesAddState.code)


@router.message(SeriesAddState.code)
async def series_code(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    code = message.text.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,31}", code) or not await db.unique_code(code):
        await message.answer(tr(row["language"], "content_duplicate"))
        return
    await state.update_data(code=code)
    await message.answer(tr(row["language"], "series_add_alt_prompt"))
    await state.set_state(SeriesAddState.alternative)


@router.message(SeriesAddState.alternative)
async def series_alt(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    value = message.text.strip()
    await state.update_data(alternative_title=None if value == "-" else value)
    await message.answer(tr(row["language"], "series_add_desc_prompt"))
    await state.set_state(SeriesAddState.description)


@router.message(SeriesAddState.description)
async def series_desc(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    value = message.text.strip()
    await state.update_data(description=None if value == "-" else value)
    await message.answer(tr(row["language"], "series_add_poster_prompt"))
    await state.set_state(SeriesAddState.poster)


@router.message(SeriesAddState.poster, Command("skip"))
async def series_no_poster(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(poster_file_id=None)
    await message.answer(tr(row["language"], "series_add_genre_prompt"))
    await state.set_state(SeriesAddState.genre)


@router.message(SeriesAddState.poster)
async def series_poster(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    file_id, _ = extract_media(message)
    if not file_id:
        await message.answer(tr(row["language"], "invalid"))
        return
    await state.update_data(poster_file_id=file_id)
    await message.answer(tr(row["language"], "series_add_genre_prompt"))
    await state.set_state(SeriesAddState.genre)


@router.message(SeriesAddState.genre)
async def series_genre(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    genre = await db.genre(message.text.strip())
    if not genre:
        await message.answer(tr(row["language"], "genre_not_found"))
        return
    await state.update_data(genre_id=genre["id"])
    await message.answer(tr(row["language"], "series_add_country_prompt"))
    await state.set_state(SeriesAddState.country)


@router.message(SeriesAddState.country)
async def series_country(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    country = await db.country(message.text.strip())
    if not country:
        await message.answer(tr(row["language"], "country_not_found"))
        return
    await state.update_data(country_id=country["id"])
    await message.answer(tr(row["language"], "series_add_year_prompt"))
    await state.set_state(SeriesAddState.year)


@router.message(SeriesAddState.year)
async def series_year(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    try:
        year = int(message.text.strip())
    except ValueError:
        await message.answer(tr(row["language"], "series_add_year_invalid"))
        return
    if not 1888 <= year <= 2100:
        await message.answer(tr(row["language"], "series_add_year_invalid"))
        return
    await state.update_data(release_year=year)
    await message.answer(tr(row["language"], "series_add_language_prompt"))
    await state.set_state(SeriesAddState.language)


@router.message(SeriesAddState.language)
async def series_language(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(language=message.text.strip())
    await message.answer(tr(row["language"], "series_add_translation_prompt"))
    await state.set_state(SeriesAddState.translation)


@router.message(SeriesAddState.translation)
async def series_translation(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(translation_type=message.text.strip())
    await message.answer(tr(row["language"], "series_add_rating_prompt"))
    await state.set_state(SeriesAddState.rating)


@router.message(SeriesAddState.rating)
async def series_rating(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    try:
        rating = float(message.text.strip())
    except ValueError:
        await message.answer(tr(row["language"], "invalid_rating"))
        return
    if not 0 <= rating <= 10:
        await message.answer(tr(row["language"], "invalid_rating"))
        return
    await state.update_data(rating=rating)
    data = await state.get_data()
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"], "confirm"), callback_data="series_save:yes")],[InlineKeyboardButton(text=tr(row["language"], "cancel"), callback_data="series_save:no")]])
    await message.answer(tr(row["language"], "series_preview", title=data["title"], code=data["code"], rating=rating), reply_markup=markup)
    await state.set_state(SeriesAddState.confirm)


@router.callback_query(SeriesAddState.confirm, F.data == "series_save:yes")
async def series_save(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    data = await state.get_data()
    kind = data.get("content_type", "series")
    if not admin or not await _content_perm(db, admin, kind, "create"):
        await state.clear(); await deny(cb, row["language"]); return
    if not await db.unique_code(data["code"]):
        await cb.answer(tr(row["language"], "content_duplicate"), show_alert=True)
        return
    series_id = await db.add_series(data)
    await db.log_admin(int(admin["telegram_id"]), "add_series" if data.get("content_type") != "anime" else "add_anime", str(series_id), data["title"])
    await state.clear()
    await cb.message.answer(tr(row["language"], "content_saved"))
    await cb.answer()


@router.callback_query(SeriesAddState.confirm, F.data == "series_save:no")
async def series_cancel(cb: CallbackQuery, state: FSMContext, db: Database):
    row, _ = await admin_context(cb, db)
    await state.clear()
    await cb.message.answer(tr(row["language"], "cancelled"))
    await cb.answer()


@router.message(EpisodeAddState.series_code)
async def episode_series(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    series = await db.series_by_code(message.text.strip())
    if not series:
        await message.answer(tr(row["language"], "not_found"))
        return
    await state.update_data(series_id=series["id"])
    await message.answer(tr(row["language"], "season_number_prompt"))
    await state.set_state(EpisodeAddState.season)


@router.message(EpisodeAddState.season)
async def episode_season(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    try:
        value = int(message.text.strip())
        if value < 1:
            raise ValueError
    except ValueError:
        await message.answer(tr(row["language"], "invalid_number"))
        return
    await state.update_data(season_no=value)
    await message.answer(tr(row["language"], "episode_number_prompt"))
    await state.set_state(EpisodeAddState.episode)


@router.message(EpisodeAddState.episode)
async def episode_number(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    try:
        value = int(message.text.strip())
        if value < 1:
            raise ValueError
    except ValueError:
        await message.answer(tr(row["language"], "invalid_number"))
        return
    await state.update_data(ep_no=value)
    await message.answer(tr(row["language"], "episode_title_prompt"))
    await state.set_state(EpisodeAddState.title)


@router.message(EpisodeAddState.title)
async def episode_title(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    await state.update_data(title=message.text.strip())
    await message.answer(tr(row["language"], "episode_desc_prompt"))
    await state.set_state(EpisodeAddState.description)


@router.message(EpisodeAddState.description)
async def episode_description(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    value = message.text.strip()
    await state.update_data(description=None if value == "-" else value)
    await message.answer(tr(row["language"], "episode_code_prompt"))
    await state.set_state(EpisodeAddState.code)


@router.message(EpisodeAddState.code)
async def episode_code(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    code = message.text.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,31}", code) or not await db.unique_code(code):
        await message.answer(tr(row["language"], "content_duplicate"))
        return
    await state.update_data(code=code)
    await message.answer(tr(row["language"], "episode_media_prompt"))
    await state.set_state(EpisodeAddState.media)


@router.message(EpisodeAddState.media)
async def episode_media(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    file_id, media_type = extract_media(message)
    if not file_id:
        await message.answer(tr(row["language"], "invalid"))
        return
    duration = None
    media = message.video or message.audio or message.animation
    if media is not None:
        duration = getattr(media, "duration", None)
    await state.update_data(file_id=file_id, media_type=media_type, caption=message.caption, duration=duration)
    await message.answer(tr(row["language"], "save_question"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"], "confirm"), callback_data="episode_save:yes")],[InlineKeyboardButton(text=tr(row["language"], "cancel"), callback_data="episode_save:no")]]))
    await state.set_state(EpisodeAddState.confirm)


@router.callback_query(EpisodeAddState.confirm, F.data == "episode_save:yes")
async def episode_save(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    row, admin = await admin_context(cb, db)
    data = await state.get_data()
    if not admin or not await _content_perm(db, admin, "episode", "create"):
        await state.clear(); await deny(cb, row["language"]); return
    if not await db.unique_code(data["code"]):
        await cb.answer(tr(row["language"], "episode_duplicate"), show_alert=True); return
    if await db.episode_by_position(data["series_id"], data["season_no"], data["ep_no"]):
        await cb.answer(tr(row["language"], "episode_duplicate"), show_alert=True); return
    eid = await db.add_episode(data["series_id"], data["season_no"], data["ep_no"], data["code"], data["title"], data["description"], data["file_id"], data["media_type"], data.get("caption"), data.get("duration"))
    await db.log_admin(int(admin["telegram_id"]), "add_episode", str(eid), data["code"])
    await db.log_activity(int(row['id']), 'admin_add_episode', 'episode', int(eid), data['code']) if await db.user(int(admin['telegram_id'])) else None
    await _notify_episode_followers(bot, db, int(data['series_id']), int(eid))
    await state.clear()
    await cb.message.answer(tr(row["language"], "content_saved"))
    await cb.answer()


@router.callback_query(EpisodeAddState.confirm, F.data == "episode_save:no")
async def episode_cancel(cb: CallbackQuery, state: FSMContext, db: Database):
    row, _ = await admin_context(cb, db)
    await state.clear()
    await cb.message.answer(tr(row["language"], "cancelled"))
    await cb.answer()


@router.message(EpisodeEditState.code)
async def episode_edit_code(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await _content_perm(db, admin, "episode", "edit"):
        await state.clear(); await deny(message, row["language"]); return
    code=message.text.strip()
    episode=await db.episode_by_code(code)
    if not episode:
        await message.answer(tr(row["language"], "not_found")); return
    await state.update_data(episode_id=int(episode["id"]), code=episode["code"])
    buttons=[
        [InlineKeyboardButton(text=tr(row["language"],"episode_number_edit"),callback_data="epedit:episode_number"), InlineKeyboardButton(text=tr(row["language"],"episode_title_edit"),callback_data="epedit:title")],
        [InlineKeyboardButton(text=tr(row["language"],"episode_description_edit"),callback_data="epedit:description")],
        [InlineKeyboardButton(text=tr(row["language"],"episode_media_edit"),callback_data="epedit:media"), InlineKeyboardButton(text=tr(row["language"],"episode_caption_edit"),callback_data="epedit:caption")],
        [InlineKeyboardButton(text=tr(row["language"],"back"),callback_data="adm:content")]
    ]
    await message.answer(tr(row["language"],"episode_field_prompt"),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(EpisodeEditState.field)

@router.callback_query(EpisodeEditState.field,F.data.startswith("epedit:"))
async def episode_edit_field(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db)
    if not admin or not await _content_perm(db, admin, "episode", "edit"):
        await state.clear(); await deny(cb,row["language"]); return
    field=cb.data.split(":",1)[1]
    await state.update_data(field=field)
    await cb.message.answer(tr(row["language"],"episode_field_prompt")+"\n"+field)
    await state.set_state(EpisodeEditState.value)
    await cb.answer()

@router.message(EpisodeEditState.value)
async def episode_edit_value(message:Message,state:FSMContext,db:Database):
    row,admin=await admin_context(message,db)
    if not admin or not await _content_perm(db, admin, "episode", "edit"):
        await state.clear(); await deny(message,row["language"]); return
    data=await state.get_data(); field=data["field"]
    value=message.text.strip() if message.text is not None else None
    if field=='episode_number':
        try:
            new_no=int(value)
            if new_no<1: raise ValueError
        except ValueError:
            await message.answer(tr(row['language'],'invalid_number')); return
        try:
            await db.change_episode_number(int(data['episode_id']),new_no)
        except ValueError as exc:
            if str(exc)=='episode_number_conflict':
                await message.answer(tr(row['language'],'episode_duplicate')); return
            raise
    elif field=='media':
        file_id,media_type=extract_media(message)
        if not file_id:
            await message.answer(tr(row["language"],"invalid")); return
        await db.update_episode(int(data["episode_id"]),media_file_id=file_id,media_type=media_type)
    elif field=='caption':
        await db.update_episode(int(data["episode_id"]),caption=value or None)
    elif field in {'title','description'}:
        await db.update_episode(int(data["episode_id"]),**{field:(None if value=='-' else value)})
    else:
        await message.answer(tr(row["language"],"invalid")); return
    await db.log_admin(int(admin["telegram_id"]),"edit_episode",data["code"],field)
    await state.clear()
    await message.answer(tr(row["language"],"episode_updated"))

@router.message(EpisodeDeleteState.code)
async def episode_delete_code(message:Message,state:FSMContext,db:Database):
    row,admin=await admin_context(message,db)
    if not admin or not await _content_perm(db, admin, "episode", "delete"):
        await state.clear(); await deny(message,row["language"]); return
    code=message.text.strip()
    episode=await db.episode_by_code(code)
    if not episode:
        await message.answer(tr(row["language"],"not_found")); return
    await state.update_data(episode_id=int(episode["id"]),code=code)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"],"confirm"),callback_data="epdelete:yes"),InlineKeyboardButton(text=tr(row["language"],"cancel"),callback_data="epdelete:no")]])
    await message.answer(f"⚠️ {episode['series_title']} · S{episode['season_number']} E{episode['episode_number']}\n{tr(row['language'],'confirm')}?",reply_markup=kb)
    await state.set_state(EpisodeDeleteState.confirm)

@router.callback_query(EpisodeDeleteState.confirm,F.data=="epdelete:yes")
async def episode_delete_yes(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db)
    if not admin or not await _content_perm(db, admin, "episode", "delete"):
        await state.clear(); await deny(cb,row["language"]); return
    data=await state.get_data()
    await db.delete_episode(int(data["episode_id"]))
    await db.log_admin(int(admin["telegram_id"]),"delete_episode",data["code"])
    await state.clear()
    await cb.message.answer(tr(row["language"],"episode_deleted")); await cb.answer()

@router.callback_query(EpisodeDeleteState.confirm,F.data=="epdelete:no")
async def episode_delete_no(cb:CallbackQuery,state:FSMContext,db:Database):
    row,_=await admin_context(cb,db); await state.clear(); await cb.message.answer(tr(row["language"],"cancelled")); await cb.answer()

async def content_list_message(message: Message, db: Database, lang: str):
    """Admin content library entry screen. The actual item lists are paginated by type."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=tr(lang, "movies"), callback_data="admincontent:list:movie:0"),
            InlineKeyboardButton(text=tr(lang, "series"), callback_data="admincontent:list:series:0"),
        ],
        [
            InlineKeyboardButton(text=tr(lang, "anime"), callback_data="admincontent:list:anime:0"),
            InlineKeyboardButton(text=tr(lang, "cartoons"), callback_data="admincontent:list:cartoon:0"),
        ],
        [InlineKeyboardButton(text=tr(lang, "search_content"), callback_data="content:search")],
        [InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:content")],
    ])
    await message.edit_text(tr(lang, "content_list"), reply_markup=kb)


async def _admin_content_items(db: Database, kind: str, limit: int = 8, offset: int = 0, query: str | None = None):
    params: list[Any] = []
    parts = []
    title_clause = ""
    if query:
        title_clause = " AND (title LIKE ? OR alternative_title LIKE ? OR original_title LIKE ? OR code LIKE ?)"
        q = f"%{query}%"
        params.extend([q, q, q, q])
    if kind == "movie":
        parts = [f"SELECT id,title,code,content_type,release_year,active,visibility,created_at,'movie' kind FROM movies WHERE content_type='movie'{title_clause}"]
    elif kind in {"series", "anime", "cartoon"}:
        parts = [f"SELECT id,title,code,content_type,release_year,active,visibility,created_at,'series' kind FROM series WHERE content_type=?{title_clause}"]
        params.insert(0, kind)
        if kind in {"anime", "cartoon"}:
            parts.append(f"SELECT id,title,code,content_type,release_year,active,visibility,created_at,'movie' kind FROM movies WHERE content_type=?{title_clause}")
            params.extend([kind] + ([f"%{query}%"] * 4 if query else []))
    else:
        return []
    sql = " UNION ALL ".join(parts) + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return await db.fetchall(sql, tuple(params))


async def _admin_content_count(db: Database, kind: str, query: str | None = None) -> int:
    if kind == "movie":
        tables = [("movies", "movie")]
    elif kind in {"series", "anime", "cartoon"}:
        tables = [("series", kind)]
        if kind in {"anime", "cartoon"}:
            tables.append(("movies", kind))
    else:
        return 0
    total = 0
    for table, ctype in tables:
        if query:
            q = f"%{query}%"
            row = await db.fetchone(f"SELECT COUNT(*) c FROM {table} WHERE content_type=? AND (title LIKE ? OR alternative_title LIKE ? OR original_title LIKE ? OR code LIKE ?)", (ctype,q,q,q,q))
        elif table == "movies":
            row = await db.fetchone("SELECT COUNT(*) c FROM movies WHERE content_type=?", (ctype,))
        else:
            row = await db.fetchone("SELECT COUNT(*) c FROM series WHERE content_type=?", (ctype,))
        total += int(row["c"] or 0)
    return total


def _row_value(row, key: str, default=None):
    try:
        return row[key] if key in row.keys() else default
    except (AttributeError, KeyError):
        return default


def _content_permission_kind(storage_kind: str, content) -> str:
    ctype = str(_row_value(content, "content_type", storage_kind) or storage_kind)
    if storage_kind == "series" and ctype in {"series", "anime", "cartoon"}:
        return ctype
    if storage_kind == "movie" and ctype in {"movie", "anime", "cartoon"}:
        return "movie" if ctype == "movie" else ctype
    return storage_kind


def _admin_content_label(lang: str, row) -> str:
    status = "🟢" if int(row["active"] or 0) else "⚪"
    visibility = str(row["visibility"] or "public")
    vis = {"public":"", "code_only":" 🔐", "hidden":" 🚫"}.get(visibility, "")
    return f"{status} {row['title'][:34]} · {row['code']}{vis}"


@router.callback_query(F.data.regexp(r'^admincontent:list:(movie|series|anime|cartoon|search):\d+$'))
async def admin_content_list(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    lang = row["language"]
    if not admin:
        await deny(cb, lang)
        return
    kind = cb.data.split(":")[2]
    page = int(cb.data.split(":")[3])
    if not await _content_perm(db, admin, kind, "view"):
        await deny(cb, lang)
        return
    size = max(4, int(await db.setting("pagination_size", "8")))
    total_items = await _admin_content_count(db, kind)
    total_pages = max(1, (total_items + size - 1) // size)
    page = max(0, min(page, total_pages - 1))
    rows = await _admin_content_items(db, kind, size, page * size)
    kb = [[InlineKeyboardButton(text=_admin_content_label(lang, r), callback_data=f"admincontent:item:{r['kind']}:{r['id']}:{kind}:{page}")] for r in rows]
    if page > 0 or page < total_pages - 1:
        nav=[]
        if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admincontent:list:{kind}:{page-1}"))
        nav.append(InlineKeyboardButton(text=tr(lang,"page",current=page+1,total=total_pages), callback_data="noop"))
        if page < total_pages - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admincontent:list:{kind}:{page+1}"))
        kb.append(nav)
    if not rows:
        kb.append([InlineKeyboardButton(text=tr(lang,"add_content"), callback_data="content:add")])
    kb.append([InlineKeyboardButton(text=tr(lang,"back"), callback_data="content:list")])
    title = {"movie":tr(lang,"movies"),"series":tr(lang,"series"),"anime":tr(lang,"anime"),"cartoon":tr(lang,"cartoons")}[kind]
    text = f"{title}\n\n" + (f"{tr(lang,'content_list')} · {page+1}/{total_pages}" if rows else tr(lang,"content_library_empty"))
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


async def _render_admin_edit_fields(db: Database, admin, lang: str, content, kind: str, cid: int, back_kind: str, page: int, message):
    fields = [
        [InlineKeyboardButton(text=tr(lang,"edit_title_label"), callback_data=f"admincontent:field:title:{kind}:{cid}:{back_kind}:{page}"), InlineKeyboardButton(text=tr(lang,"edit_description_label"), callback_data=f"admincontent:field:description:{kind}:{cid}:{back_kind}:{page}")],
        [InlineKeyboardButton(text=tr(lang,"edit_year_label"), callback_data=f"admincontent:field:release_year:{kind}:{cid}:{back_kind}:{page}"), InlineKeyboardButton(text=tr(lang,"edit_rating_label"), callback_data=f"admincontent:field:rating:{kind}:{cid}:{back_kind}:{page}")],
        [InlineKeyboardButton(text=tr(lang,"edit_active_label"), callback_data=f"admincontent:field:active:{kind}:{cid}:{back_kind}:{page}"), InlineKeyboardButton(text=tr(lang,"edit_visibility_label"), callback_data=f"admincontent:field:visibility:{kind}:{cid}:{back_kind}:{page}")],
        [InlineKeyboardButton(text=tr(lang,"edit_poster_label"), callback_data=f"admincontent:field:poster_file_id:{kind}:{cid}:{back_kind}:{page}")],
    ]
    if kind == "movie":
        fields.append([InlineKeyboardButton(text=tr(lang,"edit_media_label"), callback_data=f"admincontent:field:media_file_id:{kind}:{cid}:{back_kind}:{page}")])
    fields.append([InlineKeyboardButton(text=tr(lang,"back"), callback_data=f"admincontent:item:{kind}:{cid}:{back_kind}:{page}")])
    await message.edit_text(tr(lang,"edit_choose"), reply_markup=InlineKeyboardMarkup(inline_keyboard=fields))


@router.callback_query(F.data.regexp(r'^admincontent:item:(movie|series):\d+:(movie|series|anime|cartoon|search):\d+$'))
async def admin_content_item(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    lang = row["language"]
    if not admin:
        await deny(cb, lang); return
    _,_,kind,cid,back_kind,page = cb.data.split(":")
    cid=int(cid); page=int(page)
    content = await db.content_by_kind_id(kind,cid,public_only=False)
    if not content:
        await cb.answer(tr(lang,"not_found"),show_alert=True); return
    perm_kind = _content_permission_kind(kind, content)
    if not await _content_perm(db, admin, perm_kind, "view"):
        await deny(cb,lang); return
    ctype = str(_row_value(content,"content_type",kind) or kind)
    title = _row_value(content,"title","—")
    country = _row_value(content,"country_uz") or _row_value(content,"country_ru") or _row_value(content,"country_en") or "—"
    genre = _row_value(content,"genre_uz") or _row_value(content,"genre_ru") or _row_value(content,"genre_en") or "—"
    text = (f"🎬 {title}\n\n🔐 {_row_value(content,'code','—')}\n📂 {ctype}\n📅 {_row_value(content,'release_year') or '—'}\n"
            f"🌍 {country}\n🎭 {genre}\n🔊 {_row_value(content,'language') or '—'}\n⭐ {_row_value(content,'rating') or 0}\n👁 {_row_value(content,'views_count') or 0}\n"
            f"📌 {'🟢' if int(_row_value(content,'active',0) or 0) else '⚪'} {_row_value(content,'visibility') or 'public'}\n\n📝 {_row_value(content,'description') or '—'}")
    kb=[]
    if await _content_perm(db,admin,perm_kind,"edit"):
        kb.append([InlineKeyboardButton(text=tr(lang,"edit_content"),callback_data=f"admincontent:edit:{kind}:{cid}:{back_kind}:{page}")])
    if await _content_perm(db,admin,perm_kind,"view"):
        kb.append([InlineKeyboardButton(text=tr(lang,"content_preview"),callback_data=f"admincontent:preview:{kind}:{cid}:{back_kind}:{page}"), InlineKeyboardButton(text=tr(lang,"content_stats"),callback_data=f"admincontent:stats:{kind}:{cid}:{back_kind}:{page}")])
    if await _content_perm(db,admin,perm_kind,"delete"):
        kb.append([InlineKeyboardButton(text=tr(lang,"delete_content"),callback_data=f"admincontent:delete:{kind}:{cid}:{back_kind}:{page}")])
    back_cb = f"admincontent:search:{page}" if back_kind == "search" else f"admincontent:list:{back_kind}:{page}"
    kb.append([InlineKeyboardButton(text=tr(lang,"back"),callback_data=back_cb)])
    await cb.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()

@router.callback_query(F.data.regexp(r'^admincontent:preview:(movie|series):\d+:(movie|series|anime|cartoon|search):\d+$'))
async def admin_content_preview(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin: await deny(cb,lang); return
    _,_,kind,cid,back_kind,page=cb.data.split(':'); cid=int(cid); page=int(page)
    content=await db.content_by_kind_id(kind,cid,public_only=False)
    if not content: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    perm_kind=_content_permission_kind(kind,content)
    if not await _content_perm(db,admin,perm_kind,'view'): await deny(cb,lang); return
    preview = f"🎬 {_row_value(content,'title','—')}\n\n🔐 {_row_value(content,'code','—')}\n📅 {_row_value(content,'release_year') or '—'}\n⭐ {_row_value(content,'rating') or 0}\n\n{_row_value(content,'description') or '—'}"
    kb=[[InlineKeyboardButton(text=tr(lang,'back'),callback_data=f'admincontent:item:{kind}:{cid}:{back_kind}:{page}')]]
    await cb.message.edit_text(preview,reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.regexp(r'^admincontent:stats:(movie|series):\d+:(movie|series|anime|cartoon|search):\d+$'))
async def admin_content_stats(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin: await deny(cb,lang); return
    _,_,kind,cid,back_kind,page=cb.data.split(':'); cid=int(cid); page=int(page)
    content=await db.content_by_kind_id(kind,cid,public_only=False)
    if not content: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    perm_kind=_content_permission_kind(kind,content)
    if not await _content_perm(db,admin,perm_kind,'view'): await deny(cb,lang); return
    if not content: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    text=f"📊 {_row_value(content,'title','—')}\n\n👁 {_row_value(content,'views_count') or 0}\n🔎 {_row_value(content,'search_count') or 0}\n❤️ {_row_value(content,'likes_count') or 0}"
    kb=[[InlineKeyboardButton(text=tr(lang,'back'),callback_data=f'admincontent:item:{kind}:{cid}:{back_kind}:{page}')]]
    await cb.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.regexp(r'^admincontent:delete:(movie|series):\d+:(movie|series|anime|cartoon|search):\d+$'))
async def admin_content_delete_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin: await deny(cb,lang); return
    _,_,kind,cid,back_kind,page=cb.data.split(':'); cid=int(cid); page=int(page)
    content=await db.content_by_kind_id(kind,cid,public_only=False)
    if not content: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    perm_kind=_content_permission_kind(kind,content)
    if not await _content_perm(db,admin,perm_kind,'delete'): await deny(cb,lang); return
    await state.clear(); await state.update_data(code=content['code'],content_kind=kind,permission_kind=perm_kind,back_kind=back_kind,back_page=page)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'confirm'),callback_data='delete:yes')],[InlineKeyboardButton(text=tr(lang,'cancel'),callback_data='delete:no')]])
    await cb.message.edit_text(f"⚠️ {content['title']}\n🔐 {content['code']}\n\n{tr(lang,'confirm')}",reply_markup=kb)
    await state.set_state(DeleteState.confirm); await cb.answer()

@router.callback_query(F.data.startswith('admincontent:edit:'))
async def admin_content_edit_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin: await deny(cb,lang); return
    _,_,kind,cid,back_kind,page=cb.data.split(':'); cid=int(cid); page=int(page)
    content=await db.content_by_kind_id(kind,cid,public_only=False)
    if not content: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    perm_kind=_content_permission_kind(kind,content)
    if not await _content_perm(db,admin,perm_kind,'edit'): await deny(cb,lang); return
    await state.clear(); await state.update_data(kind=kind,cid=cid,code=content['code'],permission_kind=perm_kind,back_kind=back_kind,back_page=page)
    await _render_admin_edit_fields(db,admin,lang,content,kind,cid,back_kind,page,cb.message); await cb.answer()

@router.callback_query(F.data.regexp(r'^admincontent:field:(title|description|release_year|rating|active|visibility|poster_file_id|media_file_id):(movie|series):\d+:(movie|series|anime|cartoon|search):\d+$'))
async def admin_content_field_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin: await deny(cb,lang); return
    _,_,field,kind,cid,back_kind,page=cb.data.split(':'); cid=int(cid); page=int(page)
    content=await db.content_by_kind_id(kind,cid,public_only=False)
    if not content: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    perm_kind=_content_permission_kind(kind,content)
    if not await _content_perm(db,admin,perm_kind,'edit'): await deny(cb,lang); return
    await state.clear(); await state.update_data(kind=kind,cid=cid,code=content['code'],permission_kind=perm_kind,field=field,back_kind=back_kind,back_page=page)
    await state.set_state(EditState.value)
    await cb.message.answer(tr(lang,'edit_value_prompt',field=field)); await cb.answer()



async def _collect_admin_content_search(db: Database, admin, query: str):
    query=query.strip()
    rows=[]
    for kind in ("movie","series","anime","cartoon"):
        rows.extend(await _admin_content_items(db, kind, 60, 0, query))
    seen=set(); result=[]
    for r in rows:
        key=(str(r["kind"]),int(r["id"]))
        if key in seen: continue
        seen.add(key)
        perm_kind=_content_permission_kind(str(r["kind"]),r)
        if await _content_perm(db,admin,perm_kind,"view"): result.append(r)
    result.sort(key=lambda r:(str(r["created_at"] or ""),int(r["id"])),reverse=True)
    return result


async def _render_admin_search_results(message: Message, db: Database, lang: str, admin, query: str, page: int):
    size=max(4,int(await db.setting("pagination_size","8")))
    rows=await _collect_admin_content_search(db,admin,query)
    total_pages=max(1,(len(rows)+size-1)//size)
    page=max(0,min(int(page),total_pages-1))
    chunk=rows[page*size:(page+1)*size]
    kb=[[InlineKeyboardButton(text=_admin_content_label(lang,r),callback_data=f"admincontent:item:{r['kind']}:{r['id']}:search:{page}")] for r in chunk]
    if page>0 or page<total_pages-1:
        nav=[]
        if page>0: nav.append(InlineKeyboardButton(text="⬅️",callback_data=f"admincontent:search:{page-1}"))
        nav.append(InlineKeyboardButton(text=tr(lang,"page",current=page+1,total=total_pages),callback_data="noop"))
        if page<total_pages-1: nav.append(InlineKeyboardButton(text="➡️",callback_data=f"admincontent:search:{page+1}"))
        kb.append(nav)
    kb.append([InlineKeyboardButton(text=tr(lang,"back"),callback_data="adm:content")])
    title=tr(lang,"search_results")
    status=(tr(lang,"page",current=page+1,total=total_pages) if chunk else tr(lang,"content_admin_search_empty"))
    await message.edit_text(f"{title}\n\n🔎 {query}\n\n{status}",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.message(AdminContentSearchState.query)
async def admin_content_search_message(message: Message, state: FSMContext, db: Database):
    row,admin=await admin_context(message,db); lang=row['language']
    if not admin or not await _any_content_perm(db,admin,'view'):
        await state.clear(); await deny(message,lang); return
    query=(message.text or '').strip()
    if not query:
        await message.answer(tr(lang,'content_admin_search_prompt')); return
    await state.update_data(query=query,page=0)
    # Send a new result message because the search query itself is a user message.
    size=max(4,int(await db.setting("pagination_size","8")))
    rows=await _collect_admin_content_search(db,admin,query)
    total_pages=max(1,(len(rows)+size-1)//size); chunk=rows[:size]
    kb=[[InlineKeyboardButton(text=_admin_content_label(lang,r),callback_data=f"admincontent:item:{r['kind']}:{r['id']}:search:{page}")] for r in chunk]
    if total_pages>1: kb.append([InlineKeyboardButton(text=tr(lang,'page',current=1,total=total_pages),callback_data='admincontent:search:1'),InlineKeyboardButton(text='➡️',callback_data='admincontent:search:1')])
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:content')])
    await message.answer(f"{tr(lang,'search_results')}\n\n🔎 {query}\n\n"+(tr(lang,'page',current=1,total=total_pages) if chunk else tr(lang,'content_admin_search_empty')),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.regexp(r'^admincontent:search:\d+$'))
async def admin_content_search_page(cb: CallbackQuery, state: FSMContext, db: Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await _any_content_perm(db,admin,'view'):
        await deny(cb,lang); return
    data=await state.get_data(); query=str(data.get('query') or '').strip()
    if not query:
        await cb.message.edit_text(tr(lang,'content_admin_search_prompt'),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:content')]])); await cb.answer(); return
    page=int(cb.data.split(':')[-1]); await state.update_data(page=page)
    await _render_admin_search_results(cb.message,db,lang,admin,query,page); await cb.answer()


# --------------------------- edit/delete ---------------------------
@router.message(EditState.code)
async def edit_code(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin:
        await deny(message, row["language"]); return
    code = message.text.strip()
    movie = await db.movie_by_code(code)
    series = None if movie else await db.series_by_code(code)
    if not movie and not series:
        await message.answer(tr(row["language"], "not_found"))
        return
    kind = "movie" if movie else "series"
    content = movie or series
    permission_kind = str(content["content_type"]) if str(content["content_type"]) in {"series","anime","cartoon"} else "movie"
    if not await _content_perm(db, admin, permission_kind, "edit"):
        await deny(message, row["language"]); return
    await state.update_data(kind=kind, permission_kind=permission_kind, cid=int(content["id"]), code=content["code"])
    fields = [
        [InlineKeyboardButton(text=tr(row["language"], "edit_title_label"), callback_data="editfield:title"), InlineKeyboardButton(text=tr(row["language"], "edit_alt_label"), callback_data="editfield:alternative_title")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_original_label"), callback_data="editfield:original_title"), InlineKeyboardButton(text=tr(row["language"], "edit_description_label"), callback_data="editfield:description")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_code_label"), callback_data="editfield:code"), InlineKeyboardButton(text=tr(row["language"], "edit_year_label"), callback_data="editfield:release_year")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_rating_label"), callback_data="editfield:rating"), InlineKeyboardButton(text=tr(row["language"], "edit_language_label"), callback_data="editfield:language")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_translation_label"), callback_data="editfield:translation_type"), InlineKeyboardButton(text=tr(row["language"], "edit_quality_label"), callback_data="editfield:quality")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_age_label"), callback_data="editfield:age_rating"), InlineKeyboardButton(text=tr(row["language"], "edit_audio_label"), callback_data="editfield:audio_languages")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_subtitle_label"), callback_data="editfield:subtitle_languages"), InlineKeyboardButton(text=tr(row["language"], "edit_active_label"), callback_data="editfield:active")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_featured_label"), callback_data="editfield:featured")],
        [InlineKeyboardButton(text=tr(row["language"], "edit_visibility_label"), callback_data="editfield:visibility"), InlineKeyboardButton(text=tr(row["language"], "edit_moderation_label"), callback_data="editfield:moderation_status")],
    ]
    if kind == "movie":
        fields.append([InlineKeyboardButton(text=tr(row["language"], "edit_media_label"), callback_data="editfield:media_file_id"), InlineKeyboardButton(text=tr(row["language"], "edit_poster_label"), callback_data="editfield:poster_file_id")])
    else:
        fields.append([InlineKeyboardButton(text=tr(row["language"], "edit_poster_label"), callback_data="editfield:poster_file_id")])
        if content['content_type'] == 'anime':
            fields.append([InlineKeyboardButton(text=tr(row["language"], "edit_studio_label"), callback_data="editfield:studio"), InlineKeyboardButton(text=tr(row["language"], "edit_anime_type_label"), callback_data="editfield:anime_type")])
            fields.append([InlineKeyboardButton(text=tr(row["language"], "edit_status_label"), callback_data="editfield:status")])
    await message.answer(tr(row["language"], "edit_choose"), reply_markup=InlineKeyboardMarkup(inline_keyboard=fields))
    await state.set_state(EditState.field)


@router.callback_query(EditState.field, F.data.startswith("editfield:"))
async def edit_field(cb: CallbackQuery, state: FSMContext, db: Database):
    row, _ = await admin_context(cb, db)
    field = cb.data.split(":", 1)[1]
    await state.update_data(field=field)
    await cb.message.answer(tr(row["language"], "edit_value_prompt", field=field))
    await state.set_state(EditState.value)
    await cb.answer()


@router.message(EditState.value)
async def edit_value(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    data = await state.get_data()
    field = data["field"]
    permission_kind = str(data.get("permission_kind") or ("series" if data.get("kind") == "series" else "movie"))
    if not admin or not await _content_perm(db, admin, permission_kind, "edit"):
        await state.clear(); await deny(message, row["language"]); return

    if field in {"media_file_id", "poster_file_id"}:
        file_id, media_type = extract_media(message)
        if not file_id:
            await message.answer(tr(row["language"], "invalid"))
            return
        value = file_id
        if field == "media_file_id" and data.get("kind") == "movie":
            await db.update_content("movie", data["cid"], "media_file_id", file_id)
            await db.update_content("movie", data["cid"], "media_type", media_type)
        else:
            await db.update_content(data["kind"], data["cid"], field, value)
    else:
        value: Any = message.text.strip()
        if field == "rating":
            try:
                value = float(value)
            except ValueError:
                await message.answer(tr(row["language"], "invalid_rating"))
                return
            if not 0 <= value <= 10:
                await message.answer(tr(row["language"], "invalid_rating"))
                return
        elif field == "release_year":
            try:
                value = int(value)
            except ValueError:
                await message.answer(tr(row["language"], "invalid_year"))
                return
        elif field in {"active", "featured"}:
            value = 1 if value.lower() in {"1", "true", "yes", "ha", "on"} else 0
        elif field in {"alternative_title","original_title","studio","anime_type","status","age_rating","quality","audio_languages","subtitle_languages"} and value == "-":
            value = None
        await db.update_content(data["kind"], data["cid"], field, value)

    await db.log_admin(int(admin["telegram_id"]), "edit_content", data["code"], field)
    await state.clear()
    await message.answer(tr(row["language"], "settings_saved"))


@router.message(DeleteState.code)
async def delete_code(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    code = message.text.strip()
    content = await db.movie_by_code(code) or await db.series_by_code(code) or await db.episode_by_code(code)
    if not content:
        await message.answer(tr(row["language"], "not_found"))
        return
    content_kind = "episode" if "season_id" in content.keys() else ("series" if "series_id" not in content.keys() and "content_type" in content.keys() and content["content_type"] == "series" else None)
    if content_kind is None:
        ctype = str(content["content_type"]) if "content_type" in content.keys() else "movie"
        content_kind = ctype if ctype in {"anime","cartoon"} else "movie"
    if not await _content_perm(db, (await db.admin_any(message.from_user.id)), content_kind, "delete"):
        await deny(message, row["language"]); return
    await state.update_data(code=code, content_kind=content_kind)
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"], "confirm"), callback_data="delete:yes")],[InlineKeyboardButton(text=tr(row["language"], "cancel"), callback_data="delete:no")]])
    await message.answer(f"⚠️ {code}\n{tr(row['language'], 'confirm')}?", reply_markup=markup)
    await state.set_state(DeleteState.confirm)


@router.callback_query(DeleteState.confirm, F.data == "delete:yes")
async def delete_yes(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    data = await state.get_data()
    if not admin or not await _content_perm(db, admin, data.get("permission_kind", data.get("content_kind", "movie")), "delete"):
        await state.clear(); await deny(cb, row["language"]); return
    await db.delete_content_by_code(data["code"])
    await db.log_admin(int(admin["telegram_id"]), "delete_content", data["code"])
    await state.clear()
    back_kind = data.get("back_kind", "movie")
    back_page = int(data.get("back_page", 0))
    await cb.message.edit_text(tr(row["language"], "content_deleted"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"], "back"), callback_data=f"admincontent:list:{back_kind}:{back_page}")],[InlineKeyboardButton(text=tr(row["language"], "admin_panel"), callback_data="adm:home")]]))
    await cb.answer()


@router.callback_query(DeleteState.confirm, F.data == "delete:no")
async def delete_no(cb: CallbackQuery, state: FSMContext, db: Database):
    row, _ = await admin_context(cb, db)
    await state.clear()
    await cb.message.answer(tr(row["language"], "cancelled"))
    await cb.answer()


# --------------------------- channels ---------------------------
async def show_channels(cb: CallbackQuery, db: Database, lang: str):
    rows = await db.channels()
    lines = [tr(lang, "channel_row", id=r['id'], active=('🟢' if r['active'] else '⚫'), required=('🔒' if int(r['required']) else '▫️'), name=r['name'], username=r['username'] or '—', telegram_id=r['telegram_id'] or '—') for r in rows]
    text = tr(lang, "channels_text", rows="\n".join(lines)) if rows else tr(lang, "channel_list_empty")
    buttons = [
        [InlineKeyboardButton(text=f"{'🟢' if r['active'] else '⚫'} {r['name'][:25]}", callback_data=f"channel:toggle:{r['id']}"), InlineKeyboardButton(text="✏️", callback_data=f"channel:edit:{r['id']}"), InlineKeyboardButton(text="🗑", callback_data=f"channel:delete:{r['id']}")]
        for r in rows
    ]
    buttons.append([InlineKeyboardButton(text=tr(lang,"add_channel"), callback_data="channel:add")])
    buttons.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(Command("channels"))
async def channels_cmd(message: Message, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db,admin,"channels.manage"):
        await deny(message, row["language"])
        return
    rows = await db.channels()
    lines = [tr(row["language"], "channel_row", id=r['id'], active=('🟢' if r['active'] else '⚫'), required=('🔒' if int(r['required']) else '▫️'), name=r['name'], username=r['username'] or '—', telegram_id=r['telegram_id'] or '—') for r in rows]
    text = tr(row["language"], "channels_text", rows="\n".join(lines)) if rows else tr(row["language"], "channel_list_empty")
    buttons = [[InlineKeyboardButton(text=f"{'🟢' if r['active'] else '⚫'} {r['name'][:25]}", callback_data=f"channel:toggle:{r['id']}"), InlineKeyboardButton(text="✏️", callback_data=f"channel:edit:{r['id']}"), InlineKeyboardButton(text="🗑", callback_data=f"channel:delete:{r['id']}")] for r in rows]
    buttons.append([InlineKeyboardButton(text=tr(row["language"],"add_channel"), callback_data="channel:add")])
    buttons.append([InlineKeyboardButton(text=tr(row["language"], "back"), callback_data="adm:home")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.message(Command("add_channel"))
async def add_channel_cmd(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db,admin,"channels.manage"):
        await deny(message, row["language"])
        return
    await message.answer(tr(row["language"], "channel_add_prompt"))
    await state.set_state(ChannelState.add)


@router.callback_query(F.data == "channel:add")
async def channel_add_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"channels.manage"):
        await deny(cb, row["language"])
        return
    await cb.message.answer(tr(row["language"], "channel_add_prompt"))
    await state.set_state(ChannelState.add)
    await cb.answer()


async def save_channel_from_text(message: Message, state: FSMContext, db: Database, edit: bool = False):
    row, admin = await admin_context(message, db)
    parts = [x.strip() for x in message.text.split("|")]
    if len(parts) < 2:
        await message.answer(tr(row["language"], "invalid"))
        return
    name, ref = parts[0], parts[1]
    invite = parts[2] if len(parts) > 2 and parts[2] else None
    required = True if len(parts) < 4 else str(parts[3]).strip().lower() in {'1','true','yes','y','ha'}
    username = ref if ref.startswith("@") else None
    tg_id = int(ref) if re.fullmatch(r"-?\d+", ref) else None
    if not username and tg_id is None:
        await message.answer(tr(row["language"], "invalid"))
        return
    try:
        chat = await message.bot.get_chat(tg_id if tg_id is not None else username)
    except TelegramAPIError:
        chat = None
    if not chat:
        await message.answer(tr(row["language"], "channel_invalid"))
        return
    try:
        me = await message.bot.get_me()
        bot_member = await message.bot.get_chat_member(chat.id, me.id)
        if bot_member.status not in {"administrator", "creator"}:
            await message.answer(tr(row["language"], "channel_invalid"))
            return
    except TelegramAPIError:
        await message.answer(tr(row["language"], "channel_invalid"))
        return
    tg_id = chat.id
    username = f"@{chat.username}" if chat.username else username
    name = chat.title or name
    existing = await db.fetchone("SELECT id FROM channels WHERE (telegram_id=? OR (username IS NOT NULL AND lower(username)=lower(?)))", (tg_id, username))
    data = await state.get_data()
    if existing and (not edit or int(existing['id']) != int(data.get('channel_id',-1))):
        await message.answer(tr(row["language"], "channel_duplicate"))
        return
    if edit:
        data = await state.get_data()
        await db.execute("UPDATE channels SET name=?,username=?,telegram_id=?,invite_link=?,required=?,updated_at=? WHERE id=?", (name, username, tg_id, invite, 1 if required else 0, utcnow(), data["channel_id"]))
        await db.log_admin(int(admin["telegram_id"]), "edit_channel", str(data["channel_id"]))
    else:
        await db.add_channel(name, username, tg_id, invite or (f"https://t.me/{username.lstrip('@')}" if username else None), required)
        await db.log_admin(int(admin["telegram_id"]), "add_channel", ref, name)
    await state.clear()
    await message.answer(tr(row["language"], "settings_saved"))


@router.message(ChannelState.add)
async def channel_add_save(message: Message, state: FSMContext, db: Database):
    await save_channel_from_text(message, state, db, edit=False)


@router.callback_query(F.data.startswith("channel:toggle:"))
async def channel_toggle(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"channels.manage"):
        await deny(cb, row["language"])
        return
    cid = int(cb.data.split(":")[-1])
    await db.toggle_channel(cid)
    await db.log_admin(int(admin["telegram_id"]), "toggle_channel", str(cid))
    await show_channels(cb, db, row["language"])
    await cb.answer()


@router.callback_query(F.data.startswith("channel:delete:"))
async def channel_delete_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"channels.manage"):
        await deny(cb, row["language"])
        return
    cid = int(cb.data.split(":")[-1])
    channel = await db.fetchone("SELECT * FROM channels WHERE id=?", (cid,))
    if not channel:
        await cb.answer(tr(row["language"],"not_found"), show_alert=True)
        return
    await state.clear(); await state.update_data(channel_id=cid)
    await cb.message.answer(
        f"⚠️ {channel['name']}\n{tr(row['language'],'confirm')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(row['language'],'confirm'),callback_data='channel:delete_yes'),InlineKeyboardButton(text=tr(row['language'],'cancel'),callback_data='channel:delete_no')]
        ])
    )
    await state.set_state(ChannelDeleteState.confirm)
    await cb.answer()

@router.callback_query(ChannelDeleteState.confirm, F.data == 'channel:delete_yes')
async def channel_delete_yes(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"channels.manage"):
        await state.clear(); await deny(cb, row["language"]); return
    cid=int((await state.get_data())['channel_id'])
    await db.delete_channel(cid)
    await db.log_admin(int(admin["telegram_id"]), "delete_channel", str(cid))
    await state.clear()
    await show_channels(cb, db, row["language"])
    await cb.answer(tr(row['language'],'deleted'), show_alert=True)

@router.callback_query(ChannelDeleteState.confirm, F.data == 'channel:delete_no')
async def channel_delete_no(cb: CallbackQuery, state: FSMContext, db: Database):
    row,_=await admin_context(cb,db); await state.clear(); await cb.answer(tr(row['language'],'cancelled'), show_alert=True)


@router.callback_query(F.data.startswith("channel:edit:"))
async def channel_edit_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"channels.manage"):
        await deny(cb, row["language"])
        return
    await state.update_data(channel_id=int(cb.data.split(":")[-1]))
    await cb.message.answer(tr(row["language"], "channel_add_prompt"))
    await state.set_state(ChannelState.edit)
    await cb.answer()


@router.message(ChannelState.edit)
async def channel_edit_save(message: Message, state: FSMContext, db: Database):
    await save_channel_from_text(message, state, db, edit=True)


# --------------------------- user management ---------------------------
async def show_users(cb: CallbackQuery, lang: str, permissions: set[str] | None = None):
    await cb.message.edit_text(tr(lang,'users_title'),reply_markup=users_menu(lang, permissions or set()))

@router.callback_query(F.data.startswith('users:list:'))
async def users_list(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'users.view'):
        await deny(cb,lang); return
    mode=cb.data.split(':')[-1]
    if mode=='banned':
        rows=await db.banned_users(50)
        buttons=[[InlineKeyboardButton(text=f"🚫 {r['first_name'] or 'User'} · {r['telegram_id']}",callback_data=f'user:profile:{r["telegram_id"]}')] for r in rows]
        text=tr(lang,'banned_users')
    else:
        rows=await db.fetchall("SELECT telegram_id,first_name,username FROM users WHERE is_active=1 AND telegram_id NOT IN (SELECT telegram_id FROM bans WHERE status='active') ORDER BY last_seen_at DESC LIMIT 50")
        buttons=[[InlineKeyboardButton(text=f"🟢 {r['first_name'] or 'User'} · {r['telegram_id']}",callback_data=f'user:profile:{r["telegram_id"]}')] for r in rows]
        text=tr(lang,'active_users')
    buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:users')])
    await cb.message.edit_text(text+"\n\n"+("\n".join([f"• {r['telegram_id']}" for r in rows]) if rows else '—'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@router.callback_query(F.data.startswith('user:profile:'))
async def user_profile(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'users.view'):
        await deny(cb,lang); return
    uid=int(cb.data.split(':')[-1]); data=await db.user_stats(uid)
    if not data: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    ban=data['ban']; status=tr(lang,'ban') if ban else tr(lang,'active_users')
    expires=(ban['ban_expires_at'][:19].replace('T',' ') if ban and ban.get('ban_expires_at') else tr(lang,'ban_permanent')) if ban else '—'
    text=tr(lang, "user_profile_text", name=data['first_name'], telegram_id=data['telegram_id'], username=data['username'] or '—',
            language=data['language'], registered=data['created_at'][:19], favorites=data['favorites_count'],
            history=data['history_count'], referrals=data['referrals_count'], tickets=data['tickets_count'],
            questions=data['questions_count'], status=status, reason=ban['ban_reason'] if ban else '—', expires=expires)
    buttons=[]
    if ban:
        if await has_permission(db,admin,'users.unban'): buttons.append([InlineKeyboardButton(text=tr(lang,'unban'),callback_data=f'user:unban:{uid}')])
    else:
        if await has_permission(db,admin,'users.ban'): buttons.append([InlineKeyboardButton(text=tr(lang,'ban_user'),callback_data=f'user:ban:{uid}')])
    buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:users')])
    await cb.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await cb.answer()

@router.callback_query(F.data=='user:search')
async def user_search_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db)
    if not admin or not await has_permission(db,admin,'users.view'):
        await deny(cb,row['language']); return
    await cb.message.answer(tr(row['language'],'user_search_prompt')); await state.set_state(AdminUserState.search); await cb.answer()

@router.message(AdminUserState.search)
async def user_search_save(message:Message,state:FSMContext,db:Database):
    row,admin=await admin_context(message,db); user=await db.user_by_query((message.text or '').strip()); await state.clear()
    if not admin or not await has_permission(db,admin,'users.view'):
        await deny(message,row['language']); return
    if not user: await message.answer(tr(row['language'],'not_found')); return
    await message.answer(tr(row['language'],'users_title'),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='👤 '+str(user['telegram_id']),callback_data=f'user:profile:{user["telegram_id"]}')],[InlineKeyboardButton(text=tr(row['language'],'back'),callback_data='adm:users')]]))

@router.callback_query(F.data.startswith('user:ban:'))
async def user_ban_menu(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']; uid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'users.ban'):
        await deny(cb,lang); return
    if await db.admin(uid):
        await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    target=await db.user(uid)
    if not target: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    buttons=[]
    for label,minutes in [('1h',60),('6h',360),('12h',720),('1d',1440),('3d',4320),('7d',10080),('30d',43200)]:
        buttons.append([InlineKeyboardButton(text=label,callback_data=f'user:ban_duration:{uid}:{minutes}')])
    buttons += [[InlineKeyboardButton(text='♾ '+tr(lang,'ban_permanent'),callback_data=f'user:ban_duration:{uid}:0')],[InlineKeyboardButton(text='⏱ Custom',callback_data=f'user:ban_custom:{uid}')],[InlineKeyboardButton(text=tr(lang,'back'),callback_data=f'user:profile:{uid}')]]
    await cb.message.edit_text(tr(lang,'ban_duration'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await cb.answer()


@router.callback_query(F.data.startswith('user:ban_duration:'))
async def user_ban_duration(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']; _,_,uid,minutes=cb.data.split(':')
    if not admin or not await has_permission(db,admin,'users.ban'):
        await deny(cb,lang); return
    if await db.admin(int(uid)):
        await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await state.clear(); await state.update_data(target_id=int(uid),duration_minutes=int(minutes)); await cb.message.answer(tr(lang,'ban_reason_prompt')); await state.set_state(AdminBanState.reason); await cb.answer()

@router.callback_query(F.data.startswith('user:ban_custom:'))
async def user_ban_custom(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']; uid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'users.ban'):
        await deny(cb,lang); return
    await state.clear(); await state.update_data(target_id=uid); await cb.message.answer(tr(lang,'ban_custom_minutes_prompt')); await state.set_state(AdminBanState.custom_minutes); await cb.answer()

@router.message(AdminBanState.custom_minutes)
async def user_ban_custom_minutes(message:Message,state:FSMContext,db:Database):
    row,admin=await admin_context(message,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'users.ban'):
        await state.clear(); await deny(message,lang); return
    try: minutes=int((message.text or '').strip())
    except ValueError: await message.answer(tr(lang,'invalid_number')); return
    if minutes<1 or minutes>525600: await message.answer(tr(lang,'invalid_number')); return
    await state.update_data(duration_minutes=minutes); await message.answer(tr(lang,'ban_reason_prompt')); await state.set_state(AdminBanState.reason)

@router.message(AdminBanState.reason)
async def user_ban_reason(message:Message,state:FSMContext,db:Database,bot:Bot):
    row,admin=await admin_context(message,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'users.ban'):
        await state.clear(); await deny(message,lang); return
    data=await state.get_data(); reason=(message.text or '').strip() or '—'; uid=int(data['target_id'])
    if await db.admin(uid): await state.clear(); await message.answer(tr(lang,'unauthorized')); return
    from datetime import timedelta
    minutes=int(data['duration_minutes']); expires=None if minutes==0 else (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat()
    await db.ban_user(uid,int(admin['telegram_id']),reason,expires)
    await db.log_admin(int(admin['telegram_id']),'ban_user',str(uid),reason)
    await state.clear(); await message.answer(tr(lang,'ban_success'))
    try:
        target_lang=(await db.user(uid))['language'] if await db.user(uid) else lang
        when=expires[:19].replace('T',' ') if expires else tr(target_lang,'ban_permanent')
        await bot.send_message(uid,tr(target_lang,'user_banned',reason=reason,expires=when))
    except TelegramAPIError:
        logger.debug('Could not notify user about ban', exc_info=True)

@router.callback_query(F.data.startswith('user:unban:'))
async def user_unban(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']; uid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'users.unban'):
        await deny(cb,lang); return
    await db.unban_user(uid); await db.log_admin(int(admin['telegram_id']),'unban_user',str(uid)); await cb.answer(tr(lang,'unban_success'),show_alert=True); await user_profile(cb,db)

# --------------------------- support ---------------------------
async def show_tickets(cb: CallbackQuery, db: Database, lang: str):
    rows = await db.open_tickets()
    kb = [[InlineKeyboardButton(text=f"#{r['id']} {r['category']}", callback_data=f"ticket:open:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    await cb.message.edit_text(tr(lang,"tickets"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("ticket:open:"))
async def ticket_open(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"feedback.view"):
        await deny(cb, row["language"])
        return
    ticket = await db.ticket(int(cb.data.split(":")[-1]))
    if not ticket:
        await cb.answer(tr(row["language"], "not_found"), show_alert=True)
        return
    messages = await db.ticket_messages(int(ticket["id"]))
    body=[
        f"💬 Ticket #{ticket['id']}",
        f"👤 User ID: {ticket['telegram_id']}",
        f"Category: {ticket['category']}",
        f"Status: {ticket['status']}",
    ]
    for item in messages:
        speaker = "👤 User" if int(item["sender_telegram_id"]) == int(ticket["telegram_id"]) else "👨‍💼 Admin"
        body.append(f"{speaker}: {item['message'][:1600]}")
    buttons=[]
    if await has_permission(db,admin,"feedback.reply") and ticket["status"] != "closed":
        buttons.append([InlineKeyboardButton(text=tr(row["language"],"reply"),callback_data=f"ticket:reply:{ticket['id']}"),
                        InlineKeyboardButton(text=tr(row["language"],"close"),callback_data=f"ticket:close:{ticket['id']}")])
    buttons.append([InlineKeyboardButton(text=tr(row["language"],"back"),callback_data="adm:tickets")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.answer("\n\n".join(body), reply_markup=markup)
    await cb.answer()

@router.callback_query(F.data.startswith("ticket:reply:"))
async def ticket_reply_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"feedback.reply"):
        await deny(cb, row["language"])
        return
    await state.update_data(ticket_id=int(cb.data.split(":")[-1]))
    await cb.message.answer(tr(row["language"], "ticket_answer_prompt"))
    await state.set_state(TicketReplyState.answer)
    await cb.answer()


@router.message(TicketReplyState.answer)
async def ticket_reply_save(message: Message, state: FSMContext, db: Database, bot: Bot):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db, admin, "feedback.reply"):
        await state.clear()
        await deny(message, row["language"])
        return
    data = await state.get_data()
    ticket = await db.ticket(int(data["ticket_id"]))
    if not ticket:
        await state.clear()
        await message.answer(tr(row["language"], "not_found"))
        return
    response=(message.text or "").strip()
    if not response:
        await message.answer(tr(row["language"], "enter_text"))
        return
    if len(response)>2000:
        await message.answer(tr(row["language"], "too_long"))
        return
    await db.answer_ticket(int(data["ticket_id"]), int(admin["telegram_id"]), response)
    user_row = await db.user(int(ticket['telegram_id']))
    recipient_lang = user_row["language"] if user_row else row["language"]
    if user_row: await db.notify(int(user_row['id']), 'ticket_reply', response)
    await db.log_admin(int(admin["telegram_id"]), "answer_ticket", str(data["ticket_id"]))
    await state.clear()
    try:
        await bot.send_message(ticket["telegram_id"], tr(recipient_lang, "ticket_answered_user", id=data["ticket_id"], answer=response),
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                   [InlineKeyboardButton(text=tr(recipient_lang,"reply"),callback_data=f"user_ticket:reply:{data['ticket_id']}")]
                               ]))
    except TelegramAPIError:
        pass
    await message.answer(tr(row["language"], "settings_saved"))


@router.callback_query(F.data.startswith("ticket:close:"))
async def ticket_close(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"feedback.reply"):
        await deny(cb, row["language"])
        return
    ticket_id = int(cb.data.split(":")[-1])
    await db.execute("UPDATE support_tickets SET status='closed',closed_at=?,updated_at=? WHERE id=?", (utcnow(), utcnow(), ticket_id))
    await db.log_admin(int(admin["telegram_id"]), "close_ticket", str(ticket_id))
    await cb.answer(tr(row["language"], "closed"), show_alert=True)


# --------------------------- anonymous Q&A ---------------------------
async def show_questions(cb: CallbackQuery, db: Database, lang: str):
    rows = await db.questions()
    kb = [[InlineKeyboardButton(text=f"❓ #{r['id']} · {r['status']}", callback_data=f"qa_admin:open:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    await cb.message.edit_text(tr(lang, "questions_admin_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith("qa_admin:open:"))
async def qa_open(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"qa.view"):
        await deny(cb, row["language"])
        return
    question = await db.question(int(cb.data.split(":")[-1]))
    if not question:
        await cb.answer(tr(row["language"], "not_found"), show_alert=True)
        return
    await db.execute(
        "UPDATE anonymous_questions SET status='reviewing',updated_at=? WHERE id=? AND status='new'",
        (utcnow(), question['id'])
    )
    messages = await db.anonymous_messages(int(question["id"]))
    body = [
        f"{tr(row['language'],'question_open',id=question['id'])}",
        f"Internal User ID: {question['telegram_id']}",
        f"Status: {question['status']}",
    ]
    for item in messages:
        speaker = tr(row["language"], "anonymous_user_label") if item["sender_type"]=="user" else tr(row["language"], "admin_speaker_label")
        body.append(f"{speaker}: {item['message'][:1600]}")
    buttons=[]
    if await has_permission(db,admin,"qa.reply"):
        buttons.append([InlineKeyboardButton(text=tr(row["language"],"reply"),callback_data=f"qa_admin:reply:{question['id']}"),
                        InlineKeyboardButton(text=tr(row["language"],"qa_published"),callback_data=f"qa_admin:publish:{question['id']}")])
    moderation=[]
    if await has_permission(db,admin,"qa.view"):
        moderation.append(InlineKeyboardButton(text="📦 Archive",callback_data=f"qa_admin:archive:{question['id']}"))
        moderation.append(InlineKeyboardButton(text="🗑 Delete",callback_data=f"qa_admin:delete:{question['id']}"))
    if await has_permission(db,admin,"users.ban"):
        moderation.append(InlineKeyboardButton(text="🚫 Block user",callback_data=f"qa_admin:block:{question['id']}"))
    if moderation:
        # Keep Telegram rows compact.
        for i in range(0,len(moderation),2):
            buttons.append(moderation[i:i+2])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons or [[InlineKeyboardButton(text=tr(row["language"],"back"),callback_data="adm:qa")]])
    await cb.message.answer("\n\n".join(body), reply_markup=markup)
    await cb.answer()

@router.callback_query(F.data.startswith("qa_admin:reply:"))
async def qa_reply_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"qa.reply"):
        await deny(cb, row["language"])
        return
    await state.update_data(question_id=int(cb.data.split(":")[-1]))
    await cb.message.answer(tr(row["language"], "qa_answer_prompt"))
    await state.set_state(QAReplyState.answer)
    await cb.answer()


@router.message(QAReplyState.answer)
async def qa_reply_save(message: Message, state: FSMContext, db: Database, bot: Bot):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db, admin, "qa.reply"):
        await state.clear(); await deny(message, row["language"]); return
    data = await state.get_data()
    question = await db.question(int(data["question_id"]))
    if not question:
        await state.clear()
        await message.answer(tr(row["language"], "not_found"))
        return
    answer=(message.text or "").strip()
    if not answer:
        await message.answer(tr(row["language"], "enter_text"))
        return
    if len(answer)>2000:
        await message.answer(tr(row["language"], "too_long"))
        return
    await db.answer_qa(int(data["question_id"]), int(admin["telegram_id"]), answer)
    user_row = await db.user(int(question['telegram_id']))
    recipient_lang = user_row["language"] if user_row else row["language"]
    if user_row: await db.notify(int(user_row['id']), 'qa_reply', answer)
    await db.log_admin(int(admin["telegram_id"]), "answer_anonymous_question", str(data["question_id"]))
    await state.clear()
    try:
        await bot.send_message(
            question["telegram_id"],
            tr(recipient_lang, "qa_answered", answer=answer),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=tr(recipient_lang,"reply"),callback_data=f"user_qa:reply:{data['question_id']}")]
            ])
        )
    except TelegramAPIError:
        pass
    await message.answer(tr(row["language"], "settings_saved"))


@router.callback_query(F.data.startswith('qa_admin:archive:'))
async def qa_archive(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db)
    if not admin or not await has_permission(db,admin,"qa.view"):
        await deny(cb,row['language']); return
    qid=int(cb.data.split(':')[-1])
    await db.execute("UPDATE anonymous_questions SET status='archived',updated_at=? WHERE id=?",(utcnow(),qid))
    await db.log_admin(int(admin['telegram_id']),'archive_qa',str(qid))
    await cb.answer(tr(row['language'],'archived'), show_alert=True)

@router.callback_query(F.data.startswith('qa_admin:block:'))
async def qa_block_user(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db)
    if not admin or not await has_permission(db,admin,"users.ban"):
        await deny(cb,row['language']); return
    qid=int(cb.data.split(':')[-1])
    q=await db.question(qid)
    if q:
        await db.execute('INSERT OR IGNORE INTO user_blocks(telegram_id,reason,created_at,created_by) VALUES(?,?,?,?)',(q['telegram_id'],'anonymous Q&A abuse',utcnow(),admin['telegram_id']))
        await db.log_admin(int(admin['telegram_id']),'block_qa_user',str(q['telegram_id']))
    await cb.answer(tr(row['language'],'blocked'), show_alert=True)

@router.callback_query(F.data.startswith('qa_admin:delete:'))
async def qa_delete(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db)
    if not admin or not await has_permission(db,admin,"qa.view"):
        await deny(cb,row['language']); return
    qid=int(cb.data.split(':')[-1])
    await db.execute('DELETE FROM anonymous_questions WHERE id=?',(qid,))
    await db.log_admin(int(admin['telegram_id']),'delete_qa',str(qid))
    await cb.answer(tr(row['language'],'deleted'), show_alert=True)

@router.callback_query(F.data.startswith("qa_admin:publish:"))
async def qa_publish(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"qa.reply"):
        await deny(cb, row["language"])
        return
    qid = int(cb.data.split(":")[-1])
    published_id = await db.publish_qa(qid)
    if published_id:
        await db.log_admin(int(admin["telegram_id"]), "publish_qa", str(qid))
    await cb.answer(tr(row["language"], "qa_published"), show_alert=True)


# --------------------------- broadcast ---------------------------
async def show_broadcast(cb: CallbackQuery, lang: str):
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "all_users"), callback_data="broadcast:target:all")],
            [InlineKeyboardButton(text=tr(lang, "active_users"), callback_data="broadcast:target:active")],
            [InlineKeyboardButton(text=tr(lang, "recent_users"), callback_data="broadcast:target:recent")],
            [InlineKeyboardButton(text=tr(lang, "language_users"), callback_data="broadcast:target:language")],
            [InlineKeyboardButton(text=tr(lang, "selected_users"), callback_data="broadcast:target:selected")],
            [InlineKeyboardButton(text='📜 Broadcast history',callback_data='broadcast:history')],
            [InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")],
        ]
    )
    await cb.message.edit_text(tr(lang, "broadcast_target"), reply_markup=markup)


@router.callback_query(F.data=='broadcast:history')
async def broadcast_history(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db)
    if not admin or not await has_permission(db,admin,'broadcast.send'):
        await deny(cb,row['language']); return
    rows=await db.broadcasts(30)
    text=tr(row["language"],"broadcast_history")+"\n\n"+"\n".join(f"#{r['id']} · {r['target_type']} · {r['successful_count']}/{r['total_recipients']} · {r['start_time'][:19]}" for r in rows)
    await cb.message.answer(text if rows else tr(row["language"],"no_broadcasts"))
    await cb.answer()

@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db,admin,"broadcast.send"):
        await deny(message, row["language"])
        return
    await state.clear()
    await message.answer(tr(row["language"], "broadcast_prompt") + "\n\nTarget: all/active/recent")
    await state.set_state(BroadcastState.message)
    await state.update_data(target="all")


@router.callback_query(F.data.startswith("broadcast:target:"))
async def broadcast_target_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db,admin,"broadcast.send"):
        await deny(cb, row["language"])
        return
    target = cb.data.split(":")[-1]
    await state.clear()
    await state.update_data(target=target)
    if target == 'selected':
        await cb.message.answer(tr(row['language'], 'broadcast_ids_prompt'))
        await state.set_state(BroadcastState.selected)
    elif target == 'language':
        await cb.message.answer(tr(row['language'], 'broadcast_language_prompt'))
        await state.update_data(waiting_language=True)
        await state.set_state(BroadcastState.selected)
    else:
        await cb.message.answer(tr(row["language"], "broadcast_prompt"))
        await state.set_state(BroadcastState.message)
    await cb.answer()


@router.message(BroadcastState.selected)
async def broadcast_selected(message: Message, state: FSMContext, db: Database):
    row, _ = await admin_context(message, db)
    data = await state.get_data()
    raw = (message.text or '').strip()
    if data.get('waiting_language'):
        if raw.lower() not in {'uz','ru','en'}:
            await message.answer('uz / ru / en dan birini yuboring.')
            return
        await state.update_data(language_target=raw.lower(), waiting_language=False, target='language')
        await message.answer(tr(row["language"], "broadcast_prompt"))
        await state.set_state(BroadcastState.message)
        return
    ids=[]
    for part in raw.split(','):
        part=part.strip()
        if part.isdigit() or (part.startswith('-') and part[1:].isdigit()):
            ids.append(int(part))
    ids=list(dict.fromkeys(ids))
    if not ids:
        await message.answer(tr(row["language"], "invalid")); return
    await state.update_data(selected=ids)
    await message.answer(tr(row["language"], "broadcast_prompt"))
    await state.set_state(BroadcastState.message)

@router.message(BroadcastState.message)
async def broadcast_message(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    data = await state.get_data()
    target = data.get("target", "all")
    if target not in {"all", "active", "recent", "language", "selected"}:
        target = "all"
    if message.media_group_id:
        key = (message.from_user.id, message.media_group_id)
        album = list(data.get("album_message_ids", []))
        album.append(message.message_id)
        await state.update_data(album_message_ids=album, source_chat_id=message.chat.id, target=target)
        old = ALBUM_TASKS.get(key)
        if old and not old.done():
            old.cancel()
        async def finish_album():
            await asyncio.sleep(1.2)
            current = await state.get_data()
            ids = current.get("album_message_ids", [])
            recipients = await db.users_for_broadcast(target, language=current.get('language_target'), ids=current.get('selected'))
            await state.update_data(source_message_id=ids, total=len(recipients))
            markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"], "confirm"), callback_data="broadcast:confirm")],[InlineKeyboardButton(text=tr(row["language"], "cancel"), callback_data="broadcast:cancel")]])
            await message.answer(tr(row["language"], "broadcast_confirm", total=len(recipients)) + f"\n🎞 Media group: {len(ids)} ta", reply_markup=markup)
            await state.set_state(BroadcastState.target)
        ALBUM_TASKS[key] = asyncio.create_task(finish_album())
        return
    recipients = await db.users_for_broadcast(target, language=data.get('language_target'), ids=data.get('selected'))
    await state.update_data(source_chat_id=message.chat.id, source_message_id=message.message_id, total=len(recipients))
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"], "confirm"), callback_data="broadcast:confirm")],[InlineKeyboardButton(text=tr(row["language"], "cancel"), callback_data="broadcast:cancel")]])
    await message.answer(tr(row["language"], "broadcast_confirm", total=len(recipients)), reply_markup=markup)
    await state.set_state(BroadcastState.target)


@router.callback_query(BroadcastState.target, F.data == "broadcast:confirm")
async def broadcast_confirm(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot):
    row, admin = await admin_context(cb, db)
    data = await state.get_data()
    await cb.message.answer(tr(row["language"],"broadcast_started"))
    ok, failed, total = await run_broadcast(bot, db, int(admin["telegram_id"]), int(data["source_chat_id"]), data["source_message_id"], data.get("target", "all"), data.get('language_target'), data.get('selected'))
    await db.log_admin(int(admin["telegram_id"]), "broadcast", "", f"{ok}/{total}")
    await state.clear()
    await cb.message.answer(tr(row["language"], "broadcast_done", ok=ok, failed=failed, total=total))
    await cb.answer()


@router.callback_query(BroadcastState.target, F.data == "broadcast:cancel")
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext, db: Database):
    row, _ = await admin_context(cb, db)
    await state.clear()
    await cb.message.answer(tr(row["language"], "cancelled"))
    await cb.answer()


# --------------------------- stats/settings/logs ---------------------------
async def show_stats(cb: CallbackQuery, db: Database, lang: str):
    stats = await db.stats()
    await cb.message.edit_text(tr(lang, "stats_text", **stats), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")]]))


async def show_logs(cb: CallbackQuery, db: Database, lang: str):
    rows = await db.logs(40)
    text = tr(lang, 'audit_logs_title') + "\n\n" + "\n".join(f"{r['timestamp'][:19]} · {r['admin_id']} · {r['action']} · {r['target'] or ''}" for r in rows)
    await cb.message.edit_text(text if rows else tr(lang, 'logs_empty'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")]]))


async def show_settings(cb: CallbackQuery, db: Database, lang: str, permissions: set[str] | None = None):
    text = tr(lang, "settings_text", maintenance=await db.setting("maintenance_mode", "0"), support=await db.setting("support_enabled", "1"), qa=await db.setting("anonymous_qa_enabled", "1"), ref=await db.setting("referral_enabled", "1"), page=await db.setting("pagination_size", "8"))
    effective = permissions or set()
    if "settings.manage" in effective:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛠 Maintenance", callback_data="set:maintenance")],
            [InlineKeyboardButton(text="💬 Support", callback_data="set:support")],
            [InlineKeyboardButton(text="❓ Anonymous Q&A", callback_data="set:qa")],
            [InlineKeyboardButton(text="🎁 Referrals", callback_data="set:ref")],
            [InlineKeyboardButton(text="🔢 Page size", callback_data="set:page")],
            [InlineKeyboardButton(text='🏷 Bot title', callback_data='set:title'), InlineKeyboardButton(text='📝 Welcome text', callback_data='set:welcome')],
            [InlineKeyboardButton(text='🌐 Default language', callback_data='set:default_language')],
        ])
    else:
        markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(F.data.startswith("set:"))
async def settings_action(cb: CallbackQuery, db: Database, state: FSMContext):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db, admin, "settings.manage"):
        await deny(cb, row["language"])
        return
    key = cb.data.split(":", 1)[1]
    if key == 'title':
        await state.update_data(key='bot_title')
        await cb.message.answer(tr(row['language'], 'setting_bot_title_prompt'))
        await state.set_state(SettingsState.value)
        await cb.answer()
        return
    if key == 'welcome':
        await state.update_data(key=f'welcome_text_{row["language"]}')
        await cb.message.answer(tr(row['language'], 'setting_welcome_prompt'))
        await state.set_state(SettingsState.value)
        await cb.answer()
        return
    if key == 'default_language':
        await cb.message.answer(tr(row['language'], 'setting_language_prompt'))
        await state.update_data(key='default_language')
        await state.set_state(SettingsState.value)
        await cb.answer()
        return
    if key == "page":
        await state.update_data(key="pagination_size")
        await cb.message.answer(tr(row['language'], 'setting_page_prompt'))
        await state.set_state(SettingsState.value)
        await cb.answer()
        return
    mapping = {"maintenance": "maintenance_mode", "support": "support_enabled", "qa": "anonymous_qa_enabled", "ref": "referral_enabled"}
    real_key = mapping[key]
    value = "0" if await db.setting(real_key, "0") == "1" else "1"
    await db.set_setting(real_key, value)
    await db.log_admin(int(admin["telegram_id"]), "setting", real_key, value)
    await show_settings(cb, db, row["language"])
    await cb.answer()


@router.message(SettingsState.value)
async def settings_value(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db, admin, "settings.manage"):
        await state.clear()
        await deny(message, row["language"])
        return
    data = await state.get_data()
    key = data.get("key")
    raw = (message.text or "").strip()
    if key == "pagination_size":
        try:
            value = int(raw)
        except ValueError:
            await message.answer(tr(row["language"], "invalid")); return
        if not 4 <= value <= 20:
            await message.answer(tr(row["language"], "invalid")); return
    elif key == "default_language":
        value = raw.lower()
        if value not in {"uz","ru","en"}:
            await message.answer(tr(row["language"], "language_invalid")); return
    elif key == "bot_title":
        value = raw[:120]
        if not value:
            await message.answer(tr(row["language"], "invalid")); return
    elif key and key.startswith("welcome_text_"):
        value = raw[:3500]
        if not value:
            await message.answer(tr(row["language"], "invalid")); return
    else:
        value = raw[:3500]
        if not value:
            await message.answer(tr(row["language"], "invalid")); return
    await db.set_setting(key, str(value))
    await db.log_admin(int(admin["telegram_id"]), "setting", data["key"], str(value))
    await state.clear()
    await message.answer(tr(row["language"], "settings_saved"))


# --------------------------- genres ---------------------------
async def show_genres(cb: CallbackQuery, db: Database, lang: str):
    rows = await db.genres()
    kb = []
    for r in rows:
        kb.append([InlineKeyboardButton(text=f"{'🟢' if r['active'] else '⚫'} #{r['id']} {r[f'name_{lang}'][:22]}", callback_data=f"genre_manage:toggle:{r['id']}"), InlineKeyboardButton(text='✏️', callback_data=f"genre_manage:rename:{r['id']}"), InlineKeyboardButton(text='🗑', callback_data=f"genre_manage:delete:{r['id']}")])
    kb.append([InlineKeyboardButton(text="➕ Add genre", callback_data="genre_manage:add")])
    kb.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    await cb.message.edit_text(tr(lang, "genres_manage"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "genre_manage:add")
async def genre_add_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await section_access(db,admin,"genres"):
        await deny(cb, row["language"])
        return
    await cb.message.answer("UZ | RU | EN ko‘rinishida yuboring:")
    await state.set_state(GenreState.add)
    await cb.answer()


@router.message(GenreState.add)
async def genre_add_save(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    parts = [x.strip() for x in message.text.split("|")]
    if len(parts) != 3:
        await message.answer(tr(row["language"], "invalid"))
        return
    try:
        await db.execute("INSERT INTO genres(name_uz,name_ru,name_en) VALUES(?,?,?)", parts)
    except Exception:
        await message.answer(tr(row["language"], "generic_error"))
        return
    await db.log_admin(int(admin["telegram_id"]), "add_genre", "", message.text)
    await state.clear()
    await message.answer(tr(row["language"], "settings_saved"))


@router.callback_query(F.data.startswith("genre_manage:toggle:"))
async def genre_toggle(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await section_access(db,admin,"genres"):
        await deny(cb, row["language"])
        return
    gid = int(cb.data.split(":")[-1])
    await db.execute("UPDATE genres SET active=1-active WHERE id=?", (gid,))
    await db.log_admin(int(admin["telegram_id"]), "toggle_genre", str(gid))
    await show_genres(cb, db, row["language"])
    await cb.answer()


@router.callback_query(F.data.startswith("genre_manage:rename:"))
async def genre_rename_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await section_access(db,admin,"genres"):
        await deny(cb, row["language"]); return
    await state.update_data(genre_id=int(cb.data.split(":")[-1]))
    await cb.message.answer("UZ | RU | EN ko‘rinishida yangi nom yuboring:")
    await state.set_state(GenreState.rename)
    await cb.answer()


@router.message(GenreState.rename)
async def genre_rename_save(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await section_access(db,admin,"genres"):
        await state.clear(); await deny(message, row["language"]); return
    parts=[x.strip() for x in (message.text or '').split('|')]
    if len(parts)!=3 or any(not x for x in parts):
        await message.answer(tr(row["language"], "invalid")); return
    data=await state.get_data()
    await db.execute("UPDATE genres SET name_uz=?,name_ru=?,name_en=? WHERE id=?", (*parts, int(data['genre_id'])))
    await db.log_admin(int(admin['telegram_id']), 'rename_genre', str(data['genre_id']))
    await state.clear(); await message.answer(tr(row['language'], 'settings_saved'))


@router.callback_query(F.data.startswith("genre_manage:delete:"))
async def genre_delete_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not await section_access(db,admin,"genres"):
        await deny(cb, row["language"]); return
    gid=int(cb.data.split(":")[-1])
    genre=await db.fetchone("SELECT * FROM genres WHERE id=? AND active=1",(gid,))
    if not genre:
        await cb.answer(tr(row['language'],'not_found'),show_alert=True); return
    await state.clear(); await state.update_data(genre_id=gid)
    await cb.message.answer(
        f"⚠️ {genre[f'name_{row["language"]}']}\n{tr(row['language'],'confirm')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(row['language'],'confirm'),callback_data='genre_manage:delete_yes'),InlineKeyboardButton(text=tr(row['language'],'cancel'),callback_data='genre_manage:delete_no')]
        ])
    )
    await state.set_state(GenreDeleteState.confirm); await cb.answer()

@router.callback_query(GenreDeleteState.confirm,F.data=='genre_manage:delete_yes')
async def genre_delete_yes(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await admin_context(cb,db);
    if not admin or not await section_access(db,admin,'genres'):
        await state.clear(); await deny(cb,row['language']); return
    gid=int((await state.get_data())['genre_id'])
    await db.execute("UPDATE genres SET active=0 WHERE id=?",(gid,))
    await db.log_admin(int(admin['telegram_id']),'delete_genre',str(gid)); await state.clear(); await show_genres(cb,db,row['language']); await cb.answer(tr(row['language'],'deleted'),show_alert=True)

@router.callback_query(GenreDeleteState.confirm,F.data=='genre_manage:delete_no')
async def genre_delete_no(cb:CallbackQuery,state:FSMContext,db:Database):
    row,_=await admin_context(cb,db); await state.clear(); await cb.answer(tr(row['language'],'cancelled'),show_alert=True)


# --------------------------- admin management ---------------------------
def _admin_role_label(lang: str, role: str) -> str:
    return tr(lang, ROLE_LABEL_KEYS.get(role, "role_admin_label"))

async def _can_manage_target(db: Database, actor, target, action: str = "manage") -> bool:
    if not actor or not target or int(actor["id"]) == int(target["id"]):
        return False
    actor_role = str(actor["role"]); target_role = str(target["role"])
    if actor_role == "ceo":
        return target_role != "ceo"
    if actor_role == "senior_admin":
        return target_role == "admin" and target["parent_admin_id"] == actor["id"]
    return False

async def show_admins(cb: CallbackQuery, db: Database, lang: str):
    row, admin = await admin_context(cb, db)
    if not admin or not await has_permission(db, admin, "admins.view"):
        await deny(cb, lang); return
    rows = await db.admins()
    role_labels = {
        "ceo": tr(lang, "role_ceo_label"),
        "senior_admin": tr(lang, "role_senior_admin_label"),
        "admin": tr(lang, "role_admin_label"),
    }
    children = {}
    for r in rows:
        parent = r["parent_admin_id"]
        if parent: children.setdefault(int(parent), []).append(r)
    lines=[]
    for r in rows:
        if r["role"] == "admin" and r["parent_admin_id"]:
            continue
        status = "🟢" if int(r["active"]) else "⚪"
        lines.append(f"{status} {role_labels.get(r['role'],r['role'])} · {r['telegram_id']}")
        for ch in children.get(int(r["id"]), []):
            cstatus="🟢" if int(ch["active"]) else "⚪"
            lines.append(f"   └─ {cstatus} {role_labels['admin']} · {ch['telegram_id']}")
    text = tr(lang, "admins_title") + "\n\n" + ("\n".join(lines) if lines else "—")
    buttons=[]
    if str(admin["role"]) == "ceo":
        buttons.append([InlineKeyboardButton(text=tr(lang,"add_admin"),callback_data="adminmgmt:add")])
    elif str(admin["role"]) == "senior_admin" and await has_permission(db,admin,"admins.create_junior"):
        buttons.append([InlineKeyboardButton(text=tr(lang,"add_junior"),callback_data="adminmgmt:add_junior")])
    if str(admin["role"]) == "ceo" and await has_permission(db,admin,"admins.manage"):
        buttons.append([InlineKeyboardButton(text=tr(lang,"remove_admin"),callback_data="adminmgmt:remove")])
    # Target-specific management buttons
    for r in rows:
        if await _can_manage_target(db,admin,r):
            buttons.append([InlineKeyboardButton(text=f"👤 {r['telegram_id']} · {role_labels.get(r['role'],r['role'])}",callback_data=f"adminmgmt:view:{r['id']}")])
    if await has_permission(db,admin,"permissions.manage") and str(admin["role"])=="ceo":
        for r in rows:
            if r["role"] != "ceo" and int(r["active"]):
                buttons.append([InlineKeyboardButton(text=f"🔐 {r['telegram_id']}",callback_data=f"adminperm:{r['telegram_id']}:0")])
    buttons.append([InlineKeyboardButton(text=tr(lang,"back"),callback_data="adm:home")])
    await cb.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data == "adminmgmt:add")
async def admin_add_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db); lang=row["language"]
    if not admin or str(admin["role"]) != "ceo" or not await has_permission(db,admin,"admins.manage"):
        await deny(cb, lang); return
    await state.clear(); await state.update_data(creator_role="ceo", parent_admin_id=None)
    await cb.message.answer(tr(lang,"ask_user_id")); await state.set_state(AdminAddState.telegram_id); await cb.answer()

@router.callback_query(F.data == "adminmgmt:add_junior")
async def admin_add_junior_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db); lang=row["language"]
    if not admin or str(admin["role"]) != "senior_admin" or not await has_permission(db,admin,"admins.create_junior"):
        await deny(cb, lang); return
    if await db.active_junior_count(int(admin["id"])):
        await cb.answer(tr(lang,"junior_limit_reached"),show_alert=True); return
    await state.clear(); await state.update_data(creator_role="senior_admin", parent_admin_id=int(admin["id"]), forced_role="admin")
    await cb.message.answer(tr(lang,"ask_user_id")); await state.set_state(AdminAddState.telegram_id); await cb.answer()

@router.message(AdminAddState.telegram_id)
async def admin_add_id(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db); lang=row["language"]
    if not admin:
        await state.clear(); await deny(message,lang); return
    data=await state.get_data()
    remove=bool(data.get("remove"))
    try: telegram_id=int((message.text or "").strip())
    except ValueError:
        await message.answer(tr(lang,"invalid")); return
    if telegram_id <= 0:
        await message.answer(tr(lang,"invalid")); return
    if remove:
        target=await db.admin_any(telegram_id)
        if not await _can_manage_target(db,admin,target):
            await message.answer(tr(lang,"unauthorized")); await state.clear(); return
        await db.remove_admin(telegram_id); await db.log_admin(int(admin["telegram_id"]),"deactivate_admin",str(telegram_id))
        await state.clear(); await message.answer(tr(lang,"admin_removed")); return
    existing=await db.admin_any(telegram_id)
    if existing and int(existing["active"]):
        await message.answer(tr(lang,"admin_exists")); return
    await state.update_data(telegram_id=telegram_id)
    forced=data.get("forced_role")
    if forced:
        await state.update_data(role=forced)
        await message.answer(tr(lang,"ask_admin_password")); await state.set_state(AdminAddPasswordState.password)
    else:
        await message.answer(tr(lang,"ask_role"),reply_markup=roles_keyboard(lang)); await state.set_state(AdminAddState.role)

@router.callback_query(AdminAddState.role, F.data.startswith("role:"))
async def admin_add_role(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db); lang=row["language"]
    if not admin or str(admin["role"]) != "ceo" or not await has_permission(db,admin,"admins.manage"):
        await deny(cb,lang); return
    role=cb.data.split(":",1)[1]
    if role not in {"senior_admin","admin"}:
        await cb.answer(tr(lang,"invalid"),show_alert=True); return
    data=await state.get_data(); telegram_id=int(data["telegram_id"])
    if telegram_id==int(admin["telegram_id"]):
        await cb.answer(tr(lang,"unauthorized"),show_alert=True); return
    await state.update_data(role=role,parent_admin_id=None)
    await cb.message.answer(tr(lang,"ask_admin_password")); await state.set_state(AdminAddPasswordState.password); await cb.answer()

@router.message(AdminAddPasswordState.password)
async def admin_add_password(message: Message, state: FSMContext, db: Database, bot: Bot):
    row, creator = await admin_context(message, db); lang=row["language"]
    if not creator:
        await state.clear(); await deny(message,lang); return
    password=(message.text or "").strip(); ok,reason=validate_password(password)
    if not ok:
        await message.answer(tr(lang,"password_too_short" if reason=="too_short" else "password_too_long")); return
    data=await state.get_data(); telegram_id=int(data["telegram_id"]); role=str(data["role"]); parent_id=data.get("parent_admin_id")
    if role == "admin":
        if parent_id is None and str(creator["role"]) != "ceo":
            await message.answer(tr(lang,"unauthorized")); await state.clear(); return
        if parent_id is not None and str(creator["role"]) != "senior_admin":
            await message.answer(tr(lang,"unauthorized")); await state.clear(); return
    else:
        if str(creator["role"]) != "ceo":
            await message.answer(tr(lang,"unauthorized")); await state.clear(); return
    try:
        await db.add_admin(telegram_id,role,int(creator["telegram_id"]),hash_password(password),int(parent_id) if parent_id else None)
    except ValueError as exc:
        state_map={"junior_limit":"junior_limit_reached","invalid_parent":"invalid","admin_exists":"admin_exists","invalid_admin_role":"invalid"}
        await state.clear(); await message.answer(tr(lang,state_map.get(str(exc),"invalid"))); return
    await db.invalidate_admin_session(telegram_id)
    await set_user_commands(bot, telegram_id)
    await db.log_admin(int(creator["telegram_id"]),"add_admin",str(telegram_id),f"role={role};parent={parent_id}")
    await state.clear(); await message.answer(tr(lang,"admin_added"))

@router.callback_query(F.data == "adminmgmt:remove")
async def admin_remove_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or str(admin["role"])!="ceo" or not await has_permission(db,admin,"admins.manage"):
        await deny(cb,row["language"]); return
    await state.clear(); await state.update_data(remove=True)
    await cb.message.answer(tr(row["language"],"ask_user_id")); await state.set_state(AdminAddState.telegram_id); await cb.answer()

@router.callback_query(F.data.startswith("adminmgmt:view:"))
async def admin_profile_view(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb,db); lang=row["language"]
    target=await db.admin_by_id(int(cb.data.split(":")[-1]))
    if not admin or not await _can_manage_target(db,admin,target):
        await deny(cb,lang); return
    role=_admin_role_label(lang,str(target["role"]))
    parent=await db.admin_by_id(int(target["parent_admin_id"])) if target["parent_admin_id"] else None
    junior=await db.junior_of(int(target["id"])) if target["role"]=="senior_admin" else None
    text=(f"👨‍💼 {tr(lang,'admin_profile')}\n\nID: {target['telegram_id']}\nRole: {role}\nStatus: {'🟢' if target['active'] else '⚪'}\nCreated by: {target['created_by'] or '—'}\nParent: {parent['telegram_id'] if parent else '—'}\nJunior: {junior['telegram_id'] if junior else '—'}")
    buttons=[]
    if target["role"]=="admin" and await has_permission(db,admin,"admins.permissions_junior"):
        buttons.append([InlineKeyboardButton(text=tr(lang,"manage_permissions"),callback_data=f"adminperm:{target['telegram_id']}:0")])
    if target["active"]:
        buttons.append([InlineKeyboardButton(text=tr(lang,"deactivate_admin"),callback_data=f"adminmgmt:disable:{target['telegram_id']}")])
    else:
        buttons.append([InlineKeyboardButton(text=tr(lang,"activate_admin"),callback_data=f"adminmgmt:enable:{target['telegram_id']}")])
    buttons.append([InlineKeyboardButton(text=tr(lang,"back"),callback_data="adm:admins")])
    await cb.message.edit_text(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)); await cb.answer()

@router.callback_query(F.data.startswith("adminmgmt:disable:"))
@router.callback_query(F.data.startswith("adminmgmt:enable:"))
async def admin_toggle_active(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb,db); lang=row["language"]
    parts=cb.data.split(":"); action=parts[1]; tid=int(parts[2]); target=await db.admin_any(tid)
    if not admin or not await _can_manage_target(db,admin,target):
        await deny(cb,lang); return
    if target["role"]=="admin" and target["parent_admin_id"] and str(admin["role"])=="senior_admin" and int(target["parent_admin_id"]) != int(admin["id"]):
        await deny(cb,lang); return
    await db.set_admin_active(tid,action=="enable")
    await db.log_admin(int(admin["telegram_id"]),action+"_admin",str(tid))
    await cb.answer(tr(lang,"admin_status_saved"),show_alert=True)
    # reopen management list
    await show_admins(cb,db,lang)

# --------------------------- granular admin permissions ---------------------------
async def render_admin_permissions(cb:CallbackQuery,db:Database,target_id:int,page:int):
    row,admin=await admin_context(cb,db); lang=row['language']
    target=await db.admin_any(target_id)
    if not admin or not target or target['role']=='ceo' or not await _can_manage_target(db,admin,target) or not await has_permission(db,admin,'permissions.manage' if admin['role']=='ceo' else 'admins.permissions_junior'):
        await deny(cb,lang); return
    size=10; perms=list(ALL_PERMISSIONS); total=max(1,(len(perms)+size-1)//size); page=max(0,min(page,total-1)); chunk=perms[page*size:(page+1)*size]
    buttons=[]
    for perm in chunk:
        allowed=await has_permission(db,target,perm)
        buttons.append([InlineKeyboardButton(text=('✅ ' if allowed else '❌ ')+PERMISSION_LABELS[perm][:43],callback_data=f'adminperm:toggle:{target_id}:{perm}:{page}')])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton(text='⬅️',callback_data=f'adminperm:{target_id}:{page-1}'))
    nav.append(InlineKeyboardButton(text=f'{page+1}/{total}',callback_data='noop'))
    if page<total-1: nav.append(InlineKeyboardButton(text='➡️',callback_data=f'adminperm:{target_id}:{page+1}'))
    buttons.append(nav); buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:admins')])
    await cb.message.edit_text(f"{tr(lang,'manage_permissions')}\n\nID: {target_id}",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.regexp(r'^adminperm:\d+:\d+$'))
async def admin_permissions(cb:CallbackQuery,db:Database):
    parts=cb.data.split(':')
    if len(parts)==3:
        _,target_id,page=parts; await render_admin_permissions(cb,db,int(target_id),int(page)); await cb.answer(); return
    await cb.answer()

@router.callback_query(F.data.startswith('adminperm:toggle:'))
async def admin_permission_toggle(cb:CallbackQuery,db:Database):
    row,admin=await admin_context(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'permissions.manage' if admin['role']=='ceo' else 'admins.permissions_junior'):
        await deny(cb,lang); return
    parts=cb.data.split(':',4); target_id=int(parts[2]); perm=parts[3]; page=int(parts[4])
    target=await db.admin_any(target_id)
    if not target or target['role']=='ceo' or perm not in ALL_PERMISSIONS or not await _can_manage_target(db,admin,target):
        await cb.answer(tr(lang,'admin_not_found'),show_alert=True); return
    current=await has_permission(db,target,perm)
    await db.set_admin_permission(target_id,perm,not current)
    await db.log_admin(int(admin['telegram_id']),'set_permission',str(target_id),f'{perm}={not current}')
    await cb.answer(tr(lang,'permission_saved'))
    await render_admin_permissions(cb,db,target_id,page)

# --------------------------- security + incoming questions ---------------------------
async def show_security(cb: CallbackQuery, db: Database, lang: str):
    row, admin = await admin_context(cb, db)
    if not admin:
        await deny(cb, lang)
        return
    rows = [
        [InlineKeyboardButton(text=tr(lang, "change_password"), callback_data="sec:change")],
    ]
    if admin["role"] == "ceo":
        rows.append([InlineKeyboardButton(text=tr(lang, "reset_password"), callback_data="sec:reset")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    await cb.message.edit_text(tr(lang, "security"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data == "sec:change")
async def security_change_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin:
        await deny(cb, row["language"])
        return
    await state.clear()
    await cb.message.answer(tr(row["language"], "password_current"))
    await state.set_state(PasswordChangeState.current)
    await cb.answer()

@router.message(PasswordChangeState.current)
async def security_current_password(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin:
        await state.clear()
        await deny(message, row["language"])
        return
    if not verify_password((message.text or "").strip(), admin["password_hash"]):
        await message.answer(tr(row["language"], "wrong_password"))
        return
    await state.set_state(PasswordChangeState.new)
    await message.answer(tr(row["language"], "password_new"))

@router.message(PasswordChangeState.new)
async def security_new_password(message: Message, state: FSMContext, db: Database):
    row, admin = await admin_context(message, db)
    if not admin:
        await state.clear()
        await deny(message, row["language"])
        return
    password=(message.text or "").strip()
    ok, reason=validate_password(password)
    if not ok:
        await message.answer(tr(row["language"], "password_too_short" if reason=="too_short" else "password_too_long"))
        return
    await state.update_data(new_password=password)
    await state.set_state(PasswordChangeState.confirm)
    await message.answer(tr(row["language"], "password_confirm"))

@router.message(PasswordChangeState.confirm)
async def security_confirm_password(message: Message, state: FSMContext, db: Database, bot: Bot):
    row, admin = await admin_context(message, db)
    if not admin:
        await state.clear()
        await deny(message, row["language"])
        return
    data=await state.get_data()
    if (message.text or "").strip() != data.get("new_password"):
        await message.answer(tr(row["language"], "password_mismatch"))
        return
    admin_id=int(admin["telegram_id"])
    await db.update_admin_password(admin_id, hash_password(data["new_password"]))
    await db.log_admin(admin_id, "change_own_password")
    await state.clear()
    await set_user_commands(bot, admin_id)
    await message.answer(tr(row["language"], "password_changed"))

@router.callback_query(F.data == "sec:reset")
async def security_reset_list(cb: CallbackQuery, db: Database):
    row, admin = await admin_context(cb, db)
    if not admin or not (str(admin["role"]) == "ceo" or await has_permission(db,admin,"admins.manage_junior")):
        await deny(cb, row["language"])
        return
    rows=await db.admins()
    buttons=[]
    for target in rows:
        if int(target["telegram_id"]) == int(admin["telegram_id"]):
            continue
        manageable = str(admin["role"]) == "ceo" or (str(admin["role"]) == "senior_admin" and target["role"] == "admin" and target["parent_admin_id"] == admin["id"])
        if not manageable or not int(target["active"]):
            continue
        label_key=ROLE_LABEL_KEYS.get(target["role"], "role_admin_label")
        buttons.append([InlineKeyboardButton(text=f"🔁 {target['telegram_id']} · {tr(row['language'],label_key)}",callback_data=f"sec:reset:{target['telegram_id']}")])
    buttons.append([InlineKeyboardButton(text=tr(row["language"], "back"), callback_data="adm:security")])
    await cb.message.edit_text(tr(row["language"], "reset_password"), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@router.callback_query(F.data.startswith("sec:reset:"))
async def security_reset_start(cb: CallbackQuery, state: FSMContext, db: Database):
    row, admin = await admin_context(cb, db)
    target_id=int(cb.data.split(":")[-1])
    target=await db.admin_any(target_id)
    senior_owns = bool(admin and str(admin["role"]) == "senior_admin" and target and target["role"] == "admin" and target["parent_admin_id"] == admin["id"] and await has_permission(db,admin,"admins.manage_junior"))
    if not admin or (str(admin["role"]) != "ceo" and not senior_owns):
        await deny(cb, row["language"]); return
    if not target or not int(target["active"]) or target_id==int(admin["telegram_id"]) or target["role"]=="ceo":
        await cb.answer(tr(row["language"], "admin_not_found"), show_alert=True); return
    await state.clear(); await state.update_data(target_id=target_id)
    await cb.message.answer(tr(row["language"], "ask_admin_password"))
    await state.set_state(AdminResetState.password); await cb.answer()

@router.message(AdminResetState.password)
async def security_reset_save(message: Message, state: FSMContext, db: Database, bot: Bot):
    row, admin = await admin_context(message, db)
    if not admin or admin["role"] != "ceo":
        await state.clear()
        await deny(message, row["language"])
        return
    password=(message.text or "").strip()
    ok, reason=validate_password(password)
    if not ok:
        await message.answer(tr(row["language"], "password_too_short" if reason=="too_short" else "password_too_long"))
        return
    target_id=int((await state.get_data())["target_id"])
    target=await db.admin_any(target_id)
    if not target or not int(target["active"]) or target_id==int(admin["telegram_id"]):
        await state.clear()
        await message.answer(tr(row["language"], "admin_not_found"))
        return
    await db.update_admin_password(target_id, hash_password(password))
    await db.log_admin(int(admin["telegram_id"]), "reset_admin_password", str(target_id))
    await set_user_commands(bot, target_id)
    await state.clear()
    await message.answer(tr(row["language"], "admin_password_reset_done"))

async def show_inbox(cb: CallbackQuery, db: Database, lang: str):
    row, admin = await admin_context(cb, db)
    if not admin:
        await deny(cb, lang)
        return
    permissions = await effective_permissions(db, admin)
    tickets = await db.open_tickets() if "feedback.view" in permissions else []
    questions = await db.questions() if "qa.view" in permissions else []
    text = f"{tr(lang, 'inquiries')}\n\n{tr(lang, 'tickets')}: {len(tickets)}\n{tr(lang, 'qa_manage')}: {len(questions)}"
    await cb.message.edit_text(text, reply_markup=inquiries_menu(lang, permissions))

@router.message(Command("stats"))
async def stats_cmd(message: Message, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db,admin,"statistics.view"):
        await deny(message, row["language"]); return
    stats = await db.stats()
    await message.answer(tr(row["language"], "stats_text", **stats), reply_markup=admin_panel(row['language'],admin['role'],await effective_permissions(db,admin)))


@router.message(Command("users"))
async def users_cmd(message: Message, db: Database):
    row, admin = await admin_context(message, db)
    if not admin or not await has_permission(db,admin,"users.view"):
        await deny(message, row["language"]); return
    await message.answer(tr(row["language"],'users_title'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(row["language"],'search_user'), callback_data="user:search")],[InlineKeyboardButton(text=tr(row["language"],'back'), callback_data="adm:home")]]))
