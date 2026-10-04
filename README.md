# CineviaXMovieBot — Ultimate Professional Telegram Cinema Platform

CineviaXMovieBot is a modular Telegram cinema platform built for Python 3.12+, aiogram 3.x, aiosqlite, SQLite, python-dotenv, async FSM flows, inline/reply keyboards and structured logging. It is designed around real handlers and database operations rather than demo-only UI.

## Core features

### Users
- Four distinct content experiences: Movies, Series, Anime and Cartoons; cartoons may be single-video or episodic.
- Smart search by code, title, original/alternative title, language, genre, country and year; result buttons show content type.
- Category-specific detail cards, watch, favorites, Watch Later, recent Continue Watching and category-aware share deep-links.
- Series → seasons → episodes.
- Popular, new releases and practical recommendations from real database signals.
- Genres, countries and years.
- Profiles and Telegram deep-link referrals.
- Support tickets with replies and ticket history.
- Anonymous Q&A with private sender routing and optional anonymized public Q&A.
- Uzbek, Russian and English UI with centralized JSON localization.
- Mandatory channel subscriptions managed from the admin panel.

### Private admin control center
Roles: `CEO`, `Katta Admin`, `Oddiy Admin`.

- **CEO**: full control, admin management, security/password reset, settings and all operational sections.
- **Katta Admin**: content, channels, users, tickets, anonymous Q&A, broadcasts, statistics, logs and genres.
- **Oddiy Admin**: content, incoming questions/tickets, anonymous Q&A and statistics. Destructive content deletion and admin-management operations are not available.

Admin access is protected by a password session. The `/admin` and `/sdd` entry points are not part of the ordinary user's command menu. An authorized admin first sees their role and then must enter the password. Sessions expire automatically. Failed password attempts can trigger a temporary lock.

Each admin can change their own password. The CEO can reset another administrator's password. Passwords are stored as PBKDF2-SHA256 hashes, never as plain text.

Sensitive callback actions re-check the authenticated session and current role before executing.

Admin tools include content add/edit/delete, series/episode management, channel management, user lookup and restriction, support/Q&A replies, broadcast targeting, statistics, settings, maintenance mode, audit logs and moderation.

## Architecture

```text
CineviaXMovieBot/
├── main.py
├── config.py
├── .env.example
├── requirements.txt
├── README.md
├── .gitignore
├── database/
│   ├── __init__.py
│   └── db.py
├── handlers/
├── keyboards/
├── locales/
│   ├── uz.json
│   ├── ru.json
│   └── en.json
├── services/
├── states/
├── utils/
├── tests/
└── deploy/
```


## Production security upgrades

- Required-channel checks are performed live against every active channel marked `required=1`; missing channels remain blocking until all required memberships are verified.
- Temporary and permanent user bans are stored with reason, issuer and expiration. Expired bans are cleaned automatically in the running process and also lazily on access.
- Granular admin permissions can override the default role permissions for non-CEO administrators. Sensitive handlers re-check the permission before the action.
- Content management buttons are filtered using effective permissions, not only the role name.

## Database

SQLite initializes automatically. Main tables include:

`users`, `movies`, `series`, `seasons`, `episodes`, `genres`, `countries`, `favorites`, `watch_later`, `watch_history`, `channels`, `referrals`, `support_tickets`, `ticket_messages`, `anonymous_questions`, `anonymous_answers`, `published_qa`, `admins`, `broadcasts`, `broadcast_targets`, `bot_settings`, `admin_logs`, `search_history`, `notifications`, `user_blocks`.

The schema uses foreign keys, indexes, unique constraints, status fields and timestamps.

## Installation — Windows

### 1. Python
Use Python 3.12+.

### 2. Virtual environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. `.env`

Copy `.env.example` to `.env` and fill it in:

```env
BOT_TOKEN=YOUR_BOT_TOKEN
DATABASE_PATH=movies.db
CEO_OWNER_ID=YOUR_TELEGRAM_ID
CEO_INITIAL_PASSWORD=CHANGE_THIS_TO_A_STRONG_PASSWORD
BOT_USERNAME=CineviaXMovieBot
LOG_LEVEL=INFO
DEFAULT_LANGUAGE=uz
PAGINATION_SIZE=8
ADMIN_SESSION_MINUTES=720
ADMIN_LOGIN_MAX_ATTEMPTS=5
ADMIN_LOGIN_LOCK_MINUTES=15
```

Never commit `.env`. Never put a bot token in Python source.

### 4. Run

```powershell
python main.py
```

Only one process should poll one Telegram bot token at a time.

## Admin setup

Set `CEO_OWNER_ID` to the primary CEO Telegram ID and set a strong `CEO_INITIAL_PASSWORD`. After startup, run `/admin` from that Telegram account. The bot shows the CEO role and asks for the password.

There are exactly three supported roles: **CEO**, **Katta Admin**, and **Oddiy Admin**. A CEO can add administrators by Telegram ID, choose the role, and set an initial password. Maximum active CEO accounts: 3.

Admin command scope is installed only after a successful admin login and removed after logout/deactivation. Ordinary users keep only the public command menu.

## Adding content

