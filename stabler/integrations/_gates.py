"""Whether an outbound integration may queue work at all. No frappe import.

Both hooks used to enqueue on one condition — `docstatus == 1` — and left the
"am I configured" question to the job itself, one layer down and one worker
later. Measured on prod 2026-08-28: neither integration is configured on any of
the eight tenants (`onec_outbox`, `onec_rest_endpoint`, `eimzo_endpoint` and
`ehf_stub_signature` all unset, 8 / 8), and anjan alone had accumulated 8576
`EHF Submission` rows since 2026-05-30, every one of them status Error with the
same message, none ever successful, 481 of them in the last week.

Nothing here is a new switch. These are the questions `_push_file`, `_push_rest`
and `sign()` already ask; asking them before the enqueue rather than after it
means an unconfigured integration costs nothing, and a configured one starts
working again with no further change.
"""

from __future__ import annotations


def _present(value) -> bool:
	"""A config value that is actually set to something.

	`site_config.json` is hand-edited, so a half-removed setting shows up as `""`
	rather than as an absent key — and an empty string passes any check written
	as `is not None`.
	"""
	return bool(str(value or "").strip())


def one_c_can_push(mode, outbox, rest_endpoint) -> bool:
	"""Whether a 1C push has somewhere to go.

	`push()` branches on the mode and each branch reads a different key, so the
	gate has to branch the same way. Checking only the outbox would keep queueing
	work on a REST site; checking only the endpoint would switch off a working
	file drop.

	An unrecognised or missing mode is read as "file", matching `push()`'s own
	`or "file"` fallback — a site with no Stabler Settings row still has a
	working file drop, and the gate must not be the thing that stops it.
	"""
	if str(mode or "").strip() == "rest":
		return _present(rest_endpoint)
	return _present(outbox)


def ehf_can_submit(eimzo_endpoint, stub_signature) -> bool:
	"""Whether an EHF submission has anything that can sign it.

	Two ways to succeed, so both are asked: a real EIMZO endpoint, or the
	development stub. The stub is read as a number the way `sign()` reads it
	(`int(... or 0)`), because `ehf_stub_signature: 0` is how somebody switches
	the stub off and 0 is exactly the value a presence check would call
	"configured". An unparseable value is not a licence to queue.
	"""
	if _present(eimzo_endpoint):
		return True
	try:
		return int(stub_signature or 0) != 0
	except (TypeError, ValueError):
		return False
