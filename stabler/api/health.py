"""Whether this bench is processing background jobs, answered by the web layer.

The web layer and the queue fail independently, and on 2026-07-28 they did: for
43.7 h gunicorn served all eight tenants while the workers were dead. Every
existing alarm in this app runs as a scheduled job, so every one of them was
dead too. This endpoint is deliberately the exception — it answers from inside
the request that the SPA is already making, and needs nothing enqueued.
"""

from __future__ import annotations

import frappe

from stabler.stabler.job_health import verdict

# rq registers every live worker in this set and lets the entry expire when the
# worker stops heartbeating, so its cardinality is "workers listening right now".
_RQ_WORKERS_KEY = "rq:workers"


@frappe.whitelist()
def background_jobs() -> dict:
	"""Queue health for the shell banner. Any logged-in user, not just admins.

	Not gated behind `_require_admin`: an outage that pauses queued work affects
	whoever is doing the work, and telling only the administrator reproduces the
	silence this was written to end.
	"""
	try:
		from frappe.utils.background_jobs import get_redis_conn

		workers = get_redis_conn().scard(_RQ_WORKERS_KEY)
	except Exception as exc:
		# Deliberately broad: every failure here — redis refusing connections,
		# a missing config key, an auth change — means the same thing to the
		# caller, and a traceback would turn a degraded bench into a 500 storm
		# across every open tab.
		return verdict(0, error=str(exc)[:200])
	return verdict(workers)
