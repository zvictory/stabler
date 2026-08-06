app_name = "stabler"
app_title = "Stabler"
app_publisher = "Stabler"
app_description = "Financial operations, simplified"
app_email = "admin@stabler.app"
app_license = "mit"

login_redirect_url = "/stabler#/dashboard"
home_page = "/stabler"

website_route_rules = [
	{"from_route": "/stabler", "to_route": "stabler"},
	{"from_route": "/stabler/<path:app_path>", "to_route": "stabler"},
]

before_request = [
	"stabler.middleware.desk_gate.gate_desk",
]

# Record-level company isolation (framework-level; inherited by REST + Desk).
# Restriction applies only to users with an explicit Allowed Companies list and
# who are not admins — see stabler/api/permissions.py.
permission_query_conditions = {
	"Sales Invoice": "stabler.api.permissions.sales_invoice_query",
	"Purchase Invoice": "stabler.api.permissions.purchase_invoice_query",
	"Payment Entry": "stabler.api.permissions.payment_entry_query",
	"Journal Entry": "stabler.api.permissions.journal_entry_query",
	"Sales Order": "stabler.api.permissions.sales_order_query",
	"Purchase Order": "stabler.api.permissions.purchase_order_query",
	"Delivery Note": "stabler.api.permissions.delivery_note_query",
	"Purchase Receipt": "stabler.api.permissions.purchase_receipt_query",
	"Stock Entry": "stabler.api.permissions.stock_entry_query",
	"Stock Reconciliation": "stabler.api.permissions.stock_reconciliation_query",
	"Bank Transaction": "stabler.api.permissions.bank_transaction_query",
	"CRM Activity": "stabler.api.permissions.crm_activity_query",
	"CRM Stage Event": "stabler.api.permissions.crm_stage_event_query",
	"Tender Master": "stabler.api.permissions.tender_master_query",
	# Master scoping by owner/territory (gap #46) — safe-by-default: only restricts
	# users with an explicit Allowed Owner/Territory list; admins unaffected.
	"Customer": "stabler.api.permissions.customer_query",
	"Supplier": "stabler.api.permissions.supplier_query",
}

has_permission = {
	"Sales Invoice": "stabler.api.permissions.company_has_permission",
	"Purchase Invoice": "stabler.api.permissions.company_has_permission",
	"Payment Entry": "stabler.api.permissions.company_has_permission",
	"Journal Entry": "stabler.api.permissions.company_has_permission",
	"Sales Order": "stabler.api.permissions.company_has_permission",
	"Purchase Order": "stabler.api.permissions.company_has_permission",
	"Delivery Note": "stabler.api.permissions.company_has_permission",
	"Purchase Receipt": "stabler.api.permissions.company_has_permission",
	"Stock Entry": "stabler.api.permissions.company_has_permission",
	"Stock Reconciliation": "stabler.api.permissions.company_has_permission",
	"Bank Transaction": "stabler.api.permissions.company_has_permission",
	"CRM Activity": "stabler.api.permissions.company_has_permission",
	"CRM Stage Event": "stabler.api.permissions.company_has_permission",
	"Tender Master": "stabler.api.permissions.company_has_permission",
	"Customer": "stabler.api.permissions.master_has_permission",
	"Supplier": "stabler.api.permissions.master_has_permission",
}

# Frappe bu hook'u uygulama bazlı okur (environment.py:193), yani ERPNext'in
# fixture'ları `--app stabler` koşusuna gelmez. Kendi asgari setimizi kuruyoruz.
before_tests = "stabler.tests.fixtures.before_tests"

