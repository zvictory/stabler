# Stabler — Denetim ve Eleştiri Raporu (audit_critique.md)

**Tarih:** 04.07.2026 · **Rol:** CPO & Enterprise Systems Architect (Critique Team)
**Kapsam:** Salt-okuma denetimi — 16 modül, ~189 Vue bileşeni, ~310 Python dosyası, 485 whitelisted endpoint, patches, hooks, görevler.
**Hedef kalibre:** QuickBooks Enterprise / NetSuite.

---

## 0. Yönetici Özeti

Stabler'ın çekirdek mimarisi sağlam: optimistic locking (`check_concurrency`), şirket bazlı satır-seviyesi izolasyon (permission_query_conditions), Decimal tabanlı bordro motoru, idempotent CBU kur senkronu ve disiplinli tarih/para bileşen standardı mevcut. Ancak NetSuite kalibresine giden yolda **3 kritik güvenlik/veri bütünlüğü açığı**, **5 kritik finansal hassasiyet hatası** ve **~45 dosyaya yayılmış merkezi status kuralı ihlali** tespit edildi. Frontend test kapsamı **%0**.

**Genel puan: 6.5/10** — tek lokasyonlu perakende/dağıtım KOBİ'leri için üretime uygun; üretim (manufacturing), konsolidasyon ve regüle sektörler için henüz değil.

### ⚠ Standart Çelişkisi (önce bunu netleştirin)
Talimatta "tüm tarih alanları **Flatpickr** + **dd/mm/yyyy**" denmiş. Kod tabanında **Flatpickr hiç yok**. Fiili ve belgelenmiş standart (CLAUDE.md): `DateInput.vue` bileşeni + `formatDate()` ile **dd.mm.yyyy** (`composables/date.js:4-5,17-48`). Kod bu standarda büyük ölçüde uyumlu. Karar gerekli: (a) mevcut DateInput/dd.mm.yyyy standardı resmileşir (önerilen — 189 bileşende tutarlı), veya (b) Flatpickr + dd/mm/yyyy'ye göç edilir (yüksek maliyet, düşük getiri). Bu rapor fiili standardı esas alır.

Benzer şekilde "shop/catalog dinamik katalog sayfası" kuralı SPA'da karşılık bulmuyor; katalog/vitrin `stable-erp-website/` (Next.js pazarlama sitesi) tarafında yaşıyor. ERP SPA'sında marka/üretici standalone filtre sayfası tespit edilmedi — kural şu an ihlal edilmiyor ama ERP tarafında bir "catalog" yüzeyi de yok.

---

## 1. Kritik Bulgular (P0 — derhal)

### 1.1 `list_customers` — izin kontrolü olmayan ham SQL (veri sızıntısı / IDOR)
- **Dosya:** `stabler/api/sales.py:73-96` (ayrıca `get_customer_defaults` ~:100)
- **Sorun:** `_assert_company_scope` yalnızca `company` argümanını doğruluyor; `frappe.has_permission("Customer", "read")` kontrolü yok ve ham SQL, Frappe'nin `permission_query_conditions` katmanını tamamen baypas ediyor. Kısıtlı kullanıcı tüm müşteri master datasını (telefon, e-posta dahil) çekebilir.
- **Fix:** Endpoint başına `frappe.has_permission` + kullanıcının allowed-company listesini WHERE'e enjekte et; veya `frappe.get_all`'a geç (satır-seviyesi izin otomatik uygulanır). CRM/HR modüllerindeki benzer ham-SQL list endpoint'leri için tam tarama yapılmalı.

### 1.2 Request handler içinde `frappe.db.commit()` — atomiklik ihlali
- **Kapsam:** `api/` altında **78 adet** `frappe.db.commit()`; örnekler: `api/timepay_admin.py:83`, `api/crm.py:364,695,720,733,744`, `api/organization.py:307,328,354`, `api/remittance.py:396`, `api/hr_attendance.py:141`.
- **Sorun:** Frappe başarılı yanıtta zaten commit eder. Handler ortasındaki commit, sonrasında oluşan hatada **yarım kalmış işlem** bırakır (ör. status kaydedildi, log kaydedilmedi); eşzamanlı yazımlarda optimistic lock'u zayıflatır.
- **Fix:** Whitelisted handler'lardan tüm açık commit'leri kaldır; commit yalnızca scheduler/background job'larda kalsın. Kritik bölümler için `frappe.db.savepoint` + hata durumunda rollback.

### 1.3 CBU ters kur hesabı — float bölme
- **Dosya:** `stabler/tasks/cbu_rate_refresh.py:80` — `round(1.0 / float(rate), 10)`
- **Sorun:** IEEE 754 float bölmesi ile üretilen ters kur (UZS→USD) birikimli hata taşır; büyük tutarlı çapraz işlemlerde GL dengesizliğine dönüşür.
- **Fix:** `from decimal import Decimal; (Decimal("1") / Decimal(str(rate))).quantize(Decimal("1E-10"), ROUND_HALF_UP)`.

