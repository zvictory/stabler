import frappe
from frappe.utils import flt, today, getdate, add_days
from datetime import date, datetime
from decimal import Decimal
import openpyxl
import io
import json
import hashlib

REF_PREFIX = "MSA-IMP-"

def _to_date(value) -> date | None:
	if value is None or value == "":
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	s = str(value).strip()
	for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
		try:
			return datetime.strptime(s, fmt).date()
		except ValueError:
			continue
	return None

def _to_decimal(value) -> Decimal | None:
	if value is None or value == "":
		return None
	if isinstance(value, Decimal):
		return value
	if isinstance(value, (int, float)):
		return Decimal(str(value))
	s = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
	try:
		return Decimal(s)
	except Exception:
		return None

def _clean_str(value) -> str:
	if value is None:
		return ""
	return str(value).strip()

def _deterministic_ref(posting_date, amount, remark, deposit) -> str:
	raw = "|".join([
		posting_date.isoformat() if hasattr(posting_date, "isoformat") else str(posting_date),
		f"{amount}",
		remark or "",
		deposit or "",
	])
	return REF_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

def parse_xlsx(file_content) -> list[dict]:
	wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
	ws = wb.active
	rows_iter = ws.iter_rows(values_only=True)
	header = next(rows_iter, None)
	if not header:
		return []

	normalized = [(str(c).strip().lower() if c is not None else "") for c in header]
	
	header_synonyms = {
		"date": ("date",),
		"amount": ("amount",),
		"remark": ("remark", "remark (notes)", "notes"),
		"customer": ("customer",),
		"deposit": ("deposit",),
		"exchange_rate": ("exchange rate", "exchange_rate", "xr"),
		"usd_amount": ("usd amount", "usd_amount", "usd"),
		"child_customer": ("child customer", "child_customer", "child"),
	}

	col = {}
	for field_name, synonyms in header_synonyms.items():
		for syn in synonyms:
			if syn in normalized:
				col[field_name] = normalized.index(syn)
				break

	missing = [k for k in ("date", "amount", "customer", "deposit") if k not in col]
	if missing:
		raise ValueError(f"Payments xlsx header missing required columns: {missing}")

	def pick(row: tuple, key: str):
		i = col.get(key)
		if i is None or i >= len(row):
			return None
		return row[i]

	rows = []
	for row_num, row in enumerate(rows_iter, start=2):
		if not row or all(c is None or c == "" for c in row):
			continue

		raw_date = pick(row, "date")
		raw_amount = pick(row, "amount")
		posting_date = _to_date(raw_date)
		amount = _to_decimal(raw_amount)

		row_dict = {
			"row_num": row_num,
			"posting_date": posting_date or date.min,
			"amount": amount if amount is not None else Decimal("0"),
			"remark": _clean_str(pick(row, "remark")),
			"customer": _clean_str(pick(row, "customer")),
			"deposit": _clean_str(pick(row, "deposit")),
			"exchange_rate": _to_decimal(pick(row, "exchange_rate")),
			"usd_amount": _to_decimal(pick(row, "usd_amount")),
			"child_customer": _clean_str(pick(row, "child_customer")),
		}
		rows.append(row_dict)

	wb.close()
	return rows

def _fetch_open_invoices(customer: str) -> list[dict]:
	"""Return open SI dicts ordered by posting_date asc, oldest first.

	Includes child customers' invoices if the customer is a parent.
	"""
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, "docstatus": 1, "outstanding_amount": [">", 0]},
		fields=["name", "outstanding_amount", "posting_date", "customer"],
		order_by="posting_date asc, name asc"
	)

	# Fetch child customers
	children = frappe.get_all(
		"Customer",
		filters={"custom_parent_customer": customer},
		pluck="name"
	)
	if children:
		child_invoices = frappe.get_all(
			"Sales Invoice",
			filters={"customer": ["in", children], "docstatus": 1, "outstanding_amount": [">", 0]},
			fields=["name", "outstanding_amount", "posting_date", "customer"],
			order_by="posting_date asc, name asc"
		)
		invoices.extend(child_invoices)
		# Sort globally by posting_date, name
		invoices.sort(key=lambda x: (x.get("posting_date") or "", x["name"]))

	return invoices

def simulate_fifo_multi(rows: list[dict]) -> list[dict]:
	# Get open invoices per unique customer in rows
	unique_customers = {r["customer"] for r in rows if r["customer"]}
	invoices_by_customer = {c: _fetch_open_invoices(c) for c in unique_customers}

	sims = []
	for r in rows:
		if r["amount"] <= 0:
			# Refund row: no allocations
			sims.append({
				"parsed": r,
				"allocations": [],
				"overpayment": r["amount"],
				"refund": True
			})
			continue

		cust = r["customer"]
		invoices = invoices_by_customer.get(cust) or []
		remaining_payment = Decimal(str(r["amount"]))
		allocations = []

		for inv in invoices:
			outstanding = Decimal(str(inv["outstanding_amount"]))
			if outstanding <= 0:
				continue
			if remaining_payment <= 0:
				break

			allocated = min(remaining_payment, outstanding)
			inv["outstanding_amount"] = float(outstanding - allocated)
			remaining_payment -= allocated

			allocations.append({
				"invoice_name": inv["name"],
				"allocated": allocated,
				"customer": inv["customer"]
			})

		sims.append({
			"parsed": r,
			"allocations": allocations,
			"overpayment": remaining_payment,
			"refund": False
		})

	return sims