scheduler_events = {
	"daily": [
		"stabler.tasks.cbu_rate_refresh.fetch_and_store",
		"stabler.tasks.roi_refresh.daily",
		"stabler.service.schedule_engine.generate_rolling_schedule_rows",
		"stabler.tasks.gl_integrity.nightly_scan",
		"stabler.api.backup.run_scheduled_backup",
		"stabler.integrations.timepay.sync.nightly_sync",
		"stabler.integrations.timepay.processor.nightly_process",
		# Seal the audit hash-chain nightly (gap #42 tamper-evidence).
		"stabler.api.audit.seal_audit_log",
		"stabler.tasks.eta_payment_alert.check_upcoming_deadlines",
		# Watch the repost queue — both COGS poisonings survived on its silence.
		"stabler.tasks.repost_queue_alert.check_repost_queue",
	],
	"weekly": [
		# Two-tier backup retention pruning (gap #47).
		"stabler.api.backup.apply_retention_policy",
	],
	"hourly": [
		"stabler.integrations.one_c.hooks.hourly_sync",
		# Poll Didox for counterparty acceptance/rejection of sent ЭСФ (B4).
		"stabler.integrations.didox.hooks.sync_pending_statuses",
		# Poll UZEX etender for new/updated lots → CRM Deal upsert (WP-302).
		"stabler.tasks.uzex_poll.fetch_and_store",
	],
}

