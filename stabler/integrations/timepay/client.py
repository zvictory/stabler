from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import urlencode

import requests

API_BASE = "https://api.app.time-pay.uz"
ORIGIN = "https://app.time-pay.uz"
REFRESH_THRESHOLD_SECONDS = 5 * 60


class TimepayApiError(Exception):
	def __init__(self, status: int, body: str | None, message: str):
		super().__init__(message)
		self.status = status
		self.body = body


def decode_jwt_exp(token: str) -> int:
	try:
		_payload = token.split(".")[1]
		_padding = "=" * (-len(_payload) % 4)
		decoded = base64.urlsafe_b64decode((_payload + _padding).encode("ascii"))
		body = json.loads(decoded.decode("utf-8"))
		exp = body["exp"]
	except Exception as exc:
		raise TimepayApiError(0, None, "Invalid Timepay token") from exc
	if not isinstance(exp, int):
		raise TimepayApiError(0, None, "Invalid Timepay token expiry")
	return exp


def _query(params: dict[str, Any]) -> str:
	clean = {key: value for key, value in params.items() if value is not None}
	encoded = urlencode(clean)
	return f"?{encoded}" if encoded else ""


class TimepayClient:
	def __init__(
		self,
		store,
		*,
		transport=None,
		api_base: str = API_BASE,
		origin: str = ORIGIN,
		now_epoch: int | None = None,
	):
		self.store = store
		self.transport = transport or requests
		self.api_base = api_base.rstrip("/")
		self.origin = origin
		self.now_epoch = now_epoch

	def _now(self) -> int:
		return self.now_epoch if self.now_epoch is not None else int(time.time())

	def _headers(self, access: str, *, json_body: bool = False) -> dict[str, str]:
		headers = {
			"Authorization": f"Bearer {access}",
			"Accept": "application/json",
			"Accept-Language": "uz",
			"Origin": self.origin,
		}
		if json_body:
			headers["Content-Type"] = "application/json"
		return headers

	def _ensure_fresh_access(self, tokens: dict[str, Any]) -> dict[str, Any]:
		if int(tokens["access_expires_at"]) - self._now() >= REFRESH_THRESHOLD_SECONDS:
			return tokens
		self.refresh()
		fresh = self.store.get_tokens()
		if not fresh:
			raise TimepayApiError(0, None, "Tokens vanished after refresh")
		return fresh

	def _with_auth(self, call):
		initial = self.store.get_tokens()
		if not initial:
			raise TimepayApiError(0, None, "Timepay credentials not connected")
		tokens = self._ensure_fresh_access(initial)
		response = call(tokens["access"])
		if response.status_code == 401:
			self.refresh()
			fresh = self.store.get_tokens()
			if not fresh:
				raise TimepayApiError(401, None, "Refresh succeeded but tokens missing")
			response = call(fresh["access"])
		if response.status_code < 200 or response.status_code >= 300:
			raise TimepayApiError(response.status_code, getattr(response, "text", ""), f"Timepay {response.status_code}")
		body = response.json()
		if not isinstance(body, dict):
			raise TimepayApiError(response.status_code, None, "Invalid Timepay response")
		return body

	def refresh(self) -> None:
		tokens = self.store.get_tokens()
		if not tokens:
			raise TimepayApiError(0, None, "No Timepay tokens to refresh")
		response = self.transport.request(
			"POST",
			f"{self.api_base}/api/v1/user/token/refresh/",
			headers={
				"Content-Type": "application/json",
				"Accept": "application/json",
				"Origin": self.origin,
			},
			json={"refresh": tokens["refresh"]},
		)
		if response.status_code < 200 or response.status_code >= 300:
			raise TimepayApiError(response.status_code, getattr(response, "text", ""), "Refresh failed")
		body = response.json()
		access = body.get("access") if isinstance(body, dict) else None
		refresh = body.get("refresh") if isinstance(body, dict) else None
		if not isinstance(access, str) or not access:
			raise TimepayApiError(response.status_code, None, "Refresh response missing access token")
		next_tokens = {
			"access": access,
			"access_expires_at": decode_jwt_exp(access),
		}
		if isinstance(refresh, str) and refresh:
			next_tokens["refresh"] = refresh
			next_tokens["refresh_expires_at"] = decode_jwt_exp(refresh)
		self.store.save_refreshed(next_tokens)

	def list_employees(self, *, date: str | None = None, role: str | None = None, offset: int | None = None, limit: int | None = None) -> dict[str, Any]:
		qs = _query({"date": date, "role": role, "offset": offset, "limit": limit})
		return self._with_auth(
			lambda access: self.transport.request(
				"GET",
				f"{self.api_base}/api/v1/user/employees/{qs}",
				headers=self._headers(access),
			)
		)

	def daily_stats(
		self,
		*,
		date: str,
		offset: int | None = None,
		limit: int | None = None,
		branch_ids: list[int] | None = None,
		department_ids: list[int] | None = None,
		schedule_ids: list[int] | None = None,
		position_ids: list[int] | None = None,
		employee_ids: list[int] | None = None,
	) -> dict[str, Any]:
		qs = _query({"offset": offset, "limit": limit})
		payload = {
			"date": date,
			"branch_ids": branch_ids or [],
			"department_ids": department_ids or [],
			"schedule_ids": schedule_ids or [],
			"position_ids": position_ids or [],
			"employee_ids": employee_ids or [],
		}
		return self._with_auth(
			lambda access: self.transport.request(
				"POST",
				f"{self.api_base}/api/v1/user/employee-daily-stats/{qs}",
				headers=self._headers(access, json_body=True),
				json=payload,
			)
		)