### 1.4 Ödeme tahsis toleransı para birimi-körü
- **Dosyalar:** `api/money.py:1080` ve `:1404` (`total_allocated > party_amount + 0.005`), `api/hr_pay.py:199`; ayrıca `0.005` sabiti 8+ dosyada dağınık (`dashboard.py:83`, `export.py:368`, `hr_finance.py:142,195`, `employee_advance.py:137`…).
- **Sorun:** 0.005 toleransı 2-ondalık varsayımıdır. UZS fiilen 0-2 ondalıkla çalışır; 0-ondalık senaryoda tolerans anlamsızlaşır, sessiz fazla-tahsise izin verir. Sabitin 8 dosyada tekrarı ayrıca bakım riski.
- **Fix:** `get_currency_precision(currency)` türevli tek merkezi `MONEY_EPSILON(currency)` yardımcı fonksiyonu; tüm karşılaştırmalar oradan.

### 1.5 Maaş tahakkuku — çift yuvarlama ile borç/alacak dengesizliği
- **Dosya:** bordro tahakkuk JE üretimi (payroll adapter/accrual yolu — `api/_payroll_adapter.py` / `_payroll_summary.py`)
- **Sorun:** Kalem bazında yuvarlanan alacaklar toplamı, yuvarlanmış toplam borçla eşleşmiyor → dönem başına 1–100 UZS fark; GL integrity taramasında sürekli gürültü üretir.
- **Fix:** "Son satır artık farkı yutar" (residual allocation) deseni: N-1 satır yuvarla, son satır = yuvarlanmış toplam − diğerleri. `_fx_residual.py`'deki mevcut Decimal deseniyle aynı yaklaşım kullanılabilir.

### 1.6 Marj hesabı — saf float çıkarma
- **Dosya:** `api/_sales_margin.py`
- **Sorun:** 100M+ UZS tutarlarda float çıkarma/precision kaybı; marj raporu kuruş seviyesinde yanlış.
- **Fix:** `flt(x, precision)` disiplini veya Decimal.

---

## 2. Orta Öncelikli Bulgular (P1)

| # | Bulgu | Dosya | Fix stratejisi |
|---|-------|-------|----------------|
| 2.1 | `crm_analytics` sınırsız sorgu — 100K+ deal'de OOM/DoS | `api/crm.py:414-446` | `limit_page_length` + arka planda ön-hesaplama, cache'ten servis |
| 2.2 | Dashboard/CoA endpoint'lerinde rate-limit yok (money.py:14'te desen zaten var, yaygınlaştırılmamış) | `api/dashboard.py:92-126`, `api/money.py:78-100` | `@rate_limit(limit=10, seconds=60)` |
| 2.3 | `patches.txt`'te `[post_model_sync]` yok; yeni kolon okuyan her patch `has_column` guard'ına muhtaç (kırılgan) | `stabler/patches.txt` | Data-mutation patch'lerini `[post_model_sync]` bölümüne taşı |
| 2.4 | SQL'e tablo adı `%` interpolasyonu (sabit ama desen tehlikeli) | `api/repost_monitor.py:26` | `frappe.get_all(_RIV, group_by="status")` |
| 2.5 | **~45 dosyada** hardcoded status→badge eşlemesi; merkezi `getStatusBadgeClass` kuralı ihlal | `public/js/pages/**` (en yoğun: sales, money, hr listeleri) | Tek sprint'lik mekanik refactor: tüm inline eşlemeleri `composables/status.js`'e taşı |
| 2.6 | Frontend test kapsamı %0 (E2E yok); backend ~%60 | `stabler/tests/` (40 modül, tümü py) | Playwright ile smoke E2E: direct-URL form load, ödeme akışı, POS satışı |
| 2.7 | Router: Reports hub rotasında `meta:{module}` eksik → direct-URL guard baypası | `public/js/router.js` | Meta ekle + `_MODULE_ROLES`'a kayıt |
| 2.8 | POS: tek yazarkasa, offline modu yok, vardiya/Z-raporu yok — perakende iddiası için zayıf | `pages/sales/` (POS sayfası) | Roadmap Faz 1 (bkz. erp_roadmap.md) |

---

## 3. Düşük Öncelikli Bulgular (P2)

