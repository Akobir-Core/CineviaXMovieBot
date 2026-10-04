from __future__ import annotations
from datetime import datetime, timezone

# Granular permissions. Role defaults keep the existing three-level model, while
# admin_permissions rows can override individual permissions for non-CEO admins.
ROLE_DEFAULTS: dict[str, set[str]] = {
    "ceo": {
        "movies.view","movies.create","movies.edit","movies.delete",
        "series.view","series.create","series.edit","series.delete",
        "anime.view","anime.create","anime.edit","anime.delete",
        "cartoons.view","cartoons.create","cartoons.edit","cartoons.delete",
        "episodes.view","episodes.create","episodes.edit","episodes.delete",
        "users.view","users.ban","users.unban","users.history",
        "channels.manage","feedback.view","feedback.reply","qa.view","qa.reply",
        "statistics.view","broadcast.send","backup.create","settings.manage","admins.manage","permissions.manage","collections.manage","reports.view","reports.resolve","health.view","moods.manage","release.manage"
    },
    "senior_admin": {
        "movies.view","movies.create","movies.edit","movies.delete",
        "series.view","series.create","series.edit","series.delete",
        "anime.view","anime.create","anime.edit","anime.delete",
        "cartoons.view","cartoons.create","cartoons.edit","cartoons.delete",
        "episodes.view","episodes.create","episodes.edit","episodes.delete",
        "users.view","users.history","channels.manage",
        "feedback.view","feedback.reply","qa.view","qa.reply","statistics.view","reports.view","health.view","broadcast.send","collections.manage","reports.view","reports.resolve","health.view","moods.manage","release.manage","admins.view","admins.create_junior","admins.manage_junior","admins.permissions_junior"
    },
    # Junior Admin starts with content-operation permissions only; the CEO/Senior
    # may grant additional permissions within their own effective scope.
    "admin": {
        "movies.view","movies.create","movies.edit",
        "series.view","series.create","series.edit",
        "anime.view","anime.create","anime.edit",
        "cartoons.view","cartoons.create","cartoons.edit",
        "episodes.view","episodes.create","episodes.edit",
    },
}

PERMISSION_LABELS = {
    "movies.view":"Movies · View", "movies.create":"Movies · Create", "movies.edit":"Movies · Edit", "movies.delete":"Movies · Delete",
    "series.view":"Series · View", "series.create":"Series · Create", "series.edit":"Series · Edit", "series.delete":"Series · Delete",
    "anime.view":"Anime · View", "anime.create":"Anime · Create", "anime.edit":"Anime · Edit", "anime.delete":"Anime · Delete",
    "cartoons.view":"Cartoons · View", "cartoons.create":"Cartoons · Create", "cartoons.edit":"Cartoons · Edit", "cartoons.delete":"Cartoons · Delete",
    "episodes.view":"Episodes · View", "episodes.create":"Episodes · Create", "episodes.edit":"Episodes · Edit", "episodes.delete":"Episodes · Delete",
    "users.view":"Users · View", "users.ban":"Users · Ban", "users.unban":"Users · Unban", "users.history":"Users · History",
    "channels.manage":"Channels · Manage", "feedback.view":"Feedback · View", "feedback.reply":"Feedback · Reply",
    "qa.view":"Q&A · View", "qa.reply":"Q&A · Reply", "statistics.view":"Statistics · View",
    "broadcast.send":"Broadcast · Send", "backup.create":"Backup · Create", "settings.manage":"Settings · Manage",
    "admins.manage":"Admins · Manage", "admins.view":"Admins · View", "admins.create_junior":"Admins · Create Junior", "admins.manage_junior":"Admins · Manage Junior", "admins.permissions_junior":"Admins · Junior Permissions", "permissions.manage":"Permissions · Manage",
}

PERMISSION_LABELS.update({
    "collections.manage":"Collections · Manage",
    "reports.view":"Reports · View",
    "reports.resolve":"Reports · Resolve",
    "health.view":"Health · View",
    "moods.manage":"Moods · Manage",
    "release.manage":"Releases · Manage",
})

ALL_PERMISSIONS = tuple(PERMISSION_LABELS)

def role_has(role: str, permission: str) -> bool:
    return permission in ROLE_DEFAULTS.get(role, set())

async def has_permission(db, admin, permission: str) -> bool:
    if not admin or not int(admin["active"]):
        return False
    if str(admin["role"]) == "ceo":
        return True
    # A Junior can never have a permission outside the effective permission set
    # of their Senior parent. This prevents permission escalation.
    parent_id = admin["parent_admin_id"] if "parent_admin_id" in admin.keys() else None
    if str(admin["role"]) == "admin" and parent_id:
        parent = await db.admin_by_id(int(parent_id))
        if not parent or str(parent["role"]) != "senior_admin" or not int(parent["active"]):
            return False
        if not await has_permission(db, parent, permission):
            return False
    row = await db.fetchone("SELECT allowed FROM admin_permissions WHERE admin_id=? AND permission=?", (int(admin["id"]), permission))
    if row is not None:
        return bool(row["allowed"])
    return role_has(str(admin["role"]), permission)

async def set_permission(db, admin_id: int, permission: str, allowed: bool) -> None:
    await db.execute(
        "INSERT INTO admin_permissions(admin_id,permission,allowed,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(admin_id,permission) DO UPDATE SET allowed=excluded.allowed,updated_at=excluded.updated_at",
        (admin_id, permission, 1 if allowed else 0, datetime.now(timezone.utc).isoformat()),
    )

async def clear_override(db, admin_id: int, permission: str) -> None:
    await db.execute("DELETE FROM admin_permissions WHERE admin_id=? AND permission=?", (admin_id, permission))


async def effective_permissions(db, admin) -> set[str]:
    if not admin or not int(admin["active"]):
        return set()
    if str(admin["role"]) == "ceo":
        return set(ALL_PERMISSIONS)
    base=set(ROLE_DEFAULTS.get(str(admin["role"]), set()))
    rows=await db.admin_permission_overrides(int(admin["id"]))
    for row in rows:
        if int(row["allowed"]): base.add(str(row["permission"]))
        else: base.discard(str(row["permission"]))
    parent_id = admin["parent_admin_id"] if "parent_admin_id" in admin.keys() else None
    if str(admin["role"]) == "admin" and parent_id:
        parent = await db.admin_by_id(int(parent_id))
        if not parent or str(parent["role"]) != "senior_admin" or not int(parent["active"]):
            return set()
        base &= await effective_permissions(db, parent)
    return base
