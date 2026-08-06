import frappe


def run():
	user = "logistics.mikas@erpstable.com"
	frappe.set_user(user)
	frappe.session.user = user
	frappe.session.data.user = user
	frappe.session.data.user_type = "System User"
	frappe.session.roles = frappe.get_roles(user)

	from stabler.api.tender import logist_board

	try:
		res = logist_board("Mikas")
		print("SUCCESS! Rows:", len(res.get("rows", [])))
	except Exception:
		import traceback

		print("ERROR IN TEST:")
		traceback.print_exc()
