"""Kindle Cover Fixer — calibre interface action.

Listens for books being added to the library (from any source: store-plugin
downloads, manual adds, etc.) and, when enabled, automatically embeds the cover
+ metadata into the book files and looks up / stores the Amazon ASIN so covers
show on the Kindle Colorsoft.

This plugin is an independent, unofficial tool and has no association with,
endorsement by, or affiliation with Amazon or Kindle. "Amazon", "Kindle", and
"Colorsoft" are trademarks of their respective owners, used here only to
describe interoperability.

Threading notes: the db ``book_created`` listener may fire on a worker thread,
so it only emits a Qt signal; the real work runs on a background thread and
marshals back to the GUI thread (via another signal) for db writes and UI
refresh, mirroring how calibre itself does background metadata work.
"""

import threading

from calibre.gui2 import error_dialog, info_dialog, question_dialog
from calibre.gui2.actions import InterfaceAction

try:
    from qt.core import (QObject, pyqtSignal, QTimer, QMenu, QDialog, QVBoxLayout,
                         QHBoxLayout, QPlainTextEdit, QPushButton, QApplication)
except (ImportError, ModuleNotFoundError):
    from PyQt5.QtCore import QObject, pyqtSignal, QTimer
    from PyQt5.QtWidgets import (QMenu, QDialog, QVBoxLayout, QHBoxLayout,
                                 QPlainTextEdit, QPushButton, QApplication)

from calibre_plugins.kindle_cover_fixer.config import prefs
from calibre_plugins.kindle_cover_fixer import column
from calibre_plugins.kindle_cover_fixer.plog import log, get_log, clear_log

try:
    from calibre.db.listeners import EventType
except Exception:
    EventType = None


class _Bridge(QObject):
    book_added = pyqtSignal(object)   # book_id, from any thread -> GUI
    run_on_gui = pyqtSignal(object)   # a callable -> run on GUI thread
    progress = pyqtSignal(str)        # status-bar progress text -> GUI


