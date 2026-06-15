# Uzbek POS Payment Gateways (Payme · Click · Uzum Bank)

Dynamic-QR online payments for the Stabler POS (`/stabler/#/pos`). The cashier
picks an online payment mode, the SPA shows a QR, the customer scans and pays in
their bank app, the provider calls our webhook, and the POS Sales Invoice is
created automatically — all inside Stabler, no Frappe Desk.

## Flow

```
Cashier builds cart ──▶ picks "Payme/Click/Uzum" mode ──▶ Take Payment
        │
        ▼
pos_gateway_start ──▶ creates POS Payment Session (Pending) + checkout URL + QR
        │                         (NO invoice yet — cart snapshot is stored)
        ▼
SPA shows QR, polls pos_gateway_status every 2.5s
        │
customer pays ──▶ provider webhook ──▶ finalize ──▶ POS Sales Invoice (paid)
        │                                              + session = Paid
        ▼
SPA poll sees "Paid" ──▶ success ──▶ cart cleared
```

The Sales Invoice is only created **after** the provider confirms payment, so an
abandoned/expired QR never produces an invoice. Finalization reuses the same
`build_paid_pos_invoice` path as the cash flow, so stock, pricing and GL match.

## Webhook URLs (register these in each provider's merchant cabinet)

| Provider   | URL |
|------------|-----|
| Payme      | `https://anjan.erpstable.com/api/method/stabler.integrations.uzpay.payme.merchant_endpoint` |
| Click      | `https://anjan.erpstable.com/api/method/stabler.integrations.uzpay.click.merchant_endpoint` |
| Uzum Bank  | `https://anjan.erpstable.com/api/method/stabler.integrations.uzpay.uzum.merchant_endpoint` |

All three are `allow_guest=True`. Authenticity is enforced per provider:
Payme = HTTP Basic (`Paycom:<key>`), Click = MD5 `sign_string`, Uzum = HTTP Basic
(username/password).

## Configuration — secrets go in `site_config.json`, never the DB

```jsonc
// sites/anjan.erpstable.com/site_config.json
{
  // ---- Payme (Paycom) ----
  "payme_merchant_id": "xxxxxxxxxxxxxxxxxxxxxxxx",
  "payme_key": "PROD_MERCHANT_KEY",
  "payme_test_key": "TEST_MERCHANT_KEY",
  "payme_test_mode": 1,                 // 1 = test host + test key; remove/0 for prod
  "payme_account_field": "order_id",    // must match the account field in the cabinet

  // ---- Click (SHOP API) ----
  "click_service_id": "12345",
  "click_merchant_id": "6789",
  "click_secret_key": "CLICK_SECRET_KEY",
  "click_merchant_user_id": "54321",

  // ---- Uzum Bank ----
  "uzum_service_id": "111222",
  "uzum_merchant_username": "MERCHANT_USER",
  "uzum_merchant_password": "MERCHANT_PASS",
  "uzum_amount_in_tiyin": 1,
  // Adjust these to the exact field names / deep-link Uzum issues you:
  "uzum_order_field": "orderId",
  "uzum_transid_field": "transId",
  "uzum_amount_field": "amount",
  "uzum_checkout_template": "https://www.uzumbank.uz/open-service?serviceId={service_id}&orderId={order_id}&amount={amount_tiyin}"
}
```

Apply with `bench --site anjan.erpstable.com set-config ...` or by editing the
file, then `bench restart`.

> **Amounts.** Sessions store the invoice total in UZS. Payme/Uzum settle in
> **tiyin** (×100); Click settles in **soums**. Conversions are handled in
> `common.py` (`to_tiyin` / `from_tiyin`).

## In-app setup (no Desk for cashiers; admin uses Desk once)

1. **Mode of Payment** — create `Payme`, `Click`, `Uzum` (Desk → Mode of
   Payment) and give each a **default account** for the company (the clearing/
   bank account the provider settles into).
2. **Stabler Settings → POS Online Payment Gateways** — add one
   `POS Gateways` row per provider: *Company*, *Mode of Payment*, *Provider*,
   Enabled ✓. Set *POS Session TTL* (default 15 min).
3. **POS Profile** — add the same payment modes to the profile's `payments`
   table so cashiers can select them.

Once mapped, the POS automatically shows those modes with a `· Payme/Click/Uzum`
suffix and routes them through the QR modal instead of instant cash checkout.

## Deploy

```bash
bench --site anjan.erpstable.com migrate     # creates POS Payment Session +
                                             # Stabler POS Gateway doctypes
bench build --app stabler                     # ships the new SPA bundle
bench restart                                 # picks up the new .py + site config
```

`qrcode` (ships with Frappe) renders the QR as inline SVG. If it is ever
missing, checkout still works — the modal shows the tappable payment link and a
"QR unavailable" note instead of crashing.

## Operational notes

- **Idempotency.** `POS Payment Session.order_id` is UNIQUE; webhook retries are
  serialized with a row lock and re-finalization returns the existing invoice.
- **Refunds.** Payme `CancelTransaction` / Uzum `reverse` on an already-paid
  session cancels the linked Sales Invoice (reversing stock + GL). Click has no
  reverse callback — refund from the Click cabinet, then cancel the invoice in
  Stabler.
- **Reconciliation.** Payme `GetStatement` returns sessions in a time range.
  Every provider call is appended to the session's *Provider Payload Log*.
- **Expiry.** Pending sessions past their TTL flip to `Expired` on the next
  status poll (and reject late `CreateTransaction`/`Prepare`).
