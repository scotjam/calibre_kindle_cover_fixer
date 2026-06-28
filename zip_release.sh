#!/bin/bash
version=$(grep ' version' __init__.py | sed -r "s/^.*version\s*= \(([0-9]+), ([0-9]+), ([0-9]+)\).*/\1.\2.\3/")
zip "calibre_kindle_cover_fixer-v${version}.zip" README.md plugin-import-name-kindle_cover_fixer.txt __init__.py ui.py config.py asin.py asin_browser.py asin_cache.py column.py plog.py images/icon.png
