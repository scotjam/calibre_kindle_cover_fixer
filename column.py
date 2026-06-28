"""Helpers for the managed "Kindle Cover" status column.

A calibre custom column (lookup name ``#kindle_cover``, type text) shows, per
book: ``ASIN+Embed``, ``ASIN`` or blank. Creating a custom column is a schema
change, so calibre must be restarted before the column appears and can be
written to.
"""

LABEL = 'kindle_cover'       # custom column label (no leading '#')
LOOKUP = '#' + LABEL         # how it is referenced everywhere else
HEADING = 'Kindle Cover'


def column_exists(db) -> bool:
    try:
        return LOOKUP in db.new_api.field_metadata
    except Exception:
        return False


def create_column(db):
    """Create the custom text column. Caller must prompt for a restart."""
    db.new_api.create_custom_column(LABEL, HEADING, 'text', False)


def status_for(has_asin: bool, embedded: bool) -> str:
    if has_asin and embedded:
        return 'ASIN+Embed'
    if has_asin:
        return 'ASIN'
    if embedded:
        return 'Embed'
    return ''


def has_asin(identifiers) -> bool:
    ids = identifiers or {}
    return bool(ids.get('amazon') or ids.get('mobi-asin'))
