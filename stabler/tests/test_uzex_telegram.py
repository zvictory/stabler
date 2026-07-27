"""Unit tests for stabler.integrations.uzex.telegram builders (WP-307, Frappe-free).

cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_uzex_telegram -v
"""

from __future__ import annotations

import unittest

from stabler.integrations.uzex.telegram import (
	build_keyboard,
	build_new_lot_text,
	parse_callback,
	verify_secret,
)

_NORM = {
	"lot_id": 500606,
	"lot_no": "26121006500606",
	"name": "Bosmaxona xizmatlari tenderi",
	"customer_org": "Shahrisabz 1-son maktab",
	"start_price": 162975654.0,
	"currency": "UZS",
	"deadline": "2026-07-08 11:47:09",
}


class TestBuildText(unittest.TestCase):
	def test_contains_key_fields(self):
		txt = build_new_lot_text(_NORM)
		self.assertIn("26121006500606", txt)
		self.assertIn("Bosmaxona", txt)
		self.assertIn("Shahrisabz", txt)
		self.assertIn("2026-07-08 11:47:09", txt)
		# price formatted with space thousands, no comma
		self.assertIn("162 975 654", txt)
		self.assertNotIn("162,975,654", txt)

	def test_html_escaped(self):
		txt = build_new_lot_text({"lot_no": "1", "name": "A & B <tag>"})
		self.assertIn("&amp;", txt)
		self.assertIn("&lt;tag&gt;", txt)
		self.assertNotIn("<tag>", txt)

	def test_sparse_norm_safe(self):
		txt = build_new_lot_text({"lot_no": "X"})
		self.assertIn("X", txt)


class TestKeyboard(unittest.TestCase):
	def test_url_and_go_nogo(self):
		kb = build_keyboard(_NORM, "DEAL-0001")
		flat = [b for row in kb["inline_keyboard"] for b in row]
		urls = [b for b in flat if "url" in b]
		cbs = [b["callback_data"] for b in flat if "callback_data" in b]
		self.assertTrue(any("etender.uzex.uz/lot/500606" in b["url"] for b in urls))
		self.assertIn("uzex_go:DEAL-0001", cbs)
		self.assertIn("uzex_nogo:DEAL-0001", cbs)

	def test_no_buttons_when_empty(self):
		self.assertIsNone(build_keyboard({}, None))


class TestParseCallback(unittest.TestCase):
	def test_go(self):
		self.assertEqual(parse_callback("uzex_go:DEAL-0001"), ("go", "DEAL-0001"))

	def test_nogo(self):
		self.assertEqual(parse_callback("uzex_nogo:DEAL-0002"), ("no-go", "DEAL-0002"))

	def test_deal_name_with_colon_preserved(self):
		self.assertEqual(parse_callback("uzex_go:CRM-DEAL:2026:1"), ("go", "CRM-DEAL:2026:1"))

	def test_garbage(self):
		self.assertEqual(parse_callback(None), (None, None))
		self.assertEqual(parse_callback("nope"), (None, None))
		self.assertEqual(parse_callback("other:x"), (None, None))


class TestVerifySecret(unittest.TestCase):
	"""WP-308 fail-closed webhook secret — the three acceptance scenarios."""

	def test_a_unset_secret_rejected(self):
		# (a) secret unset -> reject (would 403 in the handler)
		self.assertFalse(verify_secret(None, "anything"))
		self.assertFalse(verify_secret("", "anything"))

	def test_b_wrong_header_rejected(self):
		# (b) wrong header -> reject
		self.assertFalse(verify_secret("s3cr3t", "wrong"))
		self.assertFalse(verify_secret("s3cr3t", None))

	def test_c_correct_header_accepted(self):
		# (c) correct header -> accept (handler proceeds to apply)
		self.assertTrue(verify_secret("s3cr3t", "s3cr3t"))


if __name__ == "__main__":
	unittest.main()