def _get_file_content(file_url=None):
	if "file" in frappe.request.files:
		return frappe.request.files["file"].stream.read()
	if file_url:
		from frappe.utils.file_manager import get_file
		_, content = get_file(file_url)
		return content
	frappe.throw("No file uploaded or file URL provided.")

@frappe.whitelist()
def preview_payment_import(file_url=None):
	content = _get_file_content(file_url)
	rows = parse_xlsx(content)

	# Fetch valid UZS accounts and customers for validation
	uzs_accounts = frappe.get_all(
		"Account",
		filters={"account_currency": "UZS", "is_group": 0},
		pluck="name"
	)
	if not uzs_accounts:
		uzs_accounts = frappe.get_all("Account", filters={"is_group": 0}, pluck="name")
	
	valid_accounts = set(uzs_accounts)
	valid_customers = set(frappe.get_all("Customer", pluck="name"))

	eligible = []
	errors = []

	for r in rows:
		row_errors = []
		if not r["deposit"]:
			row_errors.append("Deposit account is empty")
		elif r["deposit"] not in valid_accounts:
			row_errors.append(f"Account '{r['deposit']}' not found in ERPNext")

		if r["customer"] not in valid_customers:
			row_errors.append(f"Customer '{r['customer']}' not found in ERPNext")

		if r["amount"] < 0 and r["child_customer"] and r["child_customer"] not in valid_customers:
			row_errors.append(f"Child customer '{r['child_customer']}' not found in ERPNext")

		if row_errors:
			errors.append({"row_num": r["row_num"], "customer": r["customer"], "errors": row_errors})
		else:
			eligible.append(r)

	sims = simulate_fifo_multi(eligible)

	return {
		"total_rows": len(rows),
		"eligible_count": len(eligible),
		"error_count": len(errors),
		"error_rows": errors,
		"can_import": len(eligible) > 0,
		"preview_rows": [
			{
				"row_num": s["parsed"]["row_num"],
				"date": s["parsed"]["posting_date"].isoformat() if hasattr(s["parsed"]["posting_date"], "isoformat") else str(s["parsed"]["posting_date"]),
				"customer": s["parsed"]["customer"],
				"amount": float(abs(s["parsed"]["amount"])),
				"refund": s["refund"],
				"deposit": s["parsed"]["deposit"],
				"alloc_count": len(s["allocations"]),
				"overpayment": float(s["overpayment"]),
			}
			for s in sims
		]
	}

@frappe.whitelist()
def execute_payment_import(file_url=None, company=None):
	if not company:
		company = frappe.defaults.get_user_default("Company") or frappe.get_all("Company", pluck="name", limit=1)[0]

	content = _get_file_content(file_url)
	rows = parse_xlsx(content)

	# Fetch valid accounts and customers
	uzs_accounts = frappe.get_all("Account", filters={"account_currency": "UZS", "is_group": 0}, pluck="name")
	if not uzs_accounts:
		uzs_accounts = frappe.get_all("Account", filters={"is_group": 0}, pluck="name")
	
	valid_accounts = set(uzs_accounts)
	valid_customers = set(frappe.get_all("Customer", pluck="name"))

	eligible = []
	for r in rows:
		if r["deposit"] in valid_accounts and r["customer"] in valid_customers:
			if not (r["amount"] < 0 and r["child_customer"] and r["child_customer"] not in valid_customers):
				eligible.append(r)

	sims = simulate_fifo_multi(eligible)

	ar_account = frappe.get_cached_value("Company", company, "default_receivable_account")
	if not ar_account:
		ar_account = "Debtors - M" # fallback

	created = []
	errors = []
	skipped = []

	for s in sims:
		r = s["parsed"]
		ref = _deterministic_ref(r["posting_date"], r["amount"], r["remark"], r["deposit"])
		
		# Idempotency check
		if frappe.db.exists("Payment Entry", {"reference_no": ref, "docstatus": 1}):
			skipped.append({"row_num": r["row_num"], "reason": "Already imported"})
			continue

		try:
			pe = frappe.new_doc("Payment Entry")
			pe.payment_type = "Pay" if s["refund"] else "Receive"
			pe.party_type = "Customer"
			pe.party = r["child_customer"] if (s["refund"] and r["child_customer"]) else r["customer"]
			pe.company = company
			pe.posting_date = r["posting_date"]
			
			if pe.payment_type == "Receive":
				pe.paid_from = ar_account
				pe.paid_to = r["deposit"]
			else:
				pe.paid_from = r["deposit"]
				pe.paid_to = ar_account

			pe.paid_amount = float(abs(r["amount"]))
			pe.received_amount = float(abs(r["amount"]))
			pe.source_exchange_rate = 1.0
			pe.target_exchange_rate = 1.0
			pe.reference_no = ref
			pe.reference_date = r["posting_date"]
			pe.remarks = r["remark"] or "Imported Payment Entry"

			# Allocations
			for alloc in s["allocations"]:
				pe.append("references", {
					"reference_doctype": "Sales Invoice",
					"reference_name": alloc["invoice_name"],
					"allocated_amount": float(alloc["allocated"])
				})

			pe.insert(ignore_permissions=True)
			pe.submit()
			created.append(pe.name)
		except Exception as exc:
			frappe.db.rollback()
			errors.append({"row_num": r["row_num"], "error": str(exc)})

	return {
		"status": "success",
		"created_count": len(created),
		"error_count": len(errors),
		"skipped_count": len(skipped),
		"created": created,
		"errors": errors,
		"skipped": skipped,
	}