class KindleCoverFixer(InterfaceAction):

    name = 'Kindle Cover Fixer'
    # (text, icon, tooltip, keyboard shortcut)
    action_spec = ('Kindle Cover Fixer', None,
                   'Embed covers and Amazon ASIN into book files for Kindle', None)
    action_type = 'current'

    # --------------------------------------------------------------- setup

    def genesis(self):
        try:
            icon = get_icons('images/icon.png', 'Kindle Cover Fixer')
            if icon is not None:
                self.qaction.setIcon(icon)
        except Exception:
            pass
        self.qaction.triggered.connect(self.process_selected)

        menu = QMenu(self.gui)
        menu.addAction('Process selected books now', self.process_selected)
        menu.addSeparator()
        menu.addAction('Add "Kindle Cover" status column', self.add_column)
        menu.addAction('Refresh "Kindle Cover" column (all books)', self.refresh_column_all)
        menu.addSeparator()
        menu.addAction('Set up KFX + PDOC sending (Colorsoft covers)', self.setup_kfx_pdoc_action)
        menu.addAction('Convert selected to KFX (PDOC)', self.convert_selected_kfx)
        menu.addAction('Send selected to Kindle as KFX (convert if needed)', self.send_selected_kfx)
        menu.addAction('Send selected PDFs to Kindle via Amazon (convert)', self.send_pdfs_via_amazon)
        menu.addSeparator()
        menu.addAction('Diagnose ASIN lookup (selected book)', self.diagnose)
        menu.addAction('View log', self.view_log)
        menu.addAction('Configure…', self.show_configuration)
        self.qaction.setMenu(menu)
        self.menu = menu

        self._pending = set()
        self._listener_db_id = None

        self._bridge = _Bridge()
        self._bridge.book_added.connect(self._queue_book)
        self._bridge.run_on_gui.connect(lambda fn: fn())
        self._bridge.progress.connect(self._show_progress)

        # Debounce bursts of adds into one batch.
        self._debounce = QTimer(self.gui)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(4000)
        self._debounce.timeout.connect(self._flush_pending)

        self._register_listener(self.gui.current_db)

        # Real-browser ASIN lookup (created on the GUI thread so QtWebEngine has
        # the right thread affinity).
        self._asin_browser = None
        try:
            from calibre_plugins.kindle_cover_fixer.asin_browser import available as _ab_avail, AsinBrowser
            if _ab_avail():
                self._asin_browser = AsinBrowser(self, prefs['amazon_domain'])
        except Exception as err:
            log('ASIN browser unavailable: %s' % err)

        # Configure KFX/PDOC sending once (the actual Colorsoft cover fix).
        if prefs['kfx_pdoc_setup'] and not prefs['kfx_pdoc_done']:
            try:
                if self._setup_kfx_pdoc(announce=False):
                    prefs['kfx_pdoc_done'] = True
            except Exception as err:
                log('KFX/PDOC auto-setup failed: %s' % err)

    def library_changed(self, db):
        # Re-register the listener against the new library.
        self._register_listener(db)

    def _register_listener(self, db):
        if EventType is None:
            return
        try:
            api = db.new_api
            if getattr(api, 'library_id', None) == self._listener_db_id:
                return
            try:
                api.add_listener(self._on_db_event, check_already_added=True)
            except TypeError:
                api.add_listener(self._on_db_event)
            self._listener_db_id = getattr(api, 'library_id', object())
        except Exception as err:
            import traceback
            traceback.print_exc()

    # ----------------------------------------------------- add detection

    def _on_db_event(self, event_type, library_id, data):
        # May be called on a non-GUI thread.
        try:
            if event_type == EventType.book_created and prefs['auto_enabled']:
                self._bridge.book_added.emit(int(data))
        except Exception:
            pass

    def _queue_book(self, book_id):   # GUI thread
        self._pending.add(int(book_id))
        self._debounce.start()

    def _flush_pending(self):         # GUI thread
        ids = sorted(self._pending)
        self._pending.clear()
        if not ids:
            return
        ids = self._filter_by_tags(ids)
        if ids:
            self._start(ids, interactive=False)

    def _filter_by_tags(self, ids):
        wanted = [t.strip().lower() for t in (prefs['only_tags'] or '').split(',') if t.strip()]
        if not wanted:
            return ids
        db = self.gui.current_db.new_api
        out = []
        for bid in ids:
            try:
                tags = [t.lower() for t in (db.field_for('tags', bid) or ())]
            except Exception:
                tags = []
            if any(w in tags for w in wanted):
                out.append(bid)
        return out

    # --------------------------------------------------- manual trigger

    def process_selected(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        ids = [self.gui.library_view.model().id(r) for r in rows]
        if not ids:
            return error_dialog(self.gui, 'Kindle Cover Fixer',
                                'No books selected.', show=True)

        # ASIN lookup hits the network per book without an existing ASIN, which
        # is slow for big selections -- let the user opt out of it for this run.
        do_asin = bool(prefs['fetch_asin'])
        if do_asin and len(ids) > 25:
            do_asin = question_dialog(
                self.gui, 'Kindle Cover Fixer',
                'Also look up Amazon ASINs online for the %d selected books?\n\n'
                'This can be slow (one lookup per book without an ASIN). '
                'Choose "No" to just embed covers/metadata now (fast).' % len(ids))
        self._start(ids, interactive=True, do_asin=do_asin)

    def show_configuration(self):
        self.interface_action_base_plugin.do_user_config(self.gui)

    # ------------------------------------------------------- processing

    def _start(self, book_ids, interactive, do_asin=None):
        book_ids = [int(b) for b in book_ids]
        if do_asin is None:
            do_asin = bool(prefs['fetch_asin'])
        # Ensure the ASIN browser exists (created here, on the GUI thread, so it
        # works even if genesis didn't set it, e.g. after an in-place update).
        if not hasattr(self, '_asin_browser'):
            self._asin_browser = None
        if do_asin and prefs['browser_asin'] and self._asin_browser is None:
            try:
                from calibre_plugins.kindle_cover_fixer.asin_browser import available as _ab, AsinBrowser
                if _ab():
                    self._asin_browser = AsinBrowser(self, prefs['amazon_domain'])
            except Exception as err:
                log('ASIN browser init failed: %s' % err)
        # Instant feedback: reflect current state in the column right away.
        self._update_column(book_ids)
        try:
            self.gui.status_bar.show_message(
                'Kindle Cover Fixer: processing %d book(s)…' % len(book_ids), 4000)
        except Exception:
            pass
        t = threading.Thread(target=self._worker, args=(book_ids, interactive, do_asin), daemon=True)
        t.start()

    def _worker(self, book_ids, interactive, do_asin):
        """Off the GUI thread. Embed first (fast, local) so the column populates
        quickly, then do the slower ASIN lookups. Reports progress per book to
        the status bar."""
        asin_count = 0
        asin_attempted = 0
        embedded = False
        no_amazon_source = False
        total = len(book_ids)
        try:
            db = self.gui.current_db.new_api
            log('Process %d book(s): embed=%s asin=%s' % (total, prefs['embed_metadata'], do_asin))

            # 1) Embed cover+metadata into the files, one book at a time so we
            #    can report progress (calibre's embed_metadata ignores its own
            #    report_progress argument).
            if prefs['embed_metadata']:
                ok = 0
                for i, bid in enumerate(book_ids, 1):
                    self._bridge.progress.emit('Kindle Cover Fixer: embedding %d/%d' % (i, total))
                    try:
                        db.embed_metadata([bid])
                        embedded = True
                        ok += 1
                    except Exception as err:
                        log('embed failed for book %s: %s' % (bid, err))
                log('Embedded %d/%d book(s)' % (ok, total))
                if embedded:
                    self._bridge.run_on_gui.emit(lambda: self._mark_embedded(book_ids))

            # 2) Look up ASINs for books that don't already have one.
            if do_asin:
                from calibre_plugins.kindle_cover_fixer.asin import (
                    lookup_identifiers, asin_from_identifiers, enabled_sources)
                from calibre_plugins.kindle_cover_fixer import asin_cache

                browser = getattr(self, '_asin_browser', None)
                use_browser = bool(prefs['browser_asin']) and browser is not None
                if use_browser:
                    browser.domain = prefs['amazon_domain'] or 'amazon.com'
                    log('ASIN method: real browser (Google then %s), cache size=%d'
                        % (browser.domain, asin_cache.size()))
                else:
                    sources = enabled_sources()
                    log('ASIN method: calibre sources: %s' % (', '.join(sources) or '(none)'))
                    if not any('amazon' in s.lower() for s in sources):
                        no_amazon_source = True
                        log('WARNING: no Amazon metadata source enabled -> ASIN lookup will fail.')

                need = []
                for bid in book_ids:
                    try:
                        mi = db.get_metadata(bid)
                        ex = dict(mi.identifiers or {})
                        if not (ex.get('mobi-asin') or ex.get('amazon')):
                            need.append((bid, mi, ex))
                    except Exception:
                        pass
                n_need = len(need)
                asin_attempted = n_need
                log('ASIN lookup needed for %d/%d book(s)' % (n_need, total))

                for i, (bid, mi, ex) in enumerate(need, 1):
                    self._bridge.progress.emit('Kindle Cover Fixer: finding ASIN %d/%d' % (i, n_need))
                    label = '"%s" by %s' % (mi.title, ', '.join(mi.authors or []))

                    asin = asin_cache.get(mi)
                    if asin:
                        log('ASIN [%d/%d] %s -> %s (cache)' % (i, n_need, label, asin))
                    elif use_browser:
                        query = ('%s %s' % (mi.title or '', ' '.join(mi.authors or []))).strip()
                        isbn = (mi.identifiers or {}).get('isbn', '')
                        log('ASIN [%d/%d] browser: %s (isbn=%s)' % (i, n_need, label, isbn or '-'))
                        try:
                            asin = browser.lookup(query, isbn)
                        except Exception as err:
                            log('  browser lookup error: %s' % err)
                            asin = None
                        log('  -> %s' % (asin or 'none'))
                    else:
                        log('ASIN [%d/%d] identify: %s' % (i, n_need, label))
                        try:
                            results = lookup_identifiers(mi)
                        except Exception as err:
                            log('  identify error: %s' % err)
                            results = []
                        log('  identify returned %d result(s)' % len(results))
                        asin = None
                        for ids in results:
                            log('   ids: %s' % ids)
                            asin = asin_from_identifiers(ids)
                            if asin:
                                break
                        log('  -> %s' % (asin or 'none'))

                    if not asin or len(asin) != 10:
                        continue
                    asin_cache.put(mi, asin)
                    ex['mobi-asin'] = asin
                    ex['amazon'] = asin
                    try:
                        db.set_field('identifiers', {bid: ex})
                        db.embed_metadata([bid])
                        asin_count += 1
                        self._bridge.run_on_gui.emit(lambda b=bid: self._refresh_one(b))
                    except Exception as err:
                        log('  write failed for book %s: %s' % (bid, err))

                if use_browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
        except Exception as err:
            log('processing failed: %s' % err)
        finally:
            self._bridge.run_on_gui.emit(
                lambda: self._finish(book_ids, asin_count, asin_attempted, embedded,
                                     do_asin, no_amazon_source, interactive))

    def _show_progress(self, text):   # GUI thread
        try:
            self.gui.status_bar.show_message(text, 0)
        except Exception:
            pass

    def _mark_embedded(self, book_ids):   # GUI thread, called as soon as embed completes
        seen = set(prefs['embedded_ids'])
        seen.update(int(b) for b in book_ids)
        prefs['embedded_ids'] = sorted(seen)
        self._update_column(book_ids)
        try:
            self.gui.library_view.model().refresh_ids(list(book_ids))
        except Exception:
            pass

    def _finish(self, book_ids, asin_count, asin_attempted, embedded, did_asin,
                no_amazon_source, interactive):  # GUI
        try:
            self.gui.status_bar.clearMessage()
        except Exception:
            pass
        self._update_column(book_ids)
        try:
            self.gui.library_view.model().refresh_ids(list(book_ids))
        except Exception:
            pass

        if not column.column_exists(self.gui.current_db) and not prefs['prompted_create']:
            prefs['prompted_create'] = True
            self._offer_create_column()

        # On automatic adds, optionally convert new books to KFX and send.
        if not interactive and prefs['auto_kfx_send']:
            self._auto_kfx(book_ids)

        parts = ['Processed %d book(s).' % len(book_ids)]
        parts.append('Cover/metadata embedded into files.' if embedded
                     else 'Embedding was skipped (disabled in settings).')
        if did_asin:
            if asin_attempted == 0:
                parts.append('All selected book(s) already had an ASIN — no lookup needed.')
            else:
                parts.append('Looked up %d book(s) without an ASIN; found %d.'
                             % (asin_attempted, asin_count))
                if no_amazon_source:
                    parts.append('\n⚠ No Amazon metadata source is enabled, so no ASINs can be found.\n'
                                 'Enable it in Preferences ▸ Sharing/Downloading ▸ Metadata download '
                                 '(tick "Amazon.com"), then run this again.')
                elif asin_count == 0:
                    if prefs['browser_asin']:
                        parts.append('\nNo ASINs were found via the browser lookup. If a captcha or '
                                     'cookie-consent page appeared in the minimised window, clear it once '
                                     'and re-run. You can also set the Amazon site in Configure (ideally '
                                     'the store your Kindle uses). See "View log" for what each search returned.')
                    else:
                        parts.append('\nNo ASINs were returned by calibre\'s metadata sources. Amazon '
                                     'commonly blocks calibre\'s scraper — enable "use a real browser for '
                                     'ASIN lookup" in Configure. See "View log" for details.')
        else:
            parts.append('ASIN lookup was skipped for this run.')
        if not column.column_exists(self.gui.current_db):
            parts.append('\nTip: add the "Kindle Cover" column from this plugin\'s menu to see status.')
        log('Finished: embedded=%s asin_attempted=%d asin_found=%d no_amazon_source=%s'
            % (embedded, asin_attempted, asin_count, no_amazon_source))
        msg = '\n'.join(parts)

        if interactive:
            info_dialog(self.gui, 'Kindle Cover Fixer', msg, show=True)
        elif prefs['notify']:
            try:
                self.gui.status_bar.show_message(
                    'Kindle Cover Fixer: processed %d book(s)' % len(book_ids), 5000)
            except Exception:
                pass

    def _refresh_one(self, book_id):   # GUI thread
        self._update_column([book_id])
        try:
            self.gui.library_view.model().refresh_ids([book_id])
        except Exception:
            pass

    # ------------------------------------------ KFX / PDOC sending setup

    def setup_kfx_pdoc_action(self):
        if self._setup_kfx_pdoc(announce=True):
            prefs['kfx_pdoc_done'] = True

    def _setup_kfx_pdoc(self, announce=False):
        """Configure calibre's KFX Output to produce Personal Documents (PDOC),
        which is what makes covers appear on the Colorsoft. Requires jhowell's
        KFX Output plugin."""
        try:
            from calibre.customize.ui import output_format_plugins
            has_kfx = any(getattr(p, 'file_type', '') == 'kfx' for p in output_format_plugins())
        except Exception as err:
            log('could not enumerate output plugins: %s' % err)
            has_kfx = False
        if not has_kfx:
            log('KFX Output plugin not installed; KFX/PDOC not configured.')
            if announce:
                error_dialog(self.gui, 'Kindle Cover Fixer',
                             'The KFX Output plugin is not installed.\n\nInstall jhowell\'s '
                             '"KFX Output" (and "KFX Input") via Preferences ▸ Plugins ▸ Get new '
                             'plugins, restart calibre, then run this again.', show=True)
            return False
        try:
            from calibre.ebooks.conversion.config import load_defaults, save_defaults
            recs = load_defaults('kfx_output')
            recs['cde_type_pdoc'] = True
            save_defaults('kfx_output', recs)
            log('KFX Output configured: cde_type_pdoc=True (Personal Document / PDOC).')
        except Exception as err:
            log('failed to set KFX Output PDOC default: %s' % err)
            if announce:
                error_dialog(self.gui, 'Kindle Cover Fixer',
                             'Could not write KFX Output defaults: %s' % err, show=True)
            return False
        if prefs['set_output_format_kfx']:
            try:
                from calibre.utils.config import prefs as cprefs
                cprefs['output_format'] = 'KFX'
                log('Preferred output format set to KFX.')
            except Exception as err:
                log('could not set preferred output format: %s' % err)

        # Make KFX the format the Kindle prefers to receive, so a normal "Send to
        # device" sends KFX (when the book has it) instead of AZW3/EPUB.
        try:
            from calibre.devices.kindle.driver import KINDLE2
            opts = KINDLE2._config().parse()
            fmap = list(getattr(opts, 'format_map', None) or list(KINDLE2.FORMATS))
            if 'kfx' not in fmap:
                fmap.append('kfx')
            fmap = ['kfx'] + [f for f in fmap if f != 'kfx']
            KINDLE2._configProxy()['format_map'] = fmap
            log('Kindle device preferred format order set (KFX first): %s' % fmap)
        except Exception as err:
            log('could not set Kindle preferred format order: %s' % err)

        previewer = self._kindle_previewer_installed()
        log('Kindle Previewer 3 detected: %s' % previewer)

        if announce:
            extra = ' and the preferred output format to KFX' if prefs['set_output_format_kfx'] else ''
            msg = ('KFX Output is set to create Personal Documents (PDOC)%s, and KFX is now the '
                   'Kindle\'s preferred send format.\n\n' % extra)
            if not previewer:
                msg += ('⚠ Kindle Previewer 3 was NOT detected. KFX Output needs Amazon\'s free '
                        '"Kindle Previewer 3" app installed to actually build KFX files — without it, '
                        'calibre falls back to a normal format and covers won\'t appear. Install it '
                        'and restart calibre, then re-run this.\n\n')
            msg += ('To put covers on the Colorsoft:\n'
                    '• Connect the Kindle, select books, then this plugin ▸ "Send selected to Kindle '
                    'as KFX (convert if needed)" — it converts to KFX/PDOC and sends in one step.\n'
                    '• Or "Convert selected to KFX (PDOC)" first, then a normal Send to device (KFX is '
                    'now preferred).\n\n'
                    'Delete any old non-KFX copy from the Kindle first; restart the Kindle if a cover '
                    'doesn\'t appear. KFX books appear under "Personal Documents".')
            info_dialog(self.gui, 'Kindle Cover Fixer', msg, show=True)
        return True

    # ------------------------------------------ convert / send as KFX

    def _selected_ids(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        return [self.gui.library_view.model().id(r) for r in rows]

    # Formats from which KFX conversion is clean (reflowable). PDFs are handled
    # separately because PDF->KFX reflows badly.
    _REFLOWABLE = {'EPUB', 'AZW3', 'MOBI', 'AZW', 'FB2', 'DOCX', 'HTMLZ', 'RTF',
                   'ODT', 'LIT', 'PDB', 'TXT', 'HTML'}

    def _classify(self, ids):
        """Split book ids into (have_kfx, to_convert, pdf_asis).

        - have_kfx: already has a KFX format.
        - pdf_asis: PDF-only and 'convert PDFs to KFX' is off -> send unchanged.
        - to_convert: everything else lacking KFX -> convert to KFX."""
        db = self.gui.current_db.new_api
        convert_pdf = prefs['convert_pdf_to_kfx']
        have_kfx, to_convert, pdf_asis = [], [], []
        for bid in ids:
            try:
                fmts = {f.upper() for f in (db.field_for('formats', bid) or ())}
            except Exception:
                fmts = set()
            if 'KFX' in fmts:
                have_kfx.append(bid)
            elif 'PDF' in fmts and not (fmts & self._REFLOWABLE) and not convert_pdf:
                pdf_asis.append(bid)
            else:
                to_convert.append(bid)
        return have_kfx, to_convert, pdf_asis

    @staticmethod
    def _kfx_available():
        try:
            from calibre.customize.ui import available_output_formats
            return 'kfx' in available_output_formats()
        except Exception:
            return True

    def convert_selected_kfx(self):
        ids = self._selected_ids()
        if not ids:
            return error_dialog(self.gui, 'Kindle Cover Fixer', 'Select a book first.', show=True)
        have_kfx, to_convert, pdf_asis = self._classify(ids)
        if not to_convert:
            bits = []
            if have_kfx:
                bits.append('%d already have KFX' % len(have_kfx))
            if pdf_asis:
                bits.append('%d are PDFs sent as-is (tick "convert PDFs to KFX" to convert them)'
                            % len(pdf_asis))
            return info_dialog(self.gui, 'Kindle Cover Fixer',
                               'Nothing to convert: %s.' % ('; '.join(bits) or 'no eligible books'),
                               show=True)
        try:
            self.gui.iactions['Convert Books'].convert_ebooks_to_format(to_convert, 'KFX')
            log('Queued KFX (PDOC) conversion for %d book(s); %d PDF(s) left as-is.'
                % (len(to_convert), len(pdf_asis)))
        except Exception as err:
            log('KFX conversion failed to start: %s' % err)
            error_dialog(self.gui, 'Kindle Cover Fixer',
                         'Could not start KFX conversion: %s' % err, show=True)

    def _auto_kfx(self, book_ids):
        """Auto path: convert newly-added books to KFX (PDOC) and, if a Kindle is
        connected, send them. PDFs are sent as-is (or converted if configured).
        Books already having KFX are left alone."""
        have_kfx, to_convert, pdf_asis = self._classify(book_ids)
        conv = self.gui.iactions.get('Convert Books')
        connected = bool(getattr(self.gui, 'device_connected', None))

        if to_convert and conv is not None:
            if not self._kfx_available():
                log('Auto-KFX skipped (KFX Output not available) for %d book(s).' % len(to_convert))
            else:
                try:
                    if connected:
                        conv.auto_convert(to_convert, None, 'KFX')
                        log('Auto-KFX: convert+send queued for %d book(s).' % len(to_convert))
                    else:
                        conv.convert_ebooks_to_format(to_convert, 'KFX')
                        log('Auto-KFX: convert-only (no device) for %d book(s).' % len(to_convert))
                except Exception as err:
                    log('Auto-KFX failed: %s' % err)

        if pdf_asis:
            if connected:
                try:
                    self.gui.sync_to_device(None, False, specific_format='PDF',
                                            send_ids=pdf_asis, do_auto_convert=False)
                    log('Auto: sent %d PDF(s) as-is (PDFs do not get a cover on the Colorsoft).'
                        % len(pdf_asis))
                except Exception as err:
                    log('Auto PDF send failed: %s' % err)
            else:
                log('Auto: %d PDF(s) left as-is (no device connected).' % len(pdf_asis))

    def send_selected_kfx(self):
        ids = self._selected_ids()
        if not ids:
            return error_dialog(self.gui, 'Kindle Cover Fixer', 'Select a book first.', show=True)
        if not getattr(self.gui, 'device_connected', None):
            return error_dialog(self.gui, 'Kindle Cover Fixer',
                                'Connect your Kindle by USB first.', show=True)
        have_kfx, to_convert, pdf_asis = self._classify(ids)
        conv = self.gui.iactions['Convert Books']
        try:
            if to_convert:
                conv.auto_convert(to_convert, None, 'KFX')   # convert (PDOC) then upload as KFX
            if have_kfx:
                self.gui.sync_to_device(None, False, specific_format='KFX',
                                        send_ids=have_kfx, do_auto_convert=False)
            if pdf_asis:
                self.gui.sync_to_device(None, False, specific_format='PDF',
                                        send_ids=pdf_asis, do_auto_convert=False)
            log('Send: %d as KFX, %d converting+sending, %d PDF as-is.'
                % (len(have_kfx), len(to_convert), len(pdf_asis)))
            note = []
            if to_convert:
                note.append('%d converting to KFX' % len(to_convert))
            if have_kfx:
                note.append('%d sent as KFX' % len(have_kfx))
            if pdf_asis:
                note.append('%d PDF(s) sent as-is (no cover on Colorsoft)' % len(pdf_asis))
            info_dialog(self.gui, 'Kindle Cover Fixer',
                        'Sending to your Kindle: %s.' % '; '.join(note), show=True)
        except Exception as err:
            log('send-as-KFX failed: %s' % err)
            error_dialog(self.gui, 'Kindle Cover Fixer', 'Send failed: %s' % err, show=True)

    def send_pdfs_via_amazon(self):
        """Email selected PDFs to the user's @kindle.com with subject 'Convert',
        so Amazon converts them server-side into a Kindle document (which gets a
        cover). This is the only route that gives PDFs a cover without the lossy
        local PDF->KFX reflow; downside is it goes via Amazon's cloud."""
        ids = self._selected_ids()
        if not ids:
            return error_dialog(self.gui, 'Kindle Cover Fixer', 'Select a book first.', show=True)
        db = self.gui.current_db.new_api
        pdf_ids = []
        for bid in ids:
            try:
                fmts = {f.upper() for f in (db.field_for('formats', bid) or ())}
            except Exception:
                fmts = set()
            if 'PDF' in fmts:
                pdf_ids.append(bid)
        if not pdf_ids:
            return info_dialog(self.gui, 'Kindle Cover Fixer',
                               'None of the selected book(s) have a PDF format.', show=True)
        addr = (prefs['kindle_email'] or '').strip()
        if not addr:
            return error_dialog(self.gui, 'Kindle Cover Fixer',
                                'Set your Kindle email (name@kindle.com) in this plugin\'s Configure '
                                'dialog first.', show=True)
        try:
            from calibre.utils.smtp import config as email_config
            if not email_config().parse().relay_host:
                return error_dialog(self.gui, 'Kindle Cover Fixer',
                                    'Outgoing email is not configured. Set it up in '
                                    'Preferences ▸ Sharing books by email, then try again.', show=True)
        except Exception:
            pass
        try:
            self.gui.send_by_mail(addr, ['pdf'], False, subject='Convert', send_ids=pdf_ids,
                                  do_auto_convert=False, specific_format='pdf')
            log('Emailed %d PDF(s) to %s with subject "Convert".' % (len(pdf_ids), addr))
            info_dialog(self.gui, 'Kindle Cover Fixer',
                        'Emailing %d PDF(s) to %s with subject "Convert" so Amazon converts them '
                        '(they then appear under Documents with a cover).\n\nThe sender address must '
                        'be in your Amazon "Approved Personal Document E-mail List", and outgoing '
                        'email must be set up in calibre.' % (len(pdf_ids), addr), show=True)
        except Exception as err:
            log('Amazon PDF send failed: %s' % err)
            error_dialog(self.gui, 'Kindle Cover Fixer', 'Send failed: %s' % err, show=True)

    @staticmethod
    def _kindle_previewer_installed():
        try:
            import sys
            if sys.platform == 'win32':
                import winreg
                try:
                    winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Amazon\Kindle Previewer 3')
                    return True
                except OSError:
                    return False
            import os
            return os.path.exists('/Applications/Kindle Previewer 3.app')
        except Exception:
            return False

    # ------------------------------------------ diagnostics & log viewer

    def diagnose(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        ids = [self.gui.library_view.model().id(r) for r in rows]
        if not ids:
            return error_dialog(self.gui, 'Kindle Cover Fixer', 'Select a book first.', show=True)
        bid = ids[0]
        db = self.gui.current_db.new_api
        mi = db.get_metadata(bid)
        log('--- DIAGNOSE ---')
        log('Book: "%s" by %s' % (mi.title, ', '.join(mi.authors or [])))
        log('Current identifiers: %s' % (dict(mi.identifiers or {}) or '(none)'))
        log('Kindle Cover column %s exists: %s' % (column.LOOKUP, column.column_exists(self.gui.current_db)))
        log('Embedded (tracked by plugin): %s' % (int(bid) in set(prefs['embedded_ids'])))
        try:
            self.gui.status_bar.show_message('Kindle Cover Fixer: diagnosing (online lookup)…', 0)
        except Exception:
            pass

        def work():
            from calibre_plugins.kindle_cover_fixer.asin import (
                enabled_sources, lookup_identifiers, asin_from_identifiers)
            srcs = enabled_sources()
            log('Enabled metadata sources: %s' % (', '.join(srcs) or '(none)'))
            if not any('amazon' in s.lower() for s in srcs):
                log('WARNING: no Amazon source enabled -> ASIN lookup will always fail.')
            results = lookup_identifiers(mi)
            log('identify returned %d result(s)' % len(results))
            chosen = None
            for r in results:
                log('  ids: %s' % r)
                chosen = chosen or asin_from_identifiers(r)
            log('ASIN that would be used: %s' % (chosen or '(none found)'))
            self._bridge.run_on_gui.emit(self._after_diagnose)

        threading.Thread(target=work, daemon=True).start()

    def _after_diagnose(self):
        try:
            self.gui.status_bar.clearMessage()
        except Exception:
            pass
        self.view_log()

    def view_log(self):
        text = get_log() or '(log is empty — run "Process selected books" or "Diagnose" first)'
        d = QDialog(self.gui)
        d.setWindowTitle('Kindle Cover Fixer — log')
        d.resize(820, 520)
        lay = QVBoxLayout(d)
        te = QPlainTextEdit(d)
        te.setReadOnly(True)
        te.setPlainText(text)
        try:
            te.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        except Exception:
            try:
                te.setLineWrapMode(QPlainTextEdit.NoWrap)
            except Exception:
                pass
        lay.addWidget(te)
        row = QHBoxLayout()
        row.addStretch(1)
        copy_btn = QPushButton('Copy', d)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(te.toPlainText()))
        row.addWidget(copy_btn)
        clear_btn = QPushButton('Clear', d)
        clear_btn.clicked.connect(lambda: (clear_log(), te.setPlainText('(cleared)')))
        row.addWidget(clear_btn)
        close_btn = QPushButton('Close', d)
        close_btn.clicked.connect(d.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)
        d.exec()

    # ------------------------------------------------ Kindle Cover column

    def _update_column(self, book_ids):
        """Write the per-book status into the #kindle_cover column (if present)."""
        db = self.gui.current_db
        if not column.column_exists(db):
            return
        api = db.new_api
        embedded = set(prefs['embedded_ids'])
        cmap = {}
        for bid in book_ids:
            try:
                ids = api.field_for('identifiers', bid) or {}
            except Exception:
                ids = {}
            cmap[bid] = column.status_for(column.has_asin(ids), int(bid) in embedded)
        try:
            api.set_field(column.LOOKUP, cmap)
        except Exception as err:
            from calibre import prints
            prints('Kindle Cover Fixer: column update failed:', err)

    def add_column(self):
        db = self.gui.current_db
        if column.column_exists(db):
            return info_dialog(self.gui, 'Kindle Cover Fixer',
                               'The "Kindle Cover" column already exists.', show=True)
        try:
            column.create_column(db)
        except Exception as err:
            return error_dialog(self.gui, 'Kindle Cover Fixer',
                                'Could not create the column: %s' % err, show=True)
        info_dialog(self.gui, 'Kindle Cover Fixer',
                    'Created the "Kindle Cover" column. Please restart calibre for it to appear, '
                    'then use the plugin menu ▸ "Refresh Kindle Cover column" to populate it.',
                    show=True)

    def _offer_create_column(self):
        if question_dialog(self.gui, 'Kindle Cover Fixer',
                           'Add a "Kindle Cover" status column to your book list?\n\n'
                           'It shows "ASIN", "ASIN+Embed" or blank per book. '
                           'calibre will need a restart after it is created.'):
            self.add_column()

    def refresh_column_all(self):
        db = self.gui.current_db
        if not column.column_exists(db):
            return self._offer_create_column()
        api = db.new_api
        embedded = set(prefs['embedded_ids'])
        cmap = {}
        for bid in api.all_book_ids():
            try:
                ids = api.field_for('identifiers', bid) or {}
            except Exception:
                ids = {}
            cmap[bid] = column.status_for(column.has_asin(ids), int(bid) in embedded)
        try:
            api.set_field(column.LOOKUP, cmap)
            self.gui.library_view.model().refresh()
        except Exception as err:
            return error_dialog(self.gui, 'Kindle Cover Fixer',
                                'Could not update the column: %s' % err, show=True)
        info_dialog(self.gui, 'Kindle Cover Fixer',
                    'Updated the Kindle Cover column for %d book(s).' % len(cmap), show=True)
