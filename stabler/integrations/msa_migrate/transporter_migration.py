"""Ingest and sync Transporter, Land Freight, Container/Truck costs and Cash/Bank payments from master reference."""

import frappe
from frappe.utils import flt

TRANSPORTER_ROWS = [
	{
		"ci_number": "IFF/EXP/26/0685",
		"transporter": "FAIR EXPORTS LOGISTICS",
		"container": "TCNU8492019",
		"vehicle_number": "01 789 AAA",
		"transport_cost": 2800.0,
		"currency": "USD",
		"paid_cash": 1000.0,
		"paid_bank": 1800.0,
		"notes": "Delivered to Warehouse 1",
	},
	{
		"ci_number": "IFF/EXP/26/0616",
		"transporter": "AL-SUPER TRANS",
		"container": "MEDU9182734",
		"vehicle_number": "01 456 BBB",
		"transport_cost": 2750.0,
		"currency": "USD",
		"paid_cash": 750.0,
		"paid_bank": 2000.0,
		"notes": "Transit cleared",
	},
	{
		"ci_number": "IFF/EXP/26/0595",
		"transporter": "MIRHA FREIGHT PVT",
		"container": "MSCU1092837",
		"vehicle_number": "01 123 CCC",
		"transport_cost": 2900.0,
		"currency": "USD",
		"paid_cash": 1400.0,
		"paid_bank": 1500.0,
		"notes": "Direct border transport",
	},
	{
		"ci_number": "HMA/PI/2229/2025-26",
		"transporter": "HMA LOGISTICS INDIA",
		"container": "CMAU7364521",
		"vehicle_number": "01 321 DDD",
		"transport_cost": 3100.0,
		"currency": "USD",
		"paid_cash": 1500.0,
		"paid_bank": 1600.0,
		"notes": "Customs cleared",
	},
	{
		"ci_number": "HMA/PI/1843/2025-26",
		"transporter": "HMA LOGISTICS INDIA",
		"container": "HLCU8273645",
		"vehicle_number": "01 654 EEE",
		"transport_cost": 3050.0,
		"currency": "USD",
		"paid_cash": 1050.0,
		"paid_bank": 2000.0,
		"notes": "Delivered",
	},
]


def run(dry_run=1):
	dry_run = int(dry_run)

	created = 0
	updated = 0

	for r in TRANSPORTER_ROWS:
		cin = r["ci_number"]
		transporter = r["transporter"]
		container = r["container"]
		vehicle = r["vehicle_number"]
		cost = flt(r["transport_cost"])
		p_cash = flt(r["paid_cash"])
		p_bank = flt(r["paid_bank"])
		notes = r.get("notes") or ""

		# Resolve CI Name
		ci_doc_name = None
		if frappe.db.exists("Commercial Invoice", cin):
			ci_doc_name = cin
		else:
			found_ci = frappe.get_all("Commercial Invoice", filters={"ci_number": cin}, fields=["name"])
			if found_ci:
				ci_doc_name = found_ci[0]["name"]

		# Ensure Transporter Supplier exists with default_currency = USD
		if not dry_run:
			if not frappe.db.exists("Supplier", transporter):
				supp = frappe.get_doc(
					{
						"doctype": "Supplier",
						"supplier_name": transporter,
						"supplier_group": "Services",
						"supplier_type": "Company",
						"default_currency": "USD",
					}
				)
				supp.insert(ignore_permissions=True)
			else:
				frappe.db.set_value("Supplier", transporter, "default_currency", "USD", update_modified=False)

		# Ensure Container exists
		container_doc_name = None
		if container:
			found_cont = frappe.get_all(
				"Import Container", filters={"container_number": container}, fields=["name"]
			)
			if found_cont:
				container_doc_name = found_cont[0]["name"]
			elif not dry_run:
				c_doc = frappe.get_doc(
					{
						"doctype": "Import Container",
						"container_number": container,
						"commercial_invoice": ci_doc_name,
						"status": "IN_TRANSIT",
					}
				)
				c_doc.insert(ignore_permissions=True)
				container_doc_name = c_doc.name

		# Check existing Freight Booking by vehicle or container
		existing = frappe.get_all(
			"Freight Booking",
			filters={"vehicle_number": vehicle} if vehicle else {"container": container_doc_name},
			fields=["name"],
		)

		target_container = container_doc_name if container_doc_name else None
		target_ci = None if target_container else ci_doc_name

		if existing:
			fb_name = existing[0]["name"]
			updated += 1
			if not dry_run:
				frappe.db.set_value(
					"Freight Booking",
					fb_name,
					{
						"transporter": transporter,
						"container": target_container,
						"commercial_invoice": target_ci,
						"vehicle_number": vehicle,
						"amount": cost,
						"cash_payment": p_cash,
						"bank_payment": p_bank,
						"route": notes,
					},
					update_modified=True,
				)
		else:
			created += 1
			if not dry_run:
				fb = frappe.get_doc(
					{
						"doctype": "Freight Booking",
						"transporter": transporter,
						"container": target_container,
						"commercial_invoice": target_ci,
						"vehicle_number": vehicle,
						"amount": cost,
						"cash_payment": p_cash,
						"bank_payment": p_bank,
						"currency": "USD",
						"status": "In Transit",
						"route": notes,
					}
				)
				fb.insert(ignore_permissions=True)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	print("\n========================================================")
	print(f"  TRANSPORTER & LAND FREIGHT MIGRATION ({mode})")
	print("========================================================")
	print(f"Total rows processed: {len(TRANSPORTER_ROWS)}")
	print(f"Created: {created} | Updated: {updated}\n")

	return {"created": created, "updated": updated, "total": len(TRANSPORTER_ROWS)}
