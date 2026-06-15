"""Uzbek POS payment gateways (Payme, Click, Uzum Bank).

A thin, provider-specific webhook layer on top of a single shared state
machine (the POS Payment Session doctype). The POS SPA creates a session and
shows a dynamic QR; the customer scans and pays in their bank app; the
provider calls our webhook; we finalize the session and materialize the POS
Sales Invoice from the cart snapshot.

Webhook endpoints (configure these URLs in each provider's merchant cabinet):

  Payme : POST /api/method/stabler.integrations.uzpay.payme.merchant_endpoint
  Click : POST /api/method/stabler.integrations.uzpay.click.merchant_endpoint
  Uzum  : POST /api/method/stabler.integrations.uzpay.uzum.merchant_endpoint

Secrets live in site_config.json (frappe.conf), never in the database. See
stabler/integrations/uzpay/README.md for the full key list.
"""
