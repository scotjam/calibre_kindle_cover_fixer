"""Persistent ASIN cache: (ISBN, or title+author) -> ASIN.

Survives removing/re-adding a book, so a looked-up ASIN is never fetched twice.
Stored in <calibre config>/plugins/kindle_cover_fixer_cache.json.
"""

import re

from calibre.utils.config import JSONConfig

_cache = JSONConfig('plugins/kindle_cover_fixer_cache')
_cache.defaults['map'] = {}


def key_for(mi) -> str:
    ids = mi.identifiers or {}
    isbn = (ids.get('isbn') or '').strip()
    if isbn:
        return 'isbn:' + isbn
    title = re.sub(r'\s+', ' ', (mi.title or '').strip().lower())
    authors = re.sub(r'\s+', ' ', ' '.join(mi.authors or []).strip().lower())
    return 'ta:%s|%s' % (title, authors)


def get(mi):
    return _cache['map'].get(key_for(mi))


def put(mi, asin):
    if not asin:
        return
    m = dict(_cache['map'])
    m[key_for(mi)] = asin
    _cache['map'] = m


def size():
    return len(_cache['map'])


def clear():
    _cache['map'] = {}
