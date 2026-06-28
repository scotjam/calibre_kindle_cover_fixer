from calibre.utils.config import JSONConfig

try:
    from qt.core import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QLineEdit, QFrame
except (ImportError, ModuleNotFoundError):
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QLineEdit, QFrame

# Stored under <calibre config>/plugins/kindle_cover_fixer.json
prefs = JSONConfig('plugins/kindle_cover_fixer')
prefs.defaults['auto_enabled'] = True      # act on newly added/downloaded books
prefs.defaults['embed_metadata'] = True    # embed cover+metadata into the book files
prefs.defaults['fetch_asin'] = True        # look up & store the Amazon ASIN
prefs.defaults['only_tags'] = ''           # if set, only auto-process books with one of these tags
prefs.defaults['notify'] = True            # show a small notification after auto-processing
prefs.defaults['embedded_ids'] = []        # book ids whose files we have embedded (for the status column)
prefs.defaults['prompted_create'] = False  # have we offered to create the Kindle Cover column yet
prefs.defaults['browser_asin'] = True      # use a real browser for ASIN lookup (calibre's Amazon source is blocked)
prefs.defaults['amazon_domain'] = 'amazon.com'  # which Amazon site to search
prefs.defaults['kfx_pdoc_setup'] = True    # configure KFX output as PDOC (Colorsoft cover fix)
prefs.defaults['set_output_format_kfx'] = True  # also set calibre's preferred output format to KFX
prefs.defaults['kfx_pdoc_done'] = False    # have we applied the KFX/PDOC config once already
prefs.defaults['auto_kfx_send'] = True     # on add: auto-convert to KFX and send to a connected Kindle
prefs.defaults['convert_pdf_to_kfx'] = False  # PDFs: default send as-is; if True, convert to KFX too
prefs.defaults['kindle_email'] = ''        # @kindle.com address for "Send PDFs via Amazon (convert)"


