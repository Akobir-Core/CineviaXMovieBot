from __future__ import annotations
import re
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database.db import Database, utcnow
from services.i18n import tr
from services.recommendations import recommend
from services.subscriptions import check_subscription, send_subscription_screen, subscription_markup
from keyboards.common import LANGS, language_prompt, user_menu, settings_menu, back_home, pager
from states.user import SearchState, SupportState, QAState, UserTicketReplyState, UserQAReplyState, CompareState
from utils.helpers import result_kb, send_media, user_lang
from utils.commands import set_admin_commands, set_user_commands

router=Router()
CODE_RE=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{2,31}$')

async def get_ctx(message_or_cb,db):
    uid=message_or_cb.from_user.id
    row=await db.user(uid)
    if not row:
        row,_=await db.ensure_user(message_or_cb.from_user)
    return row,user_lang(row)

@router.message(CommandStart())
async def start(message:Message, db:Database, bot:Bot):
    arg=message.text.split(maxsplit=1)[1] if message.text and ' ' in message.text else ''
    ref=None; content_code=None
    if arg.startswith('ref_'): ref=arg[4:]
    elif '_' in arg: content_code=arg.split('_',1)[1]
    else: content_code=arg
    row,is_new=await db.ensure_user(message.from_user,ref)
    if is_new:
        await message.answer(language_prompt(),reply_markup=LANGS)
        return
    # Every returning user must pass the live required-channel gate before the main menu.
    if not await send_subscription_screen(bot,message.chat.id,message.from_user.id,db,row['language'],f'subcheck:{content_code}' if content_code else 'subcheck'):
        return
    if content_code:
        await open_by_code(message,db,bot,content_code)
        return
    await message.answer(await db.setting(f"welcome_text_{row['language']}", tr(row['language'],'welcome')),reply_markup=user_menu(row['language']))

@router.message(Command('help'))
async def help_cmd(message:Message,db:Database):
    row,_=await get_ctx(message,db); await message.answer(tr(row['language'],'about_text'))

@router.callback_query(F.data.startswith('lang:'))
async def set_language(cb:CallbackQuery,db:Database,bot:Bot):
    lang=cb.data.split(':',1)[1]
    if lang not in {'uz','ru','en'}:
        await cb.answer(tr('uz', 'invalid_language'), show_alert=True); return
    await db.execute('UPDATE users SET language=? WHERE telegram_id=?',(lang,cb.from_user.id))
    await cb.message.edit_text(tr(lang,'language_changed'))
    admin = await db.authenticated_admin(cb.from_user.id)
    if admin:
        await set_admin_commands(bot, cb.from_user.id)
        await cb.message.answer(await db.setting(f'welcome_text_{lang}', tr(lang,'welcome')),reply_markup=user_menu(lang))
    else:
        await set_user_commands(bot, cb.from_user.id)
        if await send_subscription_screen(bot,cb.message.chat.id,cb.from_user.id,db,lang,'subcheck'):
            await cb.message.answer(await db.setting(f'welcome_text_{lang}', tr(lang,'welcome')),reply_markup=user_menu(lang))
    await cb.answer()

@router.callback_query(F.data=='nav:home')
async def nav_home(cb:CallbackQuery,db:Database,state:FSMContext):
    await state.clear()
    row,lang=await get_ctx(cb,db); await cb.message.answer(await db.setting(f'welcome_text_{lang}', tr(lang,'welcome')),reply_markup=user_menu(lang)); await cb.answer()
@router.callback_query(F.data=='nav:back')
async def nav_back(cb:CallbackQuery,state:FSMContext,db:Database):
    await state.clear()
    row,lang=await get_ctx(cb,db)
    try:
        await cb.message.delete()
    except TelegramAPIError:
        await cb.message.answer(tr(lang,'cancelled'),reply_markup=user_menu(lang))
    await cb.answer()
@router.callback_query(F.data=='noop')
async def noop(cb:CallbackQuery): await cb.answer()

async def open_by_code(event, db, bot, code: str):
    user_id = event.from_user.id
    chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id
    row = await db.user(user_id)
    if not row:
        row, _ = await db.ensure_user(event.from_user)
    lang = user_lang(row)
    code = code.strip()
    if not CODE_RE.fullmatch(code):
        await bot.send_message(chat_id, tr(lang,'not_found_link'))
        return
    ok, missing = await check_subscription(bot, user_id, db)
    if not ok:
        kb = []
        for ch in missing:
            url = ch['invite_link'] or (f"https://t.me/{str(ch['username']).lstrip('@')}" if ch['username'] else None)
            if url:
                kb.append([InlineKeyboardButton(text=f"📢 {ch['name'][:30]}", url=url)])
        kb.append([InlineKeyboardButton(text=tr(lang, 'check_subscription'), callback_data=f'subcheck:{code}')])
        await bot.send_message(chat_id, tr(lang, 'sub_required'), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return

    upper = code.upper()
    prefix = upper[:1]
    ordered = []
    if prefix == 'K':
        ordered = [('movie', db.movie_by_code)]
    elif prefix == 'S':
        ordered = [('series', db.series_by_code)]
    elif prefix == 'A':
        ordered = [('series', db.series_by_code), ('movie', db.movie_by_code)]
    elif prefix == 'M':
        ordered = [('movie', db.movie_by_code), ('series', db.series_by_code)]
    elif prefix == 'E':
        ordered = [('episode', db.episode_by_code)]
    else:
        ordered = [('movie', db.movie_by_code), ('series', db.series_by_code), ('episode', db.episode_by_code)]

    for kind, lookup in ordered:
        item = await lookup(code)
        if not item:
            continue
        if kind == 'movie':
            await show_movie(chat_id, user_id, db, bot, item, lang)
        elif kind == 'series':
            await show_series(chat_id, user_id, db, bot, item, lang)
        else:
            await show_episode(chat_id, user_id, db, bot, item, lang)
        return

    await db.execute('INSERT INTO search_history(user_id,query,created_at) VALUES(?,?,?)',(row['id'],code,utcnow()))
    await bot.send_message(chat_id, tr(lang,'not_found'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang,'support'),callback_data='support:from_search')],
        [InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]))


@router.callback_query(F.data=='subcheck')
async def subcheck_plain(cb:CallbackQuery,db:Database,bot:Bot):
    row,lang=await get_ctx(cb,db)
    ok,missing=await check_subscription(bot,cb.from_user.id,db)
    await cb.answer(tr(lang,'sub_ok') if ok else tr(lang,'sub_no'),show_alert=True)
    if not ok:
        await cb.message.answer(tr(lang,'sub_required'),reply_markup=subscription_markup(lang,missing,'subcheck'))
    else:
        await cb.message.answer(await db.setting(f'welcome_text_{lang}',tr(lang,'welcome')),reply_markup=user_menu(lang))

@router.callback_query(F.data.startswith('subcheck:'))
async def subcheck(cb:CallbackQuery,db:Database,bot:Bot):
    row,lang=await get_ctx(cb,db); code=cb.data.split(':',1)[1]
    ok,_=await check_subscription(bot,cb.from_user.id,db)
    await cb.answer(tr(lang,'sub_ok') if ok else tr(lang,'sub_no'),show_alert=True)
    if ok:
        await open_by_code(cb,db,bot,code)

