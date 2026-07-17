"""Unit tests for stabler.integrations.kassa.miniapp (WP-K7, Telegram Mini App).

Pure/frappe-free — mirrors the style of stabler.tests.test_kassa_flow. Pins the
EXACT Telegram WebApp initData HMAC algorithm (verify_init_data) so a refactor
can't silently weaken the money-adjacent auth boundary.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_miniapp -v
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from stabler.integrations.kassa.miniapp import _row_op_label, verify_init_data

_BOT_TOKEN = "123456:FAKE-TEST-TOKEN"


def _sign(fields: dict, bot_token: str) -> str:
	"""Independent re-implementation of Telegram's HMAC recipe — deliberately
	NOT calling verify_init_data — this is what pins the algorithm."""
	data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
	secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
	return hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_init_data(fields: dict, bot_token: str) -> str:
	signed_hash = _sign(fields, bot_token)
	return urlencode({**fields, "hash": signed_hash})


def _valid_fields(auth_date: int | None = None) -> dict:
	return {
		"query_id": "AAEEfoobar",
		"user": json.dumps({"id": 555111222, "first_name": "Aziz", "username": "aziz_k"}),
		"auth_date": str(auth_date if auth_date is not None else int(time.time())),
	}


class TestVerifyInitData(unittest.TestCase):
	def test_valid_signature_returns_user(self):
		fields = _valid_fields()
		init_data = _build_init_data(fields, _BOT_TOKEN)
		result = verify_init_data(init_data, _BOT_TOKEN)
		self.assertIsNotNone(result)
		self.assertEqual(result["id"], 555111222)
		self.assertEqual(result["username"], "aziz_k")
		self.assertEqual(result["auth_date"], int(fields["auth_date"]))

	def test_tampered_hash_rejected(self):
		fields = _valid_fields()
		init_data = _build_init_data(fields, _BOT_TOKEN)
		bad = init_data[:-1] + ("0" if init_data[-1] != "0" else "1")
		self.assertIsNone(verify_init_data(bad, _BOT_TOKEN))

	def test_tampered_field_after_signing_rejected(self):
		fields = _valid_fields()
		signed_hash = _sign(fields, _BOT_TOKEN)
		tampered = {**fields, "auth_date": str(int(fields["auth_date"]) + 1)}
		init_data = urlencode({**tampered, "hash": signed_hash})
		self.assertIsNone(verify_init_data(init_data, _BOT_TOKEN))

	def test_wrong_bot_token_rejected(self):
		fields = _valid_fields()
		init_data = _build_init_data(fields, _BOT_TOKEN)
		self.assertIsNone(verify_init_data(init_data, "999999:OTHER-TOKEN"))

	def test_expired_auth_date_rejected(self):
		old = int(time.time()) - 90000  # older than the 86400s default max age
		fields = _valid_fields(auth_date=old)
		init_data = _build_init_data(fields, _BOT_TOKEN)
		self.assertIsNone(verify_init_data(init_data, _BOT_TOKEN))

	def test_within_custom_max_age_accepted(self):
		old = int(time.time()) - 100
		fields = _valid_fields(auth_date=old)
		init_data = _build_init_data(fields, _BOT_TOKEN)
		self.assertIsNotNone(verify_init_data(init_data, _BOT_TOKEN, max_age_seconds=200))

	def test_missing_hash_rejected(self):
		fields = _valid_fields()
		init_data = urlencode(fields)  # no hash param at all
		self.assertIsNone(verify_init_data(init_data, _BOT_TOKEN))

	def test_missing_user_rejected(self):
		fields = {"auth_date": str(int(time.time()))}
		init_data = _build_init_data(fields, _BOT_TOKEN)
		self.assertIsNone(verify_init_data(init_data, _BOT_TOKEN))

	def test_empty_token_rejected(self):
		fields = _valid_fields()
		init_data = _build_init_data(fields, _BOT_TOKEN)
		self.assertIsNone(verify_init_data(init_data, ""))
		self.assertIsNone(verify_init_data(init_data, None))

	def test_empty_init_data_rejected(self):
		self.assertIsNone(verify_init_data("", _BOT_TOKEN))
		self.assertIsNone(verify_init_data(None, _BOT_TOKEN))

	def test_non_dict_user_rejected(self):
		fields = {"user": json.dumps([1, 2, 3]), "auth_date": str(int(time.time()))}
		init_data = _build_init_data(fields, _BOT_TOKEN)
		self.assertIsNone(verify_init_data(init_data, _BOT_TOKEN))


class TestRowOpLabel(unittest.TestCase):
	def test_strips_transfer_arrow_prefix(self):
		result = _row_op_label("Journal Entry", "Kassa Som → PK | ijara")
		self.assertTrue(result.startswith("Journal Entry"))
		self.assertTrue(result.endswith("— ijara"))

	def test_strips_konvertatsiya_prefix(self):
		result = _row_op_label("Journal Entry", "Konvertatsiya USD→UZS @12950 | bozor")
		self.assertTrue(result.startswith("Journal Entry"))
		self.assertTrue(result.endswith("— bozor"))

	def test_no_remark_returns_bare_voucher_type(self):
		self.assertEqual(_row_op_label("Journal Entry", None), "Journal Entry")
		self.assertEqual(_row_op_label("Journal Entry", ""), "Journal Entry")

	def test_no_remarks_placeholder_returns_bare_voucher_type(self):
		self.assertEqual(_row_op_label("Journal Entry", "No Remarks"), "Journal Entry")

	def test_remark_without_separator_used_as_is(self):
		result = _row_op_label("Payment Entry", "market uchun")
		self.assertEqual(result, "Payment Entry — market uchun")


if __name__ == "__main__":
	unittest.main()
