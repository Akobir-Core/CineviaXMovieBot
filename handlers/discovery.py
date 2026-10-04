from __future__ import annotations
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from services.i18n import tr
from services.recommendations import recommend
from database.db import Database
from keyboards.common import pager, back_home
from states.advanced import DiscoverFilterState
from states.user import CompareState, ReportState

router=Router()

async def discovery_menu(message:Message,db:Database,lang:str):
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang,'mood'),callback_data='discover:moods:0'),InlineKeyboardButton(text=tr(lang,'tonight_pick'),callback_data='discover:tonight')],
        [InlineKeyboardButton(text=tr(lang,'trending_radar'),callback_data='discover:trending:7:0'),InlineKeyboardButton(text=tr(lang,'collections'),callback_data='discover:collections:0')],
        [InlineKeyboardButton(text=tr(lang,'releases'),callback_data='discover:releases:0'),InlineKeyboardButton(text=tr(lang,'daily_cinema'),callback_data='discover:daily')],
        [InlineKeyboardButton(text=tr(lang,'filters'),callback_data='discover:filters')],
        [InlineKeyboardButton(text=tr(lang,'back'),callback_data='nav:home')]
    ])
    await message.answer(tr(lang,'discover'),reply_markup=kb)

async def my_cinema_menu(message:Message,db:Database,lang:str):
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang,'favorites'),callback_data='mycin:favorites'),InlineKeyboardButton(text=tr(lang,'watch_later'),callback_data='mycin:later')],
        [InlineKeyboardButton(text=tr(lang,'continue_watching'),callback_data='mycin:continue'),InlineKeyboardButton(text=tr(lang,'history'),callback_data='mycin:history')],
        [InlineKeyboardButton(text=tr(lang,'recommendations'),callback_data='mycin:recommend'),InlineKeyboardButton(text=tr(lang,'random'),callback_data='random:all')],
        [InlineKeyboardButton(text=tr(lang,'passport'),callback_data='mycin:passport'),InlineKeyboardButton(text=tr(lang,'activity'),callback_data='mycin:activity')],
        [InlineKeyboardButton(text=tr(lang,'notifications'),callback_data='mycin:notifications'),InlineKeyboardButton(text=tr(lang,'followed_series'),callback_data='mycin:followed')],
        [InlineKeyboardButton(text=tr(lang,'search_history'),callback_data='mycin:search_history')],
        [InlineKeyboardButton(text=tr(lang,'back'),callback_data='nav:home')]
    ])
    await message.answer(tr(lang,'my_cinema'),reply_markup=kb)


def result_buttons(lang, rows, back='nav:home'):
    kb=[]
    for r in rows:
        kind=str(r['kind']); kb.append([InlineKeyboardButton(text=f"{r['title'][:38]} · {r['code']}",callback_data=f'open:{kind}:{r["id"]}')])
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data=back)])
    return kb

@router.callback_query(F.data=='discover:menu')
async def discover_menu_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); await discovery_menu(cb.message,db,row['language']); await cb.answer()

