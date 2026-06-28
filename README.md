# Kindle Cover Fixer (calibre plugin)

> **Disclaimer:** This is an independent, unofficial calibre plugin with **no association with,
> endorsement by, or affiliation with Amazon or Kindle**. "Amazon", "Kindle", and "Colorsoft" are
> trademarks of their respective owners and are used here only to describe interoperability.

Helps sideloaded book covers show on Kindles.

> **The only thing we found that reliably shows covers on modern Kindle Colorsoft firmware is the
> KFX / Personal-Document (PDOC) route** (see *Important: the Colorsoft cover situation* below). The
> plugin automates that, and can auto-convert + send books as KFX/PDOC.

The plugin also does the two things below. These **may** help on some (older) Kindle versions, and
they make covers correct in the calibre library, other readers, and Send-to-Kindle — but on a current
Colorsoft they are **not** sufficient on their own:

1. **Embed the cover + metadata into the book files.** Downloading metadata in calibre only updates
   the *library*; a Kindle reads the cover from the *file*. This plugin writes the library cover and
   metadata into the actual book files (`db.embed_metadata`).
2. **Look up and store the Amazon ASIN.** Some Kindles fetch covers from Amazon by ASIN. This plugin
   uses calibre's metadata sources (and a real-browser lookup) to find the Kindle ASIN and stores it
   as the `mobi-asin` / `amazon` identifier, which embedding then writes into the file.

It runs **automatically whenever books are added/downloaded** (it listens for the library's
`book_created` event, so it catches store-plugin downloads and manual adds alike), or on demand for
selected books.

## Important: the Colorsoft cover situation
On the **Colorsoft** (and PW6 / other MTP Kindles) Amazon **blocked the `system/thumbnails` folder**
that calibre used to upload sideloaded covers — so on those devices **embedding the cover + USB does
NOT make the home-screen cover appear**, no matter what. The two things that *do* work there:

1. **Send the book as a Personal Document (PDOC), in KFX, over USB.** The Kindle then generates its own
   cover thumbnail. Install jhowell's **KFX Output** (+ KFX Input) plugin; **this plugin then
   auto-configures KFX Output to produce PDOC** (option `cde_type_pdoc`) and sets calibre's preferred
   output format to KFX — both toggleable in its Configure dialog, or re-run from its menu ▸
   *Set up KFX + PDOC sending*. Verify: a PDOC book appears under **"Personal Documents"** on the
   device, and that's when the cover shows. Trade-off: no Whispersync, books under "Personal Documents".
2. **A valid ASIN for a book that exists on *your* Kindle's Amazon store** (kept as EBOK) — then the
   Colorsoft pulls the cover from Amazon's servers. Only works for titles actually sold on that store.

**What this plugin does:** it automates *both* routes.
- **Route #1 (the Colorsoft fix):** *Set up KFX + PDOC sending* configures calibre's KFX Output to
  produce **PDOC**, makes **KFX** the preferred output and the Kindle's preferred send format, and then
  the plugin can **convert books to KFX/PDOC and send them** to a connected Kindle — automatically on
  add (optional checkbox) or on demand via *Send selected to Kindle as KFX*. Requires the **KFX Output**
  plugin and **Kindle Previewer 3**.
- **Route #2:** it embeds the cover/metadata into the files and finds/stores the Amazon ASIN — helps for
  Amazon-catalogue titles and makes covers correct in the calibre library, other readers, and
  Send-to-Kindle.

For a mixed, non-Amazon library, route #1 (KFX + PDOC) is what actually shows covers on the Colorsoft.

## Recommended workflow
1. Download or add books and *Download metadata/cover* in calibre.
2. Let this plugin embed cover/metadata (+ASIN) — automatic, or via its toolbar button.
3. For Colorsoft home-screen covers: send as **KFX / PDOC** over USB (see above). For books that are on
   your Amazon store, the embedded ASIN lets the device fetch the cover while staying a normal "Book".