From **Admin Panel → Content Management → Add Content**:

1. Title
2. Unique code
3. Type
4. Alternative title
5. Description
6. Poster or `/skip`
7. Telegram media
8. Genre
9. Country
10. Release year
11. Language
12. Translation/dubbing type
13. Rating
14. Preview
15. Confirmation
16. Save

Supported content types: movie, anime, cartoon, other. Series use a separate series/season/episode flow.

## Content codes

Examples:

```text
K12345  # movie
S12345  # series
A12345  # anime
M12345  # cartoon
```

A user can send any supported code directly; the bot checks the matching content automatically. Deep links preserve the content type prefix where available.

## Mandatory channels

From **Admin Panel → Channels → Add Channel**, enter:

```text
Channel Name | @username or -100... | invite_link
```

The bot should be an administrator in the required channel so membership checks can work. Channels are stored in the database; they are not hardcoded in Python.

## Support, Questions and Anonymous Q&A

Users have a persistent **Questions / Savollarim / Мои вопросы** area in the bottom menu. It combines their support tickets and anonymous questions into one place.

Each ticket/question keeps a message thread. Users can continue writing after an admin reply, and authorized admins receive the new message in the **Incoming Questions / Kelgan savollar** area. Admin replies are delivered back to the same user, so the conversation can continue without creating a new ticket every time.

Anonymous questions keep the real Telegram ID private for routing and moderation. The sender identity is not displayed to ordinary users and must not be published in public Q&A.

## Broadcasting

Broadcast uses Telegram message copying for broad message-type compatibility. The admin can preview and confirm broadcasts, choose target groups, and inspect successful/failed delivery totals. Telegram rate limits and failed deliveries are handled by the broadcast service.

## Statistics and logs

Statistics are read from database values, not placeholders. Admin logs capture important actions but never BOT_TOKEN values.

## Settings and maintenance

Database-backed settings cover bot title, welcome text, support, anonymous Q&A, referrals, default language, pagination size and maintenance mode. Authorized admins can continue using the bot during maintenance.

## PyCharm

1. Open the project folder.
2. Choose `.venv` as the interpreter.
3. Keep `.env` beside `main.py`.
4. Run `main.py`.
5. Stop other processes using the same bot token if you see `TelegramConflictError`.

## VS Code

1. Open the project folder.
2. Select `.venv\Scripts\python.exe`.
3. Activate the terminal environment.
4. Run `python main.py`.

## Linux VPS / 24×7

Recommended structure:

```text
/opt/cineviax/
├── .venv/
├── .env
├── main.py
├── movies.db
└── ...
```

Use the included `deploy/cineviax.service` with systemd and `deploy/backup.sh` for database backups. Keep the database on persistent disk. Configure environment variables through `.env` or systemd environment settings. `Restart=always` can restart the process after failure. A VPS provides practical always-on hosting; do not assume that every free hosting provider offers permanent 24/7 operation.

## Backup

Example:

```bash
./deploy/backup.sh
```

Keep multiple backup generations off the live database machine when possible.

## Troubleshooting

### `BOT_TOKEN topilmadi`
Check that `.env` exists beside `main.py` and contains a real BotFather token:

```text
BOT_TOKEN=...
```

### `TelegramConflictError`
Only one polling instance may use the same bot token. Stop the other Python process, PyCharm run session or VPS service.

### `ModuleNotFoundError`
Activate the project virtual environment and run:

```powershell
python -m pip install -r requirements.txt
```

### Channel check fails
The bot should be an administrator in the channel and the stored channel ID/username should be valid.

## Security

- Keep BOT_TOKEN only in `.env`.
- Keep `.env` in `.gitignore`.
- Use Telegram IDs for authorization.
- Re-check permissions in sensitive callbacks.
- Use parameterized SQL.
- Validate user input and callback data.
- Rate-limit abusive request bursts.
- Protect anonymous sender identity.
- Do not log secrets.

## Testing

Run:

```powershell
python tests/run_tests.py
```

The included static test suite checks Python syntax, locale key parity, database schema, callback prefix coverage, and secret placeholders. Live Telegram API E2E tests require a real environment with an installed dependency set and bot token; they are intentionally not faked.

## PostgreSQL migration path

Keep SQL centralized in `database/db.py`, preserve logical repository methods, replace SQLite-specific connection details, and migrate data in a controlled maintenance window. The handler/service layers should not need to know the underlying database engine.

## Admin access and hidden commands

`/admin` and `/sdd` are private entry commands. They are not included in the default user command menu. Only users present in the `admins` table with `active=1` receive the admin command scope. The configured `CEO_OWNER_ID` is provisioned as the owner at startup.

To add an administrator, open `Admin Panel -> Admin Management -> Add`, enter the target Telegram ID, choose `CEO`, `Katta Admin`, or `Oddiy Admin`, and set the initial password. The new admin must then run `/admin`, see their assigned role, and authenticate with that password. When an admin is removed or logs out, the chat command scope is reset to the public user commands.

## Search

Users can search in two ways: press `🔍 Search` and enter a query, or simply send a movie code/title in the chat. A valid code opens the matching content directly; other text is treated as a title/metadata search.