class ConfigWidget(QWidget):

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.auto = QCheckBox('Automatically process newly added / downloaded books')
        self.auto.setChecked(prefs['auto_enabled'])
        layout.addWidget(self.auto)

        self.embed = QCheckBox('Embed cover + metadata into the book files')
        self.embed.setToolTip('Writes the library cover and metadata into the actual book files so a '
                              'Kindle (especially when sideloaded over USB) can show the cover.')
        self.embed.setChecked(prefs['embed_metadata'])
        layout.addWidget(self.embed)

        self.asin = QCheckBox('Look up and embed the Amazon ASIN (for Kindle Colorsoft covers)')
        self.asin.setToolTip('The Colorsoft fetches covers from Amazon by ASIN. This uses your enabled '
                             'metadata sources (incl. Amazon) to find the Kindle ASIN and stores it as '
                             'the mobi-asin / amazon identifier, which embedding then writes into the file.')
        self.asin.setChecked(prefs['fetch_asin'])
        layout.addWidget(self.asin)

        self.browser_asin = QCheckBox('   ↳ use a real browser for ASIN lookup (recommended)')
        self.browser_asin.setToolTip(
            "calibre's built-in Amazon source is usually blocked by Amazon's anti-bot. When enabled, "
            "ASINs are found with a real (minimised) browser via a Google search then Amazon search, "
            "and cached so they aren't re-fetched if you remove/re-add a book.")
        self.browser_asin.setChecked(prefs['browser_asin'])
        layout.addWidget(self.browser_asin)

        drow = QHBoxLayout()
        drow.addWidget(QLabel('      Amazon site to search:'))
        self.amazon_domain = QLineEdit(prefs['amazon_domain'])
        self.amazon_domain.setToolTip('e.g. amazon.com, amazon.co.uk, amazon.de — ideally the store '
                                      'your Kindle is registered to.')
        drow.addWidget(self.amazon_domain)
        layout.addLayout(drow)

        row = QHBoxLayout()
        row.addWidget(QLabel('Only auto-process books tagged (comma separated, blank = all):'))
        self.only_tags = QLineEdit(prefs['only_tags'])
        row.addWidget(self.only_tags)
        layout.addLayout(row)

        self.notify = QCheckBox('Show a notification after automatic processing')
        self.notify.setChecked(prefs['notify'])
        layout.addWidget(self.notify)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine if hasattr(QFrame, 'Shape') else QFrame.HLine)
        layout.addWidget(line)

        self.kfx_pdoc_setup = QCheckBox('Send as KFX Personal Documents (the only thing that shows '
                                        'covers on Kindle Colorsoft)')
        self.kfx_pdoc_setup.setToolTip(
            'Colorsoft (and PW6/MTP Kindles) ignore sideloaded cover thumbnails. The fix is to send '
            'books as KFX with content type PDOC. This configures calibre\'s KFX Output to produce '
            'PDOC. Requires the KFX Output plugin (jhowell). Trade-off: books appear under "Personal '
            'Documents" and lose Whispersync.')
        self.kfx_pdoc_setup.setChecked(prefs['kfx_pdoc_setup'])
        layout.addWidget(self.kfx_pdoc_setup)

        self.set_output_format_kfx = QCheckBox('   ↳ also set calibre\'s preferred output format to KFX')
        self.set_output_format_kfx.setChecked(prefs['set_output_format_kfx'])
        layout.addWidget(self.set_output_format_kfx)

        self.auto_kfx_send = QCheckBox('   ↳ on every add: auto-convert to KFX and send to a connected Kindle')
        self.auto_kfx_send.setToolTip(
            'When a book is added, automatically convert it to KFX (PDOC) and, if a Kindle is '
            'connected by USB, send it. Skipped if the book already has a KFX format. Requires the '
            'KFX Output plugin + Kindle Previewer 3. KFX conversion is slow, so this queues a job per '
            'new book.')
        self.auto_kfx_send.setChecked(prefs['auto_kfx_send'])
        layout.addWidget(self.auto_kfx_send)

        self.convert_pdf = QCheckBox('         • convert PDFs to KFX too (default: send PDFs as-is)')
        self.convert_pdf.setToolTip(
            'By default PDFs are sent to the Kindle unchanged — PDF→KFX conversion is slow and low '
            'quality. Tick this to convert PDFs to KFX like other formats instead.')
        self.convert_pdf.setChecked(prefs['convert_pdf_to_kfx'])
        layout.addWidget(self.convert_pdf)

        krow = QHBoxLayout()
        krow.addWidget(QLabel('Kindle email (for "Send PDFs via Amazon"):'))
        self.kindle_email = QLineEdit(prefs['kindle_email'])
        self.kindle_email.setToolTip(
            'Your @kindle.com address (Amazon ▸ Manage Your Content and Devices ▸ Devices). PDFs are '
            'emailed here with subject "Convert" so Amazon converts them to a Kindle document with a '
            'cover. Requires outgoing email set up in Preferences ▸ Sharing books by email, and the '
            'sender address approved in Amazon\'s Personal Document E-mail List.')
        krow.addWidget(self.kindle_email)
        layout.addLayout(krow)

        note = QLabel(
            '<i>Tip: covers on the Colorsoft are most reliable when you send over USB from calibre with '
            'the cover embedded (this plugin does the embedding). ASIN lookup only helps for books that '
            'have a matching Kindle edition on Amazon.</i>')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def save_settings(self):
        prefs['auto_enabled'] = self.auto.isChecked()
        prefs['embed_metadata'] = self.embed.isChecked()
        prefs['fetch_asin'] = self.asin.isChecked()
        prefs['browser_asin'] = self.browser_asin.isChecked()
        prefs['amazon_domain'] = (self.amazon_domain.text().strip() or 'amazon.com')
        prefs['only_tags'] = self.only_tags.text().strip()
        # If the user just (re)enabled KFX/PDOC setup, re-apply it on next start.
        if self.kfx_pdoc_setup.isChecked() and not prefs['kfx_pdoc_setup']:
            prefs['kfx_pdoc_done'] = False
        prefs['kfx_pdoc_setup'] = self.kfx_pdoc_setup.isChecked()
        prefs['set_output_format_kfx'] = self.set_output_format_kfx.isChecked()
        prefs['auto_kfx_send'] = self.auto_kfx_send.isChecked()
        prefs['convert_pdf_to_kfx'] = self.convert_pdf.isChecked()
        prefs['kindle_email'] = self.kindle_email.text().strip()
        prefs['notify'] = self.notify.isChecked()
