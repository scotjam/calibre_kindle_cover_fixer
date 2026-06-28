"""Best-effort Amazon ASIN lookup using calibre's metadata sources.

The Kindle Colorsoft fetches covers from Amazon by ASIN, so storing the right
ASIN (as the ``mobi-asin`` / ``amazon`` identifier) lets the cover load. This
reuses calibre's own ``identify`` engine, which runs whatever metadata sources
the user has enabled (the Amazon source handles Amazon's anti-bot far better
than an ad-hoc scraper). Only works for books that actually have an Amazon
edition AND the Amazon source enabled; returns None otherwise.
"""

import threading

from calibre import prints

_UNKNOWN = ('Unknown',)
try:
    _UNKNOWN = ('Unknown', _('Unknown'))
except Exception:
    pass


def enabled_sources():
    """Names of the enabled metadata (identify) source plugins."""
    try:
        from calibre.customize.ui import metadata_plugins
        return [p.name for p in metadata_plugins(['identify'])]
    except Exception as err:
        prints('Kindle Cover Fixer: could not list metadata sources:', err)
        return []


def lookup_identifiers(mi, timeout=30):
    """Return a list of identifier-dicts from every metadata-source match."""
    try:
        from calibre.ebooks.metadata.sources.identify import identify
        from calibre.utils.logging import Log
    except Exception as err:
        prints('Kindle Cover Fixer: identify unavailable:', err)
        return []

    title = mi.title if (mi.title and mi.title not in _UNKNOWN) else None
    authors = [a for a in (mi.authors or []) if a and a not in _UNKNOWN] or None
    identifiers = dict(mi.identifiers or {})
    if not title and not identifiers:
        return []
    try:
        results = identify(Log(), threading.Event(), title=title, authors=authors,
                           identifiers=identifiers, timeout=timeout)
    except Exception as err:
        prints('Kindle Cover Fixer: identify() failed:', err)
        return []
    return [dict(getattr(r, 'identifiers', {}) or {}) for r in (results or [])]


def asin_from_identifiers(ids):
    """Pull a plausible ASIN out of an identifiers dict."""
    for key, val in (ids or {}).items():
        if not val:
            continue
        if key == 'mobi-asin' or key == 'amazon' or key.startswith('amazon'):
            v = str(val).strip()
            if 9 <= len(v) <= 13 and v.replace('-', '').isalnum():
                return v
    return None


def find_asin(mi, timeout=30):
    for ids in lookup_identifiers(mi, timeout):
        asin = asin_from_identifiers(ids)
        if asin:
            return asin
    return None
