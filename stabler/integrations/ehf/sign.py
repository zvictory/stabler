"""EIMZO signing for EHF payloads.

EIMZO is the Uzbek national e-signature stack; deployments run a small
local signing service (often the official EIMZO browser plugin or a
docker container that wraps it) that accepts JSON and returns a detached
signature blob.

For local development we short-circuit when `frappe.conf.ehf_stub_signature`
is truthy and return the literal string "STUB-SIG"; the SoliqOnline
endpoint (also stubbed for dev) accepts it.

Production:
  - frappe.conf.eimzo_endpoint: full URL of the local EIMZO service.
  - Optional frappe.conf.eimzo_timeout: seconds (default 10).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frappe


def sign(payload: dict[str, Any]) -> str:
	"""Return a detached signature string for the JSON-encoded payload.

	Raises a Frappe-friendly exception (caller can catch and write to
	EHFSubmission.error_message) on any signing failure.
	"""
	conf = frappe.conf
	if int(getattr(conf, "ehf_stub_signature", 0) or 0):
		return "STUB-SIG"

	endpoint = getattr(conf, "eimzo_endpoint", None)
	if not endpoint:
		raise frappe.ValidationError(
			"EIMZO endpoint not configured. Set `eimzo_endpoint` in site_config.json"
			" or enable `ehf_stub_signature` for development."
		)

	timeout = int(getattr(conf, "eimzo_timeout", 10) or 10)
	body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
	req = Request(
		endpoint,
		data=body,
		headers={"Content-Type": "application/json", "Accept": "application/json"},
		method="POST",
	)
	try:
		with urlopen(req, timeout=timeout) as resp:
			data = json.loads(resp.read().decode("utf-8"))
	except HTTPError as e:
		raise frappe.ValidationError(f"EIMZO HTTP {e.code}: {e.reason}") from e
	except URLError as e:
		raise frappe.ValidationError(f"EIMZO unreachable: {e.reason}") from e

	signature = data.get("signature") if isinstance(data, dict) else None
	if not signature:
		raise frappe.ValidationError(f"EIMZO returned no signature: {data!r}")
	return signature