## "Kindle Cover" status column
The plugin can add a custom column to the book list showing each book's state:
- **`ASIN+Embed`** — it has an Amazon ASIN *and* this plugin has embedded its cover/metadata into the files.
- **`ASIN`** — the book has an Amazon ASIN stored (not yet embedded by this plugin).
- **`Embed`** — this plugin has embedded the cover/metadata, but there's no ASIN.
- *blank* — neither.

Note: "embedded" reflects what *this plugin* has done (it can't tell whether a file was embedded by
some other means), so run **Process selected books now** on existing books to embed + mark them.

Create it from the plugin's toolbar menu ▸ **Add "Kindle Cover" status column** (calibre must be
restarted once afterwards, as adding any custom column is a schema change). Then menu ▸
**Refresh "Kindle Cover" column (all books)** populates it for your whole library; it is also updated
automatically for books the plugin processes.

## Menu actions
From the plugin's toolbar button (▾):
- **Process selected books now** — embed cover/metadata (+ ASIN) into the selected books.
- **Add / Refresh "Kindle Cover" status column** — see below.
- **Set up KFX + PDOC sending (Colorsoft covers)** — configures KFX Output → PDOC, sets KFX as the
  preferred output + device send format, and warns if Kindle Previewer 3 is missing.
- **Convert selected to KFX (PDOC)** — converts the selected (reflowable) books to KFX.
- **Send selected to Kindle as KFX (convert if needed)** — with the Kindle on USB: sends KFX (or
  converts then sends); PDFs are sent as-is (or converted, per setting).
- **Send selected PDFs to Kindle via Amazon (convert)** — emails the PDFs to your @kindle.com with
  subject "Convert" so Amazon converts them into a covered Kindle doc (see *Covers for PDFs* below).
- **Diagnose ASIN lookup (selected book)** / **View log** — troubleshooting.

## Covers for PDFs (via Amazon)
A sideloaded PDF gets **no cover** on the Colorsoft, and local PDF→KFX only works by reflowing (lossy).
The clean route is to let **Amazon** convert the PDF in the cloud: **Send selected PDFs to Kindle via
Amazon (convert)** emails them to your Kindle address with subject "Convert"; Amazon returns a Kindle
document with a cover. One-time setup:
1. **Configure ▸ "Kindle email"** → your `name@kindle.com` (Amazon ▸ Manage Your Content and Devices ▸ Devices).
2. **Preferences ▸ Sharing books by email** → set up the outgoing (SMTP) account calibre sends from.
3. Add that sender address to Amazon's **Approved Personal Document E-mail List** (details below).

### Amazon's Approved Personal Document E-mail List
This is an allow-list on your Amazon account: Amazon only accepts a document emailed to your
`@kindle.com` address if the **sender** is on this list — otherwise it's silently dropped (the usual
reason "send to Kindle by email" appears to do nothing).

- **Where to manage it:** Amazon → **Manage Your Content and Devices** → **Preferences** tab →
  **Personal Document Settings** → **Approved Personal Document E-mail List** → *Add a new approved
  e-mail address*.
- **What to add:** the email address calibre **sends *from*** — i.e. the "from"/account address you
  set up in calibre's **Preferences ▸ Sharing books by email**. (Not your `@kindle.com` address —
  that's the *destination*, found on the same Personal Document Settings page, one per device.)

The full chain: calibre sends *from* `you@example.com` → *to* `yourname@kindle.com` → Amazon checks
`you@example.com` is approved → converts (subject "Convert") → delivers to the Kindle with a cover.

Trade-offs: it goes via Amazon's cloud, needs Wi-Fi on the Kindle, and isn't instant. (Or tick
*convert PDFs to KFX* to reflow locally instead — gets a cover, lower quality.)

