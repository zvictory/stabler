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

scheduler_events = {
	"daily": [
		"stabler.tasks.cbu_rate_refresh.fetch_and_store",
		"stabler.tasks.roi_refresh.daily",
	],
	"hourly": [
		"stabler.integrations.one_c.hooks.hourly_sync",
	],
}

doc_events = {
	"Sales Invoice": {
		"on_submit": [
			"stabler.integrations.ehf.hooks.enqueue_ehf_submit",
			"stabler.integrations.one_c.hooks.enqueue_push",
			"stabler.integrations.factura.export.enqueue_export",
		],
	},
	"Payment Entry": {
		"on_submit": [
			"stabler.integrations.one_c.hooks.enqueue_push",
		],
	},
	"Stock Entry": {
		"on_submit": [
			"stabler.integrations.one_c.hooks.enqueue_push",
		],
	},
}