doc_events = {
	"CRM Deal": {
		"validate": [
			"stabler.api.crm.validate_crm_deal_hygiene",
			"stabler.api.tender_master.validate_deal_parent_tender",
		],
	},
	"Sales Invoice": {
		"before_validate": [
			# Guard first — fail fast before diag/validation runs.
			"stabler.api.desk_write_guard.assert_write_via_stabler",
			"stabler.api._accounts.validate_sales_invoice",
			"stabler.api.dimensions_hook.apply_dimensional_qty",
			"stabler.api._diag.on_txn_validate",
		],
		"validate": [
			"stabler.api.period_close.enforce_on_validate",
			"stabler.customer_hooks.check_sales_invoice_credit_limit",
			"stabler.api.valuation_guard.check_incoming_rate_currency",
		],
		"before_submit": [
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
		"before_update_after_submit": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_cancel": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_submit": [
			"stabler.integrations.ehf.hooks.enqueue_ehf_submit",
			"stabler.integrations.one_c.hooks.enqueue_push",
			"stabler.integrations.factura.export.enqueue_export",
			"stabler.maintenance.close_billed_so.on_si_submit",
		],
	},
	"Purchase Invoice": {
		"before_validate": [
			"stabler.api._accounts.validate_purchase_invoice",
			"stabler.api.dimensions_hook.apply_dimensional_qty",
			"stabler.api._diag.on_txn_validate",
		],
		"validate": [
			"stabler.api.period_close.enforce_on_validate",
			"stabler.api.valuation_guard.check_purchase_invoice_rates",
		],
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
	},
	"Purchase Order": {
		"before_validate": [
			"stabler.api.dimensions_hook.apply_dimensional_qty",
			"stabler.api._diag.on_txn_validate",
		],
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
	},
	"Sales Order": {
		"before_validate": [
			# Guard first — fail fast before diag/validation runs.
			"stabler.api.desk_write_guard.assert_write_via_stabler",
			"stabler.api.dimensions_hook.apply_dimensional_qty",
			"stabler.api._diag.on_txn_validate",
		],
		"before_update_after_submit": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_cancel": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
	},
	"Delivery Note": {
		"before_validate": [
			# Guard first — fail fast before diag/validation runs.
			"stabler.api.desk_write_guard.assert_write_via_stabler",
			"stabler.api._diag.on_txn_validate",
		],
		"validate": [
			"stabler.api.valuation_guard.check_incoming_rate_currency",
		],
		"before_update_after_submit": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_cancel": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
	},
	"Purchase Receipt": {
		"before_validate": [
			"stabler.api._diag.on_txn_validate",
		],
		"before_submit": [
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
	},
	"Payment Entry": {
		"before_validate": [
			# Guard first — fail fast before diag/validation runs.
			"stabler.api.desk_write_guard.assert_write_via_stabler",
			"stabler.api.fx_balance.auto_balance_fx_residual",
			"stabler.api._diag.on_txn_validate",
		],
		"validate": [
			"stabler.api._accounts.validate_payment_entry",
			"stabler.api.period_close.enforce_on_validate",
		],
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
		"before_update_after_submit": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_cancel": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_submit": [
			"stabler.integrations.one_c.hooks.enqueue_push",
		],
	},
	"Journal Entry": {
		"before_validate": [
			# Guard first — fail fast before diag/validation runs.
			"stabler.api.desk_write_guard.assert_write_via_stabler",
			"stabler.api.fx_balance.auto_balance_fx_residual",
			"stabler.api._diag.on_txn_validate",
		],
		"validate": [
			"stabler.api._accounts.validate_journal_entry",
			"stabler.api.period_close.enforce_on_validate",
		],
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
		"before_update_after_submit": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_cancel": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
	},
	# Stock Reconciliation / Bank Transaction / Supplier have no other Stabler
	# doc_events — these blocks exist only to carry the desk-write guard.
	"Stock Reconciliation": {
		"before_validate": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_update_after_submit": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_cancel": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
	},
	"Bank Transaction": {
		"before_validate": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_update_after_submit": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"before_cancel": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
	},
	"Supplier": {
		"before_validate": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
	},
	"Stock Entry": {
		"before_validate": [
			"stabler.api._diag.on_txn_validate",
		],
		"validate": [
			"stabler.api.period_close.enforce_on_validate",
		],
		"on_submit": [
			"stabler.integrations.one_c.hooks.enqueue_push",
		],
	},
	# Imports-module status automation. Each handler self-gates on the migration
	# flag + per-company enable_imports toggle (critique M6), so these are inert
	# on the other tenants of the shared bench.
	"Commercial Invoice": {
		"on_update": [
			"stabler.stabler.imports_module.hooks.on_commercial_invoice_update",
		],
	},
	"Import Container": {
		"on_update": [
			"stabler.stabler.imports_module.hooks.on_container_update",
		],
	},
	"Import Truck": {
		"on_update": [
			"stabler.stabler.imports_module.hooks.on_truck_update",
		],
	},
	# Import Expense: on_update create a DRAFT service Purchase Invoice for a
	# non-transport expense with a supplier + amount (transport expenses are billed
	# by the truck CROSSED_BORDER hook via the 3-tier lookup). Self-gated on the
	# migration flag + per-company enable_imports toggle (critique M6).
	"Import Expense": {
		"on_update": [
			"stabler.stabler.imports_module.hooks.import_expense_on_update",
		],
	},
	# GRN Checklist (submittable): received-kg + vet-cert gates before submit,
	# DRAFT Landed Cost Voucher build on submit. Both self-gate on the migration
	# flag + per-company enable_imports toggle (critique M6).
	"GRN Checklist": {
		"before_submit": [
			"stabler.stabler.imports_module.hooks.grn_before_submit",
		],
		"on_submit": [
			"stabler.stabler.imports_module.hooks.grn_on_submit",
		],
	},
	# Truck Receipt (submittable): freeze packing before submit; on submit create +
	# submit the partial Purchase Receipt, recompute the parent GRN, and advance the
	# truck; on cancel block while the PR is live, then recompute the GRN.
	"Truck Receipt": {
		"before_submit": [
			"stabler.stabler.imports_module.hooks.truck_receipt_before_submit",
		],
		"on_submit": [
			"stabler.stabler.imports_module.hooks.truck_receipt_on_submit",
		],
		"on_cancel": [
			"stabler.stabler.imports_module.hooks.truck_receipt_on_cancel",
		],
	},
	# Single-level customer parent/child hierarchy (plan §2 K2). Self-gates on the
	# custom_parent_customer field being present + set, so it is inert on tenants
	# without the Custom Field.
	"Customer": {
		"before_validate": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
		"validate": [
			"stabler.customer_hooks.validate_hierarchy",
		],
		"on_trash": [
			"stabler.api.desk_write_guard.assert_write_via_stabler",
		],
	},
	"Work Order": {
		"on_submit": [
			"stabler.api.manufacturing.create_material_request_for_tomorrow_wo",
		],
	},
}

custom_fields = {
	"CRM Lead": [
		dict(fieldname="custom_manzil", fieldtype="Data", label="Manzil", insert_after="mobile_no"),
		dict(fieldname="custom_sana", fieldtype="Date", label="Sana", insert_after="custom_manzil"),
		dict(fieldname="custom_izoh", fieldtype="Long Text", label="Izoh", insert_after="custom_sana"),
	],
	"Item": [
		dict(
			fieldname="custom_ikpu_code",
			fieldtype="Data",
			label="IKPU / MXIK Code",
			insert_after="item_group",
			description="Uzbek product classification code (tasnif.soliq.uz) — required by Didox for e-invoicing",
		),
	],
}
