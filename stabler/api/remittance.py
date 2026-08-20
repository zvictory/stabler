"""Remittance module — international money transfer, staged & posted as Journal Entries.

JE-only model (no dedicated doctype): a transfer is a set of linked Journal Entries
that share `stabler_remittance_id`, each tagged with `stabler_remittance_stage`.

Lifecycle
---------
1. REGISTER (create_remittance) — sender hands over cash; obligation to the receiver
   is parked in an in-transit LIABILITY account until pickup:
     Dr  cash_in_account       send_ccy     cash_in_amount
     Cr  intransit_account     receive_ccy  payout_amount      (liability owed to receiver)
     Cr  commission_account    (native)     commission         (income earned at send)

2. PAYOUT (payout_remittance) — receiver presents the pickup code; liability is settled:
     Dr  intransit_account     receive_ccy  payout_amount
     Cr  payout_account        receive_ccy  payout_amount      (cash/bank paid out)

3. REFUND (refund_remittance) — receiver never collects; full make-whole to sender
   (principal returned AND commission clawed back, per product decision):
     Dr  intransit_account     receive_ccy  payout_amount
     Dr  commission_account    (native)     commission
     Cr  cash_in_account       send_ccy     cash_in_amount

Invariant at register: cash_in_base == payout_base + commission_base (balances by
construction), so payout and refund both balance by reusing the register legs.

Verification is code-only: the pickup code is generated at register, returned to
the caller exactly once, and stored only as a salted digest. No read endpoint
displays it, and the stored value cannot be replayed at payout.

Single-company for now; the intransit account is resolved per company, so a future
cross-company corridor can settle via a due-to/due-from without reshaping the stages.
"""

from __future__ import annotations

import frappe
from frappe.model.naming import make_autoname
from frappe.utils import flt, getdate

from stabler.api import _remittance_actions as _actions
from stabler.api._common import _assert_can_read, _require_company
from stabler.api._remittance_pickup_code import (
	_gen_pickup_code,
	_pickup_code_matches,
	hash_pickup_code,
	is_hashed_pickup_code,
	store_pickup_code,
)
from stabler.api.approvals import _assert_company_scope
from stabler.api.money import (
	_date_filters,
	_round2,
	_validate_account,
	bank_cash_accounts,
	get_exchange_rate_for_currencies,
	journal_entry_detail,
)

CORRIDORS = [
	{"from_city": "Tashkent", "to_city": "Istanbul", "label": "Tashkent → Istanbul"},
	{"from_city": "Moscow", "to_city": "Dubai", "label": "Moscow → Dubai"},
]

REMITTANCE_CURRENCIES = ["USD", "EUR", "USDT"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _gen_remittance_id(company: str) -> str:
	abbr = frappe.db.get_value("Company", company, "abbr") or "REM"
	return make_autoname(f"REM-{abbr}-.YYYY.-.#####")


def _account_root_type(name: str) -> str | None:
	return frappe.db.get_value("Account", name, "root_type")


def _resolve_intransit_account(company: str, intransit_account: str | None) -> str:
	"""Return a Liability leaf account to park in-transit remittance obligations.

	If the caller passes one, validate it (leaf, in-company, Liability). Otherwise
	derive it by name from the company's Liability leaves, preferring an account
	that looks like a remittance / in-transit / payable / suspense account.
	"""
	if intransit_account:
		info = _validate_account(intransit_account, company, 2)
		if info.get("root_type") != "Liability":
			frappe.throw(f"In-transit account '{intransit_account}' must be a Liability account.")
		return intransit_account

	liabilities = frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Liability", "is_group": 0, "disabled": 0},
		fields=["name"],
		order_by="name asc",
	)
	names = [a["name"] for a in liabilities]
	for needle in ("remittance", "in transit", "in-transit", "intransit", "payable", "suspense"):
		for n in names:
			if needle in n.lower():
				return n
	frappe.throw(
		"No in-transit liability account configured for this company. "
		"Create one (e.g. 'Remittance In-Transit') or pass intransit_account."
	)