@router.callback_query(F.data.startswith('discover:moods:'))
async def moods_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; page=int(cb.data.split(':')[-1]); size=max(4,int(await db.setting('pagination_size','8'))); moods=await db.moods(); total=max(1,(len(moods)+size-1)//size); page=max(0,min(page,total-1)); chunk=moods[page*size:(page+1)*size]
    kb=[[InlineKeyboardButton(text=f"{m['emoji']} {m['name_uz' if lang=='uz' else 'name_ru' if lang=='ru' else 'name_en']}",callback_data=f"discover:mood:{m['id']}:0")] for m in chunk]
    kb+=pager(lang,'discover:moods',page,total); kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='discover:menu')]); await cb.message.answer(tr(lang,'moods_title'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.startswith('discover:mood:'))
async def mood_content_cb(cb:CallbackQuery,db:Database):
    _,_,mid,page=cb.data.split(':'); row=await db.user(cb.from_user.id); lang=row['language']; mid=int(mid); page=int(page); size=max(4,int(await db.setting('pagination_size','8'))); rows=await db.mood_content(mid,size,page*size); mood=await db.mood(mid)
    if not mood or not rows: await cb.message.answer(tr(lang,'mood_empty'),reply_markup=back_home(lang)); await cb.answer(); return
    title=mood['name_uz'] if lang=='uz' else mood['name_ru'] if lang=='ru' else mood['name_en']
    total_count=int((await db.fetchone("SELECT COUNT(*) c FROM (SELECT id FROM movies WHERE active=1 AND visibility='public' AND genre_id IN (SELECT genre_id FROM mood_genres WHERE mood_id=? ) UNION ALL SELECT id FROM series WHERE active=1 AND visibility='public' AND genre_id IN (SELECT genre_id FROM mood_genres WHERE mood_id=?))",(mid,mid)))['c'] or 0)
    total=max(1,(total_count+size-1)//size); nav=pager(lang,f'discover:mood:{mid}',page,total)
    kb=result_buttons(lang,rows,'discover:moods:0')
    kb.extend(nav)
    await cb.message.answer(f"{mood['emoji']} {title}",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data=='discover:tonight')
async def tonight_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; pick=await db.tonight_pick(int(row['id']))
    if not pick: await cb.message.answer(tr(lang,'not_found'),reply_markup=back_home(lang)); await cb.answer(); return
    await cb.message.answer(f"{tr(lang,'today_pick')}\n\n🎬 {pick['title']}\n🔐 {pick['code']}",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'watch'),callback_data=f"open:{pick['kind']}:{pick['id']}")],[InlineKeyboardButton(text=tr(lang,'back'),callback_data='discover:menu')]])); await cb.answer()

@router.callback_query(F.data.startswith('discover:trending:'))
async def trending_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; _,_,days,page=cb.data.split(':'); days=int(days); page=int(page); size=max(4,int(await db.setting('pagination_size','8'))); rows=await db.trending(days,size,page*size)
    if not rows: await cb.message.answer(tr(lang,'not_found'),reply_markup=back_home(lang)); await cb.answer(); return
    kb=result_buttons(lang,rows,'discover:menu'); period_buttons=[[InlineKeyboardButton(text='24h',callback_data='discover:trending:1:0'),InlineKeyboardButton(text='7d',callback_data='discover:trending:7:0'),InlineKeyboardButton(text='30d',callback_data='discover:trending:30:0'),InlineKeyboardButton(text=tr(lang,'all_time'),callback_data='discover:trending:0:0')]]
    period_buttons.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='discover:menu')]); await cb.message.answer(f"{tr(lang,'trending_title')} · {days}d",reply_markup=InlineKeyboardMarkup(inline_keyboard=period_buttons+kb)); await cb.answer()

