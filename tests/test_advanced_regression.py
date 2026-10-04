from __future__ import annotations
import ast, json, re, sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def load_const(name):
    tree=ast.parse((ROOT/'database'/'db.py').read_text(encoding='utf8'))
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
    return ast.literal_eval(node.value)


def test_full_schema_and_advanced_tables():
    con=sqlite3.connect(':memory:')
    con.executescript(load_const('SCHEMA'))
    con.executescript(load_const('ADVANCED_SCHEMA'))
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected={'collections','collection_items','moods','mood_genres','notification_preferences','follows','content_reports','release_calendar','activity_log','daily_picks','media_sources'}
    assert expected <= tables
    series_cols={r[1] for r in con.execute('PRAGMA table_info(series)')}
    assert {'visibility','moderation_status'} <= series_cols
    movie_cols={r[1] for r in con.execute('PRAGMA table_info(movies)')}
    assert {'visibility','moderation_status','duration','quality'} <= movie_cols
    episode_cols={r[1] for r in con.execute('PRAGMA table_info(episodes)')}
    assert {'visibility','moderation_status','search_count'} <= episode_cols
    con.close()


def test_search_union_sql_supports_movie_series_episode_and_hides_code_only():
    src=(ROOT/'database'/'db.py').read_text(encoding='utf8')
    tree=ast.parse(src)
    fn=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Database').body
    method=next(n for n in fn if isinstance(n,ast.AsyncFunctionDef) and n.name=='search')
    sql_node=next(n.value for n in method.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='sql' for t in n.targets))
    sql=ast.literal_eval(sql_node)
    con=sqlite3.connect(':memory:')
    con.executescript(load_const('SCHEMA'))
    now='2026-10-01T10:00:00+00:00'
    con.execute("INSERT INTO movies(code,title,media_file_id,media_type,content_type,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",('K1AB','Interstellar','f1','video','movie',now,now))
    con.execute("INSERT INTO movies(code,title,media_file_id,media_type,content_type,visibility,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",('K1CD','Hidden','f2','video','movie','code_only',now,now))
    con.execute("INSERT INTO series(code,title,content_type,created_at,updated_at) VALUES(?,?,?,?,?)",('S1AB','Demo Series','series',now,now))
    sid=con.execute("SELECT id FROM series WHERE code='S1AB'").fetchone()[0]
    con.execute("INSERT INTO seasons(series_id,season_number,title) VALUES(?,?,?)",(sid,1,'Season 1'))
    seid=con.execute("SELECT id FROM seasons WHERE series_id=?",(sid,)).fetchone()[0]
    con.execute("INSERT INTO episodes(season_id,code,episode_number,title,media_file_id,media_type,created_at) VALUES(?,?,?,?,?,?,?)",(seid,'E1AB',1,'Episode One','e1','video',now))
    params=(['%Demo%']*6+['Demo']+['%Demo%']*6)*2+['%Demo%']*5+[8,0]
    rows=con.execute(sql,params).fetchall()
    assert any(r[1]=='Demo Series' for r in rows)
    assert all(r[2] != 'K1CD' for r in rows)
    # Exact/LIKE query from normal search must return the public episode only.
    con.close()


def test_no_ai_dependency_or_source_reference():
    forbidden=re.compile(r'openai|google-generativeai|gemini|anthropic|groq|langchain|llama|transformers',re.I)
    for p in ROOT.rglob('*'):
        if p.is_dir() or '__pycache__' in p.parts or p.name.startswith('test_'):
            continue
        if p.suffix.lower() in {'.py','.txt','.toml','.cfg','.ini','.md','.json'}:
            text=p.read_text(encoding='utf8',errors='ignore')
            assert not forbidden.search(text), f'AI reference found in {p}'


def test_all_callback_sources_include_advanced_routers():
    files=[ROOT/'keyboards'/'admin.py',ROOT/'keyboards'/'common.py']
    handler_files=[ROOT/'handlers'/'admin.py',ROOT/'handlers'/'user.py',ROOT/'handlers'/'common.py',ROOT/'handlers'/'discovery.py',ROOT/'handlers'/'admin_advanced.py']
    kb=''.join(p.read_text(encoding='utf8') for p in files)
    handlers=''.join(p.read_text(encoding='utf8') for p in handler_files)
    dyn=set()
    for m in re.finditer(r'callback_data=f?"([^"]+)',kb):
        v=m.group(1)
        if '{' not in v and v.split(':')[0] != 'noop': dyn.add(v.split(':')[0])
    prefixes=set(re.findall(r"F\.data\.(?:startswith|regexp)\(\s*['\"]([^'\"]+)['\"]",handlers))
    prefixes={x.rstrip(':').split(':')[0] for x in prefixes}
    literals=set(x.split(':')[0] for x in re.findall(r"F\.data\s*==\s*['\"]([^'\"]+)['\"]",handlers))
    prefixes |= literals
    missing=sorted(dyn-prefixes)
    assert not missing, missing