def _find_register_je(remittance_id: str) -> str:
	if not remittance_id:
		frappe.throw("Remittance ID is required.")
	rows = frappe.get_all(
		"Journal Entry",
		filters={
			"stabler_remittance_id": remittance_id,
			"stabler_remittance_stage": "Register",
			"docstatus": 1,
		},
		pluck="name",
		limit=1,
	)
	if not rows:
		frappe.throw(f"No registered remittance found for {remittance_id}.")
	return rows[0]


def _stage_names(remittance_id: str, stage: str) -> list[str]:
	return frappe.get_all(
		"Journal Entry",
		filters={
			"stabler_remittance_id": remittance_id,
			"stabler_remittance_stage": stage,
			"docstatus": 1,
		},
		pluck="name",
	)


def _remittance_status(remittance_id: str) -> str:
	if _stage_names(remittance_id, "Refund"):
		return "Refunded"
	if _stage_names(remittance_id, "Payout"):
		return "Paid Out"
	return "Registered"


def _register_legs(je) -> dict:
	"""Pull the three register legs off a submitted register JE, keyed by role.

	cash_in = the sole debit leg; the two credit legs are split by account root
	type — the Liability leg is in-transit, the other is commission.
	"""
	debit_legs = [a for a in je.accounts if flt(a.debit) > 0]
	credit_legs = [a for a in je.accounts if flt(a.credit) > 0]
	if not debit_legs or len(credit_legs) < 2:
		frappe.throw("Register entry is malformed; cannot derive remittance legs.")
	cash_in = debit_legs[0]
	intransit = next((a for a in credit_legs if _account_root_type(a.account) == "Liability"), None)
	if intransit is None:
		frappe.throw("Register entry has no in-transit (liability) leg.")
	commission = next((a for a in credit_legs if a.name != intransit.name), None)
	return {"cash_in": cash_in, "intransit": intransit, "commission": commission}