@router.callback_query(F.data.startswith('discover:collections:'))
async def collections_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; page=int(cb.data.split(':')[-1]); size=max(4,int(await db.setting('pagination_size','8'))); total=max(1,(await db.collection_count()+size-1)//size); cols=await db.collections(size,page*size)
    if not cols: await cb.message.answer(tr(lang,'no_collections'),reply_markup=back_home(lang)); await cb.answer(); return
    kb=[[InlineKeyboardButton(text=f"📚 {c['title'][:40]}",callback_data=f"discover:collection:{c['id']}:0")] for c in cols]; kb+=pager(lang,'discover:collections',page,total); kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='discover:menu')]); await cb.message.answer(tr(lang,'collections'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.startswith('discover:collection:'))
async def collection_cb(cb:CallbackQuery,db:Database):
    _,_,cid,page=cb.data.split(':'); row=await db.user(cb.from_user.id); lang=row['language']; cid=int(cid); page=int(page); size=max(4,int(await db.setting('pagination_size','8'))); items=await db.collection_items(cid,size,page*size); col=await db.collection(cid)
    if not col or not items: await cb.message.answer(tr(lang,'collection_empty'),reply_markup=back_home(lang)); await cb.answer(); return
    kb=[]
    for i in items:
        item=await db.content_by_kind_id(i['content_kind'],int(i['content_id']),public_only=True)
        if item: kb.append([InlineKeyboardButton(text=f"{i['title'][:38]} · {i['code']}",callback_data=f"open:{i['content_kind']}:{i['content_id']}")])
    kb += pager(lang,f'discover:collection:{cid}',page,max(1,((await db.fetchone("SELECT COUNT(*) c FROM collection_items WHERE collection_id=?",(cid,)))['c']+size-1)//size))
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='discover:collections:0')]); await cb.message.answer(f"{tr(lang,'collection_title')}: {col['title']}\n\n{col['description'] or ''}",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.startswith('discover:releases:'))
async def releases_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; page=int(cb.data.split(':')[-1]); size=max(4,int(await db.setting('pagination_size','8'))); rows=await db.release_items(size,page*size)
    if not rows: await cb.message.answer(tr(lang,'no_releases'),reply_markup=back_home(lang)); await cb.answer(); return
    kb=[]
    for r in rows:
        title=r['title'] or r['content_kind']; when=str(r['release_at']).replace('T',' ')[:16]; kb.append([InlineKeyboardButton(text=f"📅 {when} · {title[:30]}",callback_data=f"open:{r['content_kind']}:{r['content_id']}")])
    total_count=int((await db.fetchone("SELECT COUNT(*) c FROM release_calendar WHERE active=1 AND datetime(release_at)>=datetime('now')"))['c'] or 0); total=max(1,(total_count+size-1)//size)
    kb += pager(lang,'discover:releases',page,total)
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='discover:menu')]); await cb.message.answer(tr(lang,'releases_title'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data=='discover:daily')
async def daily_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; pick=await db.daily_pick(int(row['id']))
    if not pick: await cb.message.answer(tr(lang,'not_found'),reply_markup=back_home(lang)); await cb.answer(); return
    item=await db.content_by_kind_id(pick['content_kind'],int(pick['content_id']))
    if not item: await cb.message.answer(tr(lang,'not_found'),reply_markup=back_home(lang)); await cb.answer(); return
    await cb.message.answer(f"{tr(lang,'daily_pick')}\n\n🎬 {item['title']}\n🔐 {item['code']}",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'watch'),callback_data=f"open:{pick['content_kind']}:{pick['content_id']}")],[InlineKeyboardButton(text=tr(lang,'back'),callback_data='discover:menu')]])); await cb.answer()

# --- Filters ---
@router.callback_query(F.data=='discover:filters')
async def filters_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language'];
    kb=[[InlineKeyboardButton(text=tr(lang,'movies'),callback_data='filter:type:movie'),InlineKeyboardButton(text=tr(lang,'series'),callback_data='filter:type:series')],[InlineKeyboardButton(text=tr(lang,'anime'),callback_data='filter:type:anime'),InlineKeyboardButton(text=tr(lang,'cartoons'),callback_data='filter:type:cartoon')],[InlineKeyboardButton(text=tr(lang,'all'),callback_data='filter:type:all')]]
    await state.clear(); await state.set_state(DiscoverFilterState.type); await cb.message.answer(tr(lang,'filters_choose_type'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(DiscoverFilterState.type,F.data.startswith('filter:type:'))
async def filter_type(cb:CallbackQuery,state:FSMContext,db:Database):
    kind=cb.data.split(':')[-1]; row=await db.user(cb.from_user.id); lang=row['language']; await state.update_data(kind=kind); genres=await db.genres(); kb=[[InlineKeyboardButton(text=tr(lang,'skip'),callback_data='filter:genre:0')]]+[[InlineKeyboardButton(text=g[f'name_{lang}'],callback_data=f"filter:genre:{g['id']}")] for g in genres]; await state.set_state(DiscoverFilterState.genre); await cb.message.answer(tr(lang,'filters_choose_genre'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(DiscoverFilterState.genre,F.data.startswith('filter:genre:'))
async def filter_genre(cb:CallbackQuery,state:FSMContext,db:Database):
    gid=int(cb.data.split(':')[-1]); row=await db.user(cb.from_user.id); lang=row['language']; await state.update_data(genre_id=gid or None); await state.set_state(DiscoverFilterState.year); await cb.message.answer(tr(lang,'filters_choose_year'),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'skip'),callback_data='filter:year:0')]])); await cb.answer()