async def content_list(message,db,lang,kind,page):
    size=max(1,int(await db.setting('pagination_size','8'))); total_count=await db.count_content(kind); total=max(1,(total_count+size-1)//size); page=max(0,min(int(page),total-1)); rows=await db.list_content(kind,size,page*size)
    title_key={'movie':'category_movie_title','series':'category_series_title','anime':'category_anime_title','cartoon':'category_cartoon_title','other':'other'}.get(kind,'new')
    tagline_key={'movie':'category_movie_tagline','series':'category_series_tagline','anime':'category_anime_tagline','cartoon':'category_cartoon_tagline'}.get(kind)
    if not rows:
        text=tr(lang,title_key) + (f"\n{tr(lang,tagline_key)}" if tagline_key else '') + f"\n\n{tr(lang,'no_category')}"
        await message.answer(text,reply_markup=back_home(lang)); return
    controls=pager(lang,f'list:{kind}',page,total)
    buttons=[]
    for r in rows:
        label=f"{r['title'][:34]} · {tr(lang, 'search_type_' + ('movie' if r['kind']=='movie' and r['content_type']=='movie' else 'anime' if r['content_type']=='anime' else 'cartoon' if r['content_type']=='cartoon' else 'series'))}"
        buttons.append([InlineKeyboardButton(text=label,callback_data=f"open:{r['kind']}:{r['id']}")])
    await message.answer(tr(lang,title_key)+(f"\n{tr(lang,tagline_key)}" if tagline_key else ''),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons+controls))

async def content_rows(message,db,lang,mode,page):
    size=max(1,int(await db.setting('pagination_size','8')))
    rows=await (db.popular(size,page*size) if mode=='popular' else db.newest(size,page*size))
    if not rows:
        await message.answer(tr(lang,'not_found'),reply_markup=back_home(lang))
        return
    total=max(1,(await db.total_catalog()+size-1)//size)
    controls=pager(lang,mode,page,total)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r['title'][:40],callback_data=f"open:{r['kind']}:{r['id']}")] for r in rows]+controls)
    await message.answer(tr(lang,'popular_title' if mode=='popular' else 'new_content'),reply_markup=kb)

@router.callback_query(F.data.startswith('list:'))
async def cb_list(cb:CallbackQuery,db:Database):
    _,kind,page=cb.data.split(':'); row,lang=await get_ctx(cb,db); await content_list(cb.message,db,lang,kind,int(page)); await cb.answer()
@router.callback_query(F.data.startswith('popular:'))
async def cb_popular(cb:CallbackQuery,db:Database): row,lang=await get_ctx(cb,db); await content_rows(cb.message,db,lang,'popular',int(cb.data.split(':')[1])); await cb.answer()
@router.callback_query(F.data.startswith('new:'))
async def cb_new(cb:CallbackQuery,db:Database): row,lang=await get_ctx(cb,db); await content_rows(cb.message,db,lang,'new',int(cb.data.split(':')[1])); await cb.answer()

