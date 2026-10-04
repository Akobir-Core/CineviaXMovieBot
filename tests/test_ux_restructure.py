from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def test_user_menu_is_compact_and_no_more_menu():
    src = (ROOT / 'keyboards' / 'common.py').read_text(encoding='utf-8')
    assert 'def more_menu' not in src
    assert 'more_menu' not in src
    assert "tr(lang, 'movies')" in src
    assert "tr(lang, 'series')" in src
    assert "tr(lang, 'anime')" in src
    assert "tr(lang, 'cartoons')" in src
    assert "tr(lang, 'my_cinema')" in src
    assert "tr(lang, 'settings')" in src


def test_admin_root_is_compact_and_explicit():
    src = (ROOT / 'keyboards' / 'admin.py').read_text(encoding='utf-8')
    block = src.split('def admin_panel', 1)[1].split('\ndef dashboard_menu', 1)[0]
    assert 'adm:dashboard' in block
    assert 'adm:content' in block
    assert 'adm:channels' in block
    assert 'adm:admins' in block
    assert 'adm:inbox' in block
    assert 'adm:settings' in block
    assert 'Advanced' not in block
    assert 'More' not in block


def test_content_root_uses_nested_management():
    src = (ROOT / 'keyboards' / 'admin.py').read_text(encoding='utf-8')
    block = src.split('def content_menu', 1)[1].split('\ndef roles_keyboard', 1)[0]
    assert 'content:add' in block
    assert 'content:list' in block
    assert 'content:search' in block
    assert 'content:edit' not in block
    assert 'content:delete' not in block


def test_advanced_back_routes_match_parent_sections():
    src = (ROOT / 'handlers' / 'admin_advanced.py').read_text(encoding='utf-8')
    reports = src.split("@router.callback_query(F.data=='adv:reports')", 1)[1].split("@router.callback_query(F.data.regexp(r'^adv:report", 1)[0]
    assert "callback_data='adm:inbox'" in reports
    health = src.split("@router.callback_query(F.data=='adv:health')", 1)[1].split("@router.callback_query(F.data=='adv:backup')", 1)[0]
    assert "callback_data='adm:dashboard'" in health
    backup = src.split("@router.callback_query(F.data=='adv:backup')", 1)[1].split("@router.callback_query(F.data=='adv:releases')", 1)[0]
    assert "callback_data='adm:dashboard'" in backup


def test_no_duplicate_content_save_cancel_decorator():
    src = (ROOT / 'handlers' / 'admin.py').read_text(encoding='utf-8')
    assert src.count('@router.callback_query(ContentAddState.confirm, F.data == "content_save:no")') == 1


def test_no_unsupported_connection_fetch_helpers():
    src = (ROOT / 'database' / 'db.py').read_text(encoding='utf-8')
    assert 'execute_fetchone' not in src
    assert 'execute_fetchall' not in src


def test_locales_have_identical_keys():
    locales = []
    for name in ('uz.json', 'ru.json', 'en.json'):
        locales.append(json.loads((ROOT / 'locales' / name).read_text(encoding='utf-8')))
    keys = set(locales[0])
    assert all(set(d) == keys for d in locales[1:])


def test_no_ai_dependencies():
    req = (ROOT / 'requirements.txt').read_text(encoding='utf-8').lower()
    banned = ('openai', 'google-generativeai', 'anthropic', 'groq', 'langchain', 'transformers')
    assert not any(x in req for x in banned)


def test_inactive_admin_can_be_managed_for_reactivation():
    src = (ROOT / 'handlers' / 'admin.py').read_text(encoding='utf-8')
    start = src.index('async def _can_manage_target')
    end = src.index('\nasync def show_admins', start)
    block = src[start:end]
    assert 'target["active"]' not in block
    assert "target_role == 'admin'" in block or 'target_role == "admin"' in block


def test_admin_content_detail_is_context_aware():
    src = (ROOT / 'handlers' / 'admin.py').read_text(encoding='utf-8')
    assert "admincontent:item:(movie|series):\\d+:(movie|series|anime|cartoon|search):\\d+" in src
    assert "back_kind == \"search\"" in src


if __name__ == '__main__':
    for name, obj in sorted(globals().items()):
        if name.startswith('test_'):
            obj()
    print('UX RESTRUCTURE TESTS: PASS')
