# Critique Raporu — MSAERP → Stabler Migration Planı v1

**Tarih:** 2026-07-09 · **İnceleyen:** Critique ajanı (Frappe mimarı + veri migration uzmanı + finans kontrolörü rolleri) · **Sonuç:** Yön doğru (~%80), plan v1 haliyle uygulanamaz — 5 BLOCKER çözülmeden Faz 1 başlamamalı. Plan v2'de tüm maddeler işlendi.

## BLOCKER

**B1 — Müşteri parent/child varsayımı TERSİNE.** Tarihsel Sales Invoice'lar ERPNext'te **parent party üzerine** kesiliyor, child sadece `custom_child_reference` etiketi (client.py:574-587); ödemeler yalnız parent seviyesinde (client.py:616-618). Üstelik iki çelişkili sync yolu var: bulk push children'ı gerçek Customer yaparken (push.py:225-288), canlı CRUD yolu child'ı local-only bırakıyor (views_customers.py:708). Child'ları gün-1'de gerçek party yapmak per-child AR/ekstre/kredi kontrolünü sessizce bozar; submitted SI'lar yeniden party'ye bağlanamaz. → Faz 0'da ERPNext Customer/SI envanteri; ekstre+kredi formülü `(customer=child) OR (customer=parent AND custom_child_reference=child_code)` UNION'u.

**B2 — Dual-pricing maskesi yanlış alanı koruyor.** ERPNext native `rate/amount/grand_total` = **agreed** (gerçek) fiyat (backfill_erpnext_native_agreed.py, invoicing.py:131-148); perm_level custom alanları gizler ama agreed, GL/party ledger/print/raporların her yerinde. Accounts rolü agreed'i her zaman görür — bu yapısal, kabul edilip imzalanmalı; maske yalnız `custom_docs_*`+`cash_difference` için gerçekçi.

**B3 — ETL, iş hook'larını tetikleyip belge çiftler.** Tarihsel dokümanlar migrate edilirken on_submit hook'ları (PO/PI/PR/LCV/PE üretimi) çalışırsa çift kayıt + çift stok. → `frappe.flags.in_msaerp_migration` guard'ı her imports hook'unda; var olan ERPNext dokümanları regenerate edilmez, MSAERP Ref ile bağlanır.

**B4 — Django read-only mekanizması YOK.** settings.py'da böyle bir middleware yok; ayrıca django-q görevleri ve sinyaller arka planda ERPNext'e yazmaya devam eder. → Gerçek freeze: DB kullanıcısını SELECT-only'ye indir, django-q cluster durdur, eski ERPNext'te Django API token'ını iptal et, webhook'ları kapat.

**B5 — K1=A çift-kaynak cutover problemi.** Staging restore bayatlar; cutover'da taze `bench restore` + `bench migrate` (MSA ERPNext sürümü bilinmiyor — v14/v15 ise upgrade mayınları) + stabler patch'leri + **tüm ETL** tek hafta sonunda. Custom field çakışmaları (custom_docs_*, custom_parent_customer zaten site'ta) idempotent patch'lerle. Dry-run #2/#3 bu tam zinciri süreyle ölçmeli.

## MAJOR (özet — plan v2'de işlendi)

M1 SRE draft-SI'ı desteklemez → rezervasyon Sales Order'da. M2 CI-aşamasında PR'a linkli PI kronolojik imkânsız → PI, PR'dan sonra (billing follows receipt); İran varışı = PO'ya avans PE. M3 Link alanları child-row hedefleyemez → allocation'lar standalone doctype + MSAERP Ref child satırları da kapsar (4.194 CILineItem!). M4 ETL eksikleri: Warehouse, File/attachment'lar (BL/foto — gümrük denetim evrakı!), User'lar, PriceList, VendorBill; Container↔GRN dairesel FK ikinci geçiş. M5 Container/CI/Truck submittable olmamalı (haftalarca mutasyon; 30+ allow_on_submit anti-pattern) → statü alanlı operasyonel doc. M6 22 kiracı: her imports hook'u `enable_imports` toggle kontrolüyle başlamalı. M7 tek-PR modeli bozulabilir malda stoku geciktirir → **PR per TruckReceipt** (partial receipt native). M8 `total_landed_cost_usd` product_cost içeriyor → LCV'de çift kapitalizasyon; product+CIF hariç tutulur; tek period-close rejimi seçilir. M9 kredi kontrol: para birimi çevrimi + B1 union formülü + native credit check ile çakışma kararı. M10 takvim %30-40 iyimser → 18-22 hafta.

## MINOR
m1 CIExpense CI+Truck çift linki (Dynamic Link tek hedef) → düz Link'ler. m2 container_number unique değil (732 satır) → naming series. m3 GRN prod geçmişi yok (3 kayıt) → senaryo bazlı doğrulama. m4 bakiye doğrulaması Django property'sine değil ERPNext party outstanding'e karşı. m5 mapping doctype adı `stabler_msaerp_ref`. m6 custom_ikpu_code zaten hooks'ta var (backfill yeter); MSA restore'daki mevcut custom field'lara karşı idempotency. m7 eşit-split kuralı PE-level hook'ta da. m8 312 URL→18 sayfa sıkıştırması: desk fallback YOK, kullanıcı anketi Faz 0'a. m9 Currency Exchange tarih çakışması önceliği tanımla. m10 rollback point-of-no-return: ilk canlı SI'dan sonra tar-restore yok.