async def show_movie(chat_id:int,user_id:int,db,bot,m,lang):
    kb=[[InlineKeyboardButton(text=tr(lang,'watch'),callback_data=f'watch:movie:{m["id"]}'),InlineKeyboardButton(text=tr(lang,'share'),callback_data=f'share:movie:{m["code"]}')],
        [InlineKeyboardButton(text=tr(lang,'compare'),callback_data=f'compare:start:movie:{m["id"]}'),InlineKeyboardButton(text=tr(lang,'report'),callback_data=f'report:movie:{m["id"]}')],
        [InlineKeyboardButton(text=tr(lang,'add_favorite'),callback_data=f'fav:movie:{m["id"]}'),InlineKeyboardButton(text=tr(lang,'add_later'),callback_data=f'later:movie:{m["id"]}')],
        [InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]
    type_key=f'type_{m["content_type"]}'
    details_key={'movie':'movie_details','cartoon':'cartoon_details','anime':'anime_details'}.get(m['content_type'],'movie_details')
    text_header=tr(lang,details_key)
    extra=[]
    if m['original_title'] and m['original_title'] != m['title']:
        extra.append(f"{tr(lang,'original_title')}: {m['original_title']}")
    if m['duration']:
        extra.append(f"{tr(lang,'duration')}: {m['duration']} min")
    if m['age_rating']:
        extra.append(f"{tr(lang,'age_rating')}: {m['age_rating']}")
    if m['quality']:
        extra.append(f"{tr(lang,'quality')}: {m['quality']}")
    if m['audio_languages']:
        extra.append(f"{tr(lang,'audio')}: {m['audio_languages']}")
    if m['subtitle_languages']:
        extra.append(f"{tr(lang,'subtitles')}: {m['subtitle_languages']}")
    text=tr(lang,'movie_text',title=m['title'],code=m['code'],type_label=tr(lang,'type_label'),content_type=tr(lang,type_key),year=m['release_year'] or '—',country=m[f'country_{lang}'] or '—',genre=m[f'genre_{lang}'] or '—',language=m['language'] or '—',rating=m['rating'],views=m['views_count'],description=m['description'] or '—')
    text=text_header+'\n\n'+text+(('\n\n'+'\n'.join(extra)) if extra else '')
    markup=InlineKeyboardMarkup(inline_keyboard=kb)
    if m['poster_file_id']:
        await bot.send_photo(chat_id,m['poster_file_id'],caption=text,reply_markup=markup)
    else:
        await bot.send_message(chat_id,text,reply_markup=markup)


async def show_series(chat_id:int,user_id:int,db,bot,s,lang):
    seasons=await db.public_seasons(s['id'])
    progress=await db.get_progress(int(user_id),int(s['id']))
    ctype=s['content_type']
    details_key={'series':'series_details','anime':'anime_details','cartoon':'cartoon_details'}.get(ctype,'series_details')
    content_label=tr(lang,'content_type_anime') if ctype=='anime' else (tr(lang,'cartoons') if ctype=='cartoon' else tr(lang,'content_type_series'))
    if ctype=='anime':
        tagline=tr(lang,'category_anime_tagline')
    elif ctype=='cartoon':
        tagline=tr(lang,'category_cartoon_tagline')
    else:
        tagline=tr(lang,'category_series_tagline')
    kb=[]
    if progress:
        kb.append([InlineKeyboardButton(text=tr(lang,'continue_watching'),callback_data=f'continue:{s["id"]}')])
    elif seasons and any(int(x['episode_count'] or 0)>0 for x in seasons):
        kb.append([InlineKeyboardButton(text=tr(lang,'watch_first'),callback_data=f'watch:series:{s["id"]}')])
    if seasons:
        kb.append([InlineKeyboardButton(text=tr(lang,'episodes'),callback_data=f'series:episodes:{s["id"]}:0')])
        # Show a compact season picker; full pagination remains on the Episodes screen.
        for x in seasons[:6]:
            kb.append([InlineKeyboardButton(text=f"📀 {x['season_number']} · {x['episode_count']} {tr(lang,'episodes_label')}",callback_data=f'season:{s["id"]}:{x["season_number"]}:0')])
    else:
        kb.append([InlineKeyboardButton(text=tr(lang,'no_episodes'),callback_data='noop')])
    follow_text=tr(lang,'unfollow') if await db.is_following(int((await db.user(user_id))['id']),int(s['id'])) else tr(lang,'follow')
    kb.append([InlineKeyboardButton(text=follow_text,callback_data=f'follow:{s["id"]}'), InlineKeyboardButton(text=tr(lang,'compare'),callback_data=f'compare:start:series:{s["id"]}')])
    kb += [[InlineKeyboardButton(text=tr(lang,'add_favorite'),callback_data=f'fav:series:{s["id"]}'), InlineKeyboardButton(text=tr(lang,'add_later'),callback_data=f'later:series:{s["id"]}')],
           [InlineKeyboardButton(text=tr(lang,'share'),callback_data=f'share:series:{s["code"]}')],
           [InlineKeyboardButton(text=tr(lang,'report'),callback_data=f'report:series:{s["id"]}')],
           [InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]
    extra=[]
    if s['original_title'] and s['original_title'] != s['title']:
        extra.append(f"{tr(lang,'original_title')}: {s['original_title']}")
    if ctype=='anime':
        for key in ('studio','anime_type','status','age_rating','quality','audio_languages','subtitle_languages'):
            if s[key]:
                label_key={'audio_languages':'audio','subtitle_languages':'subtitles'}.get(key,key)
                label=tr(lang,label_key)
                extra.append(f"{label}: {s[key]}")
    if s['quality']: extra.append(f"{tr(lang,'quality')}: {s['quality']}")
    if s['age_rating'] and ctype!='anime': extra.append(f"{tr(lang,'age_rating')}: {s['age_rating']}")
    text=tr(lang,'series_text',title=s['title'],code=s['code'],type=content_label,year=s['release_year'] or '—',country=s[f'country_{lang}'] or '—',genre=s[f'genre_{lang}'] or '—',language=s['language'] or '—',rating=s['rating'],views=s['views_count'],episodes=s['episode_count'],description=s['description'] or '—')
    text=tr(lang,details_key)+'\n'+tagline+'\n\n'+text+(('\n\n'+'\n'.join(extra)) if extra else '')
    markup=InlineKeyboardMarkup(inline_keyboard=kb)
    if s['poster_file_id']:
        await bot.send_photo(chat_id,s['poster_file_id'],caption=text,reply_markup=markup)
    else:
        await bot.send_message(chat_id,text,reply_markup=markup)


async def show_seasons(cb:CallbackQuery,series_id:int,db:Database,lang:str,page:int=0):
    size=max(1,int(await db.setting('pagination_size','8')))
    seasons=await db.public_seasons(series_id)
    total=max(1,(len(seasons)+size-1)//size)
    page=max(0,min(page,total-1))
    chunk=seasons[page*size:(page+1)*size]
    kb=[[InlineKeyboardButton(text=f"📀 {x['season_number']} · {x['episode_count']} {tr(lang,'episodes_label')}",callback_data=f"season:{series_id}:{x['season_number']}:0")] for x in chunk]
    kb += pager(lang,f'seasons:{series_id}',page,total)
    kb.append([InlineKeyboardButton(text=tr(lang,'back_to_series'),callback_data=f'open:series:{series_id}')])
    await cb.message.answer(tr(lang,'seasons_label'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data.startswith('series:episodes:'))
async def series_episodes_cb(cb:CallbackQuery,db:Database):
    _,_,series_id,page=cb.data.split(':')
    row,lang=await get_ctx(cb,db)
    await show_seasons(cb,int(series_id),db,lang,int(page))
    await cb.answer()


@router.callback_query(F.data.startswith('seasons:'))
async def seasons_page_cb(cb:CallbackQuery,db:Database):
    _,series_id,page=cb.data.split(':')
    row,lang=await get_ctx(cb,db)
    await show_seasons(cb,int(series_id),db,lang,int(page))
    await cb.answer()


@router.callback_query(F.data.startswith('season:'))
async def season_cb(cb:CallbackQuery,db:Database,bot:Bot):
    parts=cb.data.split(':')
    if len(parts)==3:
        _,series_id,season_no=parts
        page=0
    else:
        _,series_id,season_no,page=parts
        page=int(page)
    row,lang=await get_ctx(cb,db)
    ok,_=await check_subscription(bot,cb.from_user.id,db)
    if not ok:
        await cb.answer(tr(lang,'sub_no'),show_alert=True)
        return
    season=await db.season(int(series_id),int(season_no))
    if not season:
        await cb.answer(tr(lang,'not_found'),show_alert=True)
        return
    size=max(1,int(await db.setting('pagination_size','8')))
    total_count=await db.count_public_episodes(int(season['id']))
    total=max(1,(total_count+size-1)//size)
    page=max(0,min(page,total-1))
    episodes=await db.public_episodes(int(season['id']),size,page*size)
    kb=[[InlineKeyboardButton(text=f"🎞 {e['episode_number']}. {(e['title'] or '')[:35]}",callback_data=f"open:episode:{e['id']}")] for e in episodes]
    kb += pager(lang,f'season:{series_id}:{season_no}',page,total)
    kb.append([InlineKeyboardButton(text=tr(lang,'back_to_series'),callback_data=f'open:series:{series_id}')])
    await cb.message.answer(tr(lang,'season_title',season=season_no),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()


async def show_episode(chat_id:int,user_id:int,db,bot,e,lang):
    await db.bump_view('episode',int(e['id']),int((await db.user(user_id))['id']))
    if str(e['visibility']) if 'visibility' in e.keys() else 'public' == 'public':
        previous,next_episode=await db.adjacent_episodes(int(e['series_id']),int(e['season_number']),int(e['episode_number']))
    else:
        previous,next_episode=None,None
    buttons=[]
    nav=[]
    if previous:
        nav.append(InlineKeyboardButton(text=tr(lang,'previous_episode'),callback_data=f"open:episode:{previous['id']}"))
    if str(e['visibility']) if 'visibility' in e.keys() else 'public' == 'public':
        nav.append(InlineKeyboardButton(text=tr(lang,'episodes'),callback_data=f"series:episodes:{e['series_id']}:0"))
    if next_episode:
        nav.append(InlineKeyboardButton(text=tr(lang,'next_episode'),callback_data=f"open:episode:{next_episode['id']}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(text=tr(lang,'back_to_series'),callback_data=f"open:series:{e['series_id']}")])
    caption=e['caption'] or f"{e['series_title']} — {tr(lang,'episode_position',season=e['season_number'],episode=e['episode_number'])}\n{e['title'] or ''}".strip()
    if e['description']:
        caption += f"\n\n{e['description']}"
    await send_media(bot,chat_id,e['media_file_id'],e['media_type'],caption=caption,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    if not next_episode:
        final_kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang,'repeat_watch'),callback_data=f'watch:series:{e["series_id"]}')],
            [InlineKeyboardButton(text=tr(lang,'recommendations'),callback_data='end:recommend')],
            [InlineKeyboardButton(text=tr(lang,'episodes'),callback_data=f'series:episodes:{e["series_id"]}:0')],
            [InlineKeyboardButton(text=tr(lang,'back_to_series'),callback_data=f'open:series:{e["series_id"]}')]
        ])
        await bot.send_message(chat_id,tr(lang,'finish_series'),reply_markup=final_kb)


@router.callback_query(F.data=='end:recommend')
async def end_recommend_cb(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    await recommendation_list(cb.message,db,lang,int(row['id']),0)
    await cb.answer()


@router.callback_query(F.data.startswith('continue:'))
async def continue_cb(cb:CallbackQuery,db:Database,bot:Bot):
    row,lang=await get_ctx(cb,db)
    series_id=int(cb.data.split(':')[-1])
    progress=await db.get_progress(cb.from_user.id,series_id)
    if not progress:
        await cb.answer(tr(lang,'no_episodes'),show_alert=True)
        return
    e=await db.episode_by_id(int(progress['episode_id']))
    if not e:
        await cb.answer(tr(lang,'not_found'),show_alert=True)
        return
    await show_episode(cb.message.chat.id,cb.from_user.id,db,bot,e,lang)
    await cb.answer()

@router.callback_query(F.data.startswith('search_repeat:'))
async def search_repeat_cb(cb:CallbackQuery, db:Database, state:FSMContext):
    row,lang=await get_ctx(cb,db)
    try:
        item_id=int(cb.data.split(':')[-1])
    except ValueError:
        await cb.answer(tr(lang,'invalid'),show_alert=True); return
    item=await db.search_history_item(int(row['id']),item_id)
    if not item:
        await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await state.update_data(search_query=str(item['query']))
    await render_search_results(cb.message,db,lang,str(item['query']),0,state)
    await cb.answer()

@router.callback_query(F.data.startswith('search:'))
async def search_page_cb(cb:CallbackQuery,db:Database,state:FSMContext):
    parts=cb.data.split(':')
    if len(parts)!=2 or not parts[1].isdigit():
        row,lang=await get_ctx(cb,db); await cb.answer(tr(lang,'invalid'),show_alert=True); return
    row,lang=await get_ctx(cb,db)
    data=await state.get_data(); q=str(data.get('search_query') or '').strip()
    if not q:
        await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await render_search_results(cb.message,db,lang,q,int(parts[1]),state)
    await cb.answer()

@router.callback_query(F.data.startswith('open:'))
async def open_cb(cb:CallbackQuery,db:Database,bot:Bot,state:FSMContext):
    _,kind,cid=cb.data.split(':')
    await state.clear()
    row,lang=await get_ctx(cb,db)
    ok,_=await check_subscription(bot,cb.from_user.id,db)
    if not ok:
        await cb.answer(tr(lang,'sub_no'),show_alert=True); return
    if kind=='movie':
        m=await db.content_by_kind_id('movie', int(cid), public_only=True)
        if m and int(m['active']): await show_movie(cb.message.chat.id,cb.from_user.id,db,bot,m,lang)
    elif kind=='series':
        s=await db.content_by_kind_id('series', int(cid), public_only=True)
        if s and int(s['active']): await show_series(cb.message.chat.id,cb.from_user.id,db,bot,s,lang)
    elif kind=='episode':
        e=await db.content_by_kind_id('episode', int(cid), public_only=True)
        if e and int(e['active']):
            await show_episode(cb.message.chat.id,cb.from_user.id,db,bot,e,lang)
        else:
            await cb.answer(tr(lang,'not_found'),show_alert=True); return
    else:
        await cb.answer(tr(lang,'invalid'),show_alert=True); return
    if kind=='movie' and not m:
        await cb.answer(tr(lang,'not_found'),show_alert=True); return
    if kind=='series' and not s:
        await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await cb.answer()


@router.callback_query(F.data.startswith('watch:'))
async def watch_cb(cb:CallbackQuery,db:Database,bot:Bot):
    _,kind,cid=cb.data.split(':')
    row,lang=await get_ctx(cb,db)
    ok,_=await check_subscription(bot,cb.from_user.id,db)
    if not ok:
        await cb.answer(tr(lang,'sub_no'),show_alert=True); return
    if kind=='movie':
        m=await db.content_by_kind_id('movie', int(cid), public_only=True)
        if not m or not int(m['active']):
            await cb.answer(tr(lang,'not_found'),show_alert=True); return
        await db.bump_view('movie',int(cid),int(row['id']))
        await send_media(bot,cb.from_user.id,m['media_file_id'],m['media_type'],caption=f"🎬 {m['title']} | {m['code']}")
    elif kind=='series':
        progress=await db.get_progress(cb.from_user.id,int(cid))
        e=await db.episode_by_id(int(progress['episode_id'])) if progress else None
        if not e:
            seasons=await db.seasons(int(cid))
            for season in seasons:
                eps=await db.public_episodes(int(season['id']),1,0)
                if eps:
                    e=eps[0]; break
        if not e:
            await cb.answer(tr(lang,'no_episodes'),show_alert=True); return
        await show_episode(cb.message.chat.id,cb.from_user.id,db,bot,e,lang)
    await cb.answer()

@router.callback_query(F.data.startswith('fav:'))
async def fav_cb(cb:CallbackQuery,db:Database):
    _,kind,cid=cb.data.split(':'); row,lang=await get_ctx(cb,db)
    if kind not in {'movie','series'}:
        await cb.answer(tr(lang,'invalid'),show_alert=True); return
    saved=await db.toggle_saved('favorites',int(row['id']),kind,int(cid)); await cb.answer(tr(lang,'saved') if saved else tr(lang,'removed'))


@router.callback_query(F.data.startswith('later:'))
async def later_cb(cb:CallbackQuery,db:Database):
    _,kind,cid=cb.data.split(':'); row,lang=await get_ctx(cb,db)
    if kind not in {'movie','series'}:
        await cb.answer(tr(lang,'invalid'),show_alert=True); return
    saved=await db.toggle_saved('watch_later',int(row['id']),kind,int(cid)); await cb.answer(tr(lang,'saved') if saved else tr(lang,'removed'))


@router.callback_query(F.data.startswith('share:'))
async def share_cb(cb:CallbackQuery,db:Database,bot:Bot):
    row,lang=await get_ctx(cb,db)
    _,kind,code=cb.data.split(':',2)
    me=await bot.get_me()
    username=(getattr(me,'username',None) or '').lstrip('@')
    prefix=kind
    if kind=='series':
        series=await db.series_by_code(code)
        if not series:
            await cb.answer(tr(lang,'not_found'),show_alert=True); return
        prefix={'series':'series','anime':'anime','cartoon':'cartoon'}.get(series['content_type'],'series')
    elif kind=='movie':
        movie=await db.movie_by_code(code)
        if not movie:
            await cb.answer(tr(lang,'not_found'),show_alert=True); return
        prefix=movie['content_type'] if movie['content_type'] in {'anime','cartoon'} else 'movie'
    link=f"https://t.me/{username}?start={prefix}_{code}" if username else None
    if link:
        await cb.message.answer(f"{tr(lang,'share_link')}:\n{link}")
    else:
        await cb.message.answer(tr(lang,'not_found_link'))
    await cb.answer()

async def saved_list(message,db,lang,table,page):
    row,_=await get_ctx(message,db)
    size=int(await db.setting('pagination_size','8'))
    db_table='favorites' if table=='favorites' else 'watch_later'
    rows=await db.saved(db_table,int(row['id']),size,page*size)
    if not rows and page>0:
        await message.answer(tr(lang,'not_found')); return
    if not rows:
        await message.answer(tr(lang,'not_found'),reply_markup=back_home(lang)); return
    total_count=await db.count_user_list(db_table,int(row['id']))
    total=max(1,(total_count+size-1)//size)
    controls=pager(lang,f'saved:{table}',page,total)
    kb=[[InlineKeyboardButton(text=x['title'][:40],callback_data=f"open:{x['kind']}:{x['id']}")] for x in rows]+controls
    await message.answer(tr(lang,'favorites' if table=='favorites' else 'watch_later'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

async def history_list(message,db,lang,page):
    row,_=await get_ctx(message,db)
    size=int(await db.setting('pagination_size','8'))
    rows=await db.history_items(int(row['id']),size,page*size)
    total_count=await db.count_user_list('watch_history',int(row['id']))
    total=max(1,(total_count+size-1)//size)
    kb=[[InlineKeyboardButton(text=f"{r['title'][:38]} — {r['code']}",callback_data=f"open:{('series' if r['content_kind']=='series' else 'episode' if r['content_kind']=='episode' else 'movie')}:{r['content_id']}")] for r in rows]
    if page==0:
        kb.append([InlineKeyboardButton(text='🗑',callback_data='history:clear')])
    kb.extend(pager(lang,'history',page,total))
    await message.answer(tr(lang,'history'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb or [[InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]))

@router.callback_query(F.data.startswith('saved:'))
async def saved_cb(cb:CallbackQuery,db:Database):
    _,table,page=cb.data.split(':')
    row,lang=await get_ctx(cb,db)
    await saved_list(cb.message,db,lang,table,int(page))
    await cb.answer()
@router.callback_query(F.data.regexp(r'^history:\d+$'))
async def history_page_cb(cb:CallbackQuery,db:Database):
    parts=cb.data.split(':')
    if parts[-1]=='clear':
        return
    row,lang=await get_ctx(cb,db)
    await history_list(cb.message,db,lang,int(parts[-1]))
    await cb.answer()

@router.callback_query(F.data=='history:clear')
async def clear_history_confirm(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    await cb.message.answer(tr(lang,'confirm_clear_history'),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'confirm'),callback_data='history:clear_yes')],[InlineKeyboardButton(text=tr(lang,'cancel'),callback_data='nav:home')]]))
    await cb.answer()

@router.callback_query(F.data=='history:clear_yes')
async def clear_history(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    await db.clear_history(int(row['id']))
    await cb.answer(tr(lang,'history_cleared'),show_alert=True)

async def recommendation_list(message,db,lang,user_id,page):
    rows=await recommend(db,user_id,8); await message.answer(tr(lang,'recommend_title'),reply_markup=result_kb(lang,rows) if rows else back_home(lang))

async def browse_genres(message,db,lang,page=0):
    size=max(1,int(await db.setting('pagination_size','8')))
    rows=await db.genres(); total=max(1,(len(rows)+size-1)//size); page=max(0,min(int(page),total-1)); chunk=rows[page*size:(page+1)*size]
    buttons=[[InlineKeyboardButton(text=r[f'name_{lang}'],callback_data=f'genre:{r["id"]}:0')] for r in chunk]
    buttons+=pager(lang,'genres',page,total); buttons.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
    await message.answer(tr(lang,'genres'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@router.callback_query(F.data.startswith('genres:'))
async def genres_page_cb(cb:CallbackQuery,db:Database):
    page=int(cb.data.split(':')[-1]); row,lang=await get_ctx(cb,db); await browse_genres(cb.message,db,lang,page); await cb.answer()
@router.callback_query(F.data.startswith('genre:'))
async def genre_cb(cb:CallbackQuery,db:Database):
    _,gid,page=cb.data.split(':'); row,lang=await get_ctx(cb,db); size=max(1,int(await db.setting('pagination_size','8'))); p=int(page); rows=await db.genre_filter(int(gid),size,p*size); total_count=await db.count_filter('genre_id',int(gid)); total=max(1,(total_count+size-1)//size); p=max(0,min(p,total-1)); kb=result_kb(lang,rows).inline_keyboard; kb += pager(lang,f'genre:{gid}',p,total); kb += [[InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]; await cb.message.answer(tr(lang,'genres'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()
async def browse_countries(message,db,lang,page=0):
    size=max(1,int(await db.setting('pagination_size','8'))); rows=await db.countries(); total=max(1,(len(rows)+size-1)//size); page=max(0,min(int(page),total-1)); chunk=rows[page*size:(page+1)*size]
    buttons=[[InlineKeyboardButton(text=r[f'name_{lang}'],callback_data=f'country:{r["id"]}:0')] for r in chunk]; buttons+=pager(lang,'countries',page,total); buttons.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]); await message.answer(tr(lang,'countries'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@router.callback_query(F.data.startswith('countries:'))
async def countries_page_cb(cb:CallbackQuery,db:Database):
    page=int(cb.data.split(':')[-1]); row,lang=await get_ctx(cb,db); await browse_countries(cb.message,db,lang,page); await cb.answer()
@router.callback_query(F.data.startswith('country:'))
async def country_cb(cb:CallbackQuery,db:Database):
    _,cid,page=cb.data.split(':'); row,lang=await get_ctx(cb,db); size=max(1,int(await db.setting('pagination_size','8'))); p=int(page); rows=await db.country_filter(int(cid),size,p*size); total_count=await db.count_filter('country_id',int(cid)); total=max(1,(total_count+size-1)//size); p=max(0,min(p,total-1)); kb=result_kb(lang,rows).inline_keyboard; kb += pager(lang,f'country:{cid}',p,total); kb += [[InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]; await cb.message.answer(tr(lang,'countries'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()
async def browse_years(message,db,lang,page=0):
    size=max(1,int(await db.setting('pagination_size','8'))); rows=await db.years(); total=max(1,(len(rows)+size-1)//size); page=max(0,min(int(page),total-1)); chunk=rows[page*size:(page+1)*size]
    buttons=[[InlineKeyboardButton(text=str(r['year']),callback_data=f'year:{r["year"]}:0')] for r in chunk]; buttons+=pager(lang,'years',page,total); buttons.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]); await message.answer(tr(lang,'years'),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
@router.callback_query(F.data.startswith('years:'))
async def years_page_cb(cb:CallbackQuery,db:Database):
    page=int(cb.data.split(':')[-1]); row,lang=await get_ctx(cb,db); await browse_years(cb.message,db,lang,page); await cb.answer()
@router.callback_query(F.data.startswith('year:'))
async def year_cb(cb:CallbackQuery,db:Database):
    _,year,page=cb.data.split(':'); row,lang=await get_ctx(cb,db); size=max(1,int(await db.setting('pagination_size','8'))); p=int(page); rows=await db.year_filter(int(year),size,p*size); total_count=await db.count_filter('release_year',int(year)); total=max(1,(total_count+size-1)//size); p=max(0,min(p,total-1)); kb=result_kb(lang,rows).inline_keyboard; kb += pager(lang,f'year:{year}',p,total); kb += [[InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]; await cb.message.answer(tr(lang,'years'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.message(SearchState.search)
async def do_search(message:Message,state:FSMContext,db:Database):
    row,lang=await get_ctx(message,db)
    q=(message.text or '').strip()
    if not q:
        await message.answer(tr(lang,'search_prompt')); return
    await direct_search(message,db,lang,q,state)

async def render_search_results(message:Message,db:Database,lang:str,q:str,page:int,state:FSMContext|None=None):
    size=max(1,int(await db.setting('pagination_size','8')))
    total_count=await db.count_search(q)
    total=max(1,(total_count+size-1)//size)
    page=max(0,min(int(page),total-1))
    rows=await db.search(q,size,page*size)
    if not rows:
        await message.answer(tr(lang,'not_found'),reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang,'support'),callback_data='support:from_search')],
            [InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]]))
        return
    for r in rows:
        await db.bump_search(str(r['kind']),int(r['id']))
    kb=[]
    for r in rows:
        if r['kind']=='movie': key='search_type_' + ('anime' if r['content_type']=='anime' else 'cartoon' if r['content_type']=='cartoon' else 'movie')
        elif r['kind']=='series': key='search_type_' + ('anime' if r['content_type']=='anime' else 'cartoon' if r['content_type']=='cartoon' else 'series')
        else: key='search_type_anime' if str(r['code']).upper().startswith('A') else 'search_type_series'
        label=f"{tr(lang,key)} {r['title'][:34]} · {r['code']}"
        kb.append([InlineKeyboardButton(text=label[:64],callback_data=f"open:{r['kind']}:{r['id']}")])
    kb += pager(lang,'search',page,total)
    kb.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
    await message.answer(f"🔎 {q}",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data=='searchhist:history')
async def search_history_cb(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    rows=await db.search_history(int(row['id']),20)
    if not rows:
        await cb.message.answer(tr(lang,'search_history_empty'),reply_markup=back_home(lang)); await cb.answer(); return
    kb=[[InlineKeyboardButton(text=str(r['query'])[:50],callback_data=f"search_repeat:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton(text=tr(lang,'clear_history'),callback_data='searchhist:clear')])
    kb.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
    await cb.message.answer(tr(lang,'search_history'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data=='searchhist:clear')
async def search_clear_cb(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db); await db.clear_search_history(int(row['id'])); await cb.answer(tr(lang,'cleared')); await cb.message.answer(tr(lang,'search_history_empty'),reply_markup=back_home(lang))

async def profile(message,db,lang,row):
    f=await db.count_user_list('favorites',row['id']); l=await db.count_user_list('watch_later',row['id']); h=await db.count_user_list('watch_history',row['id']); refs=await db.referrals(row['id']); ts=await db.count_user_list('support_tickets',row['id']); qs=await db.count_user_list('anonymous_questions',row['id']); await message.answer(tr(lang,'profile_text',name=row['first_name'],username=row['username'] or '—',language=lang,created=row['created_at'][:10],favorites=f,later=l,history=h,referrals=refs,tickets=ts,questions=qs,refcode=row['referral_code']))
async def referral(message,db,lang):
    row,_=await get_ctx(message,db); if_disabled=(await db.setting('referral_enabled','1'))!='1';
    if if_disabled: await message.answer(tr(lang,'ref_disabled')); return
    bot_username=(await message.bot.get_me()).username; await message.answer(tr(lang,'referral_text',count=await db.referrals(row['id']),link=f'https://t.me/{bot_username}?start=ref_{row["referral_code"]}'))

@router.callback_query(F.data == 'support:cancel')
async def support_cancel(cb:CallbackQuery,state:FSMContext,db:Database):
    row,lang=await get_ctx(cb,db)
    await state.clear()
    await cb.message.answer(tr(lang,'cancelled'), reply_markup=user_menu(lang))
    await cb.answer()

@router.callback_query(F.data == 'support:from_search')
async def support_from_search(cb:CallbackQuery,state:FSMContext,db:Database):
    row,lang=await get_ctx(cb,db)
    if await db.setting('support_enabled','1')!='1':
        await cb.answer(tr(lang,'support_disabled'), show_alert=True)
        return
    await state.update_data(category='movie')
    await cb.message.answer(tr(lang,'support_prompt'))
    await state.set_state(SupportState.message)
    await cb.answer()

async def support_start(message,state,db,lang):
    if await db.setting('support_enabled','1')!='1':
        await message.answer(tr(lang,'support_disabled'))
        return
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang,'support_movie'),callback_data='support_cat:movie')],
        [InlineKeyboardButton(text=tr(lang,'support_bug'),callback_data='support_cat:bug')],
        [InlineKeyboardButton(text=tr(lang,'support_suggestion'),callback_data='support_cat:suggestion')],
        [InlineKeyboardButton(text=tr(lang,'support_other'),callback_data='support_cat:other')],
        [InlineKeyboardButton(text=tr(lang,'cancel'),callback_data='support:cancel')],
        [InlineKeyboardButton(text=tr(lang,'support_history'),callback_data='support:history')]
    ])
    await message.answer(tr(lang,'support_choose'),reply_markup=kb)
    await state.set_state(SupportState.category)

@router.callback_query(F.data == 'support:history')
async def support_history(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    tickets=await db.tickets_by_user(int(row['id']),20,0)
    if not tickets:
        await cb.message.answer(tr(lang,'no_tickets'),reply_markup=back_home(lang))
        await cb.answer()
        return
    kb=[]
    for t in tickets:
        icon='🟢' if t['status']=='answered' else '🟡' if t['status']!='closed' else '⚫'
        kb.append([InlineKeyboardButton(text=f"{icon} #{t['id']} · {t['category'][:18]}", callback_data=f'question:ticket:{t["id"]}')])
    kb.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
    await cb.message.answer(tr(lang,'support_history'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()

@router.callback_query(F.data.startswith('question:ticket:'))
async def question_ticket_open(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    tid=int(cb.data.split(':')[-1])
    ticket=await db.ticket(tid)
    if not ticket or int(ticket['telegram_id'])!=int(cb.from_user.id):
        await cb.answer(tr(lang,'not_found'),show_alert=True)
        return
    messages=await db.ticket_messages(tid)
    body=[f"💬 #{tid}\n{tr(lang,'ticket_status',status=ticket['status'])}"]
    for m in messages:
        who=tr(lang,'admin') if int(m['sender_telegram_id'])!=int(cb.from_user.id) else tr(lang,'you')
        body.append(f"{who}: {m['message'][:1200]}")
    buttons=[]
    if ticket['status']!='closed':
        buttons.append([InlineKeyboardButton(text=tr(lang,'reply'),callback_data=f'user_ticket:reply:{tid}')])
    buttons.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
    await cb.message.answer('\n\n'.join(body),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@router.callback_query(F.data.startswith('user_ticket:reply:'))
async def user_ticket_reply_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,lang=await get_ctx(cb,db)
    tid=int(cb.data.split(':')[-1])
    ticket=await db.ticket(tid)
    if not ticket or int(ticket['telegram_id'])!=int(cb.from_user.id) or ticket['status']=='closed':
        await cb.answer(tr(lang,'not_found'),show_alert=True)
        return
    await state.update_data(ticket_id=tid)
    await cb.message.answer(tr(lang,'question_reply_prompt'))
    await state.set_state(UserTicketReplyState.ticket_id)
    await cb.answer()

@router.message(UserTicketReplyState.ticket_id)
async def user_ticket_reply_save(message:Message,state:FSMContext,db:Database,bot:Bot):
    row,lang=await get_ctx(message,db)
    data=await state.get_data()
    tid=int(data['ticket_id'])
    ticket=await db.ticket(tid)
    if not ticket or int(ticket['telegram_id'])!=int(message.from_user.id) or ticket['status']=='closed':
        await state.clear()
        await message.answer(tr(lang,'not_found'))
        return
    text=(message.text or '').strip()
    if not text:
        await message.answer(tr(lang,'enter_text'))
        return
    await db.append_ticket_message(tid,message.from_user.id,text,'in_progress')
    await state.clear()
    await message.answer(tr(lang,'ticket_replied'))
    await notify_permitted_admins(
        bot, db, 'feedback.view',
        f"💬 Ticket #{tid}\n👤 User ID: {message.from_user.id}\n\n{text}",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'reply'),callback_data=f'ticket:reply:{tid}')]])
    )

@router.callback_query(SupportState.category,F.data.startswith('support_cat:'))
async def support_category(cb:CallbackQuery,state:FSMContext,db:Database): await state.update_data(category=cb.data.split(':')[1]); row,lang=await get_ctx(cb,db); await cb.message.answer(tr(lang,'support_prompt')); await state.set_state(SupportState.message); await cb.answer()
@router.message(SupportState.message)
async def support_message(message:Message,state:FSMContext,db:Database,bot:Bot):
    row,lang=await get_ctx(message,db)
    data=await state.get_data()
    text=(message.text or '').strip()
    if not text:
        await message.answer(tr(lang,'enter_text'))
        return
    if len(text)>2000:
        await message.answer(tr(lang,'too_long'))
        return
    tid=await db.create_ticket(row['id'],data['category'],text)
    await state.clear()
    await message.answer(tr(lang,'support_created',id=tid))
    await notify_permitted_admins(
        bot, db, 'feedback.view',
        f"💬 Ticket #{tid}\n👤 User ID: {message.from_user.id}\nCategory: {data['category']}\n\n{text}",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang,'reply'),callback_data=f'ticket:reply:{tid}'),
             InlineKeyboardButton(text=tr(lang,'close'),callback_data=f'ticket:close:{tid}')]
        ])
    )

async def notify_permitted_admins(bot:Bot, db:Database, permission:str, text:str, markup:InlineKeyboardMarkup):
    from services.permissions import has_permission
    for admin in await db.admins():
        if not await has_permission(db,admin,permission):
            continue
        try:
            await bot.send_message(int(admin['telegram_id']),text,reply_markup=markup)
        except TelegramAPIError:
            continue

async def question_center(message,db,lang):
    if await db.setting('support_enabled','1')!='1' and await db.setting('anonymous_qa_enabled','1')!='1':
        await message.answer(tr(lang,'not_found'),reply_markup=back_home(lang))
        return
    kb=[
        [InlineKeyboardButton(text=tr(lang,'anonymous_question'),callback_data='questions:ask')],
        [InlineKeyboardButton(text=tr(lang,'my_questions'),callback_data='questions:mine')],
        [InlineKeyboardButton(text=tr(lang,'public_questions'),callback_data='questions:public')],
        [InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]
    ]
    await message.answer(tr(lang,'questions'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data=='questions:ask')
async def questions_ask(cb:CallbackQuery,state:FSMContext,db:Database):
    row,lang=await get_ctx(cb,db)
    await qa_start(cb.message,state,db,lang)
    await cb.answer()

@router.callback_query(F.data=='questions:public')
async def questions_public(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    await public_qa(cb.message,db,lang,0)
    await cb.answer()

@router.callback_query(F.data=='questions:mine')
async def questions_mine(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    tickets=await db.tickets_by_user(int(row['id']),10,0)
    questions=await db.questions_by_user(int(row['id']),10,0)
    kb=[]
    for t in tickets:
        kb.append([InlineKeyboardButton(text=f"💬 #{t['id']} · {t['category'][:18]}",callback_data=f'question:ticket:{t["id"]}')])
    for q in questions:
        icon='🟢' if q['status']=='answered' else '🟡' if q['status']!='archived' else '⚫'
        kb.append([InlineKeyboardButton(text=f"{icon} ❓ #{q['id']}",callback_data=f'question:qa:{q["id"]}')])
    if not kb:
        await cb.message.answer(tr(lang,'no_questions'),reply_markup=back_home(lang))
    else:
        kb.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
        await cb.message.answer(tr(lang,'question_history'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()

@router.callback_query(F.data.startswith('question:qa:'))
async def question_qa_open(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    qid=int(cb.data.split(':')[-1])
    question=await db.question(qid)
    if not question or int(question['telegram_id'])!=int(cb.from_user.id):
        await cb.answer(tr(lang,'not_found'),show_alert=True)
        return
    messages=await db.anonymous_messages(qid)
    body=[tr(lang,'question_open',id=qid)]
    for m in messages:
        who=tr(lang,'admin') if m['sender_type']=='admin' else tr(lang,'you')
        body.append(f"{who}: {m['message'][:1200]}")
    buttons=[]
    if question['status']!='archived':
        buttons.append([InlineKeyboardButton(text=tr(lang,'reply'),callback_data=f'user_qa:reply:{qid}')])
    buttons.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
    await cb.message.answer('\n\n'.join(body),reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await cb.answer()

@router.callback_query(F.data.startswith('user_qa:reply:'))
async def user_qa_reply_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,lang=await get_ctx(cb,db)
    qid=int(cb.data.split(':')[-1])
    q=await db.question(qid)
    if not q or int(q['telegram_id'])!=int(cb.from_user.id) or q['status']=='archived':
        await cb.answer(tr(lang,'not_found'),show_alert=True)
        return
    await state.update_data(question_id=qid)
    await cb.message.answer(tr(lang,'question_reply_prompt'))
    await state.set_state(UserQAReplyState.question_id)
    await cb.answer()

@router.message(UserQAReplyState.question_id)
async def user_qa_reply_save(message:Message,state:FSMContext,db:Database,bot:Bot):
    row,lang=await get_ctx(message,db)
    data=await state.get_data()
    qid=int(data['question_id'])
    q=await db.question(qid)
    if not q or int(q['telegram_id'])!=int(message.from_user.id) or q['status']=='archived':
        await state.clear()
        await message.answer(tr(lang,'not_found'))
        return
    text=(message.text or '').strip()
    if not text:
        await message.answer(tr(lang,'enter_text'))
        return
    await db.append_qa_user_message(qid,message.from_user.id,text)
    await state.clear()
    await message.answer(tr(lang,'question_replied'))
    await notify_permitted_admins(
        bot, db, 'qa.view',
        f"❓ Anonymous Question #{qid}\nInternal User ID: {message.from_user.id}\n\n{text}",
        InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'reply'),callback_data=f'qa_admin:reply:{qid}')]])
    )

async def qa_start(message,state,db,lang):
    if await db.setting('anonymous_qa_enabled','1')!='1': await message.answer(tr(lang,'qa_disabled')); return
    await message.answer(tr(lang,'qa_rules')); await message.answer(tr(lang,'qa_prompt')); await state.set_state(QAState.question)
@router.message(QAState.question)
async def qa_question(message:Message,state:FSMContext,db:Database):
    row,lang=await get_ctx(message,db)
    question_text=(message.text or '').strip()
    if not question_text:
        await message.answer(tr(lang,'enter_text'))
        return
    if len(question_text)>2000:
        await message.answer(tr(lang,'too_long'))
        return
    await state.update_data(question=question_text)
    await message.answer(tr(lang,'qa_preview',question=question_text),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'confirm'),callback_data='qa:confirm')],[InlineKeyboardButton(text=tr(lang,'cancel'),callback_data='qa:cancel')]]))
    await state.set_state(QAState.confirm)
@router.callback_query(QAState.confirm,F.data=='qa:confirm')
async def qa_confirm(cb:CallbackQuery,state:FSMContext,db:Database,bot:Bot):
    row,lang=await get_ctx(cb,db); data=await state.get_data(); qid=await db.create_qa(row['id'],data['question']); await state.clear(); await cb.message.answer(tr(lang,'qa_created')); await cb.answer()
    await notify_permitted_admins(
        bot, db, 'qa.view',
        f"❓ Anonymous Question #{qid}\nInternal User ID: {row['telegram_id']}\n\n{data['question']}",
        InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang,'reply'),callback_data=f'qa_admin:reply:{qid}')],
            [InlineKeyboardButton(text=tr(lang,'qa_published'),callback_data=f'qa_admin:publish:{qid}')]
        ])
    )
