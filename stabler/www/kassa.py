"""Controller for the /kassa Telegram Mini App page (WP-K7).

Guest-servable static shell — NO kassir/company/balance data is server-rendered
here. Everything the page shows comes from the authenticated
stabler.integrations.kassa.miniapp.kassa_summary XHR (init_data-verified),
called client-side after Telegram.WebApp.ready(). Mirrors stabler.www.stabler's
no-cache guest-shell pattern (see stabler/www/stabler.py) but intentionally
carries zero session/user context onto the page itself.
"""

no_cache = 1
no_sitemap = 1


def get_context(context):
	context.no_cache = 1
	return context