## Settings
`Preferences ▸ Plugins ▸ Kindle Cover Fixer` (or its toolbar button ▸ Configure):
- **Automatically process newly added / downloaded books** — the auto trigger (on/off).
- **Embed cover + metadata into the book files** — needed by all cover routes.
- **Look up and embed the Amazon ASIN** (+ **use a real browser** / **Amazon site**) — see *ASIN lookup*.
- **Send as KFX Personal Documents** (+ **set preferred output to KFX**, **on every add: auto-convert
  to KFX and send**, **convert PDFs to KFX too**) — the Colorsoft cover route.
- **Kindle email** — for *Send PDFs via Amazon*.
- **Only auto-process books tagged …** — optional filter (blank = all new books).
- **Show a notification after automatic processing.**

## Installation

**Prerequisites** (required for the KFX / PDOC Colorsoft cover route):
1. **Amazon Kindle Previewer 3** — download and install it from Amazon (free). KFX files are built by
   Kindle Previewer, so KFX conversion fails without it.
2. **KFX Output** and **KFX Input** plugins — in calibre go to
   **Preferences ▸ Plugins ▸ Get new plugins** ("Get plugins to enhance calibre"), search for and
   install both.

**Install this plugin — from the release zip:**
1. **Preferences ▸ Advanced ▸ Plugins ▸ Load plugin from file**, and select
   `calibre_kindle_cover_fixer-vX.XX.XX.zip` from the
   [Releases](https://github.com/scotjam/calibre_kindle_cover_fixer/releases) page.
2. **Restart calibre** once both plugins (KFX Output and this one) are installed.

**Or from source:**
```shell
calibre-customize -b <path to this folder>
```
or build the zip and load it: `./zip_release.sh` then *Load plugin from file*. Restart calibre afterwards.

After restarting, run the plugin menu ▸ **Set up KFX + PDOC sending** to apply the settings — it warns
if Kindle Previewer 3 isn't detected.

## ASIN lookup
Amazon actively blocks calibre's built-in Amazon metadata source (it times out and returns nothing
even when the book clearly exists), so by default this plugin looks up ASINs with a **real, minimised
browser** (`browser_asin` setting, on by default): it runs a **Google search** first (which surfaces
the Amazon `/dp/<ASIN>` link immediately), then falls back to **Amazon's own search**. Set the
**Amazon site** in Configure to the store your Kindle uses (e.g. amazon.com, amazon.co.uk). If a
captcha / cookie-consent page appears, the minimised window is surfaced so you can clear it once.

Found ASINs are **cached** by ISBN (or title+author) in
`plugins/kindle_cover_fixer_cache.json`, so removing and re-adding a book won't re-fetch it.

Turn the browser option off to fall back to calibre's metadata sources (only works if the Amazon
source is enabled and not blocked). Use menu ▸ **Diagnose ASIN lookup (selected book)** and
▸ **View log** to see exactly what happened.

Note: a found ASIN only makes the **Colorsoft** pull a cover if that ASIN exists on the Amazon store
your Kindle is registered to. (Embedding the cover alone does **not** show covers on the Colorsoft —
see *Important: the Colorsoft cover situation* above.)

## Limitations / status
- ASIN lookup depends on calibre's Amazon metadata source (rate-limited; only matches books with a
  Kindle edition).
- **PDFs:** a sideloaded PDF gets no cover on the Colorsoft, and Kindle Previewer (so calibre's KFX
  conversion) does **not** accept PDF as a layout-preserving input — PDF→KFX only works by reflowing
  the text (lossy). So a PDF either stays cover-less (sent as-is, the default), is reflowed to KFX
  (tick "convert PDFs to KFX", lower quality but gets a cover), or is sent via Amazon's Send to Kindle
  with conversion (cloud; gets a cover).
- Built against calibre's `db.new_api` (`add_listener`/`book_created`, `embed_metadata`, `set_field`)
  and `identify()`, with Qt5/Qt6 import guards. Developed and used with calibre 9.x on Windows.