- **3.1** Scheduler görevlerinde retry yok; geçici DB/e-posta hatası entegrite uyarısını sessizce düşürür — `tasks/gl_integrity.py:13-63`. Fix: 3 denemeli backoff.
- **3.2** API istemcisi yanıtın `Content-Type: application/json` olduğunu doğrulamıyor — `public/js/api/client.js:21-79`. Fix: parse öncesi header kontrolü.
- **3.3** 18 adet çıplak `<input type="number">` — çoğu adet/saat/yüzde alanı (parasal değil), ancak MoneyInput-benzeri bir `QtyInput` standardı yok; birim tutarlılığı için önerilir.
- **3.4** 2 adet `<input type="datetime-local">` kenar durumu (DateInput kapsamı dışında) — DateTimeInput varyantı eklenmeli.
- **3.5** Erişilebilirlik: aria etiketleri kısmi, ⌘K placeholder'ı var ama odak-yönetimi/klavye navigasyonu sistematik değil. WCAG AA hedefli ayrı audit önerilir.
- **3.6** POS ekranında birkaç hardcoded hex renk — tasarım token'larına (CSS variables) taşınmalı.
- **3.7** i18n: örneklenen sayfalarda t() disiplini iyi; yeni sayfalarda harvest çalıştırılmadan merge edilen stringler için CI kontrolü yok. Fix: PR pipeline'ına `harvest --check` adımı.

---

## 4. UI/UX Eleştirisi (Modern Luxury Minimalism değerlendirmesi)

**Güçlü yanlar (korunmalı):** Desk'e sıfır kaçış (kural %100 uygulanmış), global striped table, monospace para hücreleri, SkeletonRows ile boşlukta spinner yasağı, auto-apply filtreler, dd.mm.yyyy tutarlılığı. Bu disiplin QuickBooks'un üzerinde, NetSuite ile kıyaslanabilir bir tutarlılık zemini.

**Eleştiriler:**

1. **Status renk dili parçalı (en büyük estetik borç).** ~45 sayfadaki inline badge eşlemeleri aynı durumun modülden modüle farklı renkte görünmesine yol açıyor. "Luxury minimalism" her şeyden önce tutarlılıktır; bu, 2.5'in çözümüyle birlikte kapanır.
2. **Veri yoğunluğu yönetimi listelerde iyi, formlarda değil.** Uzun formlar (fatura, bordro) dikey tek kolon akıyor; NetSuite sınıfı için bölüm bazlı kart/accordion gruplaması ve kalıcı özet paneli (sticky totals) gerekli.
3. **POS ekranı "minimal" ama "lüks" değil.** Dokunmatik hedef boyutları, ürün grid'i görsel hiyerarşisi ve ödeme adımı mikro-etkileşimleri (miktar pedi, hızlı ödeme kısayolları) rakip POS'ların (Square, Loyverse) gerisinde.
4. **Boş durumlar (empty states) pasif.** Çoğu liste "kayıt yok" ile bitiyor; ilk-kullanım anında CTA'lı, illüstrasyonlu boş durumlar (public/illustrations zaten mevcut!) onboarding hissini büyütür.
5. **Rapor sayfalarında ListToolbar atlanmış (13 sayfa).** Bilinçli ise belgelenmeli; değilse filtre deneyimi tutarsız kalıyor.
6. **Klavye-öncelikli kullanım eksik.** ⌘K vaadi placeholder'da var; global command palette, satır içi kısayollar (yeni kayıt N, kaydet ⌘S) yok. Muhasebeci persona'sı için kritik verimlilik boşluğu.

---

## 5. Mimari Değerlendirme (ERPNext v16 / ölçeklenebilirlik)

**Uyumlu:** v16 doc_events sıralaması doğru (`desk_write_guard` → diag → validation), Password field'lar şifreli, secrets site_config'te, CSRF token + same-origin credentials doğru, kullanıcı girdisi SQL'de parametrik (1.1 ve 2.4 istisna).

**Darboğazlar (NetSuite ölçeğinde):**

- Analitik/dashboard endpoint'leri istek anında agregasyon yapıyor; ön-hesaplanmış özet doctype + cache invalidation deseni yok. 1M+ GL satırında dashboard açılışı worker'ı kilitler.
- Rapor üretimi senkron; büyük exportlar (professional-excel-export) request thread'inde. Uzun raporlar background job + progress + indirme linki desenine taşınmalı.
- `frappe.cache` kullanımı seyrek; kur, CoA, modül-harita gibi sıcak veriler her istekte DB'den.
- Çoklu-şirket izolasyonu hooks ile sağlam, ancak ham SQL kullanan her yeni endpoint bu korumayı deler (1.1'in genelleştirilmiş hali). **Kural önerisi:** api/ altında ham SQL'e lint-gate — `permission_query_conditions` uygulamayan SELECT'ler PR'da reddedilir.

---

## 6. Doğrulama Notu

Kritik bulgular (1.1, 1.2, 1.3, 1.4) bu denetim sırasında kaynak üzerinde satır satır doğrulanmıştır; commit sayımı (78) `grep` ile teyitlidir. Flatpickr yokluğu tüm `public/js` üzerinde doğrulanmıştır. Ajan raporlarından gelen ve satır bazında yeniden teyit edilmeyen bulgular (1.5, 1.6, 3.x'in bir kısmı) uygulama öncesi ilgili dosyada teyit edilmelidir.

**Hiçbir kod değiştirilmemiştir. Tüm düzeltmeler onayınıza tabidir.**
