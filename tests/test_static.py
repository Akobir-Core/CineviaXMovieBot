from __future__ import annotations

import ast
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_syntax():
    for p in ROOT.rglob('*.py'):
        if '.venv' in p.parts or '__pycache__' in p.parts:
            continue
        ast.parse(p.read_text(encoding='utf-8'))


def test_locales_have_same_keys():
    maps = [json.loads((ROOT/'locales'/f'{x}.json').read_text(encoding='utf-8')) for x in ('uz','ru','en')]
    assert set(maps[0]) == set(maps[1]) == set(maps[2])


def test_schema_builds():
    src = (ROOT/'database'/'db.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    schema = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in node.targets):
            schema = ast.literal_eval(node.value)
            break
    assert schema
    con = sqlite3.connect(':memory:')
    con.executescript(schema)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    required = {'users','movies','series','seasons','episodes','genres','countries','favorites','watch_later','watch_history','channels','referrals','support_tickets','ticket_messages','anonymous_questions','anonymous_answers','anonymous_messages','published_qa','admins','admin_sessions','broadcasts','broadcast_targets','bot_settings','admin_logs','search_history','notifications','user_blocks'}
    assert required <= tables
    role_sql = con.execute("select sql from sqlite_master where name='admins'").fetchone()[0]
    assert all(role in role_sql for role in ("'ceo'", "'senior_admin'", "'admin'"))
    admin_cols = {r[1] for r in con.execute('pragma table_info(admins)')}
    assert {'password_hash','failed_attempts','locked_until','password_updated_at'} <= admin_cols
    session_cols = {r[1] for r in con.execute('pragma table_info(admin_sessions)')}
    assert {'telegram_id','authenticated_until','created_at','last_seen_at'} <= session_cols
    msg_cols = {r[1] for r in con.execute('pragma table_info(anonymous_messages)')}
    assert {'question_id','sender_type','sender_id','message','created_at'} <= msg_cols
    con.close()


def test_password_hashing_and_validation():
    import importlib.util
    spec = importlib.util.spec_from_file_location('admin_auth', ROOT/'services'/'admin_auth.py')
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    ok, reason = mod.validate_password('StrongPass123!')
    assert ok and not reason
    encoded = mod.hash_password('StrongPass123!')
    assert encoded.startswith('pbkdf2_sha256$')
    assert mod.verify_password('StrongPass123!', encoded)
    assert not mod.verify_password('WrongPassword!', encoded)
    assert mod.validate_password('1234567')[0] is False
    assert mod.validate_password('x' * 129)[0] is False


def test_local_callback_coverage():
    kb = ''.join(p.read_text(encoding='utf-8') for p in [ROOT/'keyboards'/'admin.py', ROOT/'keyboards'/'common.py'])
    handlers = ''.join(p.read_text(encoding='utf-8') for p in [ROOT/'handlers'/'admin.py', ROOT/'handlers'/'user.py', ROOT/'handlers'/'common.py', ROOT/'handlers'/'discovery.py', ROOT/'handlers'/'admin_advanced.py'])
    dynamic_prefixes = set()
    for m in re.finditer(r'callback_data=f?["\']([^"\']+)', kb):
        v=m.group(1)
        prefix=v.split(':')[0]
        if '{' not in v and prefix not in {'noop'}:
            dynamic_prefixes.add(prefix)
    handler_prefixes = set()
    for m in re.finditer(r"F\.data\.(?:startswith|regexp)\(\s*['\"]([^'\"]+)['\"]", handlers):
        handler_prefixes.add(m.group(1).rstrip(':').split(':')[0])
    for literal in re.findall(r"F\.data\s*==\s*['\"]([^'\"]+)['\"]", handlers):
        handler_prefixes.add(literal.split(':')[0])
    missing = sorted(p for p in dynamic_prefixes if p not in handler_prefixes)
    assert not missing, f'Missing callback handler prefixes: {missing}'


def test_env_example_safe():
    p = ROOT/'.env.example'
    text = p.read_text(encoding='utf-8')
    assert 'YOUR_BOT_TOKEN' in text
    assert not re.search(r'BOT_TOKEN=[0-9]{6,}:', text)


def test_admin_role_map_and_hidden_commands():
    admin_src = (ROOT/'handlers'/'admin.py').read_text(encoding='utf-8')
    kb_src = (ROOT/'keyboards'/'admin.py').read_text(encoding='utf-8')
    cmd_src = (ROOT/'utils'/'commands.py').read_text(encoding='utf-8')
    assert "ceo" in admin_src and "senior_admin" in admin_src and "admin" in admin_src
    assert "movie_admin" not in kb_src
    assert "set_admin_commands(bot, int(admin['telegram_id']))" in admin_src or 'set_admin_commands' in admin_src
    assert 'USER_COMMANDS' in cmd_src and 'ADMIN_COMMANDS' in cmd_src
    assert 'password' in admin_src and 'authenticated_admin' in admin_src


def test_questions_hub_and_two_way_threads_present():
    user_src = (ROOT/'handlers'/'user.py').read_text(encoding='utf-8')
    admin_src = (ROOT/'handlers'/'admin.py').read_text(encoding='utf-8')
    db_src = (ROOT/'database'/'db.py').read_text(encoding='utf-8')
    common_kb = (ROOT/'keyboards'/'common.py').read_text(encoding='utf-8')
    assert 'question_center' in user_src
    assert 'questions_mine' in user_src
    assert 'user_ticket_reply' in user_src and 'user_qa_reply' in user_src
    assert 'ticket_messages' in admin_src and 'anonymous_messages' in admin_src
    assert 'append_ticket_message' in db_src and 'append_qa_user_message' in db_src
    assert "tr(lang, 'questions')" in common_kb or 'questions' in common_kb


def test_multiepisode_architecture():
    db_src=(ROOT/'database'/'db.py').read_text(encoding='utf-8')
    user_src=(ROOT/'handlers'/'user.py').read_text(encoding='utf-8')
    admin_src=(ROOT/'handlers'/'admin.py').read_text(encoding='utf-8')
    kb_src=(ROOT/'keyboards'/'admin.py').read_text(encoding='utf-8')
    assert "content_type TEXT NOT NULL DEFAULT 'series'" in db_src
    assert 'watch_progress' in db_src
    assert 'adjacent_episodes' in db_src
    assert 'continue_watching' in db_src
    assert 'series:episodes:' in user_src
    assert 'next_episode' in user_src and 'previous_episode' in user_src
    assert 'EpisodeEditState' in admin_src and 'EpisodeDeleteState' in admin_src
    assert 'add_anime' in admin_src
    assert 'add_cartoon_series' in admin_src
    assert "'cartoon'" in db_src
    assert 'edit_episode' in admin_src and 'delete_episode' in admin_src


def test_series_anime_sql_behaviour():
    src = (ROOT / 'database' / 'db.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    schema = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets))
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript(schema)
    con.execute("INSERT INTO users(telegram_id,first_name,language,referral_code,created_at,last_seen_at) VALUES(?,?,?,?,?,?)", (1001,'Test','uz','REF1001','now','now'))
    con.execute("INSERT INTO series(code,title,content_type,created_at,updated_at) VALUES(?,?,?,?,?)", ('A100','Demo Anime','anime','now','now'))
    sid = con.execute("SELECT id FROM series WHERE code='A100'").fetchone()[0]
    con.execute("INSERT INTO seasons(series_id,season_number,title) VALUES(?,?,?)", (sid,1,'Season 1'))
    seid=con.execute("SELECT id FROM seasons WHERE series_id=?",(sid,)).fetchone()[0]
    for n in range(1,4):
        con.execute("INSERT INTO episodes(season_id,code,episode_number,title,media_file_id,media_type,created_at) VALUES(?,?,?,?,?,?,?)", (seid,f'A100E{n}',n,f'E{n}',f'file{n}','video','now'))
    assert con.execute("SELECT COUNT(*) FROM series WHERE content_type='anime'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM episodes WHERE season_id=?", (seid,)).fetchone()[0] == 3
    con.execute("INSERT INTO watch_progress(user_id,series_id,episode_id,season_number,episode_number,last_watched_at) VALUES(?,?,?,?,?,?)", (1,sid,2,1,2,'now'))
    assert con.execute("SELECT episode_number FROM watch_progress WHERE user_id=1 AND series_id=?", (sid,)).fetchone()[0] == 2
    # Duplicate protection at database level.
    try:
        con.execute("INSERT INTO episodes(season_id,code,episode_number,title,media_file_id,media_type,created_at) VALUES(?,?,?,?,?,?,?)", (seid,'A100E2',2,'Dup','file','video','now'))
        raise AssertionError('duplicate episode was accepted')
    except sqlite3.IntegrityError:
        pass
    con.close()


def test_category_specific_home_and_code_share():
    kb_src=(ROOT/'keyboards'/'common.py').read_text(encoding='utf-8')
    user_src=(ROOT/'handlers'/'user.py').read_text(encoding='utf-8')
    db_src=(ROOT/'database'/'db.py').read_text(encoding='utf-8')
    assert 'def more_menu' in kb_src
    assert 'category_movie_tagline' in user_src and 'category_anime_tagline' in user_src
    assert 'finish_series' in user_src and "prefix == 'K'" in user_src
    assert 'share_cb' in user_src and 'series_by_code(code)' in user_src
    assert 'original_title LIKE ?' in db_src
    assert 'duration INTEGER' in db_src and 'quality TEXT' in db_src
    assert 'content_type' in user_src and 'category_cartoon_tagline' in user_src
    assert "datetime(p.last_watched_at)>=datetime('now','-30 day')" in db_src



def test_security_schema_and_required_channels():
    src = (ROOT/'database'/'db.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    schema = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets))
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript(schema)
    channel_cols = {r['name'] for r in con.execute('PRAGMA table_info(channels)')}
    assert 'required' in channel_cols
    for table in ('bans','permissions','admin_permissions'):
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    con.execute("INSERT INTO users(telegram_id,first_name,language,referral_code,created_at,last_seen_at) VALUES(?,?,?,?,?,?)", (2001,'Security','uz','R2001','now','now'))
    con.execute("INSERT INTO admins(telegram_id,role,password_hash,created_at) VALUES(?,?,?,?)", (9001,'senior_admin','x','now'))
    aid = con.execute('SELECT id FROM admins WHERE telegram_id=9001').fetchone()['id']
    con.execute("INSERT INTO permissions(key,label) VALUES('users.ban','Users Ban')")
    con.execute("INSERT INTO admin_permissions(admin_id,permission,allowed,updated_at) VALUES(?,?,?,?)", (aid,'users.ban',1,'now'))
    con.execute("INSERT INTO channels(name,username,required,active,created_at,updated_at) VALUES(?,?,?,?,?,?)", ('Optional','@optional',0,1,'now','now'))
    con.execute("INSERT INTO channels(name,username,required,active,created_at,updated_at) VALUES(?,?,?,?,?,?)", ('Required','@required',1,1,'now','now'))
    assert con.execute('SELECT COUNT(*) FROM channels WHERE required=1 AND active=1').fetchone()[0] == 1
    con.close()


def test_core_security_static():
    sec = (ROOT/'services'/'security.py').read_text(encoding='utf-8')
    sub = (ROOT/'services'/'subscriptions.py').read_text(encoding='utf-8')
    main = (ROOT/'main.py').read_text(encoding='utf-8')
    assert 'active_ban' in sec and 'check_subscription' in sec
    assert 'member' in sub and 'administrator' in sub and 'creator' in sub
    assert 'ban_cleanup_loop' in main and ('expire_bans' in main or 'cleanup()' in main)
    assert "int(r['required'])" in sub


def test_search_union_and_pagination():
    db_src=(ROOT/'database'/'db.py').read_text(encoding='utf-8')
    user_src=(ROOT/'handlers'/'user.py').read_text(encoding='utf-8')
    assert 'async def count_search' in db_src
    assert 'SELECT * FROM (' in db_src
    assert 'async def render_search_results' in user_src
    assert "F.data.startswith('search:')" in user_src



def test_db_connection_api_consistency_and_ux_routes():
    db_src = (ROOT/'database'/'db.py').read_text(encoding='utf-8')
    sec_src = (ROOT/'services'/'security.py').read_text(encoding='utf-8')
    common_src = (ROOT/'keyboards'/'common.py').read_text(encoding='utf-8')
    admin_src = (ROOT/'handlers'/'admin.py').read_text(encoding='utf-8')
    assert 'execute_fetchone' not in db_src
    assert 'execute_fetchall' not in db_src
    assert 'async def _conn_fetchone' in db_src
    assert 'async def _conn_fetchall' in db_src
    assert 'logger = logging.getLogger(__name__)' in sec_src
    user_block = common_src[common_src.index('def user_menu'):common_src.index('def more_menu') if 'def more_menu' in common_src else len(common_src)]
    assert "tr(lang, 'more')" not in user_block
    assert "tr(lang, 'settings')" in user_block
    assert 'section == "moderation"' in admin_src
    assert 'section == "health"' in admin_src


def test_content_creation_is_type_first_and_permission_scoped():
    admin_src=(ROOT/'handlers'/'admin.py').read_text(encoding='utf-8')
    state_src=(ROOT/'states'/'content.py').read_text(encoding='utf-8')
    common_src=(ROOT/'keyboards'/'common.py').read_text(encoding='utf-8')
    assert 'choose_content_type' in admin_src
    assert 'ContentAddState.ctype' in admin_src
    assert 'permission_map' in admin_src
    assert 'cartoon_mode' in state_src
    user_block=common_src[common_src.index('def user_menu'):common_src.index('def more_menu')]
    assert "tr(lang, 'more')" not in user_block
    assert "tr(lang, 'discover')" in user_block and "tr(lang, 'my_cinema')" in user_block


def test_no_legacy_advanced_entry_and_admin_deduplication():
    adv=(ROOT/'handlers'/'admin_advanced.py').read_text(encoding='utf-8')
    admin_kb=(ROOT/'keyboards'/'admin.py').read_text(encoding='utf-8')
    common=(ROOT/'keyboards'/'common.py').read_text(encoding='utf-8')
    assert "F.data=='adm:advanced'" not in adv
    assert 'tr(lang, "tickets")' not in admin_kb.split('def admin_panel',1)[1].split('def content_menu',1)[0]
    assert 'tr(lang, "qa_manage")' not in admin_kb.split('def admin_panel',1)[1].split('def content_menu',1)[0]
    user_block=common[common.index('def user_menu'):common.index('def more_menu')]
    assert "tr(lang, 'support')" in user_block and "tr(lang, 'questions')" in user_block
