"""Tiny in-memory log for the plugin, viewable from its menu.

Keeps the last few thousand lines in a ring buffer and also echoes to calibre's
debug output (visible via ``calibre-debug -g``)."""

import time
from collections import deque

from calibre import prints

_BUF = deque(maxlen=4000)


def log(*args):
    msg = ' '.join(str(a) for a in args)
    try:
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        stamp = ''
    _BUF.append('%s  %s' % (stamp, msg))
    try:
        prints('Kindle Cover Fixer:', msg)
    except Exception:
        pass


def get_log() -> str:
    return '\n'.join(_BUF)


def clear_log():
    _BUF.clear()
