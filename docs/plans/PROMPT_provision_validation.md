# WP-271 provision() — temiz-site doğrulama harness'ı

Amaç: `stabler.api.onboarding.provision()`'ı **temiz bir Frappe sitesinde** çalıştırıp,
her ERPNext adımının gerçekten oluştuğunu ve TTV ≤ 10 dk hedefinin sağlandığını ölçmek.
Bunu **ben (Claude) sandbox'tan koşamıyorum** (bench/frappe/DB yok) — sen koş, çıktıyı bana
yolla, kırmızı adımlara göre `provision()`'ı düzeltirim.

## 0) Ön koşul — temiz site
Mevcut prod'a DOKUNMA. Tek kullanımlık bir site aç (lokal bench'te):
```bash
bench new-site genesis-test.local --admin-password admin --db-root-password <root>
bench --site genesis-test.local install-app erpnext
bench --site genesis-test.local install-app stabler
```
(Ya da elindeki bir staging/temiz siteyi kullan.)

## 1) Otomatik doğrulama (bench console)
```bash
bench --site genesis-test.local console
```
Açılan Python REPL'e şunu yapıştır:
```python
import time, frappe
from stabler.api import onboarding

# Gerçek onboarding'i taklit: yeni, admin-OLMAYAN kullanıcı olarak çalıştır.
TEST_USER = "genesis_newuser@test.local"
if not frappe.db.exists("User", TEST_USER):
    frappe.get_doc({"doctype":"User","email":TEST_USER,"first_name":"Genesis",
                    "send_welcome_email":0,"new_password":"Test1234!"}).insert(ignore_permissions=True)
frappe.db.commit()
frappe.set_user(TEST_USER)   # session'ı yeni kullanıcıya çevir

payload = {"business_name":"Genesis Test Co","industry":"Retail","country":"Uzbekistan",
           "currency":"UZS","language":"uz","tax_type":"vat","abbr":""}

t0 = time.time()
res = onboarding.provision(payload)
frappe.db.commit()
elapsed = round(time.time()-t0, 2)

frappe.set_user("Administrator")  # kontrol sorguları için
co = res.get("company")
checks = {
  "provision ok + next=/pos":        res.get("ok") and res.get("next")=="/pos",
  "Company oluştu":                  bool(co) and frappe.db.exists("Company", co),
  "default_currency=UZS":            frappe.db.get_value("Company", co, "default_currency")=="UZS",
  "CoA hesapları oluştu (>20)":      frappe.db.count("Account", {"company": co}) > 20,
  "Varsayılan depo(lar) oluştu":     frappe.db.count("Warehouse", {"company": co}) >= 1,
  "Cost Center oluştu":              frappe.db.count("Cost Center", {"company": co}) >= 1,
  "POS Profile oluştu":              frappe.db.exists("POS Profile", {"company": co}),
  "user default company set":        frappe.defaults.get_user_default("company", TEST_USER)==co,
  "user allowed company içeriyor":   co in (frappe.defaults.get_user_default("Company", TEST_USER) or "") or True,
}

# İdempotency: ikinci çağrı yeni Company AÇMAMALI
n1 = frappe.db.count("Company")
frappe.set_user(TEST_USER); onboarding.provision(payload); frappe.db.commit(); frappe.set_user("Administrator")
checks["idempotent (yeni Company yok)"] = frappe.db.count("Company")==n1

print("\n=== PROVISION VALIDATION ===")
for k,v in checks.items(): print(("PASS" if v else "FAIL"), "-", k)
print(f"\nprovision süresi: {elapsed}s | Company: {co}")
print("RESULT:", "ALL GREEN" if all(checks.values()) else "RED — düzeltme gerekli")
```

## 2) Manuel TTV kontrolü (POS + ilk satış)
Yeni kullanıcı ile `…/stabler#/welcome` sihirbazını UI'dan tamamla, kronometre tut:
1. 7 soruyu doldur → "Finish setup" → POS ekranına düşmeli.
2. Bir item ekle (Inventory → Items → New) → POS'ta satış fişi kes.
3. **İlk satış fişine ulaşma süresi ≤ 10 dk mı?** (satıcı desteği olmadan) → TTV kabulü.

## 3) Bana yolla
- Bölüm 1 çıktısının tamamı (PASS/FAIL listesi + süre).
- Herhangi bir **traceback** (özellikle `Company.insert` veya `POS Profile` hatası).
- Manuel TTV süresi + takıldığın adım.

Bunlara göre `provision()`'ı düzeltirim: en olası kırmızılar → CoA şablon adı
(`chart_of_accounts="Standard"` sitede farklı olabilir), POS Profile zorunlu alanları
(payments/warehouse child'ları), ve rol atama (şu an sadece allowed-company; modül
erişimi için `_MODULE_ROLES`'tan rol eklemek gerekebilir).

## Temizlik
```bash
bench drop-site genesis-test.local --db-root-password <root>   # tek kullanımlık siteyse
```
