from __future__ import annotations
import shutil
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from database.db import Database, utcnow
from services.i18n import tr
from services.permissions import has_permission, effective_permissions, ALL_PERMISSIONS, PERMISSION_LABELS
from states.advanced import CollectionCreateState, CollectionItemState, ReleaseAddState
router=Router()

async def ctx(ev,db):
    row=await db.user(ev.from_user.id)
    if not row: row,_=await db.ensure_user(ev.from_user)
    return row,await db.authenticated_admin(ev.from_user.id)

@router.callback_query(F.data=='adv:collections')
async def collections_admin(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    cols=await db.collections(); kb=[[InlineKeyboardButton(text='📚 '+c['title'][:40],callback_data=f"adv:collection:{c['id']}")] for c in cols]
    kb.append([InlineKeyboardButton(text='➕ '+tr(lang,'add_content'),callback_data='adv:collection:add')]); kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:content')])
    await cb.message.edit_text(tr(lang,'collections'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data=='adv:collection:add')
async def collection_add_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await state.clear(); await state.update_data(advanced_action='collection_create'); await state.set_state(CollectionCreateState.title); await cb.message.answer(tr(lang,'collection_title_prompt')); await cb.answer()

@router.message(CollectionCreateState.title)
async def collection_title(message:Message,state:FSMContext,db:Database):
    row,admin=await ctx(message,db); lang=row['language']; title=(message.text or '').strip()
    if not admin or not await has_permission(db,admin,'collections.manage'): await state.clear(); return
    if not title: await message.answer(tr(lang,'enter_text')); return
    await state.update_data(title=title); await state.set_state(CollectionCreateState.description); await message.answer(tr(lang,'collection_description_prompt'))

@router.message(CollectionCreateState.description)
async def collection_description(message:Message,state:FSMContext,db:Database):
    row,admin=await ctx(message,db); lang=row['language']; data=await state.get_data()
    if not admin or not await has_permission(db,admin,'collections.manage'): await state.clear(); return
    desc=(message.text or '').strip(); cid=await db.add_collection(data['title'],None if desc in {'','-'} else desc); await db.log_admin(int(admin['telegram_id']),'create_collection',str(cid),data['title']); await state.clear(); await message.answer(tr(lang,'settings_saved'))

@router.callback_query(F.data.regexp(r'^adv:collection:\d+$'))
async def collection_manage(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; cid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    col=await db.collection(cid)
    if not col: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    items=await db.collection_items(cid); kb=[]
    for i in items:
        kb.append([InlineKeyboardButton(text=f"{i['title'][:34]}",callback_data=f"adv:collection:item:{i['id']}"),InlineKeyboardButton(text='⬆️',callback_data=f"adv:collection:up:{i['id']}"),InlineKeyboardButton(text='⬇️',callback_data=f"adv:collection:down:{i['id']}")])
    kb.append([InlineKeyboardButton(text='➕ '+tr(lang,'add_content'),callback_data=f'adv:collection:additem:{cid}')]); kb.append([InlineKeyboardButton(text='🗑 '+tr(lang,'delete_content'),callback_data=f'adv:collection:delete:{cid}')]); kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adv:collections')])
    await cb.message.edit_text(f"📚 {col['title']}\n\n{col['description'] or ''}",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.startswith('adv:collection:additem:'))
async def collection_additem_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; cid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await state.clear(); await state.update_data(collection_id=cid); await state.set_state(CollectionItemState.code); await cb.message.answer(tr(lang,'collection_code_prompt')); await cb.answer()

@router.message(CollectionItemState.code)
async def collection_additem_save(message:Message,state:FSMContext,db:Database):
    row,admin=await ctx(message,db); lang=row['language']; data=await state.get_data(); kind,item=await db.universal_lookup((message.text or '').strip())
    if not admin or not await has_permission(db,admin,'collections.manage'): await state.clear(); return
    if not item: await message.answer(tr(lang,'not_found')); return
    await db.add_collection_item(int(data['collection_id']),kind,int(item['id'])); await db.log_admin(int(admin['telegram_id']),'add_collection_item',str(data['collection_id']),f'{kind}:{item["id"]}'); await state.clear(); await message.answer(tr(lang,'settings_saved'))

@router.callback_query(F.data.startswith('adv:collection:item:'))
async def collection_item_delete(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; iid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    item=await db.fetchone('SELECT * FROM collection_items WHERE id=?',(iid,));
    if not item: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    await db.remove_collection_item(iid); await db.log_admin(int(admin['telegram_id']),'remove_collection_item',str(iid)); await cb.answer(tr(lang,'removed'),show_alert=True); await collection_manage(CallbackProxy(cb,f"adv:collection:{item['collection_id']}"),db)

class CallbackProxy:
    def __init__(self,cb,data): self.message=cb.message; self.from_user=cb.from_user; self.data=data
    async def answer(self,*args,**kwargs): pass

@router.callback_query(F.data.startswith('adv:collection:up:'))
async def collection_up(cb:CallbackQuery,db:Database):
    iid=int(cb.data.split(':')[-1]); row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    item=await db.fetchone('SELECT collection_id FROM collection_items WHERE id=?',(iid,)); await db.move_collection_item(iid,'up'); await cb.answer();
    if item: await collection_manage(CallbackProxy(cb,f"adv:collection:{item['collection_id']}"),db)

@router.callback_query(F.data.startswith('adv:collection:down:'))
async def collection_down(cb:CallbackQuery,db:Database):
    iid=int(cb.data.split(':')[-1]); row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    item=await db.fetchone('SELECT collection_id FROM collection_items WHERE id=?',(iid,)); await db.move_collection_item(iid,'down'); await cb.answer();
    if item: await collection_manage(CallbackProxy(cb,f"adv:collection:{item['collection_id']}"),db)

@router.callback_query(F.data.startswith('adv:collection:delete:'))
async def collection_delete(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; cid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'collections.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await db.delete_collection(cid); await db.log_admin(int(admin['telegram_id']),'delete_collection',str(cid)); await cb.answer(tr(lang,'content_deleted'),show_alert=True); await collections_admin(cb,db)

@router.callback_query(F.data=='adv:moods')
async def moods_admin(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'moods.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    moods=await db.moods(); kb=[[InlineKeyboardButton(text=f"{m['emoji']} {m['name_uz' if lang=='uz' else 'name_ru' if lang=='ru' else 'name_en']}",callback_data=f'adv:mood:{m["id"]}')] for m in moods]
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:content')]); await cb.message.edit_text(tr(lang,'mood'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.regexp(r'^adv:mood:\d+$'))
async def mood_admin_detail(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; mid=int(cb.data.split(':')[-1]); mood=await db.mood(mid)
    if not admin or not await has_permission(db,admin,'moods.manage') or not mood: await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    gids=set(await db.mood_genre_ids(mid)); genres=await db.genres(); kb=[]
    for g in genres:
        name=g[f'name_{lang}']; kb.append([InlineKeyboardButton(text=('✅ ' if int(g['id']) in gids else '❌ ')+name,callback_data=f'adv:mood:toggle:{mid}:{g["id"]}')])
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adv:moods')]); await cb.message.edit_text(f"{mood['emoji']} {mood[f'name_{lang}']}",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.startswith('adv:mood:toggle:'))
async def mood_toggle(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; _,_,_,mid,gid=cb.data.split(':')
    if not admin or not await has_permission(db,admin,'moods.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    exists=await db.fetchone('SELECT 1 FROM mood_genres WHERE mood_id=? AND genre_id=?',(int(mid),int(gid)))
    if exists: await db.execute('DELETE FROM mood_genres WHERE mood_id=? AND genre_id=?',(int(mid),int(gid)))
    else: await db.execute('INSERT INTO mood_genres(mood_id,genre_id) VALUES(?,?)',(int(mid),int(gid)))
    await db.log_admin(int(admin['telegram_id']),'toggle_mood_genre',f'{mid}:{gid}'); await cb.answer(); await mood_admin_detail(cb,db)

@router.callback_query(F.data=='adv:reports')
async def reports_admin(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'reports.view'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    rs=await db.reports('open'); kb=[[InlineKeyboardButton(text=f'⚠️ #{r["id"]} {r["report_type"][:20]}',callback_data=f'adv:report:{r["id"]}')] for r in rs]; kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:inbox')]); await cb.message.edit_text(tr(lang,'report'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.regexp(r'^adv:report:\d+$'))
async def report_admin(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; rid=int(cb.data.split(':')[-1]); r=await db.report_by_id(rid)
    if not admin or not await has_permission(db,admin,'reports.view') or not r: await cb.answer(tr(lang,'not_found'),show_alert=True); return
    txt=(f"⚠️ #{rid}\n{tr(lang,'report_type',value=r['report_type'])}\n{tr(lang,'report_content',value=f'{r['content_kind']} #{r['content_id']}')}\n{tr(lang,'report_user',value=r['telegram_id'])}\n\n{r['message'] or '—'}"); kb=[]
    if await has_permission(db,admin,'reports.resolve'): kb += [[InlineKeyboardButton(text='🟢 '+tr(lang,'resolve'),callback_data=f'adv:report:resolve:{rid}')],[InlineKeyboardButton(text='🔴 '+tr(lang,'reject'),callback_data=f'adv:report:reject:{rid}')]]
    kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adv:reports')]); await cb.message.edit_text(txt,reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data.startswith('adv:report:resolve:'))
async def report_resolve(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; rid=int(cb.data.split(':')[-1]);
    if not admin or not await has_permission(db,admin,'reports.resolve'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await db.resolve_report(rid,int(admin['telegram_id']),'resolved'); await db.log_admin(int(admin['telegram_id']),'resolve_report',str(rid)); await cb.answer(tr(lang,'resolved'),show_alert=True); await reports_admin(cb,db)

@router.callback_query(F.data.startswith('adv:report:reject:'))
async def report_reject(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; rid=int(cb.data.split(':')[-1]);
    if not admin or not await has_permission(db,admin,'reports.resolve'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await db.resolve_report(rid,int(admin['telegram_id']),'rejected'); await db.log_admin(int(admin['telegram_id']),'reject_report',str(rid)); await cb.answer(tr(lang,'rejected'),show_alert=True); await reports_admin(cb,db)

@router.callback_query(F.data=='adv:health')
async def health_admin(cb:CallbackQuery,db:Database,bot:Bot):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'health.view'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    db_ok=api_ok=False; notes=[]
    try: await db.fetchone('SELECT 1'); db_ok=True
    except Exception as exc: notes.append('DB:'+type(exc).__name__)
    try: await bot.get_me(); api_ok=True
    except Exception as exc: notes.append('API:'+type(exc).__name__)
    await cb.message.edit_text(tr(lang,'health_database',status='OK' if db_ok else 'ERROR')+'\n'+tr(lang,'health_telegram',status='OK' if api_ok else 'ERROR')+'\n'+tr(lang,'health_configuration',status='OK')+(('\n'+tr(lang,'health_note',note='\n'.join(notes))) if notes else ''),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:dashboard')]])); await cb.answer()

@router.callback_query(F.data=='adv:backup')
async def backup_admin(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'backup.create'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    backup_dir=db.path.parent/'backups'; backup_dir.mkdir(exist_ok=True); dest=backup_dir/f"movies_{utcnow().replace(':','-').replace('.','-')}.db"; shutil.copy2(db.path,dest); await db.log_admin(int(admin['telegram_id']),'database_backup',dest.name); await cb.message.answer(tr(lang,'backup_created',name=dest.name),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:dashboard')]])); await cb.answer()

@router.callback_query(F.data=='adv:releases')
async def releases_admin(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'release.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    rows=await db.release_items(30,0); kb=[[InlineKeyboardButton(text=f"📅 {str(r['release_at']).replace('T',' ')[:16]} · {(r['title'] or r['content_kind'])[:30]}",callback_data=f"adv:release:delete:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton(text='➕ '+tr(lang,'add_release'),callback_data='adv:release:add')]); kb.append([InlineKeyboardButton(text=tr(lang,'back'),callback_data='adm:content')]); await cb.message.edit_text(tr(lang,'releases_title'),reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await cb.answer()

@router.callback_query(F.data=='adv:release:add')
async def release_add_start(cb:CallbackQuery,state:FSMContext,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']
    if not admin or not await has_permission(db,admin,'release.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await state.clear(); await state.set_state(ReleaseAddState.code); await cb.message.answer(tr(lang,'release_code_prompt')); await cb.answer()

@router.message(ReleaseAddState.code)
async def release_code(message:Message,state:FSMContext,db:Database):
    row,admin=await ctx(message,db); lang=row['language']; kind,item=await db.universal_lookup((message.text or '').strip())
    if not admin or not await has_permission(db,admin,'release.manage'): await state.clear(); return
    if not item: await message.answer(tr(lang,'not_found')); return
    await state.update_data(kind=kind,cid=int(item['id'])); await state.set_state(ReleaseAddState.release_at); await message.answer(tr(lang,'release_time_prompt'))

@router.message(ReleaseAddState.release_at)
async def release_time(message:Message,state:FSMContext,db:Database):
    row,admin=await ctx(message,db); lang=row['language']; raw=(message.text or '').strip()
    try: datetime.fromisoformat(raw)
    except ValueError: await message.answer(tr(lang,'invalid')); return
    await state.update_data(release_at=raw); await state.set_state(ReleaseAddState.title); await message.answer(tr(lang,'release_title_prompt'))

@router.message(ReleaseAddState.title)
async def release_title(message:Message,state:FSMContext,db:Database):
    row,admin=await ctx(message,db); lang=row['language']; data=await state.get_data(); title=None if (message.text or '').strip()=='-' else (message.text or '').strip()
    await db.add_release(data['kind'],data['cid'],data['release_at'],title=title); await db.log_admin(int(admin['telegram_id']),'add_release',str(data['cid']),data['release_at']); await state.clear(); await message.answer(tr(lang,'settings_saved'))

@router.callback_query(F.data.startswith('adv:release:delete:'))
async def release_delete(cb:CallbackQuery,db:Database):
    row,admin=await ctx(cb,db); lang=row['language']; rid=int(cb.data.split(':')[-1])
    if not admin or not await has_permission(db,admin,'release.manage'): await cb.answer(tr(lang,'unauthorized'),show_alert=True); return
    await db.deactivate_release(rid); await db.log_admin(int(admin['telegram_id']),'delete_release',str(rid)); await cb.answer(tr(lang,'removed'),show_alert=True); await releases_admin(cb,db)
