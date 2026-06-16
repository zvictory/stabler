app_name = "stabler"
app_title = "Stabler"
app_publisher = "Stabler"
app_description = "Financial operations, simplified"
app_email = "admin@stabler.app"
app_license = "mit"

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
	"Customer": "stabler.api.permissions.master_has_permission",
	"Supplier": "stabler.api.permissions.master_has_permission",
}

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
	],
	"weekly": [
		# Two-tier backup retention pruning (gap #47).
		"stabler.api.backup.apply_retention_policy",
	],
	"hourly": [
		"stabler.integrations.one_c.hooks.hourly_sync",
	],
}

doc_events = {
	"Sales Invoice": {
		"validate": [
			"stabler.api._accounts.validate_sales_invoice",
			"stabler.api.period_close.enforce_on_validate",
		],
		"before_submit": [
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
		"on_submit": [
			"stabler.integrations.ehf.hooks.enqueue_ehf_submit",
			"stabler.integrations.one_c.hooks.enqueue_push",
			"stabler.integrations.factura.export.enqueue_export",
			"stabler.maintenance.close_billed_so.on_si_submit",
		],
	},
	"Purchase Invoice": {
		"validate": [
			"stabler.api._accounts.validate_purchase_invoice",
			"stabler.api.period_close.enforce_on_validate",
		],
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
	},
	"Purchase Order": {
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
	},
	"Purchase Receipt": {
		"before_submit": [
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
	},
	"Payment Entry": {
		"before_validate": [
			"stabler.api.fx_balance.auto_balance_fx_residual",
		],
		"validate": [
			"stabler.api._accounts.validate_payment_entry",
			"stabler.api.period_close.enforce_on_validate",
		],
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
		"on_submit": [
			"stabler.integrations.one_c.hooks.enqueue_push",
		],
	},
	"Journal Entry": {
		"before_validate": [
			"stabler.api.fx_balance.auto_balance_fx_residual",
		],
		"validate": [
			"stabler.api._accounts.validate_journal_entry",
			"stabler.api.period_close.enforce_on_validate",
		],
		"before_submit": [
			"stabler.api.approvals.before_submit_gate",
			"stabler.api.sod_enforce.assert_no_sod_conflict",
		],
	},
	"Stock Entry": {
		"validate": [
			"stabler.api.period_close.enforce_on_validate",
		],
		"on_submit": [
			"stabler.integrations.one_c.hooks.enqueue_push",
		],
	},
}