def _assert_registered(remittance_id: str) -> None:
	status = _remittance_status(remittance_id)
	if status == "Paid Out":
		frappe.throw(f"Remittance {remittance_id} has already been paid out.")
	if status == "Refunded":
		frappe.throw(f"Remittance {remittance_id} has already been refunded.")


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def remittance_accounts(company: str) -> dict:
	"""Return account pools for the remittance form selectors."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	cash = bank_cash_accounts(company)
	income = frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Income", "is_group": 0, "disabled": 0},
		fields=["name", "account_currency"],
		order_by="name asc",
	)
	liabilities = frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Liability", "is_group": 0, "disabled": 0},
		fields=["name", "account_currency"],
		order_by="name asc",
	)
	return {
		"cash_accounts": cash,
		"payout_accounts": cash,
		"commission_accounts": income,
		"intransit_accounts": liabilities,
	}


@frappe.whitelist()
def list_corridors() -> list:
	"""Static corridor list (Tashkent→Istanbul, Moscow→Dubai)."""
	return CORRIDORS


# --------------------------------------------------------------------------- #
# Stage 1 — Register
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def create_remittance(
	company: str,
	posting_date: str,
	cash_in_account: str,
	commission_account: str,
	send_currency: str,
	receive_currency: str,
	amount: float | str,
	intransit_account: str | None = None,
	payout_account: str | None = None,  # deprecated at register; chosen at payout
	commission: float | str | None = None,
	commission_mode: str = "exclusive",
	commission_percent: float | str | None = None,
	exchange_rate: float | str | None = None,
	corridor: str | None = None,
	sender_name: str | None = None,
	receiver_name: str | None = None,
	memo: str | None = None,
	submit: int | str = 1,
) -> dict:
	"""Register a remittance: collect the sender's cash into an in-transit liability.

	Returns the remittance_id and the pickup_code — the code is generated here,
	server-side only, and returned ONCE (hand it to the sender). It is stored as a
	salted digest, so no read endpoint and no Journal Entry field discloses it again.

	commission_percent: when supplied, derives the absolute commission.
	                    Exclusive: commission = round2(amount × pct / 100).
	                    Inclusive: amount is the gross the sender hands over;
	                      principal = round2(amount / (1 + pct/100)),
	                      commission = round2(amount − principal).
	exchange_rate:      send_currency → receive_currency (cross-currency only).
	"""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	amount = _round2(amount)
	if commission_percent is not None:
		rate = flt(commission_percent) / 100.0
		if commission_mode == "inclusive":
			principal = _round2(amount / (1 + rate))
			commission = _round2(amount - principal)
		else:
			commission = _round2(amount * rate)
	else:
		commission = _round2(commission or 0)

	if commission_mode == "inclusive":
		cash_in_send = amount
		payout_send = _round2(amount - commission)
		commission_send = commission
	elif commission_mode == "exclusive":
		cash_in_send = _round2(amount + commission)
		payout_send = amount
		commission_send = commission
	else:
		frappe.throw(f"Invalid commission_mode: {commission_mode!r}. Use 'inclusive' or 'exclusive'.")

	if cash_in_send <= 0:
		frappe.throw("Transfer amount must be positive.")
	if commission_send < 0:
		frappe.throw("Commission must be non-negative.")

	# Validate accounts. Leg 2 is now the in-transit LIABILITY (not a payout cash acct).
	_validate_account(cash_in_account, company, 1)
	intransit_account = _resolve_intransit_account(company, intransit_account)
	comm_acct_info = _validate_account(commission_account, company, 3)

	base_currency = frappe.db.get_value("Company", company, "default_currency") or "UZS"

	# --- exchange rates ---
	if send_currency == base_currency:
		send_to_base = 1.0
	else:
		send_to_base = _round2(get_exchange_rate_for_currencies(send_currency, base_currency, posting_date))

	if receive_currency == send_currency:
		receive_to_base = send_to_base
	elif receive_currency == base_currency:
		receive_to_base = 1.0
	else:
		receive_to_base = _round2(
			get_exchange_rate_for_currencies(receive_currency, base_currency, posting_date)
		)

	if receive_currency == send_currency:
		payout_receive = payout_send
	else:
		s2r = (
			_round2(exchange_rate)
			if exchange_rate
			else _round2(get_exchange_rate_for_currencies(send_currency, receive_currency, posting_date))
		)
		payout_receive = _round2(payout_send * s2r)

	# --- base totals (anchored so JE balances exactly) ---
	cash_in_base = _round2(cash_in_send * send_to_base)
	payout_base = _round2(payout_receive * receive_to_base)
	commission_base = _round2(cash_in_base - payout_base)

	if commission_base < 0:
		frappe.throw("Commission base amount is negative — check exchange rates and commission.")

	comm_acct_currency = comm_acct_info.get("account_currency") or base_currency
	if comm_acct_currency == send_currency:
		comm_in_acct = commission_send
		comm_rate = _round2(commission_base / commission_send) if commission_send else send_to_base
	elif comm_acct_currency == base_currency:
		comm_in_acct = commission_base
		comm_rate = 1.0
	else:
		comm_in_acct = commission_base
		comm_rate = 1.0

	multi_currency = int(send_currency != base_currency or receive_currency != base_currency)

	remittance_id = _gen_remittance_id(company)
	code = _gen_pickup_code()

	parts = []
	if corridor:
		parts.append(corridor)
	if sender_name:
		parts.append(f"From: {sender_name}")
	if receiver_name:
		parts.append(f"To: {receiver_name}")
	if memo:
		parts.append(memo)
	remark = " | ".join(parts) if parts else "Remittance"

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"posting_date": getdate(posting_date),
			"company": company,
			"voucher_type": "Journal Entry",
			"multi_currency": multi_currency,
			"user_remark": remark,
			"cheque_no": remittance_id,
			"cheque_date": getdate(posting_date),
			"stabler_remittance_id": remittance_id,
			"stabler_remittance_stage": "Register",
			"stabler_pickup_code": store_pickup_code(code),
			"stabler_sender_name": (sender_name or "")[:140],
			"stabler_receiver_name": (receiver_name or "")[:140],
			"accounts": [
				{
					"account": cash_in_account,
					"account_currency": send_currency,
					"exchange_rate": send_to_base,
					"debit_in_account_currency": cash_in_send,
					"debit": cash_in_base,
					"credit_in_account_currency": 0,
					"credit": 0,
					"user_remark": remark,
				},
				{
					"account": intransit_account,
					"account_currency": receive_currency,
					"exchange_rate": _round2(payout_base / payout_receive)
					if payout_receive
					else receive_to_base,
					"credit_in_account_currency": payout_receive,
					"credit": payout_base,
					"debit_in_account_currency": 0,
					"debit": 0,
					"user_remark": remark,
				},
				{
					"account": commission_account,
					"account_currency": comm_acct_currency,
					"exchange_rate": comm_rate,
					"credit_in_account_currency": comm_in_acct,
					"credit": commission_base,
					"debit_in_account_currency": 0,
					"debit": 0,
					"user_remark": remark,
				},
			],
		}
	)
	je.insert(ignore_permissions=True)
	if int(submit):
		je.flags.ignore_approval_gate = True
		je.submit()
	return {
		"name": je.name,
		"docstatus": je.docstatus,
		"remittance_id": remittance_id,
		"pickup_code": code,
		"status": "Registered",
	}


# --------------------------------------------------------------------------- #
# Stage 2 — Payout
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def payout_remittance(
	remittance_id: str,
	pickup_code: str,
	payout_account: str,
	posting_date: str | None = None,
	submit: int | str = 1,
) -> dict:
	"""Pay out a registered remittance after verifying the pickup code (code only).

	Clears the in-transit liability into the chosen cash/bank payout account.
	"""
	reg_name = _find_register_je(remittance_id)
	reg = frappe.get_doc("Journal Entry", reg_name)
	_assert_company_scope(reg.company)
	_require_company(reg.company)
	_assert_registered(remittance_id)

	stored = (reg.get("stabler_pickup_code") or "").strip()
	if stored and not is_hashed_pickup_code(stored):
		# Registered before patch v86 and the migration has not run on this site.
		# Fail with the real cause instead of blaming the receiver's code.
		frappe.throw(
			"This transfer's pickup code is still stored in the old format. "
			"Run `bench migrate` on this site (patch v86), then retry.",
		)
	if not _pickup_code_matches(stored, pickup_code):
		frappe.throw("Invalid pickup code.", frappe.PermissionError)

	if not payout_account:
		frappe.throw("Payout cash/bank account is required.")
	pay_info = _validate_account(payout_account, reg.company, 1)

	legs = _register_legs(reg)
	intransit = legs["intransit"]
	receive_currency = intransit.account_currency
	payout_receive = _round2(intransit.credit_in_account_currency)
	payout_base = _round2(intransit.credit)

	base_currency = frappe.db.get_value("Company", reg.company, "default_currency") or "UZS"
	acct_ccy = pay_info.get("account_currency") or base_currency
	if acct_ccy == receive_currency:
		pay_in_acct = payout_receive
		pay_rate = _round2(payout_base / payout_receive) if payout_receive else 1.0
	elif acct_ccy == base_currency:
		pay_in_acct = payout_base
		pay_rate = 1.0
	else:
		pay_in_acct = payout_base
		pay_rate = 1.0

	multi_currency = int(receive_currency != base_currency or acct_ccy != base_currency)
	remark = f"Payout {remittance_id}"

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"posting_date": getdate(posting_date) if posting_date else reg.posting_date,
			"company": reg.company,
			"voucher_type": "Journal Entry",
			"multi_currency": multi_currency,
			"user_remark": remark,
			"cheque_no": remittance_id,
			"cheque_date": getdate(posting_date) if posting_date else reg.posting_date,
			"stabler_remittance_id": remittance_id,
			"stabler_remittance_stage": "Payout",
			"accounts": [
				{
					"account": intransit.account,
					"account_currency": receive_currency,
					"exchange_rate": _round2(payout_base / payout_receive) if payout_receive else 1.0,
					"debit_in_account_currency": payout_receive,
					"debit": payout_base,
					"credit_in_account_currency": 0,
					"credit": 0,
					"user_remark": remark,
				},
				{
					"account": payout_account,
					"account_currency": acct_ccy,
					"exchange_rate": pay_rate,
					"credit_in_account_currency": pay_in_acct,
					"credit": payout_base,
					"debit_in_account_currency": 0,
					"debit": 0,
					"user_remark": remark,
				},
			],
		}
	)
	je.insert(ignore_permissions=True)
	if int(submit):
		je.flags.ignore_approval_gate = True
		je.submit()
	return {"name": je.name, "docstatus": je.docstatus, "remittance_id": remittance_id, "status": "Paid Out"}


# --------------------------------------------------------------------------- #
# Stage 3 — Refund (full make-whole: principal + commission back to sender)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def refund_remittance(
	remittance_id: str,
	posting_date: str | None = None,
	reason: str | None = None,
	submit: int | str = 1,
) -> dict:
	"""Refund a registered (not yet paid-out) remittance in full.

	Per the product decision, a refund returns the full amount the sender handed
	over AND reverses the commission income (make-whole), by unwinding the three
	register legs: Dr in-transit + Dr commission, Cr cash-in.
	"""
	reg_name = _find_register_je(remittance_id)
	reg = frappe.get_doc("Journal Entry", reg_name)
	_assert_company_scope(reg.company)
	_require_company(reg.company)
	_assert_registered(remittance_id)

	legs = _register_legs(reg)
	cash_in = legs["cash_in"]
	intransit = legs["intransit"]
	commission = legs["commission"]

	base_currency = frappe.db.get_value("Company", reg.company, "default_currency") or "UZS"
	multi_currency = int(
		any(
			(leg.account_currency or base_currency) != base_currency
			for leg in (cash_in, intransit, commission)
			if leg is not None
		)
	)
	remark = f"Refund {remittance_id}" + (f" — {reason}" if reason else "")

	accounts = [
		{  # clear the in-transit liability
			"account": intransit.account,
			"account_currency": intransit.account_currency,
			"exchange_rate": flt(intransit.exchange_rate) or 1.0,
			"debit_in_account_currency": _round2(intransit.credit_in_account_currency),
			"debit": _round2(intransit.credit),
			"credit_in_account_currency": 0,
			"credit": 0,
			"user_remark": remark,
		},
		{  # return full cash to the sender
			"account": cash_in.account,
			"account_currency": cash_in.account_currency,
			"exchange_rate": flt(cash_in.exchange_rate) or 1.0,
			"credit_in_account_currency": _round2(cash_in.debit_in_account_currency),
			"credit": _round2(cash_in.debit),
			"debit_in_account_currency": 0,
			"debit": 0,
			"user_remark": remark,
		},
	]
	if commission is not None and _round2(commission.credit) > 0:
		accounts.insert(
			1,
			{  # claw back the commission income
				"account": commission.account,
				"account_currency": commission.account_currency,
				"exchange_rate": flt(commission.exchange_rate) or 1.0,
				"debit_in_account_currency": _round2(commission.credit_in_account_currency),
				"debit": _round2(commission.credit),
				"credit_in_account_currency": 0,
				"credit": 0,
				"user_remark": remark,
			},
		)

	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"posting_date": getdate(posting_date) if posting_date else reg.posting_date,
			"company": reg.company,
			"voucher_type": "Journal Entry",
			"multi_currency": multi_currency,
			"user_remark": remark,
			"cheque_no": remittance_id,
			"cheque_date": getdate(posting_date) if posting_date else reg.posting_date,
			"stabler_remittance_id": remittance_id,
			"stabler_remittance_stage": "Refund",
			"accounts": accounts,
		}
	)
	je.insert(ignore_permissions=True)
	if int(submit):
		je.flags.ignore_approval_gate = True
		je.submit()
	return {"name": je.name, "docstatus": je.docstatus, "remittance_id": remittance_id, "status": "Refunded"}


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
_TRANSFER = "Remittance Transfer"


def _transfer_states(remittance_ids: list[str], company: str | None) -> dict:
	"""The four state axes for each transfer, keyed by remittance id.

	The bridge is `_remittance_accounting._build_entry`, which stamps
	`stabler_remittance_id = transfer.name` on every stage entry — so the id these
	JE-shaped reads already carry IS the Remittance Transfer's name.

	`get_all` rather than `get_list` on purpose: this is an enrichment of rows the
	caller was already allowed to read, and `get_list` would raise for a user who
	holds Journal Entry read and no remittance role at all — turning a missing
	button into a broken screen. The role half of the gate is what withholds the
	actions from that user, and it withholds them by returning an empty list.
	"""
	ids = sorted({rid for rid in remittance_ids if rid})
	if not ids:
		return {}
	filters = {"name": ["in", ids]}
	if company:
		# Belt to the caller's own company scope: a remittance id is not a secret,
		# and this read must not become a way to learn another tenant's state.
		filters["company"] = company
	rows = frappe.get_all(_TRANSFER, filters=filters, fields=["name", *_actions.STATE_FIELDS])
	return {row["name"]: row for row in rows}


def _annotate_actions(rows: list, company: str | None = None) -> list:
	"""Stamp `allowed_actions` on JE-shaped remittance rows.

	A legacy `Rem-%` entry has no Remittance Transfer behind it, so it has no state
	machine and therefore no actions — an empty list, never a missing key, so a
	client never has to distinguish "no actions" from "this endpoint forgot".
	"""
	states = _transfer_states([row.get("stabler_remittance_id") for row in rows], company)
	roles = frappe.get_roles()  # once for the page, not once per row
	for row in rows:
		state = states.get(row.get("stabler_remittance_id"))
		row["allowed_actions"] = _actions.allowed_actions(state, roles) if state else []
	return rows


@frappe.whitelist()
def list_remittances(
	company: str,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 50,
) -> list:
	"""List remittances for this company — one row per transfer (the register JE),
	with a derived lifecycle status. Never returns the pickup code."""
	_assert_company_scope(company)  # tenant isolation: reject a foreign company arg
	_require_company(company)
	clauses, params = _date_filters(from_date, to_date)
	params["company"] = company
	params["limit"] = max(1, min(500, int(limit)))
	qualified = [c.replace("posting_date", "je.posting_date") for c in clauses]
	# Register-stage rows for the new staged model, plus legacy 'Rem-%' entries
	# that predate the remittance_id field.
	where = " AND ".join(
		[
			"je.company = %(company)s",
			"je.docstatus < 2",
			"(je.stabler_remittance_stage = 'Register' OR "
			"(COALESCE(je.stabler_remittance_id, '') = '' AND je.cheque_no LIKE 'Rem-%%'))",
			*qualified,
		]
	)
	rows = frappe.db.sql(
		f"""
        SELECT
            je.name,
            je.posting_date,
            je.user_remark,
            je.cheque_no,
            je.stabler_remittance_id,
            je.stabler_sender_name,
            je.stabler_receiver_name,
            je.docstatus,
            je.multi_currency,
            je.total_debit  AS total_debit_base,
            je.total_credit AS total_credit_base,
            c.default_currency AS base_currency,
            COALESCE(
                (SELECT debit_in_account_currency
                   FROM `tabJournal Entry Account`
                  WHERE parent = je.name AND debit_in_account_currency > 0
                  LIMIT 1),
                je.total_debit
            ) AS send_amount,
            COALESCE(
                (SELECT account_currency
                   FROM `tabJournal Entry Account`
                  WHERE parent = je.name AND debit_in_account_currency > 0
                  LIMIT 1),
                c.default_currency
            ) AS send_currency
        FROM `tabJournal Entry` je
        JOIN `tabCompany` c ON c.name = je.company
        WHERE {where}
        ORDER BY je.posting_date DESC, je.name DESC
        LIMIT %(limit)s
        """,
		params,
		as_dict=True,
	)
	for r in rows:
		r["status"] = (
			_remittance_status(r["stabler_remittance_id"]) if r.get("stabler_remittance_id") else "Legacy"
		)
	return _actions.assert_no_pickup_code(_annotate_actions(rows, company))


@frappe.whitelist()
def remittance_detail(name: str) -> dict:
	"""Full remittance detail (delegates to journal_entry_detail), enriched with the
	lifecycle status and the linked stage entries. Never returns the pickup code."""
	_assert_can_read("Journal Entry", name)
	detail = journal_entry_detail(name)
	rid = frappe.db.get_value("Journal Entry", name, "stabler_remittance_id")
	detail["stabler_remittance_id"] = rid
	if rid:
		detail["remittance_id"] = rid
		detail["remittance_status"] = _remittance_status(rid)
		detail["stages"] = frappe.get_all(
			"Journal Entry",
			filters={"stabler_remittance_id": rid, "docstatus": 1},
			fields=["name", "stabler_remittance_stage AS stage", "posting_date", "docstatus"],
			order_by="creation asc",
		)
	# The detail screen is where the buttons are drawn, so it is the read path that
	# most needs the server to have decided. Scoped on the entry's own company.
	_annotate_actions([detail], detail.get("company"))
	return _actions.assert_no_pickup_code(detail)
