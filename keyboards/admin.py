from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from services.i18n import tr
from services.permissions import ROLE_DEFAULTS


def _can(permissions: set[str], *keys: str) -> bool:
    return bool(set(keys) & permissions)


def admin_panel(lang: str, role: str, permissions: set[str] | None = None) -> InlineKeyboardMarkup:
    """Compact admin root. Core areas are grouped; operational tools live one level deeper."""
    permissions = permissions if permissions is not None else set(ROLE_DEFAULTS.get(role, set()))
    rows: list[list[InlineKeyboardButton]] = []

    # Keep the root to the six requested operational areas + security/logout.
    if any(_can(permissions, p) for p in ("statistics.view", "users.view", "reports.view", "health.view")):
        rows.append([InlineKeyboardButton(text=tr(lang, "dashboard"), callback_data="adm:dashboard")])
    if any(_can(permissions, p) for p in ("movies.view", "series.view", "anime.view", "cartoons.view", "episodes.view", "movies.create", "series.create", "anime.create", "cartoons.create")):
        rows.append([InlineKeyboardButton(text=tr(lang, "content_management"), callback_data="adm:content")])
    if _can(permissions, "channels.manage"):
        rows.append([InlineKeyboardButton(text=tr(lang, "channels"), callback_data="adm:channels")])
    if _can(permissions, "admins.view", "admins.manage", "admins.create_junior", "admins.manage_junior"):
        rows.append([InlineKeyboardButton(text=tr(lang, "admin_management"), callback_data="adm:admins")])
    if _can(permissions, "feedback.view", "qa.view", "reports.view", "feedback.reply", "qa.reply"):
        rows.append([InlineKeyboardButton(text=tr(lang, "inquiries"), callback_data="adm:inbox")])
    # Every authenticated admin needs access to their own security screen.
    rows.append([InlineKeyboardButton(text=tr(lang, "settings"), callback_data="adm:settings")])
    rows.append([InlineKeyboardButton(text=tr(lang, "logout"), callback_data="adm:logout")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dashboard_menu(lang: str, permissions: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _can(permissions, "statistics.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "analytics"), callback_data="adm:stats")])
    if _can(permissions, "users.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "users"), callback_data="adm:users")])
    if _can(permissions, "reports.view", "users.ban", "feedback.view", "qa.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "moderation"), callback_data="adm:moderation")])
    if _can(permissions, "health.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "system_health"), callback_data="adm:health")])
    if _can(permissions, "statistics.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "logs"), callback_data="adm:logs")])
    if _can(permissions, "broadcast.send"):
        rows.append([InlineKeyboardButton(text=tr(lang, "broadcast"), callback_data="adm:broadcast")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def users_menu(lang: str, permissions: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _can(permissions, "users.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "search_user"), callback_data="user:search")])
        rows.append([
            InlineKeyboardButton(text=tr(lang, "active_users"), callback_data="users:list:active"),
            InlineKeyboardButton(text=tr(lang, "banned_users"), callback_data="users:list:banned"),
        ])
    if _can(permissions, "users.ban", "reports.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "moderation"), callback_data="adm:moderation")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inquiries_menu(lang: str, permissions: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _can(permissions, "feedback.view", "feedback.reply"):
        rows.append([InlineKeyboardButton(text=tr(lang, "tickets"), callback_data="adm:tickets")])
    if _can(permissions, "qa.view", "qa.reply"):
        rows.append([InlineKeyboardButton(text=tr(lang, "qa_manage"), callback_data="adm:qa")])
    if _can(permissions, "reports.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "report"), callback_data="adv:reports")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_menu(lang: str, permissions: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _can(permissions, "settings.manage"):
        rows.append([InlineKeyboardButton(text=tr(lang, "general_settings"), callback_data="adm:settings")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def content_menu(lang: str, role: str = "admin", permissions: set[str] | None = None) -> InlineKeyboardMarkup:
    if permissions is None:
        permissions = set(ROLE_DEFAULTS.get(role, set()))
    rows: list[list[InlineKeyboardButton]] = []

    if _can(permissions, "movies.create", "series.create", "anime.create", "cartoons.create"):
        rows.append([InlineKeyboardButton(text=tr(lang, "add_content"), callback_data="content:add")])
    if _can(permissions, "movies.view", "series.view", "anime.view", "cartoons.view", "episodes.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "content_list"), callback_data="content:list")])
    if _can(permissions, "series.edit", "episodes.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "season_manage"), callback_data="content:season_manage")])
    if _can(permissions, "episodes.view", "episodes.create", "episodes.edit", "episodes.delete"):
        rows.append([InlineKeyboardButton(text=tr(lang, "episode_manage"), callback_data="content:episode_manage")])
    if _can(permissions, "collections.manage"):
        rows.append([InlineKeyboardButton(text=tr(lang, "collections"), callback_data="adv:collections")])
    if _can(permissions, "release.manage"):
        rows.append([InlineKeyboardButton(text=tr(lang, "releases"), callback_data="adv:releases")])
    if _can(permissions, "movies.view", "series.view", "anime.view", "cartoons.view"):
        rows.append([InlineKeyboardButton(text=tr(lang, "search_content"), callback_data="content:search")])
    rows.append([InlineKeyboardButton(text=tr(lang, "back"), callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def roles_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=tr(lang, "role_senior_admin_label"), callback_data="role:senior_admin")],
        [InlineKeyboardButton(text=tr(lang, "role_admin_label"), callback_data="role:admin")],
    ])
