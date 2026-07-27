import frappe
from frappe.utils import add_days, getdate, today

from stabler.api._imports_rules import get_7day_payment_deadline


def check_upcoming_deadlines():
	"""Daily scan for Commercial Invoices whose payment deadline (ETA - 7 days) is approaching.

	Checks only active CIs for companies with 'imports' enabled.
	"""
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	companies = frappe.get_all("Company", pluck="name")
	import_companies = [c for c in companies if module_map_for(c).get("imports")]
	if not import_companies:
		return

	today_str = today()
	# Check for deadlines that are today or already passed
	invoices = frappe.get_all(
		"Commercial Invoice",
		filters={
			"company": ["in", import_companies],
			"status": ["not in", ["Cancelled", "DELIVERED_TO_UZBEKISTAN"]],
			"eta_transit_port": ["is", "set"]
		},
		fields=["name", "eta_transit_port", "company", "supplier", "agreed_total"]
	)

	for ci in invoices:
		deadline = get_7day_payment_deadline(ci.eta_transit_port)
		if deadline and deadline <= today_str:
			msg = (
				f"⚠️ <b>İthalat Ödeme Uyarısı</b>\n"
				f"Ticari Fatura: <code>{ci.name}</code>\n"
				f"Tedarikçi: {ci.supplier}\n"
				f"Tutar: {ci.agreed_total:,.2f} USD\n"
				f"İran ETA: {ci.eta_transit_port}\n"
				f"Ödeme Son Günü: <b>{deadline}</b> ({'BUGÜN/GEÇMİŞ' if deadline <= today_str else 'Yaklaşıyor'})"
			)

			# Create a system notification log
			try:
				notification = frappe.new_doc("Notification Log")
				notification.for_user = "Administrator"
				notification.subject = f"Upcoming Payment Deadline for CI {ci.name}"
				notification.email_content = msg
				notification.insert(ignore_permissions=True)
			except Exception:
				pass

			# Telegram notification (optional, if configured)
			token = getattr(frappe.conf, "uzex_telegram_token", None)
			chat_id = getattr(frappe.conf, "uzex_telegram_chat_id", None)
			if token and chat_id:
				import json
				from urllib.request import Request, urlopen
				payload = {
					"chat_id": chat_id,
					"text": msg,
					"parse_mode": "HTML"
				}
				body = json.dumps(payload).encode("utf-8")
				req = Request(
					f"https://api.telegram.org/bot{token}/sendMessage",
					data=body,
					headers={"Content-Type": "application/json"},
					method="POST"
				)
				try:
					with urlopen(req, timeout=10):
						pass
				except Exception:
					pass
