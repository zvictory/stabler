import frappe


def run():
	user = "logistics.mikas@erpstable.com"
	frappe.set_user(user)
	frappe.clear_cache()
	print("Roles for user:", frappe.get_roles(user))
	meta = frappe.get_meta("Purchase Order")
	role_perms = frappe.permissions.get_role_permissions(meta, user=user)
	print("Role permissions for Purchase Order:", role_perms)
	doc = frappe.get_doc("Purchase Order", "PUR-ORD-2026-00005")
	doc_perms = frappe.permissions.get_doc_permissions(doc, user=user)
	print("Doc permissions for PUR-ORD-2026-00005:", doc_perms)