@router.callback_query(QAState.confirm,F.data=='qa:cancel')
async def qa_cancel(cb:CallbackQuery,state:FSMContext,db:Database):
    await state.clear()
    row,lang=await get_ctx(cb,db)
    await cb.message.answer(tr(lang,'cancelled'), reply_markup=user_menu(lang))
    await cb.answer()

async def public_qa(message,db,lang,page):
    size=max(1,int(await db.setting('pagination_size','8'))); rows=await db.published(size,page*size)
    if not rows:
        await message.answer(tr(lang,'no_public_qa'),reply_markup=back_home(lang)); return
    txt='\n\n'.join([f"❓ {r['question_text']}\n✅ {r['answer_text']}" for r in rows])
    buttons=pager(lang,'pqa',page,max(1,(await db.published_count()+size-1)//size))
    buttons.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
    await message.answer(txt,reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith('pqa:'))
async def pqa_page_cb(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db); await public_qa(cb.message,db,lang,int(cb.data.split(':')[-1])); await cb.answer()

@router.callback_query(F.data=='menu:language')
async def menu_lang(cb:CallbackQuery,db:Database): row,lang=await get_ctx(cb,db); await cb.message.answer(language_prompt(),reply_markup=LANGS); await cb.answer()

@router.callback_query(F.data=='menu:settings')
async def menu_settings(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    await cb.message.answer(tr(lang,'settings'), reply_markup=settings_menu(lang))
    await cb.answer()

@router.callback_query(F.data=='menu:about')
async def menu_about(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db)
    await cb.message.answer(tr(lang,'about_text'), reply_markup=back_home(lang))
    await cb.answer()

async def random_content(message,db,lang,kind='all'):
    item=await db.random_content(kind)
    if not item:
        await message.answer(tr(lang,'not_found'),reply_markup=back_home(lang)); return
    if item['kind']=='movie':
        m=await db.movie_by_id(int(item['id']))
        if m: await show_movie(message.chat.id,message.from_user.id,db,message.bot,m,lang)
    else:
        s=await db.series_by_id(int(item['id']))
        if s: await show_series(message.chat.id,message.from_user.id,db,message.bot,s,lang)

@router.callback_query(F.data=='random:all')
async def random_all_cb(cb:CallbackQuery,db:Database):
    row,lang=await get_ctx(cb,db); await random_content(cb.message,db,lang,'all'); await cb.answer()

@router.callback_query(F.data.startswith('random:'))
async def random_kind_cb(cb:CallbackQuery,db:Database):
    kind=cb.data.split(':',1)[1]
    if kind=='all': return
    row,lang=await get_ctx(cb,db);
    if kind not in {'movie','series','anime','cartoon'}:
        await cb.answer(tr(lang,'invalid'),show_alert=True); return
    await random_content(cb.message,db,lang,kind); await cb.answer()

async def direct_search(message: Message, db: Database, lang: str, q: str, state: FSMContext|None=None):
    q=q.strip()
    if not q: return False
    # Only treat input as a code when the exact code actually exists. This prevents
    # normal titles such as "Bersek" or "Interstellar" from being misclassified.
    if CODE_RE.fullmatch(q):
        exact = await db.movie_by_code(q) or await db.series_by_code(q) or await db.episode_by_code(q)
        if exact:
            if state: await state.clear()
            await open_by_code(message,db,message.bot,q)
            return True
    row,_=await get_ctx(message,db)
    await db.execute('INSERT INTO search_history(user_id,query,created_at) VALUES(?,?,?)',(row['id'],q,utcnow()))
    if state:
        await state.update_data(search_query=q)
    await render_search_results(message,db,lang,q,0,state)
    return True

@router.message(F.text)
async def text_router(message:Message, state:FSMContext, db:Database,bot:Bot):
    # State-specific handlers are registered before this handler; this is the fallback menu/search route.
    row,lang=await get_ctx(message,db)
    text=message.text.strip()
    mapping={
      tr(lang,'movies'):('list','movie'), tr(lang,'series'):('list','series'), tr(lang,'cartoons'):('list','cartoon'), tr(lang,'anime'):('list','anime'), tr(lang,'other'):('list','other'),
      tr(lang,'popular'):('popular',None), tr(lang,'new'):('new',None), tr(lang,'favorites'):('saved','favorites'), tr(lang,'watch_later'):('saved','watch_later'),
      tr(lang,'history'):('history',None), tr(lang,'continue_watching'):('continue',None), tr(lang,'recommendations'):('recommend',None), tr(lang,'random'):('random',None), tr(lang,'search'):('search',None), tr(lang,'genres'):('genres',None),
      tr(lang,'countries'):('countries',None), tr(lang,'years'):('years',None), tr(lang,'support'):('support',None), tr(lang,'notifications'):('notifications',None), tr(lang,'questions'):('questions',None), tr(lang,'anonymous_qa'):('qa',None),
      tr(lang,'referral'):('ref',None), tr(lang,'profile'):('profile',None), tr(lang,'language'):('language',None), tr(lang,'public_qa'):('pqa',None), tr(lang,'about'):('about',None), tr(lang,'my_cinema'):('my_cinema',None), tr(lang,'discover'):('discover',None), tr(lang,'settings'):('settings',None)
    }
    action,value=mapping.get(text,(None,None))
    if action=='search': await message.answer(tr(lang,'search_prompt')); await state.set_state(SearchState.search); return
    if action=='list': await content_list(message,db,lang,value,0); return
    if action=='popular': await content_rows(message,db,lang,'popular',0); return
    if action=='new': await content_rows(message,db,lang,'new',0); return
    if action=='saved': await saved_list(message,db,lang,value,0); return
    if action=='history': await history_list(message,db,lang,0); return
    if action=='continue':
        rows=await db.continue_watching(int(row['id']),8)
        if not rows:
            await message.answer(tr(lang,'no_continue'),reply_markup=back_home(lang)); return
        kb=[]
        for r in rows:
            if r['kind']=='movie':
                text=tr(lang,'continue_movie',title=r['title'])
                cbdata=f"open:movie:{r['id']}"
            else:
                text=tr(lang,'continue_episode',title=r['title'],season=r['season_number'],episode=r['episode_number'])
                cbdata=f"continue:{r['series_id']}"
            kb.append([InlineKeyboardButton(text=text[:60],callback_data=cbdata)])
        kb.append([InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')])
        await message.answer(tr(lang,'continue_watching'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); return
    if action=='recommend': await recommendation_list(message,db,lang,row['id'],0); return
    if action=='random':
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'movies'),callback_data='random:movie'),InlineKeyboardButton(text=tr(lang,'series'),callback_data='random:series')],[InlineKeyboardButton(text=tr(lang,'anime'),callback_data='random:anime'),InlineKeyboardButton(text=tr(lang,'cartoons'),callback_data='random:cartoon')],[InlineKeyboardButton(text='🎲',callback_data='random:all')],[InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]])
        await message.answer(tr(lang,'random'),reply_markup=kb); return
    if action=='genres': await browse_genres(message,db,lang); return
    if action=='countries': await browse_countries(message,db,lang); return
    if action=='years': await browse_years(message,db,lang); return
    if action=='support': await support_start(message,state,db,lang); return
    if action=='notifications':
        from handlers.discovery import show_notifications
        cb_like=type('MessageProxy',(),{})()
        await message.answer(tr(lang,'notification_settings'),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=('✅ ' if await db.notifications_enabled(int(row['id']),key) else '❌ ') + tr(lang,label),callback_data=f'notify:toggle:{key}')] for key,label in [('new_releases','notify_new_releases'),('new_episodes','notify_new_episodes'),('new_movies','notify_new_movies'),('new_anime','notify_new_anime'),('trending','notify_trending'),('daily_cinema','notify_daily')]] + [[InlineKeyboardButton(text=tr(lang,'home'),callback_data='nav:home')]])); return
    if action=='qa': await qa_start(message,state,db,lang); return
    if action=='questions': await question_center(message,db,lang); return
    if action=='ref': await referral(message,db,lang); return
    if action=='profile': await profile(message,db,lang,row); return
    if action=='language': await message.answer(language_prompt(),reply_markup=LANGS); return
    if action=='settings': await message.answer(tr(lang,'settings'),reply_markup=settings_menu(lang)); return
    if action=='pqa': await public_qa(message,db,lang,0); return
    if action=='about': await message.answer(tr(lang,'about_text')); return
    if action=='my_cinema':
        from handlers.discovery import my_cinema_menu
        await my_cinema_menu(message,db,lang); return
    if action=='discover':
        from handlers.discovery import discovery_menu
        await discovery_menu(message,db,lang); return
    await direct_search(message, db, lang, text, state)
