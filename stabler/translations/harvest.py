"""Translation harvester.

Scans Vue and Python sources for translation calls and merges any
missing keys into each language CSV under stabler/translations/.

Matched calls:
- Vue / JS:  t("source") or t('source')
- Python:    __("source"), __('source'), _("source"), _('source')

The CSVs use a flat `source,target` schema (no Frappe `csv.QUOTE_*` weirdness).
Existing rows are preserved as-is; only new sources are appended. After
appending, rows are sorted alphabetically by source so reruns are
deterministic.

Run via:
    bench --site stabler execute stabler.translations.harvest.run

Returns a dict summarising what was added per language for the bench log.
"""

from __future__ import annotations

import csv
import os
import re
from collections.abc import Iterable
from pathlib import Path

import frappe

_APP_ROOT = Path(frappe.get_app_path("stabler"))
_TRANSLATIONS_DIR = _APP_ROOT / "translations"

_LANGS = ("en", "ru", "uz", "uzc", "tr")

# Single + double quoted strings. Backreference enforces matching quotes.
_VUE_PATTERN = re.compile(r"""\bt\(\s*(['"])(?P<src>(?:\\.|(?!\1).)*?)\1""")
_PY_PATTERN = re.compile(r"""\b_{1,2}\(\s*(['"])(?P<src>(?:\\.|(?!\1).)*?)\1""")

# Skip generated bundles + test fixtures; they don't ship user-facing strings.
_SKIP_DIRS = {"__pycache__", "node_modules", "dist", "public/dist", ".git"}


def _walk(suffix: str) -> Iterable[Path]:
	for dirpath, dirnames, filenames in os.walk(_APP_ROOT):
		dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
		for name in filenames:
			if name.endswith(suffix):
				yield Path(dirpath) / name


def _collect_sources() -> set[str]:
	sources: set[str] = set()

	for path in _walk(".vue"):
		try:
			text = path.read_text(encoding="utf-8")
		except OSError:
			continue
		for match in _VUE_PATTERN.finditer(text):
			src = match.group("src").replace("\\'", "'").replace('\\"', '"')
			if src:
				sources.add(src)

	for path in _walk(".js"):
		try:
			text = path.read_text(encoding="utf-8")
		except OSError:
			continue
		for match in _VUE_PATTERN.finditer(text):
			src = match.group("src").replace("\\'", "'").replace('\\"', '"')
			if src:
				sources.add(src)

	for path in _walk(".py"):
		# Don't harvest from this file or it loops on its own patterns.
		if path.name == "harvest.py":
			continue
		try:
			text = path.read_text(encoding="utf-8")
		except OSError:
			continue
		for match in _PY_PATTERN.finditer(text):
			src = match.group("src").replace("\\'", "'").replace('\\"', '"')
			if src:
				sources.add(src)

	return sources


def _read_csv(path: Path) -> dict[str, str]:
	rows: dict[str, str] = {}
	if not path.exists():
		return rows
	with path.open("r", encoding="utf-8", newline="") as fh:
		reader = csv.reader(fh)
		header = next(reader, None)
		# Tolerate either with-header or without-header CSVs.
		if header and header != ["source", "target"]:
			# Treat first row as data if it isn't the header.
			if len(header) >= 2:
				rows[header[0]] = header[1]
		for row in reader:
			if len(row) >= 2 and row[0]:
				rows[row[0]] = row[1]
	return rows


def _write_csv(path: Path, rows: dict[str, str]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8", newline="") as fh:
		writer = csv.writer(fh)
		writer.writerow(["source", "target"])
		for source in sorted(rows):
			writer.writerow([source, rows[source]])


def run() -> dict[str, int]:
	"""Harvest sources, merge into each language CSV. Returns added-count per lang."""
	sources = _collect_sources()
	added: dict[str, int] = {}
	for lang in _LANGS:
		path = _TRANSLATIONS_DIR / f"{lang}.csv"
		existing = _read_csv(path)
		new_keys = [s for s in sources if s not in existing]
		for source in new_keys:
			# en.csv defaults target=source; other languages start empty
			# (translator fills in). Missing target → t() falls back to source.
			existing[source] = source if lang == "en" else ""
		_write_csv(path, existing)
		added[lang] = len(new_keys)
	print(f"[stabler.translations.harvest] added per lang: {added}")
	return added
