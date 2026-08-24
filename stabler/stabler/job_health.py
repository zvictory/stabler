"""Is this bench processing background jobs? Deliberately Frappe-free.

The web layer and the queue fail independently: on 2026-07-28 gunicorn served
all eight tenants normally for 43.7 h while not one background job ran. The SPA
could not report it because nothing in the product looked at a layer the SPA
does not run in. This module holds the rule that turns the two facts a web
process CAN observe -- did the queue's redis answer me, and how many rq workers
are registered in it -- into the verdict the banner shows.

The rule refuses to guess. "I could not reach redis" is reported as down, never
as healthy: the outage this exists to catch opened with redis refusing
connections, so an unreachable queue read as OK would blind the banner to the
exact case it was written for.
"""

from __future__ import annotations


def verdict(worker_count, error=None) -> dict:
	"""The banner's reading of the queue, from what the web process could observe.

	`error` is whatever went wrong while talking to the queue's redis, and it
	outranks `worker_count` — a count obtained without reaching redis cannot
	have come from redis, and trusting it is how a caller's default argument
	turns into a false all-clear.

	Never raises. The caller is a whitelisted endpoint polled by every open tab;
	an exception here would put a 500 storm on top of an already degraded bench.
	"""
	if error:
		return {"ok": False, "reason": "queue-unreachable", "workers": 0}
	try:
		workers = int(worker_count or 0)
	except (TypeError, ValueError):
		workers = 0
	if workers < 1:
		# Redis answered and nobody is listening. This is the 43.7 h state.
		return {"ok": False, "reason": "no-workers", "workers": 0}
	return {"ok": True, "reason": "", "workers": workers}
