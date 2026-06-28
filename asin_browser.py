"""Look up Amazon ASINs with a real (minimised) browser.

calibre's built-in Amazon metadata sources are frequently blocked by Amazon's
anti-bot (they time out and return nothing even when the book clearly exists),
but a real Chromium loads the pages fine. This opens a minimised QtWebEngine
window and, per book, tries:

  1. a Google search (often surfaces the Amazon ``/dp/<ASIN>`` link / "ASIN ..."
     snippet immediately), then
  2. Amazon's own search results (``data-asin``).

If a captcha / consent wall appears the window is surfaced so the user can clear
it once. QtWebEngine must run on the GUI thread while processing runs on a
worker thread, so requests are marshalled across via a queued signal and a
nested event loop.
"""

import threading
from urllib.parse import quote_plus

from calibre_plugins.kindle_cover_fixer.plog import log

try:  # Qt6 / calibre 6+
    from qt.core import QObject, pyqtSignal, QTimer, QUrl, QEventLoop, QDialog, QVBoxLayout, QLabel
    from qt.webengine import QWebEngineView, QWebEnginePage, QWebEngineProfile
    _OK = True
except Exception:
    try:  # Qt5
        from PyQt5.QtCore import QObject, pyqtSignal, QTimer, QUrl, QEventLoop
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel
        from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile
        _OK = True
    except Exception:
        _OK = False

_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

# Extract an ASIN from a Google results page (amazon /dp//gp/product links, even
# inside Google redirect URLs, or an "ASIN: B0..." snippet).
_GOOGLE_JS = r"""
(function(){
  var links=document.querySelectorAll('a');
  for(var i=0;i<links.length;i++){
    var h='';try{h=decodeURIComponent(links[i].href||'');}catch(e){h=links[i].href||'';}
    if(h.indexOf('amazon.')<0) continue;
    var m=h.match(/\/(?:dp|gp\/product|gp\/aw\/d)\/([A-Z0-9]{10})/);
    if(m) return m[1];
  }
  var t=document.body?document.body.innerText:'';
  var mm=t.match(/ASIN[:\s]+([A-Z0-9]{10})/);
  return mm?mm[1]:'';
})()
"""

# Extract the first ASIN from an Amazon search results page.
_AMAZON_JS = r"""
(function(){
  var els=document.querySelectorAll('[data-asin]');
  for(var i=0;i<els.length;i++){
    var a=els[i].getAttribute('data-asin');
    if(a && /^[A-Z0-9]{10}$/.test(a)) return a;
  }
  var links=document.querySelectorAll('a[href*="/dp/"]');
  for(var j=0;j<links.length;j++){
    var m=(links[j].getAttribute('href')||'').match(/\/dp\/([A-Z0-9]{10})/);
    if(m) return m[1];
  }
  return '';
})()
"""

_BLOCK_JS = (
    "(function(){var t=document.body?document.body.innerText:'';"
    "return /validateCaptcha|Enter the characters|Type the characters|not a robot|"
    "unusual traffic|before you continue|consent/i.test(t)?'1':'';})()"
)


def available() -> bool:
    return _OK


if _OK:
    class AsinBrowser(QObject):
        _req = pyqtSignal(str, str)   # human query, isbn

        def __init__(self, store, domain='amazon.com'):
            super().__init__(store.gui)
            self.store = store
            self.domain = domain or 'amazon.com'
            self._lock = threading.Lock()
            self._event = threading.Event()
            self._result = None
            self._dlg = None
            self._req.connect(self._on_req)

        # ---- worker thread ----
        def lookup(self, query, isbn='', timeout=80):
            if not (query or isbn):
                return None
            with self._lock:
                self._result = None
                self._event.clear()
                self._req.emit(query or '', isbn or '')
                self._event.wait(timeout)
                return self._result

        def close(self):
            try:
                if self._dlg is not None:
                    self.store._bridge.run_on_gui.emit(self._dlg.close)
                    self._dlg = None
            except Exception:
                pass

        # ---- GUI thread ----
        def _ensure(self):
            if self._dlg is not None:
                return
            self._dlg = QDialog(self.store.gui)
            self._dlg.setWindowTitle('Kindle Cover Fixer — looking up ASIN…')
            self._dlg.resize(940, 720)
            lay = QVBoxLayout(self._dlg)
            self.status = QLabel('Searching for ASINs. If a captcha or consent page appears, please '
                                 'clear it once; this window closes itself when done.')
            self.status.setWordWrap(True)
            lay.addWidget(self.status)
            self._profile = QWebEngineProfile(self._dlg)
            try:
                self._profile.setHttpUserAgent(_UA)
            except Exception:
                pass
            self._view = QWebEngineView(self._dlg)
            self._page = QWebEnginePage(self._profile, self._view)
            self._view.setPage(self._page)
            lay.addWidget(self._view, 1)
            self._dlg.show()
            self._dlg.showMinimized()

        def _on_req(self, query, isbn):
            self._done = False
            try:
                self._ensure()
                # Build the ordered list of (url, extractor-js) attempts.
                self._steps = []
                if query:
                    g = '%s site:%s' % (query, self.domain)
                    self._steps.append((
                        'https://www.google.com/search?num=10&hl=en&q=' + quote_plus(g), _GOOGLE_JS))
                amz = quote_plus(isbn or query)
                self._steps.append(('https://www.%s/s?k=%s' % (self.domain, amz), _AMAZON_JS))
                self._step = -1
                self._loop = QEventLoop()
                QTimer.singleShot(75000, self._loop.quit)   # hard safety net
                self._next_step()
                self._loop.exec()
            except Exception as err:
                log('ASIN browser error: %s' % err)
            finally:
                try:
                    self._timer.stop()
                except Exception:
                    pass
                self._event.set()

        def _next_step(self):
            self._step += 1
            if self._step >= len(self._steps):
                self._finish(None)
                return
            url, js = self._steps[self._step]
            self._cur_js = js
            self._tries = 0
            self._view.load(QUrl(url))
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = QTimer(self._dlg)
            self._timer.setInterval(1500)
            self._timer.timeout.connect(self._poll)
            self._timer.start()

        def _poll(self):
            if self._done:
                return
            self._tries += 1
            if self._tries == 6:    # let the user see/clear a wall after ~9s
                try:
                    self._dlg.showNormal(); self._dlg.raise_()
                except Exception:
                    pass
            if self._tries > 16:    # ~24s per step -> move on
                self._timer.stop()
                self._next_step()
                return
            try:
                self._page.runJavaScript(self._cur_js, self._got)
            except Exception:
                pass

        def _got(self, asin):
            if self._done:
                return
            if asin and len(asin) == 10:
                self._finish(asin)

        def _finish(self, asin):
            self._done = True
            self._result = asin
            try:
                self._timer.stop()
            except Exception:
                pass
            try:
                self._loop.quit()
            except Exception:
                pass
else:
    class AsinBrowser:   # pragma: no cover - degraded fallback
        def __init__(self, *a, **k):
            pass

        def lookup(self, *a, **k):
            return None

        def close(self):
            pass
