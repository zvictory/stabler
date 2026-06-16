"""Tests for the Timepay client credential/refresh contract.

These stay network-free. Live sync tests should inject a fake HTTP transport
instead of calling Timepay directly.
"""

from __future__ import annotations

import json
import unittest

from stabler.integrations.timepay.client import (
	TimepayApiError,
	TimepayClient,
	decode_jwt_exp,
)


ACCESS_FRESH = (
	"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
	"eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoyMDAwMDAwMDAwfQ."
	"sig"
)
ACCESS_EXPIRED = (
	"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
	"eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxMDB9."
	"sig"
)
REFRESH_OLD = (
	"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
	"eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MjAwMDAwMDAwMH0."
	"sig"
)
REFRESH_NEW = (
	"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
	"eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MjAwMDAwMTAwMH0."
	"sig"
)
ACCESS_NEW = (
	"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
	"eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoyMDAwMDAwNTAwfQ."
	"sig"
)


class MemoryTokenStore:
	def __init__(self, access=ACCESS_FRESH, refresh=REFRESH_OLD):
		self.tokens = {
			"access": access,
			"refresh": refresh,
			"access_expires_at": decode_jwt_exp(access),
			"refresh_expires_at": decode_jwt_exp(refresh),
		}
		self.saved = []

	def get_tokens(self):
		return self.tokens

	def save_refreshed(self, next_tokens):
		self.saved.append(next_tokens)
		self.tokens.update(next_tokens)


class FakeResponse:
	def __init__(self, status_code, payload):
		self.status_code = status_code
		self._payload = payload
		self.text = json.dumps(payload)

	def json(self):
		return self._payload


class FakeTransport:
	def __init__(self, responses):
		self.responses = list(responses)
		self.calls = []

	def request(self, method, url, **kwargs):
		self.calls.append({"method": method, "url": url, **kwargs})
		return self.responses.pop(0)


class DecodeJwtExpTest(unittest.TestCase):
	def test_decodes_exp_claim(self):
		self.assertEqual(decode_jwt_exp(ACCESS_FRESH), 2000000000)

	def test_rejects_invalid_token(self):
		with self.assertRaises(TimepayApiError):
			decode_jwt_exp("not-a-jwt")


class TimepayClientRefreshTest(unittest.TestCase):
	def test_refresh_persists_rotated_refresh_token(self):
		store = MemoryTokenStore(access=ACCESS_EXPIRED)
		transport = FakeTransport([
			FakeResponse(200, {"access": ACCESS_NEW, "refresh": REFRESH_NEW}),
			FakeResponse(200, {"count": 0, "next": None, "previous": None, "results": []}),
		])
		client = TimepayClient(store, transport=transport, now_epoch=1000)

		out = client.list_employees(limit=1)

		self.assertEqual(out["count"], 0)
		self.assertEqual(store.tokens["access"], ACCESS_NEW)
		self.assertEqual(store.tokens["refresh"], REFRESH_NEW)
		self.assertEqual(transport.calls[0]["url"], "https://api.app.time-pay.uz/api/v1/user/token/refresh/")
		self.assertEqual(transport.calls[0]["json"], {"refresh": REFRESH_OLD})
		self.assertEqual(transport.calls[1]["headers"]["Authorization"], f"Bearer {ACCESS_NEW}")

	def test_unauthorized_call_refreshes_once_and_retries(self):
		store = MemoryTokenStore(access=ACCESS_FRESH)
		transport = FakeTransport([
			FakeResponse(401, {"detail": "expired"}),
			FakeResponse(200, {"access": ACCESS_NEW, "refresh": REFRESH_NEW}),
			FakeResponse(200, {"count": 0, "next": None, "previous": None, "results": []}),
		])
		client = TimepayClient(store, transport=transport, now_epoch=1000)

		client.list_employees(limit=1)

		self.assertEqual(len(transport.calls), 3)
		self.assertEqual(transport.calls[1]["url"], "https://api.app.time-pay.uz/api/v1/user/token/refresh/")
		self.assertEqual(transport.calls[2]["headers"]["Authorization"], f"Bearer {ACCESS_NEW}")


if __name__ == "__main__":
	unittest.main()
