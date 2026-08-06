"""Daily alarm on the stock-valuation repost queue.

Both COGS poisonings stayed live for weeks (one for five months) not because
they were undetectable but because nobody watched the outcome: reposts piled
up, failed, or sat queued and no one was told. This turns that silence into a
daily message.

Reads `stabler.api.repost_monitor.repost_status()` — the queue-health query
already exists, this does not re-implement it — and announces through the same
Notification Log + optional Telegram path `tasks/eta_payment_alert.py` uses.
Runs only when at least one company on the site opted into the valuation
guards, so tenants that did not stay silent.
"""

import frappe
from frappe.utils import date_diff, getdate, today


def check_repost_queue():
	"""Daily: alarm when the repost queue is backed up, failing, or stale."""
	if not _any_company_guarded():
		return

	from stabler.api.repost_monitor import repost_status

	status = repost_status()
	queued = int(status.get("queued") or 0)
	failed = len(status.get("errors") or [])
	oldest_queued = status.get("oldest_queued") or ""

	queue_limit = int(_setting("repost_queue_alert_threshold", 100))
	age_limit = int(_setting("repost_queue_alert_age_days", 7))

	oldest_age = 0
	if oldest_queued:
		try:
			oldest_age = date_diff(today(), getdate(oldest_queued))
		except Exception:
			oldest_age = 0

	reasons = []
	if queued > queue_limit:
		reasons.append(f"Kuyrukta bekleyen: <b>{queued}</b> (eşik {queue_limit})")
	if failed > 0:
		reasons.append(f"Başarısız repost: <b>{failed}</b>")
	if oldest_age > age_limit:
		reasons.append(f"En eski bekleyen kayıt: <b>{oldest_age} gün</b> (eşik {age_limit})")
	if not reasons:
		return

	stuck = status.get("in_progress") or []
	msg = "⚠️ <b>Stok Değerleme Repost Kuyruğu Uyarısı</b>\n" + "\n".join(reasons)
	if stuck:
		msg += f"\nİşlemde takılı: {len(stuck)}"
	msg += "\nDeğerleme düzeltmeleri işlenmiyor olabilir — COGS bozulmasına açık durum."

	_announce("Repost queue unhealthy", msg)


def _setting(fieldname: str, default: int) -> int:
	try:
		val = frappe.db.get_single_value("Stabler Settings", fieldname)
	except Exception:
		return default
	val = int(val or 0)
	return val if val > 0 else default


def _any_company_guarded() -> bool:
	"""True when any company on this site enabled the valuation guards."""
	try:
		return bool(
			frappe.db.exists(
				"Stabler Company Modules",
				{"parent": "Stabler Settings", "parenttype": "Stabler Settings", "enable_valuation_guard": 1},
			)
		)
	except Exception:
		return False


def _announce(subject: str, msg: str) -> None:
	"""Same notification path as tasks/eta_payment_alert.py — no new plumbing."""
	try:
		notification = frappe.new_doc("Notification Log")
		notification.for_user = "Administrator"
		notification.subject = subject
		notification.email_content = msg
		notification.insert(ignore_permissions=True)
	except Exception:
		pass

	token = getattr(frappe.conf, "uzex_telegram_token", None)
	chat_id = getattr(frappe.conf, "uzex_telegram_chat_id", None)
	if token and chat_id:
		import json
		from urllib.request import Request, urlopen

		payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}
		body = json.dumps(payload).encode("utf-8")
		req = Request(
			f"https://api.telegram.org/bot{token}/sendMessage",
			data=body,
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		try:
			with urlopen(req, timeout=10):
				pass
		except Exception:
			pass
