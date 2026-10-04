from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_cache: dict[str, dict[str,str]] = {}


def load(lang: str) -> dict[str,str]:
    lang = lang if lang in {'uz','ru','en'} else 'uz'
    if lang not in _cache:
        _cache[lang] = json.loads((ROOT/'locales'/f'{lang}.json').read_text(encoding='utf-8'))
    return _cache[lang]


def tr(lang: str, key: str, **kwargs) -> str:
    text = load(lang).get(key, load('uz').get(key, key))
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text
