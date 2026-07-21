"""
MSAERP -> Stabler Import Containers, Trucks & CI Line Items Data Migration Script
Reads directly from /Users/zafar/Downloads/msaerp/db_production.sqlite3 and inserts into Frappe MariaDB.
"""

import os
import sqlite3
import frappe
from frappe.utils import flt, cint, getdate

SQLITE_DB_PATH = "/Users/zafar/Downloads/msaerp/db_production.sqlite3"
# Fallback path if running directly on production server
ALT_SQLITE_PATH = "/home/frappe/db_production.sqlite3"

def run_migration(company=None):
    sqlite_path = SQLITE_DB_PATH if os.path.exists(SQLITE_DB_PATH) else ALT_SQLITE_PATH
    if not os.path.exists(sqlite_path):
        frappe.throw(f"SQLite database file not found at {SQLITE_DB_PATH} or {ALT_SQLITE_PATH}")

    if not company:
        companies = frappe.get_all("Company", pluck="name")
        company = companies[0] if companies else "MSA"
    frappe.set_user("Administrator")
    print(f"=== STARTING MSAERP IMPORT DATA MIGRATION FOR COMPANY: {company} ===")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. Maps & Lookups
    vendors = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM proforma_app_vendor").fetchall()}
    ci_map = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM proforma_app_commercialinvoice").fetchall()}
    product_map = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM proforma_app_product").fetchall()}

    def ensure_item(prod_dict):
        if not prod_dict:
            return "ITEM-GENERIC"
        item_code = prod_dict.get("code") or prod_dict.get("name") or "ITEM-GENERIC"
        if not frappe.db.exists("Item", item_code):
            doc = frappe.new_doc("Item")
            doc.item_code = item_code
            doc.item_name = prod_dict.get("name") or item_code
            doc.stock_uom = "Kg"
            doc.item_group = "All Item Groups"
            doc.insert(ignore_permissions=True)
            print(f"Created Item: {item_code}")
        return item_code

    # --------------------------------------------------------------------------
    # 2. Backfill CI Line Items (category, boxes, box_weight_kg, docs_price)
    # --------------------------------------------------------------------------
    print("\n--- Phase 1: Backfilling Commercial Invoice Line Items ---")
    ci_items_sqlite = [dict(r) for r in cur.execute("SELECT * FROM proforma_app_cilineitem").fetchall()]
    ci_updated = 0

    # Group SQLite items by commercial_invoice_id
    items_by_ci = {}
    for row in ci_items_sqlite:
        ci_id = row["commercial_invoice_id"]
        items_by_ci.setdefault(ci_id, []).append(row)

    for ci_id, sql_items in items_by_ci.items():
        ci_row = ci_map.get(ci_id)
        if not ci_row:
            continue
        ci_number = ci_row["ci_number"]
        ci_name = frappe.db.get_value("Commercial Invoice", {"ci_number": ci_number}, "name") or \
                  frappe.db.get_value("Commercial Invoice", {"name": ci_number}, "name")
        if not ci_name:
            continue

        frappe_items = frappe.get_all("Commercial Invoice Item", filters={"parent": ci_name}, fields=["name", "item", "description", "qty"], order_by="idx ascii")
        for idx, sql_it in enumerate(sql_items):
            match_item = None
            if idx < len(frappe_items):
                match_item = frappe_items[idx]
            else:
                code_name = sql_it["code"] or sql_it["name"]
                for fi in frappe_items:
                    if fi.item == code_name or fi.description == sql_it["name"]:
                        match_item = fi
                        break
            if match_item:
                frappe.db.set_value("Commercial Invoice Item", match_item.name, {
                    "category": sql_it["category"] or None,
                    "boxes": cint(sql_it["box_qty"]),
                    "box_weight_kg": flt(sql_it["box_kg"]),
                    "docs_price": flt(sql_it["docs_price"]),
                    "docs_amount": flt(sql_it["docs_amount"])
                }, update_modified=False)
                ci_updated += 1

    frappe.db.commit()
    print(f"Updated {ci_updated} Commercial Invoice Item records.")

    # --------------------------------------------------------------------------
    # 3. Migrate Import Containers
    # --------------------------------------------------------------------------
    print("\n--- Phase 2: Migrating Import Containers ---")
    containers_sqlite = [dict(r) for r in cur.execute("SELECT * FROM proforma_app_container").fetchall()]
    cnt_created = 0
    cnt_updated = 0

    STATUS_MAP = {
        "BOOKED": "BOOKED",
        "STUFFED": "STUFFED",
        "GATE_IN": "GATE_IN",
        "ON_BOARD": "ON_BOARD",
        "IN_TRANSIT": "IN_TRANSIT",
        "DISCHARGED": "DISCHARGED",
        "AVAILABLE": "AVAILABLE",
        "ARRIVED_AT_IRAN": "ARRIVED_AT_IRAN",
        "DELIVERED_TO_UZBEKISTAN": "DELIVERED_TO_UZBEKISTAN",
        "DELIVERED": "DELIVERED_TO_UZBEKISTAN",
        "COMPLETED": "DELIVERED_TO_UZBEKISTAN",
        "CANCELLED": "Cancelled"
    }

    for c in containers_sqlite:
        c_num = c["container_number"] or f"CNT-{c['id']}"
        ci_row = ci_map.get(c["commercial_invoice_id"])
        ci_name = None
        supplier = None
        if ci_row:
            ci_number = ci_row["ci_number"]
            ci_name = frappe.db.get_value("Commercial Invoice", {"ci_number": ci_number}, "name") or \
                      frappe.db.get_value("Commercial Invoice", {"name": ci_number}, "name")
            v_id = ci_row["vendor_id"] if "vendor_id" in ci_row.keys() else None
            v_dict = vendors.get(v_id) if v_id else None
            if v_dict:
                supplier = v_dict["name"]

        status_raw = (c["status"] or "BOOKED").upper()
        status = STATUS_MAP.get(status_raw, "BOOKED")

        doc_name = frappe.db.get_value("Import Container", {"container_number": c_num}, "name")
        if doc_name:
            doc = frappe.get_doc("Import Container", doc_name)
            cnt_updated += 1
        else:
            doc = frappe.new_doc("Import Container")
            doc.container_number = c_num
            cnt_created += 1

        doc.company = company
        doc.commercial_invoice = ci_name
        doc.supplier = supplier or (frappe.db.get_value("Commercial Invoice", ci_name, "supplier") if ci_name else None)
        doc.currency = c["freight_currency"] or "USD"
        raw_size = str(c["container_size"] or "").strip()
        SIZE_MAP = {"40FT": "40", "40ft": "40", "40": "40", "20FT": "20", "20ft": "20", "20": "20", "40HC": "40HC"}
        container_size = SIZE_MAP.get(raw_size.upper(), "40") if raw_size else None
        doc.container_type = c["container_type"] or "RF"
        doc.container_size = container_size
        doc.bl_type = c["bl_type"] or None
        doc.seal_number = c["seal_number"] or None
        doc.gross_weight = flt(c["gross_weight"])
        doc.vgm = flt(c["vgm"])
        doc.status = status
        doc.total_boxes = cint(c["total_boxes"])
        doc.total_kg = flt(c["total_kg"])
        doc.total_amount = flt(c["total_amount"])
        doc.advance_70_payment_entry = c["payment_70_reference"] or None
        doc.cut_off = c["cut_off"] if c["cut_off"] else None
        doc.gate_open = c["gate_open"] if c["gate_open"] else None
        doc.gate_close = c["gate_close"] if c["gate_close"] else None
        doc.gate_in_date = c["gate_in_date"] if c["gate_in_date"] else None
        doc.customs_clearance_date = c["customs_clearance_date"] if c["customs_clearance_date"] else None
        doc.telex_release_date = c["telex_release_date"] if c["telex_release_date"] else None
        doc.allocated_deposit_amount = flt(c["allocated_deposit_amount"])
        doc.balance_due_amount = flt(c["balance_due_amount"])
        p70_raw = (c["payment_70_status"] or "Pending").title()
        P70_MAP = {"Pending": "Pending", "Paid": "Paid", "Partial": "Partial"}
        payment_70_status = P70_MAP.get(p70_raw, "Pending")
        doc.payment_70_status = payment_70_status
        doc.payment_70_date = c["payment_70_date"] if c["payment_70_date"] else None
        doc.payment_70_amount = flt(c["payment_70_amount"])

        # Container Line Items
        items_sqlite = [dict(r) for r in cur.execute(
            "SELECT * FROM proforma_app_containerlineitem WHERE container_id = ?", (c["id"],)
        ).fetchall()]
        doc.set("items", [])
        for it in items_sqlite:
            p_dict = product_map.get(it.get("product_id"))
            item_code = ensure_item(p_dict)
            doc.append("items", {
                "item_code": item_code,
                "item_name": p_dict.get("name") if p_dict else item_code,
                "category": it.get("category") or None,
                "box_qty": cint(it.get("box_qty")),
                "box_kg": flt(it.get("box_kg")),
                "total_kg": flt(it.get("total_kg")),
                "rate": flt(it.get("unit_price")),
                "amount": flt(it.get("total_amount")),
            })

        # Local Charges / Cost Lines
        cost_lines_sqlite = [dict(r) for r in cur.execute(
            "SELECT * FROM proforma_app_containerlocalcharge WHERE container_id = ?", (c["id"],)
        ).fetchall()]
        doc.set("cost_lines", [])
        for cl in cost_lines_sqlite:
            doc.append("cost_lines", {
                "cost_component": cl.get("charge_type") or cl.get("description") or "Local Charge",
                "amount": flt(cl.get("amount")),
                "currency": cl.get("currency") or "USD",
            })

        doc.flags.ignore_permissions = True
        doc.flags.ignore_validate = True
        doc.flags.ignore_links = True
        doc.save()

    frappe.db.commit()
    print(f"Containers Migration Complete: {cnt_created} Created, {cnt_updated} Updated.")

    # --------------------------------------------------------------------------
    # 4. Migrate Import Trucks
    # --------------------------------------------------------------------------
    print("\n--- Phase 3: Migrating Import Trucks ---")
    trucks_sqlite = [dict(r) for r in cur.execute("SELECT * FROM proforma_app_truck").fetchall()]
    trk_created = 0
    trk_updated = 0

    for t in trucks_sqlite:
        trk_num = t["truck_number"] or f"TRK-{t['id']}"
        ci_row = ci_map.get(t["commercial_invoice_id"])
        ci_name = None
        if ci_row:
            ci_number = ci_row["ci_number"]
            ci_name = frappe.db.get_value("Commercial Invoice", {"ci_number": ci_number}, "name") or \
                      frappe.db.get_value("Commercial Invoice", {"name": ci_number}, "name")

        doc_name = frappe.db.get_value("Import Truck", {"truck_number": trk_num}, "name")
        if doc_name:
            doc = frappe.get_doc("Import Truck", doc_name)
            trk_updated += 1
        else:
            doc = frappe.new_doc("Import Truck")
            doc.truck_number = trk_num
            trk_created += 1

        doc.company = company
        doc.commercial_invoice = ci_name
        doc.trucking_company = str(t["trucking_company_id"]) if t["trucking_company_id"] else "Standard Transport"
        doc.driver_name = t["driver_name"] or None
        doc.driver_phone = t["driver_phone"] or None
        doc.destination_warehouse = t["destination_warehouse"] or "Main Warehouse"
        doc.status = (t["status"] or "PENDING").upper()
        doc.departure_date = t["departure_date"] if t["departure_date"] else None
        doc.border_crossing_date = t["border_crossing_date"] if t["border_crossing_date"] else None
        doc.estimated_arrival = t["estimated_arrival_date"] if t["estimated_arrival_date"] else None
        doc.actual_arrival = t["actual_arrival_date"] if t["actual_arrival_date"] else None
        doc.target_temp_min = flt(t["target_temp_min"]) if t["target_temp_min"] is not None else -18.0
        doc.target_temp_max = flt(t["target_temp_max"]) if t["target_temp_max"] is not None else -15.0
        doc.total_boxes = cint(t["total_boxes"])
        doc.total_kg = flt(t["total_kg"])
        doc.transport_cost = flt(t["transport_cost"])
        doc.transport_currency = t["transport_currency"] or "USD"
        tr_p_raw = (t["transport_payment_status"] or "Unpaid").upper()
        TR_P_MAP = {"PENDING": "Unpaid", "UNPAID": "Unpaid", "PARTIAL": "Partially Paid", "PARTIALLY PAID": "Partially Paid", "PAID": "Paid"}
        doc.transport_payment_status = TR_P_MAP.get(tr_p_raw, "Unpaid")
        doc.transport_purchase_invoice = t["transport_payment_reference"] or None

        doc.flags.ignore_permissions = True
        doc.flags.ignore_validate = True
        doc.flags.ignore_links = True
        doc.save()

    frappe.db.commit()
    print(f"Trucks Migration Complete: {trk_created} Created, {trk_updated} Updated.")
    print("=== MIGRATION FINISHED SUCCESSFULLY ===")
