import asyncio
import tempfile
from pathlib import Path

from database.db import Database
from services.admin_auth import hash_password
from services.permissions import has_permission


def test_hierarchy_creation_and_limit():
    async def inner():
        with tempfile.TemporaryDirectory() as td:
            db=Database(str(Path(td)/"t.db"))
            await db.init(100, hash_password("StrongPass123!"))
            await db.add_admin(200,"senior_admin",100,hash_password("SeniorPass123!"))
            senior=await db.admin_any(200)
            await db.add_admin(300,"admin",200,hash_password("JuniorPass123!"),senior["id"])
            junior=await db.admin_any(300)
            assert junior["parent_admin_id"]==senior["id"]
            try:
                await db.add_admin(301,"admin",200,hash_password("JuniorPass124!"),senior["id"])
                assert False, "second junior should fail"
            except ValueError as e:
                assert str(e)=="junior_limit"
            assert await has_permission(db,junior,"movies.create")
            try:
                await db.add_admin(400,"ceo",200,hash_password("BadPass123!"))
                assert False, "CEO creation should be disallowed"
            except ValueError as e:
                assert str(e)=="invalid_admin_role"
    asyncio.run(inner())


def test_permission_inheritance():
    async def inner():
        with tempfile.TemporaryDirectory() as td:
            db=Database(str(Path(td)/"t.db"))
            await db.init(100, hash_password("StrongPass123!"))
            await db.add_admin(200,"senior_admin",100,hash_password("SeniorPass123!"))
            senior=await db.admin_any(200)
            await db.add_admin(300,"admin",200,hash_password("JuniorPass123!"),senior["id"])
            junior=await db.admin_any(300)
            assert await has_permission(db,senior,"movies.create")
            assert await has_permission(db,junior,"movies.create")
            await db.set_admin_permission(senior["id"],"movies.create",False)
            senior=await db.admin_any(200); junior=await db.admin_any(300)
            assert not await has_permission(db,senior,"movies.create")
            assert not await has_permission(db,junior,"movies.create")
    asyncio.run(inner())