@router.callback_query(DiscoverFilterState.year,F.data.startswith('filter:year:'))
async def filter_year(cb:CallbackQuery,state:FSMContext,db:Database):
    year=int(cb.data.split(':')[-1]); row=await db.user(cb.from_user.id); lang=row['language']; await state.update_data(year=year or None); await state.set_state(DiscoverFilterState.rating); await cb.message.answer(tr(lang,'filters_rating_prompt')); await cb.answer()

@router.message(DiscoverFilterState.rating)
async def filter_rating(message:Message,state:FSMContext,db:Database):
    row=await db.user(message.from_user.id); lang=row['language']; raw=(message.text or '').strip(); rating=None if raw in {'','-','skip'} else raw
    if rating is not None:
        try: rating=float(rating)
        except ValueError: await message.answer(tr(lang,'invalid_rating')); return
        if not 0<=rating<=10: await message.answer(tr(lang,'invalid_rating')); return
    data=await state.get_data(); data['rating']=rating; await state.clear(); size=max(8,int(await db.setting('pagination_size','8')))
    kind=data.get('kind','all'); genre_id=data.get('genre_id'); year=data.get('year')
    clauses=['active=1','visibility=\'public\'']; params=[]
    def build(table,ckind):
        c=clauses.copy(); p=[]
        if kind not in {'all',ckind}: c.append('1=0')
        if genre_id: c.append('genre_id=?'); p.append(genre_id)
        if year: c.append('release_year=?'); p.append(year)
        if rating is not None: c.append('rating>=?'); p.append(rating)
        return c,p
    # Build a compact cross-category query.
    selects=[]; allparams=[]
    for table,ckind in [('movies','movie'),('series','series')]:
        # anime/cartoon can live in either storage.
        c,p=build(table,ckind); prefix=f"{table[0]}"; selects.append(f"SELECT id,title,code,content_type,release_year,views_count,'{ckind}' kind,created_at FROM {table} WHERE {' AND '.join(c)}"); allparams+=p
    # Add content_type constraints for special categories.
    sql=f"SELECT * FROM ({selects[0]} UNION ALL {selects[1]}) q ORDER BY rating DESC,views_count DESC,created_at DESC LIMIT ?";
    # rating is not in projection; avoid invalid ORDER BY -> use views/created only.
    sql=f"SELECT * FROM ({selects[0]} UNION ALL {selects[1]}) q ORDER BY views_count DESC,created_at DESC LIMIT ?"; allparams.append(size)
    rows=await db.fetchall(sql,tuple(allparams))
    if not rows: await message.answer(tr(lang,'filter_empty'),reply_markup=back_home(lang)); return
    kb=result_buttons(lang,rows); await message.answer(tr(lang,'filters_results'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith('mycin:'))
async def mycin_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; action=cb.data.split(':',1)[1]
    from handlers.user import saved_list, history_list, recommendation_list
    if action=='passport': await show_passport(cb,db,lang)
    elif action=='activity': await show_activity(cb,db,lang)
    elif action=='notifications': await show_notifications(cb,db,lang)
    elif action in {'favorites','later'}: await saved_list(cb.message,db,lang,'favorites' if action=='favorites' else 'watch_later',0)
    elif action=='history': await history_list(cb.message,db,lang,0)
    elif action=='recommend': await recommendation_list(cb.message,db,lang,row['id'],0)
    elif action=='followed':
        rows=await db.fetchall("SELECT s.id,s.title,s.code,s.content_type FROM follows f JOIN series s ON s.id=f.series_id WHERE f.user_id=? AND s.active=1 ORDER BY s.title",(row['id'],))
        if not rows: await cb.message.answer(tr(lang,'no_followed'),reply_markup=back_home(lang))
        else: await cb.message.answer(tr(lang,'followed_series'),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"📺 {r['title'][:45]}",callback_data=f"open:series:{r['id']}")] for r in rows]+[[InlineKeyboardButton(text=tr(lang,'back'),callback_data='nav:home')]]))
    elif action=='search_history':
        rows=await db.search_history(int(row['id']),20); kb=[[InlineKeyboardButton(text=str(r['query'])[:45],callback_data=f"search_repeat:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton(text=tr(lang,'clear_history'),callback_data='mycin:clear_search')]); kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='nav:home')]); await cb.message.answer(tr(lang,'search_history'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    elif action=='clear_search': await db.clear_search_history(int(row['id'])); await cb.answer(tr(lang,'cleared'),show_alert=True)
    elif action=='continue':
        rows=await db.continue_watching(int(row['id']),8); kb=[]
        for r in rows:
            cbdata=f"open:movie:{r['id']}" if r['kind']=='movie' else f"open:episode:{r['episode_id']}"
            label=tr(lang,'continue_movie',title=r['title']) if r['kind']=='movie' else tr(lang,'continue_episode',title=r['title'],season=r['season_number'],episode=r['episode_number'])
            kb.append([InlineKeyboardButton(text=label[:55],callback_data=cbdata)])
        if not kb: await cb.message.answer(tr(lang,'no_continue'),reply_markup=back_home(lang))
        else: kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='nav:home')]); await cb.message.answer(tr(lang,'continue_watching'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await cb.answer()

async def show_passport(cb:CallbackQuery,db:Database,lang:str):
    p=await db.cinema_passport(cb.from_user.id)
    if not p: await cb.message.answer(tr(lang,'not_found'),reply_markup=back_home(lang)); return
    level=tr(lang,'passport_level_'+p['level_key'])
    txt=(f"{tr(lang,'passport_stats')}\n\n👤 {p['user']['first_name']}\n\n"
      f"{tr(lang,'watched_movies')}: {p['movies']}\n{tr(lang,'watched_series')}: {p['series']}\n{tr(lang,'watched_anime')}: {p['anime']}\n{tr(lang,'watched_cartoons')}: {p['cartoons']}\n"
      f"{tr(lang,'watched_episodes')}: {p['episodes']}\n⭐ {tr(lang,'favorites')}: {p['favorites']}\n📚 {tr(lang,'watch_later')}: {p['watch_later']}\n"
      f"{tr(lang,'passport_level')}: {level}\n{tr(lang,'favorite_genre')}: {p['favorite_genre'] or '—'}\n{tr(lang,'top_country')}: {p['country'] or '—'}\n{tr(lang,'member_since')}: {str(p['user']['created_at'])[:10]}")
    await cb.message.answer(txt,reply_markup=back_home(lang))

async def show_activity(cb:CallbackQuery,db:Database,lang:str):
    row=await db.user(cb.from_user.id); rows=await db.activity(int(row['id']),25)
    if not rows: await cb.message.answer(tr(lang,'activity_empty'),reply_markup=back_home(lang)); return
    await cb.message.answer(tr(lang,'activity_title')+'\n\n'+'\n'.join(f"• {r['action']} · {str(r['created_at']).replace('T',' ')[:16]}" for r in rows),reply_markup=back_home(lang))

async def show_notifications(cb:CallbackQuery,db:Database,lang:str):
    row=await db.user(cb.from_user.id); prefs=await db.notification_preferences(int(row['id']))
    keys=[('new_releases','notify_new_releases'),('new_episodes','notify_new_episodes'),('new_movies','notify_new_movies'),('new_anime','notify_new_anime'),('trending','notify_trending'),('daily_cinema','notify_daily')]
    kb=[[InlineKeyboardButton(text=('✅ ' if prefs[k] else '❌ ')+tr(lang,label),callback_data=f'notify:toggle:{k}')] for k,label in keys]
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='nav:home')]); await cb.message.answer(tr(lang,'notification_settings'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data.startswith('notify:toggle:'))
async def notify_toggle(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; key=cb.data.split(':')[-1]
    if key not in await db.notification_categories(): await cb.answer(tr(lang,'invalid'),show_alert=True); return
    cur=await db.notifications_enabled(int(row['id']),key); await db.set_notification(int(row['id']),key,not cur); await cb.answer(tr(lang,'enabled' if not cur else 'disabled')); await show_notifications(cb,db,lang)

@router.callback_query(F.data.startswith('follow:'))
async def follow_cb(cb:CallbackQuery,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; sid=int(cb.data.split(':')[-1]); s=await db.series_by_id(sid)
    if not s: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    enabled=await db.toggle_follow(int(row['id']),sid); await db.log_activity(int(row['id']),'follow' if enabled else 'unfollow','series',sid); await cb.answer(tr(lang,'follow_saved') if enabled else tr(lang,'unfollow_saved'),show_alert=True)

@router.callback_query(F.data.startswith('compare:start:'))
async def compare_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; _,_,kind,cid=cb.data.split(':'); await state.update_data(first_kind=kind,first_id=int(cid)); await state.set_state(CompareState.second_code); await cb.message.answer(tr(lang,'compare_prompt')); await cb.answer()

@router.message(CompareState.second_code)
async def compare_second(message:Message,state:FSMContext,db:Database):
    row=await db.user(message.from_user.id); lang=row['language']; data=await state.get_data(); code=(message.text or '').strip(); k2,item2=await db.universal_lookup(code)
    if not item2: await message.answer(tr(lang,'not_found')); return
    k1=str(data['first_kind']); item1=await db.content_by_kind_id(k1,int(data['first_id']))
    if not item1: await state.clear(); await message.answer(tr(lang,'not_found')); return
    def val(item,key,default='—'): return item[key] if key in item.keys() and item[key] not in (None,'') else default
    txt=(f"{tr(lang,'comparison')}\n\n🎬 {val(item1,'title')}  vs  🎬 {val(item2,'title')}\n\n"
         f"📅 {val(item1,'release_year')} | {val(item2,'release_year')}\n⭐ {val(item1,'rating')} | {val(item2,'rating')}\n"
         f"🌍 {val(item1,'country_'+lang)} | {val(item2,'country_'+lang)}\n🔊 {val(item1,'language')} | {val(item2,'language')}\n👁 {val(item1,'views_count')} | {val(item2,'views_count')}")
    await state.clear(); await message.answer(txt,reply_markup=back_home(lang))

@router.callback_query(F.data.startswith('report:'))
async def report_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; _,kind,cid=cb.data.split(':'); await state.update_data(content_kind=kind,content_id=int(cid)); opts=[('🎥','broken_video'),('📝','wrong_info'),('🎞','missing_episode'),('🌐','translation_error'),('💬','other')]; kb=[[InlineKeyboardButton(text=emoji+' '+key.replace('_',' '),callback_data=f'reporttype:{key}')] for emoji,key in opts]; await state.set_state(ReportState.report_type); await cb.message.answer(tr(lang,'report_problem'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(ReportState.report_type,F.data.startswith('reporttype:'))
async def report_type(cb:CallbackQuery,state:FSMContext,db:Database):
    row=await db.user(cb.from_user.id); lang=row['language']; await state.update_data(report_type=cb.data.split(':',1)[1]); await state.set_state(ReportState.message); await cb.message.answer(tr(lang,'report_prompt')); await cb.answer()

@router.message(ReportState.message)
async def report_save(message:Message,state:FSMContext,db:Database):
    row=await db.user(message.from_user.id); lang=row['language']; data=await state.get_data(); text=(message.text or '').strip()[:2000]; rid=await db.report(int(row['id']),data['content_kind'],int(data['content_id']),data['report_type'],text or None); await db.log_activity(int(row['id']),'report',data['content_kind'],int(data['content_id']),data['report_type']); await state.clear(); await message.answer(tr(lang,'report_sent'),reply_markup=back_home(lang))
