# Kassa serisi (WP-K1…K3) — Kurulum & Verify Runbook (Mikas)

Scope: **local + Mikas** (`mikas.erpstable.com`). Kod `enable_tender`/`money`
gate'leri dışında davranış değiştirmez; bot config'i olmayan sitelerde webhook
fail-closed reddeder, diğer 5 tenant etkilenmez.

Ne geldi:
- **v52 patch**: `Journal Entry.custom_crm_deal` (tender etiketi).
- **money.submit_expense_entry(deal=…)** + `list_bank_entries.crm_deal`.
- **Expenses.vue**: tender modülü açık şirkette opsiyonel "Tender (Deal)"
  typeahead + listede deal chip'i.
- **Stabler Kassir** doctype (+ child `Stabler Kassir Account`).
- **Telegram bot köprüsü**: `stabler/integrations/kassa/` — Whimsical menüsü
  (Kirim / Chiqim / Konvertatsiya / Kassadan kassaga / Qolib ketgan amal /
  Mening jadvalim / Bekor qilish) → mevcut money.py endpoint'leri,
  kassir kullanıcısı adına (impersonation) → tüm yetki/onay/backdating
  kuralları aynen uygulanır.

---

## 1. Migrate + build + test (local)

```bash
cd /Users/zafar/frappe-bench-local
bench --site "$SITE" migrate          # v52: JE custom_crm_deal
bench build --app stabler             # Expenses.vue

cd apps/stabler
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_flow   # 33 test
```

Spot-check:

```bash
bench --site "$SITE" mariadb -e "SELECT fieldname FROM \`tabCustom Field\` WHERE dt='Journal Entry' AND fieldname='custom_crm_deal';"
bench --site "$SITE" mariadb -e "SELECT name FROM tabDocType WHERE name LIKE 'Stabler Kassir%';"
```

## 2. WP-K1 — CoA kassa ağacı (veri işi, kod yok)

Mikas şirketinde `/stabler#/money/accounts` üzerinden (veya create_account):

```
Kassalar (Group, parent: Current Assets / Cash In Hand)
├─ AKassa (Group)
│  ├─ AKassa Naqd UZS      (Cash, UZS)
│  ├─ AKassa Plastik Karta (Cash, UZS)
│  └─ AKassa Naqd USD      (Cash, USD)
├─ QKassa … (aynı üçlü)
├─ SKassa … / TKassa … / Admin kassaları …
```

Kural: bot yalnız **yaprak** Cash hesaplarını kullanır; kassa grubu =
yaprakların parent'ı (bot menüsündeki "kassa" adı = parent account_name).

## 3. WP-K3 — bot konfigürasyonu

1. BotFather'dan bot aç (örn. `mikas_kassa_bot`), token'ı al.
2. `sites/<site>/site_config.json`:

```json
{
  "kassa_telegram_token": "<bot token>",
  "kassa_telegram_secret": "<uzun rastgele secret>"
}
```

3. Webhook'u kaydet (secret ZORUNLU — yoksa endpoint fail-closed reddeder):

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://mikas.erpstable.com/api/method/stabler.integrations.kassa.webhook.telegram_webhook" \
  -d "secret_token=<kassa_telegram_secret>"
```

4. Her kassir için **Stabler Kassir** kaydı (System Manager, Desk'e gerek yok —
   bench console veya ileride SPA admin sayfası):
   - `telegram_user_id`: kassirin Telegram id'si (bot'a `/start` yazınca
     Error Log'a düşen "unknown id" mesajından da alınabilir)
   - `user`: Stabler kullanıcısı — **yetkiler bu kullanıcıdan gelir**
   - `company`: MIKAS şirketi
   - `accounts`: yetkili YAPRAK cash hesapları (örn. AKassa üçlüsü)

## 4. Browser/bot smoke — Whimsical arc'ı

1. Bot'a `/start` → kassa seçim klavyesi (yalnız yetkili kassalar).
2. **Chiqim**: alt-kassa → kategori → (tender modülü açıksa) Deal seç →
   tutar `2 000 000` → izoh → ✅ Tasdiqlash. Cevap: JE adı; eşik üstüyse
   "⏳ Tasdiqqa yuborildi" (maker-checker kuyruğu `/money/approvals`).
3. **Konvertatsiya**: "USD oldim" senaryosu — hedef USD yaprağı, kaynak UZS
   yaprağı, alınan $ / verilen so'm → JE çift bacak, CBU anchor.
4. **Kassadan kassaga**: aynı para birimli hedef listesi; JE = iç virman.
5. **Qolib ketgan amal**: `05.07.2026` → sıradaki TEK işlem o tarihle yazılır,
   sonra bugüne döner; donmuş dönemse ERPNext zaten insert'te reddeder.
6. **Mening jadvalim**: yaprak başına bakiye + son 5 hareket
   (= `/money/accounts/<acc>/ledger` verisi).
7. SPA doğrulaması: `/stabler#/money/expenses` listesinde kayıt + deal chip;
   `/stabler#/money/accounts/<AKassa Naqd UZS>/ledger` yürüyen bakiye.
8. Tender P&L beslemesi (WP-K4, ayrı iş): `custom_crm_deal` etiketli JE'ler
   `_actual_block`'a henüz akmıyor — bu runbook kapsamı dışı.

## 5. Güvenlik notları

- Webhook **fail-closed**: `kassa_telegram_secret` yoksa/yanlışsa 403; token
  ve secret asla loglanmaz (uzex WP-308 kalıbı).
- Bot **hiçbir kuralı bypass etmez**: her çağrı `frappe.set_user(kassir.user)`
  altında → company scope, maker-checker onayı, backdating freeze aynen işler.
- Bilinmeyen Telegram id → "Ruxsat yo'q" + Error Log kaydı.

## 6. Rollback

- Bot'u durdur: `deleteWebhook` veya site_config'ten token/secret'i sil
  (fail-closed olduğundan secret silmek yeter).
- v52 alanı veri taşımaz-sa zararsızdır; gerekirse Custom Field
  `Journal Entry.custom_crm_deal` silinebilir (etiketler kaybolur).
- Prod deploy: CLAUDE.md prosedürü (backup tar → rsync → build → migrate →
  restart; restart 6 tenant'ı bliplet — düşük trafikte).
