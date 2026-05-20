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
