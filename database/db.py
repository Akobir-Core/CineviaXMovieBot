from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Sequence
import secrets
import string

import aiosqlite


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _conn_fetchone(db: aiosqlite.Connection, sql: str, params: Sequence[Any] = ()): 
    async with db.execute(sql, params) as cur:
        return await cur.fetchone()

async def _conn_fetchall(db: aiosqlite.Connection, sql: str, params: Sequence[Any] = ()): 
    async with db.execute(sql, params) as cur:
        return await cur.fetchall()

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL UNIQUE,
 first_name TEXT NOT NULL, last_name TEXT, username TEXT,
 language TEXT NOT NULL DEFAULT 'uz' CHECK(language IN ('uz','ru','en')),
 referral_code TEXT NOT NULL UNIQUE, referred_by INTEGER, is_active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 FOREIGN KEY(referred_by) REFERENCES users(id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_users_lang ON users(language);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS movies(
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
 title TEXT NOT NULL, alternative_title TEXT, original_title TEXT, description TEXT, poster_file_id TEXT,
 media_file_id TEXT NOT NULL, media_type TEXT NOT NULL,
 content_type TEXT NOT NULL CHECK(content_type IN ('movie','anime','cartoon','other')),
 genre_id INTEGER, country_id INTEGER, release_year INTEGER, language TEXT,
 translation_type TEXT, rating REAL NOT NULL DEFAULT 0, views_count INTEGER NOT NULL DEFAULT 0,
 duration INTEGER, age_rating TEXT, quality TEXT, audio_languages TEXT, subtitle_languages TEXT,
 likes_count INTEGER NOT NULL DEFAULT 0, search_count INTEGER NOT NULL DEFAULT 0,
 visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','code_only','hidden')), moderation_status TEXT NOT NULL DEFAULT 'verified',
 active INTEGER NOT NULL DEFAULT 1, featured INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(genre_id) REFERENCES genres(id) ON DELETE SET NULL,
 FOREIGN KEY(country_id) REFERENCES countries(id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS idx_movies_type ON movies(content_type,active);
CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(release_year,active);
CREATE INDEX IF NOT EXISTS idx_movies_views ON movies(views_count DESC);
CREATE INDEX IF NOT EXISTS idx_movies_created ON movies(created_at DESC);

CREATE TABLE IF NOT EXISTS series(
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
 title TEXT NOT NULL, alternative_title TEXT, original_title TEXT, description TEXT, poster_file_id TEXT,
 genre_id INTEGER, country_id INTEGER, release_year INTEGER, language TEXT,
 translation_type TEXT, content_type TEXT NOT NULL DEFAULT 'series' CHECK(content_type IN ('series','anime','cartoon')),
 studio TEXT, anime_type TEXT, status TEXT, age_rating TEXT, quality TEXT, audio_languages TEXT, subtitle_languages TEXT,
 rating REAL NOT NULL DEFAULT 0, views_count INTEGER NOT NULL DEFAULT 0,
 search_count INTEGER NOT NULL DEFAULT 0, visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','code_only','hidden')), moderation_status TEXT NOT NULL DEFAULT 'verified',
 active INTEGER NOT NULL DEFAULT 1, featured INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(genre_id) REFERENCES genres(id) ON DELETE SET NULL,
 FOREIGN KEY(country_id) REFERENCES countries(id) ON DELETE SET NULL);
CREATE INDEX IF NOT EXISTS idx_series_type ON series(content_type,active);
CREATE INDEX IF NOT EXISTS idx_series_views ON series(views_count DESC);
CREATE INDEX IF NOT EXISTS idx_series_created ON series(created_at DESC);
CREATE TABLE IF NOT EXISTS seasons(
 id INTEGER PRIMARY KEY AUTOINCREMENT, series_id INTEGER NOT NULL, season_number INTEGER NOT NULL,
 title TEXT, UNIQUE(series_id,season_number), FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS episodes(
 id INTEGER PRIMARY KEY AUTOINCREMENT, season_id INTEGER NOT NULL, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
 episode_number INTEGER NOT NULL, title TEXT, description TEXT, caption TEXT, duration INTEGER,
 media_file_id TEXT NOT NULL, media_type TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, views_count INTEGER NOT NULL DEFAULT 0, search_count INTEGER NOT NULL DEFAULT 0, visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','code_only','hidden')), moderation_status TEXT NOT NULL DEFAULT 'verified', created_at TEXT NOT NULL,
 UNIQUE(season_id,episode_number), FOREIGN KEY(season_id) REFERENCES seasons(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS watch_progress(
 user_id INTEGER NOT NULL, series_id INTEGER NOT NULL, episode_id INTEGER NOT NULL,
 season_number INTEGER NOT NULL, episode_number INTEGER NOT NULL, last_watched_at TEXT NOT NULL,
 PRIMARY KEY(user_id,series_id),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE,
 FOREIGN KEY(episode_id) REFERENCES episodes(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_watch_progress_user ON watch_progress(user_id,last_watched_at DESC);

CREATE TABLE IF NOT EXISTS genres(id INTEGER PRIMARY KEY AUTOINCREMENT,name_uz TEXT NOT NULL,name_ru TEXT NOT NULL,name_en TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,UNIQUE(name_uz),UNIQUE(name_ru),UNIQUE(name_en));
CREATE TABLE IF NOT EXISTS countries(id INTEGER PRIMARY KEY AUTOINCREMENT,name_uz TEXT NOT NULL,name_ru TEXT NOT NULL,name_en TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,UNIQUE(name_uz),UNIQUE(name_ru),UNIQUE(name_en));

CREATE TABLE IF NOT EXISTS favorites(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,content_kind TEXT NOT NULL,content_id INTEGER NOT NULL,
 created_at TEXT NOT NULL,UNIQUE(user_id,content_kind,content_id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS watch_later(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,content_kind TEXT NOT NULL,content_id INTEGER NOT NULL,
 created_at TEXT NOT NULL,UNIQUE(user_id,content_kind,content_id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS watch_history(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,content_kind TEXT NOT NULL,content_id INTEGER NOT NULL,
 viewed_at TEXT NOT NULL,UNIQUE(user_id,content_kind,content_id),FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);

CREATE TABLE IF NOT EXISTS channels(
 id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,username TEXT,telegram_id INTEGER,invite_link TEXT,
 required INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS referrals(
 id INTEGER PRIMARY KEY AUTOINCREMENT,referrer_user_id INTEGER NOT NULL,referred_user_id INTEGER NOT NULL UNIQUE,
 referral_code TEXT NOT NULL,created_at TEXT NOT NULL,
 FOREIGN KEY(referrer_user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(referred_user_id) REFERENCES users(id) ON DELETE CASCADE);

CREATE TABLE IF NOT EXISTS support_tickets(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,category TEXT NOT NULL,message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','in_progress','answered','closed')),
 admin_response TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,closed_at TEXT,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS ticket_messages(
 id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER NOT NULL,sender_telegram_id INTEGER NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL,
 FOREIGN KEY(ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS anonymous_questions(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,question TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','reviewing','answered','archived')),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS anonymous_answers(
 id INTEGER PRIMARY KEY AUTOINCREMENT,question_id INTEGER NOT NULL,admin_id INTEGER NOT NULL,answer TEXT NOT NULL,created_at TEXT NOT NULL,
 FOREIGN KEY(question_id) REFERENCES anonymous_questions(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS anonymous_messages(
 id INTEGER PRIMARY KEY AUTOINCREMENT,question_id INTEGER NOT NULL,
 sender_type TEXT NOT NULL CHECK(sender_type IN ('user','admin')),
 sender_id INTEGER NOT NULL,
 message TEXT NOT NULL,created_at TEXT NOT NULL,
 FOREIGN KEY(question_id) REFERENCES anonymous_questions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_anonymous_messages_question ON anonymous_messages(question_id,created_at);
CREATE TABLE IF NOT EXISTS published_qa(
 id INTEGER PRIMARY KEY AUTOINCREMENT,question_id INTEGER,category TEXT,question_text TEXT NOT NULL,answer_text TEXT NOT NULL,
 published_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,FOREIGN KEY(question_id) REFERENCES anonymous_questions(id) ON DELETE SET NULL);

CREATE TABLE IF NOT EXISTS admins(
 id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL UNIQUE,
 role TEXT NOT NULL CHECK(role IN ('ceo','senior_admin','admin')),
 password_hash TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,created_by INTEGER,parent_admin_id INTEGER,
 failed_attempts INTEGER NOT NULL DEFAULT 0,
 locked_until TEXT,
 last_login_at TEXT,
 password_updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_admins_role ON admins(role,active);
CREATE INDEX IF NOT EXISTS idx_admins_parent ON admins(parent_admin_id,active);
CREATE UNIQUE INDEX IF NOT EXISTS ux_admins_one_active_junior_per_parent ON admins(parent_admin_id) WHERE role='admin' AND active=1 AND parent_admin_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS admin_sessions(
 telegram_id INTEGER PRIMARY KEY,
 authenticated_until TEXT NOT NULL,
 created_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admin_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,admin_id INTEGER NOT NULL,action TEXT NOT NULL,target TEXT,details TEXT,timestamp TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_admin_logs_time ON admin_logs(timestamp DESC);
CREATE TABLE IF NOT EXISTS search_history(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,query TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,is_read INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS broadcasts(
 id INTEGER PRIMARY KEY AUTOINCREMENT,admin_id INTEGER NOT NULL,message_type TEXT NOT NULL,target_type TEXT NOT NULL,
 start_time TEXT NOT NULL,end_time TEXT,successful_count INTEGER NOT NULL DEFAULT 0,failed_count INTEGER NOT NULL DEFAULT 0,total_recipients INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS broadcast_targets(id INTEGER PRIMARY KEY AUTOINCREMENT,broadcast_id INTEGER NOT NULL,telegram_id INTEGER NOT NULL,status TEXT NOT NULL,error TEXT,
 FOREIGN KEY(broadcast_id) REFERENCES broadcasts(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS user_blocks(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER NOT NULL UNIQUE,reason TEXT,created_at TEXT NOT NULL,created_by INTEGER);
CREATE TABLE IF NOT EXISTS bans(
 id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL, ban_started_at TEXT NOT NULL,
 ban_expires_at TEXT, ban_reason TEXT, banned_by INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active'
   CHECK(status IN ('active','expired','revoked')), revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_bans_user_status ON bans(telegram_id,status,ban_expires_at);
CREATE TABLE IF NOT EXISTS permissions(
 key TEXT PRIMARY KEY, label TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_permissions(
 admin_id INTEGER NOT NULL, permission TEXT NOT NULL, allowed INTEGER NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(admin_id,permission),
 FOREIGN KEY(admin_id) REFERENCES admins(id) ON DELETE CASCADE,
 FOREIGN KEY(permission) REFERENCES permissions(key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fav_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_later_user ON watch_later(user_id);
CREATE INDEX IF NOT EXISTS idx_hist_user ON watch_history(user_id,viewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_ticket_status ON support_tickets(status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qa_status ON anonymous_questions(status,created_at DESC);
"""


ADVANCED_SCHEMA = """
CREATE TABLE IF NOT EXISTS collections(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL,
 description TEXT,
 poster_file_id TEXT,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_items(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 collection_id INTEGER NOT NULL,
 content_kind TEXT NOT NULL,
 content_id INTEGER NOT NULL,
 position INTEGER NOT NULL DEFAULT 0,
 UNIQUE(collection_id,content_kind,content_id),
 FOREIGN KEY(collection_id) REFERENCES collections(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_collection_items_pos ON collection_items(collection_id,position);
CREATE TABLE IF NOT EXISTS moods(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name_uz TEXT NOT NULL,
 name_ru TEXT NOT NULL,
 name_en TEXT NOT NULL,
 emoji TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mood_genres(
 mood_id INTEGER NOT NULL,
 genre_id INTEGER NOT NULL,
 PRIMARY KEY(mood_id,genre_id),
 FOREIGN KEY(mood_id) REFERENCES moods(id) ON DELETE CASCADE,
 FOREIGN KEY(genre_id) REFERENCES genres(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS notification_preferences(
 user_id INTEGER NOT NULL,
 key TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(user_id,key),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS follows(
 user_id INTEGER NOT NULL,
 series_id INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(user_id,series_id),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS content_reports(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 content_kind TEXT NOT NULL,
 content_id INTEGER NOT NULL,
 report_type TEXT NOT NULL,
 message TEXT,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','pending','resolved','rejected')),
 handled_by INTEGER,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON content_reports(status,updated_at DESC);
CREATE TABLE IF NOT EXISTS release_calendar(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 content_kind TEXT NOT NULL,
 content_id INTEGER NOT NULL,
 season_number INTEGER,
 episode_number INTEGER,
 release_at TEXT NOT NULL,
 title TEXT,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 UNIQUE(content_kind,content_id,season_number,episode_number,release_at)
);
CREATE INDEX IF NOT EXISTS idx_release_calendar_time ON release_calendar(active,release_at);
CREATE TABLE IF NOT EXISTS activity_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 action TEXT NOT NULL,
 content_kind TEXT,
 content_id INTEGER,
 details TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_activity_user_time ON activity_log(user_id,created_at DESC);
CREATE TABLE IF NOT EXISTS daily_picks(
 user_id INTEGER NOT NULL,
 day TEXT NOT NULL,
 content_kind TEXT NOT NULL,
 content_id INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(user_id,day),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS media_sources(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 content_kind TEXT NOT NULL,
 content_id INTEGER NOT NULL,
 label TEXT NOT NULL,
 file_id TEXT NOT NULL,
 media_type TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 UNIQUE(content_kind,content_id,label)
);
"""

GENRES = [
    ('Action','Боевик','Action'),('Adventure','Приключения','Adventure'),('Comedy','Комедия','Comedy'),
    ('Drama','Драма','Drama'),('Fantasy','Фэнтези','Fantasy'),('Horror','Ужасы','Horror'),('Romance','Романтика','Romance'),
    ('Sci-Fi','Фантастика','Sci-Fi'),('Thriller','Триллер','Thriller'),('Mystery','Детектив','Mystery'),
    ('Animation','Анимация','Animation'),('Crime','Криминал','Crime'),('Documentary','Документальный','Documentary')]
COUNTRIES = [
    ('O‘zbekiston','Узбекистан','Uzbekistan'),('AQSH','США','USA'),('Buyuk Britaniya','Великобритания','UK'),
    ('Yaponiya','Япония','Japan'),('Janubiy Koreya','Южная Корея','South Korea'),('Turkiya','Турция','Turkey'),
    ('Hindiston','Индия','India'),('Fransiya','Франция','France'),('Germaniya','Германия','Germany')]

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute('PRAGMA foreign_keys=ON')
        await db.execute('PRAGMA journal_mode=WAL')
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def _migrate_content_schema(self, db: aiosqlite.Connection) -> None:
        """Safely upgrade content schema while preserving existing IDs and records."""
        # Additive columns for legacy movie tables.
        movie_cols = {str(r['name']) for r in await _conn_fetchall(db, 'PRAGMA table_info(movies)')}
        for name, typ in {'visibility':"TEXT NOT NULL DEFAULT 'public'", 'moderation_status':"TEXT NOT NULL DEFAULT 'verified'"}.items():
            if name not in movie_cols:
                await db.execute(f'ALTER TABLE movies ADD COLUMN {name} {typ}')
        movie_additions = {
            'original_title': 'TEXT',
            'duration': 'INTEGER',
            'age_rating': 'TEXT',
            'quality': 'TEXT',
            'audio_languages': 'TEXT',
            'subtitle_languages': 'TEXT',
        }
        for name, typ in movie_additions.items():
            if name not in movie_cols:
                await db.execute(f'ALTER TABLE movies ADD COLUMN {name} {typ}')

        # Series needs an expanded CHECK to support episodic cartoons.
        series_cols = {str(r['name']) for r in await _conn_fetchall(db, 'PRAGMA table_info(series)')}
        for name, typ in {'visibility':"TEXT NOT NULL DEFAULT 'public'", 'moderation_status':"TEXT NOT NULL DEFAULT 'verified'"}.items():
            if name not in series_cols:
                await db.execute(f'ALTER TABLE series ADD COLUMN {name} {typ}')
        series_sql = (await _conn_fetchall(db, "SELECT sql FROM sqlite_master WHERE type='table' AND name='series'"))[0]['sql']
        needs_series_rebuild = "'cartoon'" not in str(series_sql)
        if needs_series_rebuild:
            await db.execute('PRAGMA foreign_keys=OFF')
            await db.execute('DROP TABLE IF EXISTS series_new')
            await db.execute("""CREATE TABLE series_new(
                id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
                title TEXT NOT NULL, alternative_title TEXT, original_title TEXT, description TEXT, poster_file_id TEXT,
                genre_id INTEGER, country_id INTEGER, release_year INTEGER, language TEXT,
                translation_type TEXT, content_type TEXT NOT NULL DEFAULT 'series' CHECK(content_type IN ('series','anime','cartoon')),
                studio TEXT, anime_type TEXT, status TEXT, age_rating TEXT, quality TEXT, audio_languages TEXT, subtitle_languages TEXT,
                rating REAL NOT NULL DEFAULT 0, views_count INTEGER NOT NULL DEFAULT 0,
                search_count INTEGER NOT NULL DEFAULT 0, visibility TEXT NOT NULL DEFAULT 'public' CHECK(visibility IN ('public','code_only','hidden')), moderation_status TEXT NOT NULL DEFAULT 'verified',
                active INTEGER NOT NULL DEFAULT 1, featured INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(genre_id) REFERENCES genres(id) ON DELETE SET NULL,
                FOREIGN KEY(country_id) REFERENCES countries(id) ON DELETE SET NULL
            )""")
            old_cols = {str(r['name']) for r in await _conn_fetchall(db, 'PRAGMA table_info(series)')}
            target_cols = ['id','code','title','alternative_title','original_title','description','poster_file_id','genre_id','country_id','release_year','language','translation_type','content_type','studio','anime_type','status','age_rating','quality','audio_languages','subtitle_languages','rating','views_count','search_count','visibility','moderation_status','active','featured','created_at','updated_at']
            source_expr=[]
            defaults={'original_title':'NULL','studio':'NULL','anime_type':'NULL','status':'NULL','age_rating':'NULL','quality':'NULL','audio_languages':'NULL','subtitle_languages':'NULL','visibility':"'public'",'moderation_status':"'verified'"}
            for c in target_cols:
                source_expr.append(c if c in old_cols else defaults.get(c, 'NULL'))
            await db.execute(f"INSERT INTO series_new({','.join(target_cols)}) SELECT {','.join(source_expr)} FROM series")
            await db.execute('DROP TABLE series')
            await db.execute('ALTER TABLE series_new RENAME TO series')
            await db.execute('PRAGMA foreign_keys=ON')
        else:
            additions = {
                'original_title':'TEXT','studio':'TEXT','anime_type':'TEXT','status':'TEXT','age_rating':'TEXT',
                'quality':'TEXT','audio_languages':'TEXT','subtitle_languages':'TEXT'
            }
            for name, typ in additions.items():
                if name not in series_cols:
                    await db.execute(f'ALTER TABLE series ADD COLUMN {name} {typ}')

        episode_cols = {str(r['name']) for r in await _conn_fetchall(db, 'PRAGMA table_info(episodes)')}
        for name, typ in {'visibility':"TEXT NOT NULL DEFAULT 'public'", 'moderation_status':"TEXT NOT NULL DEFAULT 'verified'"}.items():
            if name not in episode_cols:
                await db.execute(f'ALTER TABLE episodes ADD COLUMN {name} {typ}')
        for name, typ in {'caption':'TEXT','duration':'INTEGER','quality':'TEXT','audio_languages':'TEXT','subtitle_languages':'TEXT','search_count':'INTEGER NOT NULL DEFAULT 0'}.items():
            if name not in episode_cols:
                await db.execute(f'ALTER TABLE episodes ADD COLUMN {name} {typ}')

        await db.execute('CREATE INDEX IF NOT EXISTS idx_series_type ON series(content_type,active)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_series_status ON series(status,active)')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_episode_position ON episodes(season_id,episode_number)')
        await db.execute("""CREATE TABLE IF NOT EXISTS watch_progress(
            user_id INTEGER NOT NULL, series_id INTEGER NOT NULL, episode_id INTEGER NOT NULL,
            season_number INTEGER NOT NULL, episode_number INTEGER NOT NULL, last_watched_at TEXT NOT NULL,
            PRIMARY KEY(user_id,series_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE CASCADE,
            FOREIGN KEY(episode_id) REFERENCES episodes(id) ON DELETE CASCADE
        )""")
        await db.execute('CREATE INDEX IF NOT EXISTS idx_watch_progress_user ON watch_progress(user_id,last_watched_at DESC)')

    async def _migrate_admin_hierarchy_schema(self) -> None:
        cols = {str(r['name']) for r in await self.fetchall("PRAGMA table_info(admins)")}
        if 'parent_admin_id' not in cols:
            await self.execute("ALTER TABLE admins ADD COLUMN parent_admin_id INTEGER")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_admins_parent ON admins(parent_admin_id,active)")
        # Repair legacy duplicates before enforcing the one-Junior-per-Senior rule.
        duplicate_parents = await self.fetchall(
            "SELECT parent_admin_id FROM admins WHERE role='admin' AND active=1 AND parent_admin_id IS NOT NULL GROUP BY parent_admin_id HAVING COUNT(*)>1"
        )
        for dup in duplicate_parents:
            keep = await self.fetchone(
                "SELECT id FROM admins WHERE role='admin' AND active=1 AND parent_admin_id=? ORDER BY id LIMIT 1",
                (int(dup['parent_admin_id']),),
            )
            if keep:
                await self.execute(
                    "UPDATE admins SET active=0 WHERE role='admin' AND active=1 AND parent_admin_id=? AND id!=?",
                    (int(dup['parent_admin_id']), int(keep['id'])),
                )
        # Only one active Junior (role='admin') may belong to a Senior.
        await self.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_admins_one_active_junior_per_parent ON admins(parent_admin_id) WHERE role='admin' AND active=1 AND parent_admin_id IS NOT NULL")

    async def _migrate_security_schema(self, db: aiosqlite.Connection) -> None:
        # Existing installations: add channels.required without dropping data.
        channel_cols = {str(r['name']) for r in await _conn_fetchall(db, 'PRAGMA table_info(channels)')}
        if 'required' not in channel_cols:
            await db.execute("ALTER TABLE channels ADD COLUMN required INTEGER NOT NULL DEFAULT 1")
        # Legacy permanent restrictions are still honored through user_blocks; new bans
        # provide temporary/permanent lifecycle and history.
        await db.execute("CREATE TABLE IF NOT EXISTS bans( id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL, ban_started_at TEXT NOT NULL, ban_expires_at TEXT, ban_reason TEXT, banned_by INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','expired','revoked')), revoked_at TEXT )")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bans_user_status ON bans(telegram_id,status,ban_expires_at)")
        await db.execute("CREATE TABLE IF NOT EXISTS permissions(key TEXT PRIMARY KEY,label TEXT NOT NULL)")
        await db.execute("CREATE TABLE IF NOT EXISTS admin_permissions(admin_id INTEGER NOT NULL,permission TEXT NOT NULL,allowed INTEGER NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(admin_id,permission),FOREIGN KEY(admin_id) REFERENCES admins(id) ON DELETE CASCADE,FOREIGN KEY(permission) REFERENCES permissions(key) ON DELETE CASCADE)")

    async def _migrate_admins(self, initial_ceo_password_hash: str) -> None:
        """Migrate legacy owner/ceo/admin/movie_admin records to CEO/Senior Admin/Admin."""
        exists = await self.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='admins'")
        if not exists:
            return

        columns = {
            str(r["name"])
            for r in await self.fetchall("PRAGMA table_info(admins)")
        }
        legacy_roles = set()
        if "role" in columns:
            rows = await self.fetchall("SELECT role FROM admins")
            legacy_roles = {str(r["role"]) for r in rows}

        needs_rebuild = (
            "password_hash" not in columns
            or "failed_attempts" not in columns
            or "locked_until" not in columns
            or "last_login_at" not in columns
            or bool(legacy_roles & {"owner", "movie_admin"})
        )
        if not needs_rebuild:
            return

        old_rows = await self.fetchall("SELECT * FROM admins")
        await self.execute("DROP TABLE IF EXISTS admins_new")
        await self.execute("""
            CREATE TABLE admins_new(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL UNIQUE,
                role TEXT NOT NULL CHECK(role IN ('ceo','senior_admin','admin')),
                password_hash TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                created_by INTEGER,
                parent_admin_id INTEGER,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                last_login_at TEXT,
                password_updated_at TEXT
            )
        """)
        for old in old_rows:
            role = str(old["role"])
            mapped = {
                "owner": "ceo",
                "ceo": "ceo",
                "admin": "admin",
                "movie_admin": "admin",
            }.get(role, "admin")
            password_hash = str(old["password_hash"]) if "password_hash" in columns and old["password_hash"] else ""
            await self.execute(
                """INSERT INTO admins_new(
                    telegram_id,role,password_hash,active,created_at,created_by,
                    failed_attempts,locked_until,last_login_at,password_updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(old["telegram_id"]), mapped, password_hash,
                    int(old["active"]), old["created_at"], old["created_by"],
                    int(old["failed_attempts"]) if "failed_attempts" in columns and old["failed_attempts"] is not None else 0,
                    old["locked_until"] if "locked_until" in columns else None,
                    old["last_login_at"] if "last_login_at" in columns else None,
                    old["password_updated_at"] if "password_updated_at" in columns else None,
                ),
            )
        await self.execute("DROP TABLE admins")
        await self.execute("ALTER TABLE admins_new RENAME TO admins")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_admins_role ON admins(role,active)")

        # The configured CEO always has a valid role. Password is only seeded when empty.
        existing = await self.fetchone("SELECT * FROM admins WHERE telegram_id=?", (owner_id := getattr(self, "_owner_id", 0),))
        if existing and not existing["password_hash"] and owner_id:
            await self.execute(
                "UPDATE admins SET password_hash=?,password_updated_at=? WHERE telegram_id=?",
                (initial_ceo_password_hash, utcnow(), owner_id),
            )

    async def init(self, owner_id: int, initial_ceo_password_hash: str = "") -> None:
        self._owner_id = int(owner_id)
        async with self.connect() as db:
            await db.executescript(SCHEMA)
            await db.executescript(ADVANCED_SCHEMA)
            await self._migrate_content_schema(db)
            await self._migrate_security_schema(db)
            for row in GENRES:
                await db.execute(
                    'INSERT OR IGNORE INTO genres(name_uz,name_ru,name_en) VALUES(?,?,?)',
                    row
                )
            for row in COUNTRIES:
                await db.execute(
                    'INSERT OR IGNORE INTO countries(name_uz,name_ru,name_en) VALUES(?,?,?)',
                    row
                )
            mood_seed = [
                ('Fun','Веселье','Fun','😎'), ('Action','Экшен','Action','🔥'), ('Comedy','Комедия','Comedy','😂'),
                ('Emotional','Эмоциональное','Emotional','😢'), ('Smart','Умное кино','Smart','🧠'), ('Mystery','Мистика','Mystery','👻'),
                ('Romantic','Романтика','Romantic','❤️'), ('Family','Семейное','Family','👨‍👩‍👧'), ('Adventure','Приключения','Adventure','⚔️')
            ]
            for mood in mood_seed:
                await db.execute('INSERT OR IGNORE INTO moods(name_uz,name_ru,name_en,emoji) VALUES(?,?,?,?)', mood)
            mood_map = {
                'Fun':['Comedy'], 'Action':['Action','Adventure'], 'Comedy':['Comedy'], 'Emotional':['Drama','Romance'],
                'Smart':['Mystery','Documentary','Sci-Fi'], 'Mystery':['Mystery','Thriller','Horror'], 'Romantic':['Romance','Drama'],
                'Family':['Animation','Adventure','Comedy'], 'Adventure':['Adventure','Action','Fantasy']
            }
            for mood_name, genre_names in mood_map.items():
                mr=await _conn_fetchone(db, 'SELECT id FROM moods WHERE name_en=?',(mood_name,))
                if mr:
                    for gname in genre_names:
                        gr=await _conn_fetchone(db, 'SELECT id FROM genres WHERE name_en=?',(gname,))
                        if gr:
                            await db.execute('INSERT OR IGNORE INTO mood_genres(mood_id,genre_id) VALUES(?,?)',(mr[0],gr[0]))
            defaults = {
                'bot_title': 'CineviaXMovieBot',
                'welcome_text': '🎬 CineviaXMovieBot',
                'anonymous_qa_enabled': '1',
                'support_enabled': '1',
                'referral_enabled': '1',
                'public_qa_enabled': '1',
                'maintenance_mode': '0',
                'default_language': 'uz',
                'pagination_size': '8',
                'welcome_text_uz': "🎬 CineviaXMovieBot'ga xush kelibsiz!",
                'welcome_text_ru': '🎬 Добро пожаловать в CineviaXMovieBot!',
                'welcome_text_en': '🎬 Welcome to CineviaXMovieBot!',
                'admin_session_minutes': '720',
                'admin_login_max_attempts': '5',
                'admin_login_lock_minutes': '15',
            }
            from services.permissions import PERMISSION_LABELS
            for pkey, plabel in PERMISSION_LABELS.items():
                await db.execute('INSERT OR IGNORE INTO permissions(key,label) VALUES(?,?)',(pkey,plabel))
            for k, v in defaults.items():
                await db.execute(
                    'INSERT OR IGNORE INTO bot_settings(key,value,updated_at) VALUES(?,?,?)',
                    (k, v, utcnow()),
                )

        await self._migrate_admins(initial_ceo_password_hash)
        await self._migrate_admin_hierarchy_schema()

        # Re-read the schema after migration and seed the configured CEO.
        if owner_id:
            existing = await self.fetchone("SELECT * FROM admins WHERE telegram_id=?", (owner_id,))
            if existing is None:
                await self.execute(
                    """INSERT INTO admins(
                        telegram_id,role,password_hash,active,created_at,created_by,parent_admin_id,password_updated_at
                    ) VALUES(?,?,?,?,?,?,?,?)""",
                    (owner_id, 'ceo', initial_ceo_password_hash, 1, utcnow(), owner_id, None, utcnow()),
                )
            else:
                updates = ["role='ceo'", "active=1"]
                params: list[Any] = []
                if not existing["password_hash"] and initial_ceo_password_hash:
                    updates.append("password_hash=?")
                    params.append(initial_ceo_password_hash)
                    updates.append("password_updated_at=?")
                    params.append(utcnow())
                params.append(owner_id)
                await self.execute(
                    f"UPDATE admins SET {','.join(updates)} WHERE telegram_id=?",
                    tuple(params),
                )
            # There is one CEO: the configured owner. Preserve legacy records by demoting
            # any other CEO rows to Senior Admin instead of deleting their history.
            await self.execute("UPDATE admins SET role='senior_admin', parent_admin_id=NULL WHERE role='ceo' AND telegram_id!=?", (owner_id,))

    async def fetchone(self, sql: str, params: Sequence[Any]=()):
        async with self.connect() as db:
            async with db.execute(sql, params) as cur:
                return await cur.fetchone()

    async def fetchall(self, sql: str, params: Sequence[Any]=()):
        async with self.connect() as db:
            async with db.execute(sql, params) as cur:
                return await cur.fetchall()

    async def execute(self, sql: str, params: Sequence[Any]=()):
        async with self.connect() as db:
            cur = await db.execute(sql, params)
            return cur.lastrowid if cur.lastrowid is not None else cur.rowcount

    async def executemany(self, sql: str, params: Iterable[Sequence[Any]]):
        async with self.connect() as db:
            await db.executemany(sql, params)

    async def setting(self,key:str,default:str='') -> str:
        row=await self.fetchone('SELECT value FROM bot_settings WHERE key=?',(key,))
        return row['value'] if row else default

    async def set_setting(self,key:str,value:str)->None:
        await self.execute("INSERT INTO bot_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",(key,value,utcnow()))

    async def user(self,telegram_id:int): return await self.fetchone('SELECT * FROM users WHERE telegram_id=?',(telegram_id,))

    async def ensure_user(self, tg_user, referral_code:str|None=None):
        row=await self.user(tg_user.id)
        if row:
            await self.execute('UPDATE users SET first_name=?,last_name=?,username=?,last_seen_at=? WHERE telegram_id=?',(tg_user.first_name or '',tg_user.last_name,tg_user.username,utcnow(),tg_user.id))
            return row,False
        alphabet=string.ascii_uppercase+string.digits
        code=''.join(secrets.choice(alphabet) for _ in range(10))
        while await self.fetchone('SELECT 1 FROM users WHERE referral_code=?',(code,)): code=''.join(secrets.choice(alphabet) for _ in range(10))
        referrer=None
        if referral_code:
            rr=await self.fetchone('SELECT id,telegram_id FROM users WHERE referral_code=?',(referral_code,))
            if rr and int(rr['telegram_id'])!=tg_user.id: referrer=int(rr['id'])
        uid=await self.execute('INSERT INTO users(telegram_id,first_name,last_name,username,language,referral_code,referred_by,created_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?)',(
            tg_user.id,tg_user.first_name or '',tg_user.last_name,tg_user.username,await self.setting('default_language','uz'),code,referrer,utcnow(),utcnow()))
        if referrer:
            await self.execute('INSERT OR IGNORE INTO referrals(referrer_user_id,referred_user_id,referral_code,created_at) VALUES(?,?,?,?)',(referrer,uid,referral_code,utcnow()))
        return await self.user(tg_user.id),True

    async def admin_any(self,telegram_id:int):
        return await self.fetchone('SELECT * FROM admins WHERE telegram_id=?',(telegram_id,))

    async def admin(self,telegram_id:int):
        return await self.fetchone('SELECT * FROM admins WHERE telegram_id=? AND active=1',(telegram_id,))

    async def admin_by_id(self, admin_id:int):
        return await self.fetchone('SELECT * FROM admins WHERE id=?',(admin_id,))

    async def admins(self):
        return await self.fetchall(
            "SELECT * FROM admins ORDER BY CASE role WHEN 'ceo' THEN 0 WHEN 'senior_admin' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, parent_admin_id, id"
        )

    async def active_admins(self):
        return await self.fetchall(
            "SELECT * FROM admins WHERE active=1 ORDER BY CASE role WHEN 'ceo' THEN 0 WHEN 'senior_admin' THEN 1 WHEN 'admin' THEN 2 ELSE 3 END, parent_admin_id, id"
        )

    async def count_ceos(self):
        r=await self.fetchone("SELECT COUNT(*) c FROM admins WHERE active=1 AND role='ceo'")
        return int(r['c'] or 0)

    async def junior_of(self, parent_admin_id:int):
        return await self.fetchone("SELECT * FROM admins WHERE parent_admin_id=? AND role='admin' AND active=1 LIMIT 1", (parent_admin_id,))

    async def active_junior_count(self, parent_admin_id:int) -> int:
        r=await self.fetchone("SELECT COUNT(*) c FROM admins WHERE parent_admin_id=? AND role='admin' AND active=1", (parent_admin_id,))
        return int(r['c'] or 0)

    async def add_admin(self,telegram_id:int,role:str,created_by:int,password_hash:str,parent_admin_id:int|None=None):
        if role not in {'senior_admin','admin'}:
            raise ValueError('invalid_admin_role')
        if role == 'admin' and parent_admin_id is not None:
            parent = await self.admin_any(parent_admin_id)
            if not parent or parent['role'] != 'senior_admin' or not int(parent['active']):
                raise ValueError('invalid_parent')
            if await self.active_junior_count(parent_admin_id):
                raise ValueError('junior_limit')
        # Only restore/update an existing same Telegram ID; ownership may not be silently reassigned.
        existing = await self.admin_any(telegram_id)
        if existing and int(existing['active']):
            raise ValueError('admin_exists')
        if existing:
            await self.execute(
                'UPDATE admins SET role=?,password_hash=?,active=1,created_by=?,parent_admin_id=?,failed_attempts=0,locked_until=NULL,password_updated_at=? WHERE telegram_id=?',
                (role,password_hash,created_by,parent_admin_id,utcnow(),telegram_id)
            )
            return
        await self.execute(
            'INSERT INTO admins(telegram_id,role,password_hash,active,created_at,created_by,parent_admin_id,password_updated_at) VALUES(?,?,?,?,?,?,?,?)',
            (telegram_id,role,password_hash,1,utcnow(),created_by,parent_admin_id,utcnow())
        )

    async def remove_admin(self,telegram_id:int):
        await self.execute("UPDATE admins SET active=0 WHERE telegram_id=?",(telegram_id,))
        await self.invalidate_admin_session(telegram_id)

    async def set_admin_active(self, telegram_id:int, active:bool):
        await self.execute("UPDATE admins SET active=? WHERE telegram_id=?", (1 if active else 0, telegram_id))
        if not active:
            await self.invalidate_admin_session(telegram_id)

    async def admin_session_valid(self,telegram_id:int) -> bool:
        row = await self.fetchone(
            "SELECT authenticated_until FROM admin_sessions WHERE telegram_id=?",
            (telegram_id,)
        )
        if not row:
            return False
        try:
            expires = datetime.fromisoformat(str(row["authenticated_until"]))
        except ValueError:
            await self.invalidate_admin_session(telegram_id)
            return False
        if expires <= datetime.now(timezone.utc):
            await self.invalidate_admin_session(telegram_id)
            return False
        await self.execute(
            "UPDATE admin_sessions SET last_seen_at=? WHERE telegram_id=?",
            (utcnow(), telegram_id)
        )
        return True

    async def authenticated_admin(self,telegram_id:int):
        admin = await self.admin(telegram_id)
        if admin and await self.admin_session_valid(telegram_id):
            return admin
        return None

    async def set_admin_session(self,telegram_id:int,minutes:int=720):
        from datetime import timedelta
        now=utcnow()
        expires=(datetime.now(timezone.utc)+timedelta(minutes=max(5,int(minutes)))).isoformat()
        await self.execute(
            'INSERT INTO admin_sessions(telegram_id,authenticated_until,created_at,last_seen_at) VALUES(?,?,?,?) '
            'ON CONFLICT(telegram_id) DO UPDATE SET '
            'authenticated_until=excluded.authenticated_until,last_seen_at=excluded.last_seen_at',
            (telegram_id,expires,now,now)
        )

    async def invalidate_admin_session(self,telegram_id:int):
        await self.execute("DELETE FROM admin_sessions WHERE telegram_id=?",(telegram_id,))

    async def update_admin_password(self,telegram_id:int,password_hash:str):
        await self.execute(
            "UPDATE admins SET password_hash=?,password_updated_at=?,failed_attempts=0,locked_until=NULL WHERE telegram_id=?",
            (password_hash,utcnow(),telegram_id)
        )
        await self.invalidate_admin_session(telegram_id)

    async def login_state(self,telegram_id:int):
        return await self.fetchone(
            "SELECT failed_attempts,locked_until FROM admins WHERE telegram_id=? AND active=1",
            (telegram_id,)
        )

    async def login_failure(self,telegram_id:int,locked_until:str|None):
        await self.execute(
            "UPDATE admins SET failed_attempts=failed_attempts+1,locked_until=? WHERE telegram_id=?",
            (locked_until,telegram_id)
        )

    async def login_success(self,telegram_id:int):
        await self.execute(
            "UPDATE admins SET failed_attempts=0,locked_until=NULL,last_login_at=? WHERE telegram_id=?",
            (utcnow(),telegram_id)
        )

    async def log_admin(self,admin_id:int,action:str,target:str='',details:str=''):
        await self.execute(
            'INSERT INTO admin_logs(admin_id,action,target,details,timestamp) VALUES(?,?,?,?,?)',
            (admin_id,action,target,details,utcnow())
        )

    async def unique_code(self,code:str)->bool:
        return not bool(await self.fetchone('SELECT 1 FROM movies WHERE LOWER(code)=LOWER(?) UNION SELECT 1 FROM series WHERE LOWER(code)=LOWER(?) UNION SELECT 1 FROM episodes WHERE LOWER(code)=LOWER(?)',(code,code,code)))
    async def genre(self,value:str):
        value=str(value).strip()
        return await self.fetchone('SELECT * FROM genres WHERE id=? OR LOWER(TRIM(name_uz))=LOWER(?) OR LOWER(TRIM(name_ru))=LOWER(?) OR LOWER(TRIM(name_en))=LOWER(?) LIMIT 1',(value,value,value,value))
    async def country(self,value:str):
        value=str(value).strip()
        return await self.fetchone('SELECT * FROM countries WHERE id=? OR LOWER(TRIM(name_uz))=LOWER(?) OR LOWER(TRIM(name_ru))=LOWER(?) OR LOWER(TRIM(name_en))=LOWER(?) LIMIT 1',(value,value,value,value))
    async def genres(self): return await self.fetchall('SELECT * FROM genres WHERE active=1 ORDER BY id')
    async def countries(self): return await self.fetchall('SELECT * FROM countries WHERE active=1 ORDER BY id')

    async def add_movie(self,d:dict[str,Any])->int:
        return int(await self.execute(
            'INSERT INTO movies(code,title,alternative_title,original_title,description,poster_file_id,media_file_id,media_type,content_type,genre_id,country_id,release_year,language,translation_type,rating,duration,age_rating,quality,audio_languages,subtitle_languages,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (d['code'],d['title'],d.get('alternative_title'),d.get('original_title') or d.get('alternative_title'),d.get('description'),d.get('poster_file_id'),d['media_file_id'],d['media_type'],d['content_type'],d.get('genre_id'),d.get('country_id'),d.get('release_year'),d.get('language'),d.get('translation_type'),d.get('rating',0),d.get('duration'),d.get('age_rating'),d.get('quality'),d.get('audio_languages'),d.get('subtitle_languages'),utcnow(),utcnow())
        ))
    async def add_series(self,d:dict[str,Any])->int:
        content_type = d.get('content_type', 'series')
        if content_type not in {'series','anime','cartoon'}:
            raise ValueError('invalid_series_type')
        return int(await self.execute(
            'INSERT INTO series(code,title,alternative_title,original_title,description,poster_file_id,genre_id,country_id,release_year,language,translation_type,content_type,studio,anime_type,status,age_rating,quality,audio_languages,subtitle_languages,rating,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (d['code'],d['title'],d.get('alternative_title'),d.get('original_title') or d.get('alternative_title'),d.get('description'),d.get('poster_file_id'),d.get('genre_id'),d.get('country_id'),d.get('release_year'),d.get('language'),d.get('translation_type'),content_type,d.get('studio'),d.get('anime_type'),d.get('status'),d.get('age_rating'),d.get('quality'),d.get('audio_languages'),d.get('subtitle_languages'),d.get('rating',0),utcnow(),utcnow())
        ))
    async def add_episode(self,series_id:int,season_no:int,ep_no:int,code:str,title:str,description:str,file_id:str,media_type:str,caption:str|None=None,duration:int|None=None)->int:
        s=await self.fetchone('SELECT id FROM seasons WHERE series_id=? AND season_number=?',(series_id,season_no))
        season_id=int(s['id']) if s else int(await self.execute('INSERT INTO seasons(series_id,season_number,title) VALUES(?,?,?)',(series_id,season_no,f'Season {season_no}')))
        return int(await self.execute('INSERT INTO episodes(season_id,code,episode_number,title,description,caption,duration,media_file_id,media_type,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(season_id,code,ep_no,title,description,caption,duration,file_id,media_type,utcnow())))

    async def movie_by_code(self, code: str):
        return await self.fetchone(
            "SELECT m.*,g.name_uz genre_uz,g.name_ru genre_ru,g.name_en genre_en,"
            "c.name_uz country_uz,c.name_ru country_ru,c.name_en country_en "
            "FROM movies m LEFT JOIN genres g ON g.id=m.genre_id LEFT JOIN countries c ON c.id=m.country_id "
            "WHERE LOWER(m.code)=LOWER(?) AND m.active=1 AND m.visibility IN ('public','code_only')",
            (code,),
        )

    async def movie_by_id(self, i: int):
        return await self.fetchone(
            "SELECT m.*,g.name_uz genre_uz,g.name_ru genre_ru,g.name_en genre_en,"
            "c.name_uz country_uz,c.name_ru country_ru,c.name_en country_en "
            "FROM movies m LEFT JOIN genres g ON g.id=m.genre_id LEFT JOIN countries c ON c.id=m.country_id "
            "WHERE m.id=? AND m.active=1 AND m.visibility IN ('public','code_only')",
            (i,),
        )

    async def series_by_code(self, code: str):
        return await self.fetchone(
            "SELECT s.*,g.name_uz genre_uz,g.name_ru genre_ru,g.name_en genre_en,"
            "c.name_uz country_uz,c.name_ru country_ru,c.name_en country_en,"
            "(SELECT COUNT(*) FROM episodes e JOIN seasons ss ON ss.id=e.season_id WHERE ss.series_id=s.id AND e.active=1) episode_count "
            "FROM series s LEFT JOIN genres g ON g.id=s.genre_id LEFT JOIN countries c ON c.id=s.country_id "
            "WHERE LOWER(s.code)=LOWER(?) AND s.active=1 AND s.visibility IN ('public','code_only')",
            (code,),
        )

    async def series_by_id(self, i: int):
        return await self.fetchone(
            "SELECT s.*,g.name_uz genre_uz,g.name_ru genre_ru,g.name_en genre_en,"
            "c.name_uz country_uz,c.name_ru country_ru,c.name_en country_en,"
            "(SELECT COUNT(*) FROM episodes e JOIN seasons ss ON ss.id=e.season_id WHERE ss.series_id=s.id AND e.active=1) episode_count "
            "FROM series s LEFT JOIN genres g ON g.id=s.genre_id LEFT JOIN countries c ON c.id=s.country_id "
            "WHERE s.id=? AND s.active=1 AND s.visibility IN ('public','code_only')",
            (i,),
        )

    async def episode_by_code(self, code: str):
        return await self.fetchone(
            "SELECT e.*,s.series_id,s.season_number,sr.title series_title,sr.code series_code,sr.content_type series_content_type "
            "FROM episodes e JOIN seasons s ON s.id=e.season_id JOIN series sr ON sr.id=s.series_id "
            "WHERE LOWER(e.code)=LOWER(?) AND e.active=1 AND sr.active=1 "
            "AND e.visibility IN ('public','code_only') AND sr.visibility IN ('public','code_only')",
            (code,),
        )

    async def episode_by_id(self, i: int):
        return await self.fetchone(
            "SELECT e.*,s.series_id,s.season_number,sr.title series_title,sr.code series_code,sr.content_type series_content_type "
            "FROM episodes e JOIN seasons s ON s.id=e.season_id JOIN series sr ON sr.id=s.series_id "
            "WHERE e.id=? AND e.active=1 AND sr.active=1 "
            "AND e.visibility IN ('public','code_only') AND sr.visibility IN ('public','code_only')",
            (i,),
        )
    async def seasons(self,series_id:int): return await self.fetchall('SELECT s.*,COUNT(e.id) episode_count FROM seasons s LEFT JOIN episodes e ON e.season_id=s.id AND e.active=1 WHERE s.series_id=? GROUP BY s.id ORDER BY s.season_number',(series_id,))
    async def public_seasons(self,series_id:int):
        return await self.fetchall("SELECT s.*,COUNT(e.id) episode_count FROM seasons s LEFT JOIN episodes e ON e.season_id=s.id AND e.active=1 AND e.visibility='public' WHERE s.series_id=? GROUP BY s.id ORDER BY s.season_number",(series_id,))
    async def public_episodes(self,season_id:int,limit:int|None=None,offset:int=0):
        sql="SELECT * FROM episodes WHERE season_id=? AND active=1 AND visibility='public' ORDER BY episode_number"
        params=[season_id]
        if limit is not None:
            sql += ' LIMIT ? OFFSET ?'
            params.extend([limit,offset])
        return await self.fetchall(sql,tuple(params))
    async def count_public_episodes(self,season_id:int)->int:
        row=await self.fetchone("SELECT COUNT(*) c FROM episodes WHERE season_id=? AND active=1 AND visibility='public'",(season_id,))
        return int(row['c'] or 0)
    async def season(self,series_id:int,season_no:int): return await self.fetchone('SELECT * FROM seasons WHERE series_id=? AND season_number=?',(series_id,season_no))
    async def season_by_id(self, season_id:int):
        return await self.fetchone('SELECT * FROM seasons WHERE id=?',(season_id,))

    async def add_season(self, series_id:int, season_number:int, title:str|None=None)->int:
        if await self.season(series_id,season_number):
            raise ValueError('season_duplicate')
        return int(await self.execute('INSERT INTO seasons(series_id,season_number,title) VALUES(?,?,?)',(series_id,season_number,title)))

    async def update_season(self, season_id:int, **fields):
        allowed={'season_number','title'}
        if not fields or not set(fields) <= allowed: raise ValueError('season_field_not_allowed')
        if 'season_number' in fields:
            row=await self.season_by_id(season_id)
            if not row: raise ValueError('season_not_found')
            duplicate=await self.fetchone('SELECT id FROM seasons WHERE series_id=? AND season_number=? AND id!=?',(row['series_id'],int(fields['season_number']),season_id))
            if duplicate: raise ValueError('season_duplicate')
        assignments=', '.join(f'{k}=?' for k in fields)
        vals=list(fields.values())+[season_id]
        await self.execute(f'UPDATE seasons SET {assignments} WHERE id=?',tuple(vals))

    async def delete_season(self, season_id:int):
        await self.execute('DELETE FROM seasons WHERE id=?',(season_id,))

    async def episodes(self,season_id:int,limit:int|None=None,offset:int=0):
        sql="SELECT * FROM episodes WHERE season_id=? AND active=1 AND visibility IN ('public','code_only') ORDER BY episode_number"
        params=[season_id]
        if limit is not None:
            sql += ' LIMIT ? OFFSET ?'; params.extend([limit,offset])
        return await self.fetchall(sql,tuple(params))
    async def count_episodes(self,season_id:int)->int:
        row=await self.fetchone('SELECT COUNT(*) c FROM episodes WHERE season_id=? AND active=1',(season_id,)); return int(row['c'] or 0)
    async def count_series_episodes(self,series_id:int)->int:
        row=await self.fetchone('SELECT COUNT(*) c FROM episodes e JOIN seasons s ON s.id=e.season_id WHERE s.series_id=? AND e.active=1',(series_id,)); return int(row['c'] or 0)
    async def episode_by_position(self,series_id:int,season_no:int,episode_no:int):
        return await self.fetchone('SELECT e.*,s.series_id,s.season_number,sr.title series_title,sr.code series_code,sr.content_type series_content_type FROM episodes e JOIN seasons s ON s.id=e.season_id JOIN series sr ON sr.id=s.series_id WHERE s.series_id=? AND s.season_number=? AND e.episode_number=?',(series_id,season_no,episode_no))
    async def update_episode(self,episode_id:int,**fields):
        allowed={'title','description','caption','media_file_id','media_type','active'}
        if not fields or not set(fields) <= allowed:
            raise ValueError('episode_field_not_allowed')
        assignments=', '.join(f'{k}=?' for k in fields)
        values=list(fields.values())+[episode_id]
        await self.execute(f'UPDATE episodes SET {assignments} WHERE id=?',tuple(values))
    async def delete_episode(self,episode_id:int):
        await self.execute('DELETE FROM episodes WHERE id=?',(episode_id,))
    async def change_episode_number(self, episode_id:int, new_number:int):
        row=await self.episode_by_id(episode_id)
        if not row: raise ValueError('episode_not_found')
        duplicate=await self.fetchone('SELECT id FROM episodes WHERE season_id=? AND episode_number=? AND id!=?',(row['season_id'],new_number,episode_id))
        if duplicate: raise ValueError('episode_number_conflict')
        await self.execute('UPDATE episodes SET episode_number=? WHERE id=?',(new_number,episode_id))

    async def move_episode(self, episode_id:int, direction:str):
        row=await self.episode_by_id(episode_id)
        if not row: return False
        season_id=int(row['season_id']); current=int(row['episode_number'])
        op='<' if direction=='up' else '>' if direction=='down' else None
        order='DESC' if direction=='up' else 'ASC'
        if not op: return False
        neighbor=await self.fetchone(f'SELECT id,episode_number FROM episodes WHERE season_id=? AND active=1 AND episode_number {op} ? ORDER BY episode_number {order} LIMIT 1',(season_id,current))
        if not neighbor: return False
        neighbor_no=int(neighbor['episode_number'])
        async with self.connect() as db:
            await db.execute('UPDATE episodes SET episode_number=-episode_number-1000000 WHERE id=?',(episode_id,))
            await db.execute('UPDATE episodes SET episode_number=? WHERE id=?',(current,int(neighbor['id'])))
            await db.execute('UPDATE episodes SET episode_number=? WHERE id=?',(neighbor_no,episode_id))
        return True


    async def adjacent_episodes(self,series_id:int,season_no:int,episode_no:int):
        rows=await self.fetchall('SELECT e.id,s.season_number,e.episode_number FROM episodes e JOIN seasons s ON s.id=e.season_id WHERE s.series_id=? AND e.active=1 ORDER BY s.season_number,e.episode_number',(series_id,))
        idx=next((i for i,r in enumerate(rows) if int(r['season_number'])==season_no and int(r['episode_number'])==episode_no),None)
        if idx is None: return None,None
        return (rows[idx-1] if idx>0 else None, rows[idx+1] if idx+1<len(rows) else None)
    async def get_progress(self,user_id:int,series_id:int):
        return await self.fetchone('SELECT * FROM watch_progress WHERE user_id=? AND series_id=?',(user_id,series_id))
    async def set_progress(self,user_id:int,series_id:int,episode_id:int,season_no:int,episode_no:int):
        await self.execute('INSERT INTO watch_progress(user_id,series_id,episode_id,season_number,episode_number,last_watched_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,series_id) DO UPDATE SET episode_id=excluded.episode_id,season_number=excluded.season_number,episode_number=excluded.episode_number,last_watched_at=excluded.last_watched_at',(user_id,series_id,episode_id,season_no,episode_no,utcnow()))
    async def continue_watching(self,user_id:int,limit:int=8):
        return await self.fetchall('''
            SELECT * FROM (
                SELECT p.last_watched_at,p.series_id,p.episode_id,p.season_number,p.episode_number,
                       s.title,s.code,s.content_type,'series' kind,e.title episode_title
                FROM watch_progress p
                JOIN series s ON s.id=p.series_id
                JOIN episodes e ON e.id=p.episode_id
                WHERE p.user_id=? AND s.active=1 AND e.active=1
                  AND datetime(p.last_watched_at)>=datetime('now','-30 day')
                UNION ALL
                SELECT h.viewed_at AS last_watched_at,NULL AS series_id,h.content_id AS episode_id,NULL,NULL,
                       m.title,m.code,m.content_type,'movie' kind,NULL
                FROM watch_history h
                JOIN movies m ON m.id=h.content_id
                WHERE h.user_id=? AND h.content_kind='movie' AND m.active=1
                  AND datetime(h.viewed_at)>=datetime('now','-30 day')
            ) q
            ORDER BY last_watched_at DESC, COALESCE(series_id,episode_id) DESC
            LIMIT ?''',(user_id,user_id,limit))

    async def list_content(self,kind:str,limit:int,offset:int):
        if kind=='movie':
            return await self.fetchall("SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE active=1 AND visibility='public' AND content_type='movie' ORDER BY created_at DESC LIMIT ? OFFSET ?",(limit,offset))
        if kind=='series':
            return await self.fetchall("SELECT id,title,code,content_type,release_year,views_count,'series' kind FROM series WHERE active=1 AND visibility='public' AND content_type='series' ORDER BY created_at DESC LIMIT ? OFFSET ?",(limit,offset))
        if kind=='anime':
            return await self.fetchall("SELECT * FROM (SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE content_type='anime' AND active=1 AND visibility='public' UNION ALL SELECT id,title,code,content_type,release_year,views_count,'series' kind FROM series WHERE content_type='anime' AND active=1 AND visibility='public') q ORDER BY views_count DESC, id DESC LIMIT ? OFFSET ?",(limit,offset))
        if kind=='cartoon':
            return await self.fetchall("SELECT * FROM (SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE content_type='cartoon' AND active=1 AND visibility='public' UNION ALL SELECT id,title,code,content_type,release_year,views_count,'series' kind FROM series WHERE content_type='cartoon' AND active=1 AND visibility='public') q ORDER BY views_count DESC, id DESC LIMIT ? OFFSET ?",(limit,offset))
        if kind=='other':
            return await self.fetchall("SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE content_type='other' AND active=1 AND visibility='public' ORDER BY created_at DESC LIMIT ? OFFSET ?",(limit,offset))
        return []

    async def search(self,q:str,limit:int,offset:int):
        q=str(q).strip()
        like=f'%{q}%'
        sql='''
        SELECT * FROM (
            SELECT m.id,m.title,m.code,m.content_type,m.release_year,m.views_count,'movie' kind,
                   m.alternative_title,m.original_title,m.language,m.translation_type,
                   COALESCE(g.name_uz,'') genre_uz,COALESCE(g.name_ru,'') genre_ru,COALESCE(g.name_en,'') genre_en,
                   COALESCE(c.name_uz,'') country_uz,COALESCE(c.name_ru,'') country_ru,COALESCE(c.name_en,'') country_en
            FROM movies m
            LEFT JOIN genres g ON g.id=m.genre_id
            LEFT JOIN countries c ON c.id=m.country_id
            WHERE m.active=1 AND m.visibility='public' AND (
                m.code LIKE ? OR m.title LIKE ? OR m.alternative_title LIKE ? OR m.original_title LIKE ?
                OR m.language LIKE ? OR m.translation_type LIKE ? OR CAST(m.release_year AS TEXT)=?
                OR g.name_uz LIKE ? OR g.name_ru LIKE ? OR g.name_en LIKE ?
                OR c.name_uz LIKE ? OR c.name_ru LIKE ? OR c.name_en LIKE ?
            )
            UNION ALL
            SELECT s.id,s.title,s.code,s.content_type,s.release_year,s.views_count,'series' kind,
                   s.alternative_title,s.original_title,s.language,s.translation_type,
                   COALESCE(g.name_uz,'') genre_uz,COALESCE(g.name_ru,'') genre_ru,COALESCE(g.name_en,'') genre_en,
                   COALESCE(c.name_uz,'') country_uz,COALESCE(c.name_ru,'') country_ru,COALESCE(c.name_en,'') country_en
            FROM series s
            LEFT JOIN genres g ON g.id=s.genre_id
            LEFT JOIN countries c ON c.id=s.country_id
            WHERE s.active=1 AND s.visibility='public' AND (
                s.code LIKE ? OR s.title LIKE ? OR s.alternative_title LIKE ? OR s.original_title LIKE ?
                OR s.language LIKE ? OR s.translation_type LIKE ? OR CAST(s.release_year AS TEXT)=?
                OR g.name_uz LIKE ? OR g.name_ru LIKE ? OR g.name_en LIKE ?
                OR c.name_uz LIKE ? OR c.name_ru LIKE ? OR c.name_en LIKE ?
            )
            UNION ALL
            SELECT e.id,COALESCE(e.title,sr.title),e.code,'episode',NULL,e.views_count,'episode' kind,
                   NULL,NULL,NULL,NULL,'','','','','',''
            FROM episodes e
            JOIN seasons ss ON ss.id=e.season_id
            JOIN series sr ON sr.id=ss.series_id
            WHERE e.active=1 AND sr.active=1 AND e.visibility='public' AND sr.visibility='public' AND (
                e.code LIKE ? OR e.title LIKE ? OR sr.title LIKE ?
                OR sr.alternative_title LIKE ? OR sr.original_title LIKE ?
            )
        ) q
        ORDER BY 6 DESC, 1 DESC
        LIMIT ? OFFSET ?'''
        params=(like,like,like,like,like,like,q,like,like,like,like,like,like,
                like,like,like,like,like,like,q,like,like,like,like,like,like,
                like,like,like,like,like,limit,offset)
        return await self.fetchall(sql,params)

    async def count_search(self,q:str)->int:
        q=str(q).strip(); like=f'%{q}%'
        sql='''SELECT COUNT(*) c FROM (
            SELECT m.id FROM movies m LEFT JOIN genres g ON g.id=m.genre_id LEFT JOIN countries c ON c.id=m.country_id
            WHERE m.active=1 AND m.visibility='public' AND (m.code LIKE ? OR m.title LIKE ? OR m.alternative_title LIKE ? OR m.original_title LIKE ? OR m.language LIKE ? OR m.translation_type LIKE ? OR CAST(m.release_year AS TEXT)=? OR g.name_uz LIKE ? OR g.name_ru LIKE ? OR g.name_en LIKE ? OR c.name_uz LIKE ? OR c.name_ru LIKE ? OR c.name_en LIKE ?)
            UNION ALL
            SELECT s.id FROM series s LEFT JOIN genres g ON g.id=s.genre_id LEFT JOIN countries c ON c.id=s.country_id
            WHERE s.active=1 AND s.visibility='public' AND (s.code LIKE ? OR s.title LIKE ? OR s.alternative_title LIKE ? OR s.original_title LIKE ? OR s.language LIKE ? OR s.translation_type LIKE ? OR CAST(s.release_year AS TEXT)=? OR g.name_uz LIKE ? OR g.name_ru LIKE ? OR g.name_en LIKE ? OR c.name_uz LIKE ? OR c.name_ru LIKE ? OR c.name_en LIKE ?)
            UNION ALL
            SELECT e.id FROM episodes e JOIN seasons ss ON ss.id=e.season_id JOIN series sr ON sr.id=ss.series_id
            WHERE e.active=1 AND sr.active=1 AND e.visibility='public' AND sr.visibility='public' AND (e.code LIKE ? OR e.title LIKE ? OR sr.title LIKE ? OR sr.alternative_title LIKE ? OR sr.original_title LIKE ?)
        )'''
        params=(like,like,like,like,like,like,q,like,like,like,like,like,like,
                like,like,like,like,like,like,q,like,like,like,like,like,like,
                like,like,like,like,like)
        row=await self.fetchone(sql,params)
        return int(row['c'] or 0)

    async def random_content(self, kind:str='all'):
        if kind == 'movie':
            return await self.fetchone("SELECT id,title,code,content_type,'movie' kind FROM movies WHERE active=1 AND visibility='public' AND content_type='movie' ORDER BY RANDOM() LIMIT 1")
        if kind == 'series':
            return await self.fetchone("SELECT id,title,code,content_type,'series' kind FROM series WHERE active=1 AND visibility='public' AND content_type='series' ORDER BY RANDOM() LIMIT 1")
        if kind == 'anime':
            return await self.fetchone("SELECT * FROM (SELECT id,title,code,content_type,'movie' kind FROM movies WHERE active=1 AND visibility='public' AND content_type='anime' UNION ALL SELECT id,title,code,content_type,'series' kind FROM series WHERE active=1 AND visibility='public' AND content_type='anime') ORDER BY RANDOM() LIMIT 1")
        if kind == 'cartoon':
            return await self.fetchone("SELECT * FROM (SELECT id,title,code,content_type,'movie' kind FROM movies WHERE active=1 AND visibility='public' AND content_type='cartoon' UNION ALL SELECT id,title,code,content_type,'series' kind FROM series WHERE active=1 AND visibility='public' AND content_type='cartoon') ORDER BY RANDOM() LIMIT 1")
        return await self.fetchone("SELECT * FROM (SELECT id,title,code,content_type,'movie' kind FROM movies WHERE active=1 AND visibility='public' UNION ALL SELECT id,title,code,content_type,'series' kind FROM series WHERE active=1 AND visibility='public') ORDER BY RANDOM() LIMIT 1")

    async def total_catalog(self)->int:
        r=await self.fetchone("SELECT (SELECT COUNT(*) FROM movies WHERE active=1 AND visibility='public')+(SELECT COUNT(*) FROM series WHERE active=1 AND visibility='public') c")
        return int(r['c'] or 0)

    async def popular(self,limit:int,offset:int):
        activity = await self.fetchone("SELECT COALESCE((SELECT SUM(views_count) FROM movies WHERE active=1 AND visibility='public'),0) + COALESCE((SELECT SUM(views_count) FROM series WHERE active=1 AND visibility='public'),0) + COALESCE((SELECT SUM(views_count) FROM episodes WHERE active=1 AND visibility='public'),0) AS total")
        if not activity or int(activity["total"] or 0) == 0:
            return await self.newest(limit, offset)
        return await self.fetchall("SELECT * FROM (SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE active=1 AND visibility='public' UNION ALL SELECT id,title,code,content_type,release_year,views_count,'series' kind FROM series WHERE active=1 AND visibility='public') q ORDER BY views_count DESC, id DESC LIMIT ? OFFSET ?",(limit,offset))

    async def newest(self,limit:int,offset:int):
        return await self.fetchall("SELECT * FROM (SELECT id,title,code,content_type,release_year,created_at,'movie' kind FROM movies WHERE active=1 AND visibility='public' UNION ALL SELECT id,title,code,content_type,release_year,created_at,'series' kind FROM series WHERE active=1 AND visibility='public') q ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",(limit,offset))

    async def years(self): return await self.fetchall("SELECT release_year year FROM movies WHERE active=1 AND visibility='public' AND release_year IS NOT NULL UNION SELECT release_year FROM series WHERE active=1 AND visibility='public' AND release_year IS NOT NULL ORDER BY year DESC")
    async def country_filter(self,cid:int,limit:int,offset:int): return await self.fetchall("SELECT * FROM (SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE active=1 AND visibility='public' AND country_id=? UNION ALL SELECT id,title,code,content_type,release_year,views_count,'series' kind FROM series WHERE active=1 AND visibility='public' AND country_id=?) q ORDER BY views_count DESC, id DESC LIMIT ? OFFSET ?",(cid,cid,limit,offset))
    async def genre_filter(self,gid:int,limit:int,offset:int): return await self.fetchall("SELECT * FROM (SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE active=1 AND visibility='public' AND genre_id=? UNION ALL SELECT id,title,code,content_type,release_year,views_count,'series' kind FROM series WHERE active=1 AND visibility='public' AND genre_id=?) q ORDER BY views_count DESC, id DESC LIMIT ? OFFSET ?",(gid,gid,limit,offset))
    async def year_filter(self,year:int,limit:int,offset:int): return await self.fetchall("SELECT * FROM (SELECT id,title,code,content_type,release_year,views_count,'movie' kind FROM movies WHERE active=1 AND visibility='public' AND release_year=? UNION ALL SELECT id,title,code,content_type,release_year,views_count,'series' kind FROM series WHERE active=1 AND visibility='public' AND release_year=?) q ORDER BY views_count DESC, id DESC LIMIT ? OFFSET ?",(year,year,limit,offset))
    async def count_filter(self,field:str,value:int)->int:
        if field not in {'genre_id','country_id','release_year'}:
            raise ValueError('invalid_filter')
        r=await self.fetchone(f"SELECT (SELECT COUNT(*) FROM movies WHERE active=1 AND visibility='public' AND {field}=?) + (SELECT COUNT(*) FROM series WHERE active=1 AND visibility='public' AND {field}=?) c",(value,value))
        return int(r['c'] or 0)


    async def bump_view(self,kind:str,content_id:int,user_id:int):
        table={'movie':'movies','series':'series','episode':'episodes'}[kind]
        await self.execute(f'UPDATE {table} SET views_count=views_count+1 WHERE id=?',(content_id,))
        uid=user_id
        await self.execute('INSERT INTO watch_history(user_id,content_kind,content_id,viewed_at) VALUES(?,?,?,?) ON CONFLICT(user_id,content_kind,content_id) DO UPDATE SET viewed_at=excluded.viewed_at',(uid,kind,content_id,utcnow()))
        await self.log_activity(uid,'view',kind,content_id)
        if kind=='episode':
            e=await self.episode_by_id(content_id)
            if e:
                await self.set_progress(uid,int(e['series_id']),int(e['id']),int(e['season_number']),int(e['episode_number']))
    async def bump_search(self,kind:str,content_id:int):
        table={'movie':'movies','series':'series','episode':'episodes'}.get(kind)
        if table:
            await self.execute(f'UPDATE {table} SET search_count=search_count+1 WHERE id=?',(content_id,))
    async def toggle_saved(self,table:str,user_id:int,kind:str,cid:int)->bool:
        row=await self.fetchone(f'SELECT id FROM {table} WHERE user_id=? AND content_kind=? AND content_id=?',(user_id,kind,cid))
        if row:
            await self.execute(f'DELETE FROM {table} WHERE id=?',(row['id'],)); await self.log_activity(user_id,'remove_'+table,kind,cid); return False
        await self.execute(f'INSERT INTO {table}(user_id,content_kind,content_id,created_at) VALUES(?,?,?,?)',(user_id,kind,cid,utcnow())); await self.log_activity(user_id,'add_'+table,kind,cid); return True
    async def saved(self,table:str,user_id:int,limit:int,offset:int):
        return await self.fetchall(f"""SELECT x.id,x.title,x.code,x.kind,x.content_type FROM {table} s JOIN (
            SELECT id,title,code,'movie' kind,content_type FROM movies WHERE active=1
            UNION ALL SELECT id,title,code,'series' kind,'series' content_type FROM series WHERE active=1
            UNION ALL SELECT e.id,COALESCE(e.title, sr.title),e.code,'episode' kind,'episode' content_type
            FROM episodes e JOIN seasons se ON se.id=e.season_id JOIN series sr ON sr.id=se.series_id
            WHERE e.active=1 AND sr.active=1 AND e.visibility IN ('public','code_only') AND sr.visibility IN ('public','code_only')
        ) x ON x.id=s.content_id AND x.kind=s.content_kind WHERE s.user_id=? ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",(user_id,limit,offset))
    async def history(self,user_id:int,limit:int,offset:int): return await self.fetchall('SELECT * FROM watch_history WHERE user_id=? ORDER BY viewed_at DESC LIMIT ? OFFSET ?',(user_id,limit,offset))
    async def clear_history(self,user_id:int): await self.execute('DELETE FROM watch_history WHERE user_id=?',(user_id,))
    async def is_saved(self,table:str,user_id:int,kind:str,cid:int): return bool(await self.fetchone(f'SELECT 1 FROM {table} WHERE user_id=? AND content_kind=? AND content_id=?',(user_id,kind,cid)))

    async def referrals(self,user_id:int):
        r=await self.fetchone('SELECT COUNT(*) c FROM referrals WHERE referrer_user_id=?',(user_id,)); return int(r['c'] or 0)

    async def expire_bans(self):
        return await self.execute("UPDATE bans SET status='expired' WHERE status='active' AND ban_expires_at IS NOT NULL AND ban_expires_at<=?", (utcnow(),))

    async def active_ban(self, telegram_id:int):
        now = utcnow()
        await self.execute("UPDATE bans SET status='expired' WHERE telegram_id=? AND status='active' AND ban_expires_at IS NOT NULL AND ban_expires_at<=?", (telegram_id, now))
        row = await self.fetchone("SELECT * FROM bans WHERE telegram_id=? AND status='active' AND (ban_expires_at IS NULL OR ban_expires_at>?) ORDER BY id DESC LIMIT 1", (telegram_id, now))
        if row:
            return row
        legacy = await self.fetchone("SELECT * FROM user_blocks WHERE telegram_id=?", (telegram_id,))
        if legacy:
            return {"telegram_id": telegram_id, "ban_started_at": legacy['created_at'], "ban_expires_at": None, "ban_reason": legacy['reason'] or 'Restricted', "banned_by": legacy['created_by'] or 0, "status": 'active', "legacy": 1}
        return None

    async def ban_user(self, telegram_id:int, banned_by:int, reason:str, expires_at:str|None=None):
        await self.execute("UPDATE bans SET status='revoked',revoked_at=? WHERE telegram_id=? AND status='active'", (utcnow(),telegram_id))
        await self.execute("DELETE FROM user_blocks WHERE telegram_id=?", (telegram_id,))
        return int(await self.execute("INSERT INTO bans(telegram_id,ban_started_at,ban_expires_at,ban_reason,banned_by,status) VALUES(?,?,?,?,?,'active')", (telegram_id,utcnow(),expires_at,reason,banned_by)))

    async def unban_user(self, telegram_id:int):
        await self.execute("UPDATE bans SET status='revoked',revoked_at=? WHERE telegram_id=? AND status='active'", (utcnow(),telegram_id))
        await self.execute("DELETE FROM user_blocks WHERE telegram_id=?", (telegram_id,))

    async def banned_users(self,limit:int=50):
        await self.execute("UPDATE bans SET status='expired' WHERE status='active' AND ban_expires_at IS NOT NULL AND ban_expires_at<=?", (utcnow(),))
        return await self.fetchall("SELECT b.*,u.first_name,u.username FROM bans b LEFT JOIN users u ON u.telegram_id=b.telegram_id WHERE b.status='active' ORDER BY b.ban_started_at DESC LIMIT ?", (limit,))

    async def user_stats(self, telegram_id:int):
        u=await self.user(telegram_id)
        if not u: return None
        uid=int(u['id'])
        out=dict(u)
        out['favorites_count']=await self.count_user_list('favorites',uid)
        out['history_count']=await self.count_user_list('watch_history',uid)
        out['referrals_count']=await self.referrals(uid)
        out['tickets_count']=await self.count_user_list('support_tickets',uid)
        out['questions_count']=await self.count_user_list('anonymous_questions',uid)
        out['ban']=await self.active_ban(telegram_id)
        return out

    async def set_admin_permission(self, admin_id:int, permission:str, allowed:bool):
        await self.execute("INSERT INTO admin_permissions(admin_id,permission,allowed,updated_at) VALUES(?,?,?,?) ON CONFLICT(admin_id,permission) DO UPDATE SET allowed=excluded.allowed,updated_at=excluded.updated_at", (admin_id,permission,1 if allowed else 0,utcnow()))

    async def admin_permission_overrides(self, admin_id:int):
        return await self.fetchall("SELECT * FROM admin_permissions WHERE admin_id=?", (admin_id,))

    async def clear_admin_permission(self, admin_id:int, permission:str):
        await self.execute("DELETE FROM admin_permissions WHERE admin_id=? AND permission=?", (admin_id,permission))

    async def create_ticket(self,user_id:int,category:str,message:str)->int:
        tid=int(await self.execute(
            'INSERT INTO support_tickets(user_id,category,message,created_at,updated_at) VALUES(?,?,?,?,?)',
            (user_id,category,message,utcnow(),utcnow())
        ))
        user=await self.fetchone('SELECT telegram_id FROM users WHERE id=?',(user_id,))
        if user:
            await self.execute(
                'INSERT INTO ticket_messages(ticket_id,sender_telegram_id,message,created_at) VALUES(?,?,?,?)',
                (tid,int(user['telegram_id']),message,utcnow())
            )
        return tid

    async def ticket(self,i:int):
        return await self.fetchone(
            'SELECT t.*,u.telegram_id,u.first_name,u.username FROM support_tickets t '
            'JOIN users u ON u.id=t.user_id WHERE t.id=?',(i,)
        )

    async def tickets_by_user(self,user_id:int,limit:int=20,offset:int=0):
        return await self.fetchall(
            'SELECT * FROM support_tickets WHERE user_id=? ORDER BY updated_at DESC LIMIT ? OFFSET ?',
            (user_id,limit,offset)
        )

    async def open_tickets(self):
        return await self.fetchall(
            "SELECT t.*,u.telegram_id,u.first_name,u.username FROM support_tickets t "
            "JOIN users u ON u.id=t.user_id WHERE t.status!='closed' ORDER BY t.updated_at ASC LIMIT 50"
        )

    async def ticket_messages(self,ticket_id:int):
        return await self.fetchall(
            "SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY created_at ASC",
            (ticket_id,)
        )

    async def append_ticket_message(self,ticket_id:int,sender_telegram_id:int,message:str,status:str='in_progress'):
        now=utcnow()
        ticket=await self.ticket(ticket_id)
        if not ticket:
            return False
        await self.execute(
            'INSERT INTO ticket_messages(ticket_id,sender_telegram_id,message,created_at) VALUES(?,?,?,?)',
            (ticket_id,sender_telegram_id,message,now)
        )
        await self.execute(
            "UPDATE support_tickets SET status=?,updated_at=? WHERE id=?",
            (status,now,ticket_id)
        )
        if int(sender_telegram_id) != int(ticket['telegram_id']):
            await self.execute(
                "UPDATE support_tickets SET admin_response=? WHERE id=?",
                (message,ticket_id)
            )
        return True

    async def answer_ticket(self,i:int,admin_id:int,response:str):
        return await self.append_ticket_message(i,admin_id,response,'answered')

    async def create_qa(self,user_id:int,question:str)->int:
        qid=int(await self.execute(
            'INSERT INTO anonymous_questions(user_id,question,created_at,updated_at) VALUES(?,?,?,?)',
            (user_id,question,utcnow(),utcnow())
        ))
        user=await self.fetchone('SELECT telegram_id FROM users WHERE id=?',(user_id,))
        if user:
            await self.execute(
                'INSERT INTO anonymous_messages(question_id,sender_type,sender_id,message,created_at) VALUES(?,?,?,?,?)',
                (qid,'user',int(user['telegram_id']),question,utcnow())
            )
        return qid

    async def question(self,i:int):
        return await self.fetchone(
            'SELECT q.*,u.telegram_id FROM anonymous_questions q JOIN users u ON u.id=q.user_id WHERE q.id=?',
            (i,)
        )

    async def questions(self):
        return await self.fetchall(
            "SELECT q.*,u.telegram_id FROM anonymous_questions q JOIN users u ON u.id=q.user_id "
            "WHERE q.status!='archived' ORDER BY q.updated_at ASC LIMIT 50"
        )

    async def questions_by_user(self,user_id:int,limit:int=20,offset:int=0):
        return await self.fetchall(
            "SELECT * FROM anonymous_questions WHERE user_id=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (user_id,limit,offset)
        )

    async def anonymous_messages(self,question_id:int):
        return await self.fetchall(
            "SELECT * FROM anonymous_messages WHERE question_id=? ORDER BY created_at ASC",
            (question_id,)
        )

    async def append_qa_user_message(self,question_id:int,user_telegram_id:int,message:str):
        question=await self.question(question_id)
        if not question or int(question['telegram_id']) != int(user_telegram_id):
            return False
        now=utcnow()
        await self.execute(
            'INSERT INTO anonymous_messages(question_id,sender_type,sender_id,message,created_at) VALUES(?,?,?,?,?)',
            (question_id,'user',user_telegram_id,message,now)
        )
        await self.execute(
            "UPDATE anonymous_questions SET status='new',updated_at=? WHERE id=?",
            (now,question_id)
        )
        return True

    async def answer_qa(self,i:int,admin_id:int,answer:str):
        question=await self.question(i)
        if not question:
            return False
        now=utcnow()
        await self.execute(
            "UPDATE anonymous_questions SET status='answered',updated_at=? WHERE id=?",
            (now,i)
        )
        await self.execute(
            'INSERT INTO anonymous_answers(question_id,admin_id,answer,created_at) VALUES(?,?,?,?)',
            (i,admin_id,answer,now)
        )
        await self.execute(
            'INSERT INTO anonymous_messages(question_id,sender_type,sender_id,message,created_at) VALUES(?,?,?,?,?)',
            (i,'admin',admin_id,answer,now)
        )
        return True

    async def latest_qa_answer(self,i:int): return await self.fetchone('SELECT * FROM anonymous_answers WHERE question_id=? ORDER BY created_at DESC LIMIT 1',(i,))
    async def publish_qa(self,i:int):
        q=await self.question(i); a=await self.latest_qa_answer(i)
        if not q or not a: return None
        return int(await self.execute('INSERT INTO published_qa(question_id,question_text,answer_text,published_at) VALUES(?,?,?,?)',(i,q['question'],a['answer'],utcnow())))
    async def published(self,limit:int=8,offset:int=0): return await self.fetchall('SELECT * FROM published_qa WHERE active=1 ORDER BY published_at DESC LIMIT ? OFFSET ?',(limit,offset))
    async def published_count(self)->int:
        r=await self.fetchone('SELECT COUNT(*) c FROM published_qa WHERE active=1'); return int(r['c'] or 0)

    async def channels(self): return await self.fetchall('SELECT * FROM channels ORDER BY id')
    async def add_channel(self,name:str,username:str|None,tg_id:int|None,invite:str|None,required:bool=True)->int: return int(await self.execute('INSERT INTO channels(name,username,telegram_id,invite_link,required,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(name,username,tg_id,invite,1 if required else 0,utcnow(),utcnow())))
    async def toggle_channel(self,i:int): await self.execute('UPDATE channels SET active=1-active,updated_at=? WHERE id=?',(utcnow(),i))
    async def delete_channel(self,i:int): await self.execute('DELETE FROM channels WHERE id=?',(i,))

    async def users_for_broadcast(self,target:str,language:str|None=None,ids:list[int]|None=None):
        if target=='selected' and ids:
            marks=','.join('?'*len(ids)); return await self.fetchall(f'SELECT telegram_id FROM users WHERE is_active=1 AND telegram_id IN ({marks})',ids)
        if target=='language': return await self.fetchall('SELECT telegram_id FROM users WHERE is_active=1 AND language=?',(language,))
        if target=='active': return await self.fetchall("SELECT telegram_id FROM users WHERE is_active=1 AND datetime(last_seen_at)>=datetime('now','-7 day')")
        if target=='recent': return await self.fetchall("SELECT telegram_id FROM users WHERE is_active=1 AND datetime(last_seen_at)>=datetime('now','-30 day')")
        return await self.fetchall('SELECT telegram_id FROM users WHERE is_active=1')
    async def create_broadcast(self,admin_id:int,msg_type:str,target:str,ids:list[int])->int:
        bid=int(await self.execute('INSERT INTO broadcasts(admin_id,message_type,target_type,start_time,total_recipients) VALUES(?,?,?,?,?)',(admin_id,msg_type,target,utcnow(),len(ids))))
        await self.executemany('INSERT INTO broadcast_targets(broadcast_id,telegram_id,status) VALUES(?,?,?)',[(bid,i,'pending') for i in ids]); return bid
    async def broadcast_target(self,bid:int,uid:int,status:str,error:str=''): await self.execute('UPDATE broadcast_targets SET status=?,error=? WHERE broadcast_id=? AND telegram_id=?',(status,error,bid,uid))
    async def finish_broadcast(self,bid:int,ok:int,failed:int): await self.execute('UPDATE broadcasts SET successful_count=?,failed_count=?,end_time=? WHERE id=?',(ok,failed,utcnow(),bid))


    async def count_content(self,kind:str)->int:
        if kind=='series':
            r=await self.fetchone("SELECT COUNT(*) c FROM series WHERE active=1 AND visibility='public' AND content_type='series'")
            return int(r['c'] or 0)
        if kind=='anime':
            r=await self.fetchone("SELECT (SELECT COUNT(*) FROM movies WHERE active=1 AND visibility='public' AND content_type='anime') + (SELECT COUNT(*) FROM series WHERE active=1 AND visibility='public' AND content_type='anime') c")
            return int(r['c'] or 0)
        if kind=='movie':
            r=await self.fetchone("SELECT COUNT(*) c FROM movies WHERE active=1 AND visibility='public' AND content_type='movie'")
        elif kind=='cartoon':
            r=await self.fetchone("SELECT (SELECT COUNT(*) FROM movies WHERE active=1 AND visibility='public' AND content_type='cartoon') + (SELECT COUNT(*) FROM series WHERE active=1 AND visibility='public' AND content_type='cartoon') c")
        elif kind=='other':
            r=await self.fetchone("SELECT COUNT(*) c FROM movies WHERE active=1 AND visibility='public' AND content_type='other'")
        else:
            r=await self.fetchone("SELECT COUNT(*) c FROM movies WHERE active=1 AND visibility='public'")
        return int(r['c'] or 0)

    async def update_content(self,kind:str,cid:int,field:str,value):
        allowed={
          'movie': {'title','alternative_title','original_title','description','code','poster_file_id','media_file_id','media_type','genre_id','country_id','release_year','language','translation_type','rating','active','featured','duration','age_rating','quality','audio_languages','subtitle_languages','visibility','moderation_status'},
          'series': {'title','alternative_title','original_title','description','code','poster_file_id','genre_id','country_id','release_year','language','translation_type','rating','active','featured','studio','anime_type','status','age_rating','quality','audio_languages','subtitle_languages','visibility','moderation_status'}
        }
        if field not in allowed.get(kind,set()): raise ValueError('field_not_allowed')
        table='movies' if kind=='movie' else 'series'
        await self.execute(f"UPDATE {table} SET {field}=?,updated_at=? WHERE id=?",(value,utcnow(),cid))

    async def delete_content_by_code(self,code:str):
        r=await self.fetchone('SELECT id FROM movies WHERE code=? AND active=1',(code,))
        if r:
            await self.execute("UPDATE movies SET active=0,updated_at=? WHERE id=?",(utcnow(),r['id'])); return 'movie',int(r['id'])
        r=await self.fetchone('SELECT id FROM series WHERE code=? AND active=1',(code,))
        if r:
            await self.execute("UPDATE series SET active=0,updated_at=? WHERE id=?",(utcnow(),r['id'])); return 'series',int(r['id'])
        r=await self.fetchone('SELECT id FROM episodes WHERE code=? AND active=1',(code,))
        if r:
            await self.execute('DELETE FROM episodes WHERE id=?',(r['id'],)); return 'episode',int(r['id'])
        return None,None

    async def user_by_query(self,q:str):
        q=q.strip().lstrip('@')
        if q.isdigit(): return await self.user(int(q))
        return await self.fetchone('SELECT * FROM users WHERE lower(username)=lower(?)',(q,))

    async def count_user_list(self,table:str,user_id:int)->int:
        r=await self.fetchone(f'SELECT COUNT(*) c FROM {table} WHERE user_id=?',(user_id,)); return int(r['c'] or 0)

    async def history_items(self,user_id:int,limit:int,offset:int):
        return await self.fetchall("""SELECT h.*,COALESCE(m.title,s.title,e.title,'') title,COALESCE(m.code,s.code,e.code,'') code,COALESCE(m.content_type,'series') content_type
        FROM watch_history h LEFT JOIN movies m ON h.content_kind='movie' AND h.content_id=m.id
        LEFT JOIN series s ON h.content_kind='series' AND h.content_id=s.id
        LEFT JOIN episodes e ON h.content_kind='episode' AND h.content_id=e.id
        WHERE h.user_id=? ORDER BY h.viewed_at DESC LIMIT ? OFFSET ?""",(user_id,limit,offset))

    async def logs(self,limit:int=30):
        return await self.fetchall("SELECT * FROM admin_logs ORDER BY timestamp DESC LIMIT ?",(limit,))

    async def broadcasts(self,limit:int=20):
        return await self.fetchall("SELECT * FROM broadcasts ORDER BY id DESC LIMIT ?",(limit,))

    async def notify(self,user_id:int,kind:str,text:str)->None:
        await self.execute('INSERT INTO notifications(user_id,kind,text,created_at) VALUES(?,?,?,?)',(user_id,kind,text,utcnow()))

    async def notifications(self,user_id:int,unread_only:bool=True):
        if unread_only:
            return await self.fetchall('SELECT * FROM notifications WHERE user_id=? AND is_read=0 ORDER BY id DESC LIMIT 50',(user_id,))
        return await self.fetchall('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 50',(user_id,))

    async def mark_notifications_read(self,user_id:int)->None:
        await self.execute('UPDATE notifications SET is_read=1 WHERE user_id=?',(user_id,))

    async def stats(self):
        queries={
            'users':'SELECT COUNT(*) c FROM users',
            'new_today':"SELECT COUNT(*) c FROM users WHERE date(created_at)=date('now')",
            'movies':"SELECT COUNT(*) c FROM movies WHERE active=1 AND content_type='movie'",
            'cartoons':"SELECT COUNT(*) c FROM movies WHERE active=1 AND content_type='cartoon'",
            'anime':"SELECT (SELECT COUNT(*) FROM movies WHERE active=1 AND content_type='anime')+(SELECT COUNT(*) FROM series WHERE active=1 AND content_type='anime') c",
            'series':"SELECT COUNT(*) c FROM series WHERE active=1 AND content_type='series'",
            'episodes':"SELECT COUNT(*) c FROM episodes e JOIN series s ON s.id=(SELECT series_id FROM seasons WHERE id=e.season_id) WHERE e.active=1 AND s.active=1",
            'views_movies':"SELECT COALESCE(SUM(views_count),0) c FROM movies",
            'views_series':"SELECT COALESCE(SUM(views_count),0) c FROM series",
            'views_episodes':"SELECT COALESCE(SUM(views_count),0) c FROM episodes",
            'tickets':"SELECT COUNT(*) c FROM support_tickets WHERE status!='closed'",
            'questions':"SELECT COUNT(*) c FROM anonymous_questions WHERE status!='archived'",
            'referrals':'SELECT COUNT(*) c FROM referrals'
        }
        out={}
        for k,sql in queries.items():
            r=await self.fetchone(sql); out[k]=int(r['c'] or 0)
        out['views']=out.pop('views_movies')+out.pop('views_series')+out.pop('views_episodes')
        return out


    async def activity(self, user_id:int, limit:int=30):
        return await self.fetchall("SELECT * FROM activity_log WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id,limit))

    async def log_activity(self,user_id:int,action:str,content_kind:str|None=None,content_id:int|None=None,details:str|None=None):
        await self.execute("INSERT INTO activity_log(user_id,action,content_kind,content_id,details,created_at) VALUES(?,?,?,?,?,?)", (user_id,action,content_kind,content_id,details,utcnow()))

    async def cinema_passport(self, telegram_id: int):
        u=await self.user(telegram_id)
        if not u: return None
        uid=int(u['id'])
        movies=int((await self.fetchone("SELECT COUNT(*) c FROM watch_history h JOIN movies m ON h.content_kind='movie' AND h.content_id=m.id WHERE h.user_id=? AND m.content_type='movie'",(uid,)))['c'] or 0)
        series=int((await self.fetchone("SELECT COUNT(DISTINCT p.series_id) c FROM watch_progress p JOIN series s ON s.id=p.series_id WHERE p.user_id=? AND s.content_type='series'",(uid,)))['c'] or 0)
        anime=int((await self.fetchone("SELECT COUNT(DISTINCT p.series_id) c FROM watch_progress p JOIN series s ON s.id=p.series_id WHERE p.user_id=? AND s.content_type='anime'",(uid,)))['c'] or 0)
        cartoons=int((await self.fetchone("SELECT COUNT(DISTINCT x.cid) c FROM (SELECT h.content_id cid FROM watch_history h JOIN movies m ON h.content_kind='movie' AND h.content_id=m.id WHERE h.user_id=? AND m.content_type='cartoon' UNION ALL SELECT p.series_id FROM watch_progress p JOIN series s ON s.id=p.series_id WHERE p.user_id=? AND s.content_type='cartoon') x",(uid,uid)))['c'] or 0)
        episodes=int((await self.fetchone("SELECT COUNT(*) c FROM watch_history WHERE user_id=? AND content_kind='episode'",(uid,)))['c'] or 0)
        fav=int((await self.fetchone("SELECT COUNT(*) c FROM favorites WHERE user_id=?",(uid,)))['c'] or 0)
        later=int((await self.fetchone("SELECT COUNT(*) c FROM watch_later WHERE user_id=?",(uid,)))['c'] or 0)
        fav_genre=await self.fetchone("""SELECT g.name_en name,COUNT(*) score FROM favorites f LEFT JOIN movies m ON f.content_kind='movie' AND f.content_id=m.id LEFT JOIN series s ON f.content_kind='series' AND f.content_id=s.id JOIN genres g ON g.id=COALESCE(m.genre_id,s.genre_id) WHERE f.user_id=? GROUP BY g.id ORDER BY score DESC LIMIT 1""",(uid,))
        top_country=await self.fetchone("""SELECT c.name_en name,COUNT(*) score FROM watch_history h LEFT JOIN movies m ON h.content_kind='movie' AND h.content_id=m.id LEFT JOIN series s ON h.content_kind='series' AND h.content_id=s.id JOIN countries c ON c.id=COALESCE(m.country_id,s.country_id) WHERE h.user_id=? GROUP BY c.id ORDER BY score DESC LIMIT 1""",(uid,))
        total=movies+series+anime+cartoons+episodes
        level_key='new_viewer' if total<5 else 'explorer' if total<15 else 'movie_fan' if total<30 else 'cinema_addict' if total<60 else 'cinema_master'
        return {'user':dict(u),'movies':movies,'series':series,'anime':anime,'cartoons':cartoons,'episodes':episodes,'favorites':fav,'watch_later':later,'total':total,'level_key':level_key,'favorite_genre':(fav_genre['name'] if fav_genre else None),'country':(top_country['name'] if top_country else None)}

    async def favorite_genres(self, user_id: int, limit: int = 5):
        return await self.fetchall(
            "SELECT id,name_uz,name_ru,name_en,SUM(score) score FROM ("
            "SELECT g.id,g.name_uz,g.name_ru,g.name_en,COUNT(*) score "
            "FROM favorites f JOIN movies m ON f.content_kind='movie' AND f.content_id=m.id "
            "JOIN genres g ON g.id=m.genre_id WHERE f.user_id=? GROUP BY g.id "
            "UNION ALL "
            "SELECT g.id,g.name_uz,g.name_ru,g.name_en,COUNT(*) score "
            "FROM favorites f JOIN series s ON f.content_kind='series' AND f.content_id=s.id "
            "JOIN genres g ON g.id=s.genre_id WHERE f.user_id=? GROUP BY g.id) q "
            "GROUP BY id,name_uz,name_ru,name_en ORDER BY score DESC,id LIMIT ?",
            (user_id,user_id,limit),
        )

    async def moods(self):
        return await self.fetchall("SELECT * FROM moods WHERE active=1 ORDER BY id")

    async def mood(self,mood_id:int): return await self.fetchone("SELECT * FROM moods WHERE id=? AND active=1",(mood_id,))

    async def mood_genre_ids(self,mood_id:int):
        return [int(r['genre_id']) for r in await self.fetchall("SELECT genre_id FROM mood_genres WHERE mood_id=?",(mood_id,))]

    async def mood_content(self,mood_id:int,limit:int=8,offset:int=0):
        gids=await self.mood_genre_ids(mood_id)
        if not gids: return []
        marks=','.join('?'*len(gids)); params=gids+gids+[limit,offset]
        return await self.fetchall(f"""SELECT * FROM (\
            SELECT m.id,m.title,m.code,m.content_type,m.release_year,m.views_count,'movie' kind,m.genre_id,m.created_at FROM movies m WHERE m.active=1 AND m.visibility='public' AND m.genre_id IN ({marks})\
            UNION ALL SELECT s.id,s.title,s.code,s.content_type,s.release_year,s.views_count,'series' kind,s.genre_id,s.created_at FROM series s WHERE s.active=1 AND s.visibility='public' AND s.genre_id IN ({','.join('?'*len(gids))})\
        ) q ORDER BY views_count DESC, created_at DESC LIMIT ? OFFSET ?""", tuple(params))

    async def tonight_pick(self,user_id:int):
        prefs=await self.favorite_genres(user_id,5)
        gids=[int(r['id']) for r in prefs]
        base=[]
        if gids:
            marks=','.join('?'*len(gids))
            base=await self.fetchall(f"""SELECT * FROM (SELECT m.id,m.title,m.code,m.content_type,m.release_year,m.views_count,'movie' kind,m.genre_id,m.created_at FROM movies m WHERE m.active=1 AND m.visibility='public' AND m.genre_id IN ({marks}) UNION ALL SELECT s.id,s.title,s.code,s.content_type,s.release_year,s.views_count,'series' kind,s.genre_id,s.created_at FROM series s WHERE s.active=1 AND s.visibility='public' AND s.genre_id IN ({marks})) q ORDER BY views_count DESC,created_at DESC LIMIT 30""", tuple(gids+gids))
        if not base:
            base=await self.newest(30,0)
        if not base: return None
        # Deterministic-ish weighted pick using stable current timestamp bucket and scores.
        idx=int(datetime.now(timezone.utc).timestamp()//3600) % len(base)
        return base[idx]

    async def trending(self,period_days:int=7,limit:int=8,offset:int=0):
        days=int(period_days)
        if days <= 0:
            recent_movie = "COALESCE((SELECT COUNT(*) FROM watch_history h WHERE h.content_kind='movie' AND h.content_id=m.id),0)"
            recent_series = "COALESCE((SELECT COUNT(*) FROM watch_history h WHERE h.content_kind='series' AND h.content_id=s.id),0)"
            params=(limit,offset)
        else:
            since=f"-{days} day"
            recent_movie = "COALESCE((SELECT COUNT(*) FROM watch_history h WHERE h.content_kind='movie' AND h.content_id=m.id AND datetime(h.viewed_at)>=datetime('now',?)),0)"
            recent_series = "COALESCE((SELECT COUNT(*) FROM watch_history h WHERE h.content_kind='series' AND h.content_id=s.id AND datetime(h.viewed_at)>=datetime('now',?)),0)"
            params=(since,since,limit,offset)
        return await self.fetchall(f"""SELECT * FROM (
        SELECT m.id,m.title,m.code,m.content_type,m.release_year,m.views_count,'movie' kind,
               {recent_movie} recent,m.featured,m.created_at
        FROM movies m WHERE m.active=1 AND m.visibility='public'
        UNION ALL
        SELECT s.id,s.title,s.code,s.content_type,s.release_year,s.views_count,'series' kind,
               {recent_series} recent,s.featured,s.created_at
        FROM series s WHERE s.active=1 AND s.visibility='public'
        ) q ORDER BY (recent*6 + views_count + featured*2) DESC, created_at DESC, id DESC LIMIT ? OFFSET ?""", params)

    async def toggle_follow(self,user_id:int,series_id:int)->bool:
        row=await self.fetchone("SELECT 1 FROM follows WHERE user_id=? AND series_id=?",(user_id,series_id))
        if row:
            await self.execute("DELETE FROM follows WHERE user_id=? AND series_id=?",(user_id,series_id)); return False
        await self.execute("INSERT INTO follows(user_id,series_id,created_at) VALUES(?,?,?)",(user_id,series_id,utcnow())); return True

    async def is_following(self,user_id:int,series_id:int)->bool:
        return bool(await self.fetchone("SELECT 1 FROM follows WHERE user_id=? AND series_id=?",(user_id,series_id)))

    async def followers_of(self,series_id:int):
        return await self.fetchall("SELECT u.* FROM follows f JOIN users u ON u.id=f.user_id WHERE f.series_id=? AND u.is_active=1",(series_id,))

    async def notifications_enabled(self,user_id:int,key:str)->bool:
        row=await self.fetchone("SELECT enabled FROM notification_preferences WHERE user_id=? AND key=?",(user_id,key))
        return bool(int(row['enabled'])) if row else True

    async def set_notification(self,user_id:int,key:str,enabled:bool):
        await self.execute("INSERT INTO notification_preferences(user_id,key,enabled) VALUES(?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET enabled=excluded.enabled",(user_id,key,1 if enabled else 0))

    async def notification_preferences(self,user_id:int):
        keys=['new_releases','new_episodes','new_movies','new_anime','trending','daily_cinema']
        out={}
        for k in keys: out[k]=await self.notifications_enabled(user_id,k)
        return out

    async def report(self,user_id:int,kind:str,cid:int,report_type:str,message:str|None=None)->int:
        return int(await self.execute("INSERT INTO content_reports(user_id,content_kind,content_id,report_type,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(user_id,kind,cid,report_type,message,utcnow(),utcnow())))

    async def reports(self,status:str='open',limit:int=50):
        return await self.fetchall("SELECT r.*,u.telegram_id,u.first_name,u.username FROM content_reports r JOIN users u ON u.id=r.user_id WHERE r.status=? ORDER BY r.updated_at ASC LIMIT ?",(status,limit))

    async def report_by_id(self,rid:int): return await self.fetchone("SELECT r.*,u.telegram_id,u.first_name,u.username FROM content_reports r JOIN users u ON u.id=r.user_id WHERE r.id=?",(rid,))

    async def resolve_report(self,rid:int,admin_id:int,status:str):
        if status not in {'pending','resolved','rejected'}: raise ValueError('invalid_report_status')
        await self.execute("UPDATE content_reports SET status=?,handled_by=?,updated_at=? WHERE id=?",(status,admin_id,utcnow(),rid))

    async def collections(self,limit:int=50,offset:int=0): return await self.fetchall("SELECT * FROM collections WHERE active=1 ORDER BY created_at DESC LIMIT ? OFFSET ?",(limit,offset))
    async def collection(self,cid:int): return await self.fetchone("SELECT * FROM collections WHERE id=? AND active=1",(cid,))
    async def collection_count(self)->int: return int((await self.fetchone("SELECT COUNT(*) c FROM collections WHERE active=1"))['c'] or 0)
    async def add_collection(self,title:str,description:str|None=None,poster_file_id:str|None=None)->int: return int(await self.execute("INSERT INTO collections(title,description,poster_file_id,created_at,updated_at) VALUES(?,?,?,?,?)",(title,description,poster_file_id,utcnow(),utcnow())))
    async def update_collection(self,cid:int,**fields):
        allowed={'title','description','poster_file_id','active'}; data={k:v for k,v in fields.items() if k in allowed}
        if not data: return
        sets=','.join(f'{k}=?' for k in data); vals=list(data.values())+[utcnow(),cid]
        await self.execute(f"UPDATE collections SET {sets},updated_at=? WHERE id=?",vals)
    async def delete_collection(self,cid:int): await self.update_collection(cid,active=0)
    async def collection_items(self,cid:int,limit:int=20,offset:int=0):
        return await self.fetchall("""SELECT ci.*,COALESCE(m.title,s.title,e.title,'') title,COALESCE(m.code,s.code,e.code,'') code,COALESCE(m.content_type,s.content_type,'episode') content_type FROM collection_items ci
        LEFT JOIN movies m ON ci.content_kind='movie' AND ci.content_id=m.id
        LEFT JOIN series s ON ci.content_kind='series' AND ci.content_id=s.id
        LEFT JOIN episodes e ON ci.content_kind='episode' AND ci.content_id=e.id
        WHERE ci.collection_id=? ORDER BY ci.position ASC,ci.id ASC LIMIT ? OFFSET ?""",(cid,limit,offset))
    async def add_collection_item(self,cid:int,kind:str,content_id:int)->bool:
        pos=int((await self.fetchone("SELECT COALESCE(MAX(position),-1)+1 p FROM collection_items WHERE collection_id=?",(cid,)))['p'])
        try:
            await self.execute("INSERT INTO collection_items(collection_id,content_kind,content_id,position) VALUES(?,?,?,?)",(cid,kind,content_id,pos)); return True
        except Exception: return False
    async def remove_collection_item(self,item_id:int): await self.execute("DELETE FROM collection_items WHERE id=?",(item_id,))
    async def move_collection_item(self,item_id:int,direction:str)->bool:
        row=await self.fetchone("SELECT * FROM collection_items WHERE id=?",(item_id,));
        if not row: return False
        op='<' if direction=='up' else '>'
        order='DESC' if direction=='up' else 'ASC'
        neighbor=await self.fetchone(f"SELECT * FROM collection_items WHERE collection_id=? AND position {op} ? ORDER BY position {order} LIMIT 1",(row['collection_id'],row['position']))
        if not neighbor: return False
        async with self.connect() as con:
            await con.execute('UPDATE collection_items SET position=-position-1000000 WHERE id=?',(item_id,))
            await con.execute('UPDATE collection_items SET position=? WHERE id=?',(row['position'],neighbor['id']))
            await con.execute('UPDATE collection_items SET position=? WHERE id=?',(neighbor['position'],item_id))
        return True

    async def release_items(self,limit:int=20,offset:int=0):
        return await self.fetchall("SELECT * FROM release_calendar WHERE active=1 AND datetime(release_at)>=datetime('now') ORDER BY release_at ASC LIMIT ? OFFSET ?",(limit,offset))
    async def add_release(self,kind:str,cid:int,release_at:str,title:str|None=None,season_number:int|None=None,episode_number:int|None=None)->int:
        return int(await self.execute("INSERT OR IGNORE INTO release_calendar(content_kind,content_id,season_number,episode_number,release_at,title,created_at) VALUES(?,?,?,?,?,?,?)",(kind,cid,season_number,episode_number,release_at,title,utcnow())))

    async def daily_pick(self,user_id:int):
        day=datetime.now(timezone.utc).date().isoformat()
        row=await self.fetchone("SELECT * FROM daily_picks WHERE user_id=? AND day=?",(user_id,day))
        if row: return row
        pick=await self.tonight_pick(user_id)
        if not pick: return None
        await self.execute("INSERT OR IGNORE INTO daily_picks(user_id,day,content_kind,content_id,created_at) VALUES(?,?,?,?,?)",(user_id,day,pick['kind'],int(pick['id']),utcnow()))
        return await self.fetchone("SELECT * FROM daily_picks WHERE user_id=? AND day=?",(user_id,day))

    async def universal_lookup(self,code:str):
        code=code.strip()
        m=await self.movie_by_code(code)
        if m: return 'movie',m
        s=await self.series_by_code(code)
        if s: return 'series',s
        e=await self.episode_by_code(code)
        if e: return 'episode',e
        return None,None



    async def content_by_kind_id(self, kind: str, content_id: int, *, public_only: bool = True):
        if kind == 'movie':
            extra = " AND m.visibility='public'" if public_only else ""
            return await self.fetchone(f"SELECT m.*,g.name_uz genre_uz,g.name_ru genre_ru,g.name_en genre_en,c.name_uz country_uz,c.name_ru country_ru,c.name_en country_en FROM movies m LEFT JOIN genres g ON g.id=m.genre_id LEFT JOIN countries c ON c.id=m.country_id WHERE m.id=? AND m.active=1{extra}", (content_id,))
        if kind == 'series':
            extra = " AND s.visibility='public'" if public_only else ""
            return await self.fetchone(f"SELECT s.*,g.name_uz genre_uz,g.name_ru genre_ru,g.name_en genre_en,c.name_uz country_uz,c.name_ru country_ru,c.name_en country_en,(SELECT COUNT(*) FROM episodes e JOIN seasons ss ON ss.id=e.season_id WHERE ss.series_id=s.id AND e.active=1) episode_count FROM series s LEFT JOIN genres g ON g.id=s.genre_id LEFT JOIN countries c ON c.id=s.country_id WHERE s.id=? AND s.active=1{extra}", (content_id,))
        if kind == 'episode':
            extra = " AND e.visibility='public' AND sr.visibility='public'" if public_only else ""
            return await self.fetchone(f"SELECT e.*,s.series_id,s.season_number,sr.title series_title,sr.code series_code,sr.content_type series_content_type FROM episodes e JOIN seasons s ON s.id=e.season_id JOIN series sr ON sr.id=s.series_id WHERE e.id=? AND e.active=1 AND sr.active=1{extra}", (content_id,))
        return None

    async def search_history(self, user_id: int, limit: int = 20):
        return await self.fetchall("SELECT * FROM search_history WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id,limit))
    async def search_history_item(self, user_id: int, item_id: int):
        return await self.fetchone("SELECT * FROM search_history WHERE id=? AND user_id=?", (item_id,user_id))


    async def clear_search_history(self, user_id: int):
        await self.execute("DELETE FROM search_history WHERE user_id=?", (user_id,))

    async def notification_categories(self):
        return ('new_releases','new_episodes','new_movies','new_anime','trending','daily_cinema')

    async def report_count(self, status: str = 'open') -> int:
        row=await self.fetchone("SELECT COUNT(*) c FROM content_reports WHERE status=?", (status,))
        return int(row['c'] or 0)

    async def release_count(self) -> int:
        row=await self.fetchone("SELECT COUNT(*) c FROM release_calendar WHERE active=1 AND datetime(release_at)>=datetime('now')")
        return int(row['c'] or 0)

    async def deactivate_release(self, release_id:int):
        await self.execute("UPDATE release_calendar SET active=0 WHERE id=?", (release_id,))

    async def set_visibility(self, kind:str, content_id:int, visibility:str):
        if visibility not in {'public','code_only','hidden'}: raise ValueError('invalid_visibility')
        table={'movie':'movies','series':'series','episode':'episodes'}.get(kind)
        if not table: raise ValueError('invalid_content_kind')
        await self.execute(f"UPDATE {table} SET visibility=? WHERE id=?", (visibility,content_id))

    async def set_moderation_status(self, kind:str, content_id:int, status:str):
        if status not in {'verified','needs_review','reported'}: raise ValueError('invalid_moderation_status')
        table={'movie':'movies','series':'series','episode':'episodes'}.get(kind)
        if not table: raise ValueError('invalid_content_kind')
        await self.execute(f"UPDATE {table} SET moderation_status=? WHERE id=?", (status,content_id))

    async def media_sources_for(self, kind:str, content_id:int):
        return await self.fetchall("SELECT * FROM media_sources WHERE content_kind=? AND content_id=? AND active=1 ORDER BY id", (kind,content_id))

    async def add_media_source(self, kind:str, content_id:int, label:str, file_id:str, media_type:str):
        await self.execute("INSERT INTO media_sources(content_kind,content_id,label,file_id,media_type) VALUES(?,?,?,?,?) ON CONFLICT(content_kind,content_id,label) DO UPDATE SET file_id=excluded.file_id,media_type=excluded.media_type,active=1", (kind,content_id,label,file_id,media_type))

    async def delete_media_source(self, source_id:int):
        await self.execute("UPDATE media_sources SET active=0 WHERE id=?", (source_id,))

    async def compare_items(self, first:tuple[str,int], second:tuple[str,int]):
        out=[]
        for kind,cid in (first,second):
            item=await self.content_by_kind_id(kind,cid)
            out.append((kind,item))
        return out
    async def cleanup(self):
        await self.expire_bans()
        await self.execute("DELETE FROM admin_sessions WHERE authenticated_until<=?",(utcnow(),))
        await self.execute("DELETE FROM notifications WHERE created_at < datetime('now','-90 day')")
