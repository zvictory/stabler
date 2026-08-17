"""Regression for stabler-abs7: harvest.py must write LF-terminated CSVs.

`csv.writer` defaults to a CRLF line terminator regardless of how the file was
opened (opening with `newline=""` only stops the *file layer* from translating
`\n`, it does not touch what the writer itself emits). `_write_csv` used to open
with `newline=""` and an unset `lineterminator`, so every harvest run rewrote all
five catalogs from LF to CRLF -- a full-file diff on every commit that touched a
translation. The committed catalogs are LF; this test pins the writer to that.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock


def _under_bench() -> bool:
	try:
		import frappe

		return frappe.local.site is not None
	except Exception:
		return False


_UNDER_BENCH = _under_bench()

frappe_mock = MagicMock()
frappe_mock.get_app_path = MagicMock(return_value=".")

_FAKES = {"frappe": frappe_mock}

if not _UNDER_BENCH:
	_SAVED = {name: sys.modules.get(name) for name in _FAKES}
	sys.modules.update(_FAKES)

from stabler.translations import harvest

if not _UNDER_BENCH:
	for _name, _saved in _SAVED.items():
		if _saved is None:
			sys.modules.pop(_name, None)
		else:
			sys.modules[_name] = _saved


@unittest.skipIf(_UNDER_BENCH, "needs the frappe mock: runs in its own process via `make test`")
class TestWriteCsvEmitsLf(unittest.TestCase):
	def test_write_csv_never_emits_crlf(self):
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "out.csv"
			harvest._write_csv(path, {"hello": "hello", "world": "world"})
			data = path.read_bytes()
			self.assertNotIn(b"\r\n", data)
			self.assertEqual(data, b"source,target\nhello,hello\nworld,world\n")


if __name__ == "__main__":
	unittest.main()