## Multi-episode Series & Anime

The project supports multi-episode `series` and `anime` content without duplicating the parent content record for every episode.

Flow:

`Main code -> content details -> seasons -> paginated episodes -> episode media -> previous/next -> back to series`

Highlights:

- Series and anime each use one parent code.
- Existing one-video anime records in `movies` remain compatible.
- New multi-episode anime is stored in the `series` table with `content_type='anime'`.
- Seasons are created automatically when the first episode is added.
- Episode lists use pagination instead of hundreds of inline buttons.
- Previous/next navigation crosses season boundaries.
- `Continue Watching` stores the latest episode per user and series.
- Admins can add, edit, replace media/caption, and delete episodes.
- Episode codes are globally unique against movies, series, and other episodes.

### Database migration

On startup the bot upgrades an older database in place by adding the `series.content_type`, `episodes.caption`, `episodes.duration`, and `watch_progress` structures when they are missing. Existing user/content records are not intentionally deleted by this migration.


## Latest audit result

The latest maintenance pass focused on root-cause user-side failures rather than masking the generic technical-error response. The current codebase was checked for Python parse errors, database-method references, locale parity, SQL behavior, callback coverage and security-related structures.

Recent fixes include:
- exact code detection before treating normal text as a code;
- search pagination and safe UNION ordering;
- duplicate callback acknowledgement in history pagination;
- case/whitespace-insensitive genre and country lookup;
- permission-aware support ticket and anonymous Q&A actions;
- safer channel and genre deletion confirmation;
- paginated genres, countries, years and published Q&A;
- localized validation/status messages.

Verified in the build environment:
- AST parse: PASS
- database-method mapping (106 referenced methods): PASS
- locale parity (UZ/RU/EN): PASS
- static test suite: PASS
- SQLite smoke test: PASS
- real Telegram API end-to-end runtime: NOT VERIFIED in this environment because outbound package installation/network access is unavailable.


## Advanced deterministic features
- Cinema Passport with database-backed levels
- Mood discovery and deterministic recommendations
- Tonight/Daily picks
- Trending Radar
- Collections and collection ordering
- Release Calendar
- Notification preferences and followed series
- Content reports and moderation metadata
- Search history and discovery filters
- No AI/LLM dependencies

## Admin hierarchy
- CEO: full control.
- Senior Admin (Katta Admin): can manage at most one active Junior Admin.
- Junior Admin (Kichik Admin): cannot create or manage other administrators.
- Junior permissions are always limited by the Senior parent's effective permissions.
- All sensitive actions are validated server-side and recorded in audit logs.

## Latest maintenance pass — October 2026

This build was audited from the existing CineviaXMovieBot codebase rather than generated as a separate replacement project.

### Root-cause fixes
- Replaced unsupported direct `Connection.execute_fetchone/execute_fetchall` usage with cursor-based helpers inside the existing `Database` abstraction.
- Added the missing `logging` import/logger used by the security middleware error path.
- Added missing `datetime` import required by release-calendar administration.

### UX and navigation
- Removed `➕ More` from the primary user keyboard.
- Added direct `Discover`, `My Cinema`, `Questions`, `Support`, `Profile`, and `Settings` navigation.
- Added a dedicated user Settings screen for language, notifications and About.
- Reorganized the admin Content screen around Add, Library, Edit/Delete, Season/Episode management, Collections and Releases.
- Removed duplicate top-level Support/Q&A admin entries; they are grouped under Moderation.
- Routed Moderation and System Health admin buttons to real handlers.
- Removed the obsolete visible `Advanced` entry point while retaining internal `adv:*` callback namespaces for supported tools.

### Content-management UX
- `➕ Add Content` now starts with content type selection.
- Supported types: Movie, Series, Anime, Cartoon.
- Cartoon creation explicitly asks for single-video or series mode.
- Content type choices are filtered by the admin's actual permissions.
- Creation prompts and key admin text were rewritten for clearer Uzbek/Russian/English UX.
- Movie preview now includes type, year, country, genre, language, translation, rating and description.

### Verification
- Python syntax/compileall: PASS
- Existing regression/static suite: PASS
- Total automated tests in this build: 21/21 PASS
- AI dependency/source scan: PASS
- SQLite schema and multi-episode behavior: PASS

A real Telegram network/runtime session was not executed in this environment because the environment does not have network access to install missing runtime dependencies.

## UX / admin panel restructure

- The normal user home is now kept compact: content categories, Discover, My Cinema, inquiries/support, Profile and Settings. The old `More` menu is no longer exposed.
- The admin root is grouped into Dashboard, Content, Channels, Administrators, Inquiries and Settings; operational tools are nested under these sections.
- Content Library uses type-first browsing and context-aware detail pages. Edit, preview, statistics and destructive actions are reached from the relevant content detail screen.
- Back navigation preserves the current content/list context instead of always returning to the root.
- Report, health and backup screens return to their logical parent section.
- Admin settings prompts and health output are localized through the existing JSON i18n layer.
- Final local validation: Python syntax and static regression tests passed. Real Telegram API/E2E testing is environment-dependent and is not claimed here.
