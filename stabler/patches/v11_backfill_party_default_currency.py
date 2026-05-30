"""
Backfill default_currency on Customer / Supplier records left NULL or empty.

Background
----------
Forensic audit on 2026-05-21 found 132 parties (36 customers + 96 suppliers)
on the ANJAN production site with NULL or empty-string default_currency.
Stabler's AR/AP-by-currency grouping (the #26 / #27 fix) reads this field
to label rows; missing values silently fell into a "NULL" bucket in the UI.

Strategy
--------
For each party with NULL/empty default_currency:
  1. Look at its posted GL Entry rows. Take the account_currency that
     appears most often → that's the party's de-facto transaction currency.
  2. If the party has zero GL history (orphan master), default to the
     company base currency.

This was applied to the live DB on 2026-05-21:
  - Customers backfilled from GL:        29
  - Customers defaulted to base (USD):    7
  - Suppliers backfilled from GL:        54
  - Suppliers defaulted to base (USD):   42

A mysqldump of tabCustomer + tabSupplier was taken to:
  sites/stabler/private/backups/manual/tabGL_Entry_pre_36_20260521_013847.sql.gz
(same file, taken once for both #36 and #37).

The patch is idempotent — once default_currency is set on a row the WHERE
clause skips it, so re-running is a no-op.
"""

import frappe


def execute() -> None:
	base_ccy = frappe.db.get_default("currency") or "USD"

	for party_type, table in (("Customer", "tabCustomer"), ("Supplier", "tabSupplier")):
		# Backfill from dominant posted account_currency.
		frappe.db.sql(
			f"""
			UPDATE `{table}` p
			JOIN (
				SELECT party,
					SUBSTRING_INDEX(GROUP_CONCAT(account_currency ORDER BY c DESC), ',', 1) AS ccy
				FROM (
					SELECT party, account_currency, COUNT(*) AS c
					FROM `tabGL Entry`
					WHERE party_type = %s AND is_cancelled = 0
					GROUP BY party, account_currency
				) x
				GROUP BY party
			) g ON g.party = p.name
			SET p.default_currency = g.ccy,
				p.modified = NOW(),
				p.modified_by = 'Administrator'
			WHERE p.default_currency IS NULL OR p.default_currency = ''
			""",
			(party_type,),
		)

		# Orphans (no GL history) → base currency.
		frappe.db.sql(
			f"""
			UPDATE `{table}`
			SET default_currency = %s,
				modified = NOW(),
				modified_by = 'Administrator'
			WHERE default_currency IS NULL OR default_currency = ''
			""",
			(base_ccy,),
		)

	frappe.db.commit()
	frappe.logger().info(
		"v11_backfill_party_default_currency: filled NULL default_currency on Customer + Supplier"
	)
