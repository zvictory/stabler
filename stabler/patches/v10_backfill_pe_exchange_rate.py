"""
Backfill transaction_exchange_rate on Payment Entry GL rows that ERPNext core
mis-stamped as 1.0 (or 0) despite a non-base account_currency.

Background
----------
ANJAN runs on USD base but transacts mostly in UZS. Forensic audit on
2026-05-21 found 2,952 GL Entry rows (1,320 distinct Payment Entries, posted
2026-03-11 → 2026-05-13) where:
  - account_currency = UZS
  - debit/credit (base USD) and debit_in_account_currency/credit_in_account_currency (UZS)
    reconcile correctly against the parent PE.source_exchange_rate
  - but transaction_exchange_rate was stored as 1.0 (or 0), losing the per-row
    UZS→USD rate metadata

Stabler itself reads transaction_exchange_rate nowhere, so the bad data
was cosmetic at the UI level. The fix is still applied because:
  1. Reports that GROUP BY transaction_exchange_rate / period rate stamp
     (CBU compliance, exchange-gain analysis) need accurate metadata.
  2. The data is trivially recoverable via the debit / debit_in_account_currency
     ratio — leaving it wrong would compound if any future query starts
     relying on the field.

Source of the upstream bug: apps/erpnext core's
PaymentEntry.set_transaction_currency_and_rate + add_party_gl_entries
(payment_entry.py around line 1277). Not fixable from stabler.

Mutation
--------
This patch is an idempotent SQL backfill that has ALREADY BEEN RUN against
the production DB on 2026-05-21 from the bench shell, with a mysqldump
snapshot taken first to:
  sites/stabler/private/backups/manual/tabGL_Entry_pre_36_20260521_013847.sql.gz

The patch is registered in patches.txt so any future site clone / new
deploy that hasn't had the manual fix run will receive the same backfill
automatically. The WHERE clause filters to only rows still mis-stamped, so
re-running is a no-op.
"""

import frappe


def execute() -> None:
	rows = frappe.db.sql(
		"""
		UPDATE `tabGL Entry`
		SET transaction_exchange_rate = ROUND(
			(debit + credit) /
			(debit_in_account_currency + credit_in_account_currency),
			9
		),
		modified = NOW(),
		modified_by = 'Administrator'
		WHERE voucher_type = 'Payment Entry'
		  AND account_currency != %s
		  AND is_cancelled = 0
		  AND (debit_in_account_currency > 0 OR credit_in_account_currency > 0)
		  AND ABS(
				(debit + credit) /
				NULLIF(debit_in_account_currency + credit_in_account_currency, 0)
				- COALESCE(transaction_exchange_rate, 0)
		  ) > 0.0001
		""",
		(frappe.db.get_default("currency") or "USD",),
	)
	frappe.db.commit()
	frappe.logger().info(
		f"v10_backfill_pe_exchange_rate: recomputed transaction_exchange_rate on {rows} rows"
	)
