# İmport zincirini Vendor Center'a bağlama — Tasarım Dokümanı

**Tarih:** 16.07.2026 · **Bağlam:** MSA (msa.erpstable.com) import operasyonu · **Durum:** Tasarım (kod yok)
**Kararlar (kullanıcı onaylı):** (1) Proforma (PI) ve Commercial Invoice (CI) **ayrı belgeler**, PI → CI takip eder. (2) Bakiye **hibrit**: 70% avans gerçek GL'de, 30% kalan sanal taahhüt (exposure); CI teslimde Purchase Invoice'a dönüp GL'yi kapatır. (3) Çıktı bu doküman.
**Ek karar (16.07, netleştirme):** Her PI'nin ödeme anlaşması **nakit vs banka** olarak İKİ AYRI kısma bölünür; her kısmın ayrı taahhüdü, ayrı avans takibi (% ödendi / kalan) ve Vendor Center'da AYRI bakiyesi olur → **çift-defter** (resmi banka/GL + gölge nakit/kayıt-dışı).

---

## 1. Mevcut durum (kod üzerinde doğrulandı, 16.07.2026)

**Zincir yapısal olarak bağlı ama finansal olarak Vendor Center'a kör.**

Doctype topolojisi:
```
Import PI Group (title, company, status)         ← sadece gruplama zarfı; supplier YOK
   └─ Commercial Invoice (supplier✓, ci_number, agreed_total, docs_total,
        cash_difference, currency, incoterm, 10 lojistik durumu)
         ├─ Commercial Invoice PO Link (CI ↔ Purchase Order, allocated_qty/amount)
         └─ Import Container (commercial_invoice✓, supplier✓, total_amount,
              advance_70_payment_entry → Payment Entry✓, allocated_deposit_amount,
              balance_due_amount, payment_70_status/date/amount)
Purchase Order (custom_import_pi_group linki, v41/v42 costing alanları)
Purchase Invoice (custom_commercial_invoice, custom_import_container,
   custom_import_truck, custom_import_expense — v46 vendor-trace ref'leri)  ← GL'ye yazan TEK yer
```

**Kritik boşluk:** `supplier_detail` (Vendor Center) bakiyesi yalnız `tabGL Entry` + `Purchase Invoice`'tan geliyor:
- `outstanding_by_currency`, `overdue_amount`, `lifetime_base`, `recent_invoices` → hepsi Purchase Invoice/GL.
- **CI, Import PI Group ve Container tamamen GL dışı** → vendor bakiyesinde HİÇ görünmüyor.
- 70% avans zaten `advance_70_payment_entry` (Payment Entry, GL'de) ama Vendor Center bunu import bağlamıyla ilişkilendirmiyor.

**Terminoloji çakışması:** Kodda "Proforma Invoice" doctype'ı YOK. `Commercial Invoice` hem proforma hem ticari faturayı temsil ediyor gibi. Karar (1) bunu ayırıyor.

---

## 2. Hedef veri modeli

### 2.1 Yeni: Proforma Invoice (PI) doctype
Supplier ile ilk parasal taahhüt burada doğar (CI'dan önce).
Alanlar (öneri): `pi_number`, `pi_date`, `company`, `supplier`✓, `currency`, `import_pi_group` (Link), `agreed_total`, `advance_pct` (varsayılan 70), `incoterm`, `status` (Select: `DRAFT → CONFIRMED → SUPERSEDED_BY_CI → CANCELLED`), `items` (child: item, qty, rate, amount), `remarks`.
- **PI = taahhüt belgesi.** GL'ye yazmaz; sanal exposure yaratır (§3).
- PI onaylanınca (CONFIRMED) 70% avans Payment Entry'si buradan tetiklenebilir (party = supplier).

### 2.2 Commercial Invoice PI'yi takip eder
CI'ya yeni alan: `proforma_invoice` (Link Proforma Invoice, opsiyonel ama şiddetle önerilen).
- CI oluşturulunca PI → `SUPERSEDED_BY_CI`, CI `proforma_invoice`'a PI'yi işaretler.
- Container zaten CI'ya bağlı → PI ↔ CI ↔ Container zinciri tamamlanır.
- CI, PI'nin `agreed_total`'ını devralır; fark (`cash_difference`) CI'da kalır.

### 2.3 Import PI Group'a supplier ekl(opsiyonel netlik)
Grup çok-supplier olabiliyorsa dokunma; tek-supplier ise `supplier` alanı ekleyip raporlamayı kolaylaştır. (Karar bekler — mevcut kullanım paternine göre.)

### 2.4 Link topolojisi (hedef)
```
Proforma Invoice ──(supersedes)──▶ Commercial Invoice ──▶ Import Container(lar)
      │ supplier                         │ supplier            │ advance_70_payment_entry (GL)
      │ agreed_total (taahhüt)           │ agreed/docs/cash    │ balance_due_amount (sanal)
      └──────────────┬───────────────────┴─────────────────────┘
                     ▼
        Purchase Order(lar) ──(CI PO Link)──▶ Purchase Invoice ──▶ GL / Vendor bakiyesi
                     (teslim/mal kabulünde CI → PInvoice, 30% GL'ye yazılır)
```

---

## 3. Hibrit bakiye modeli (kararın kalbi)

Supplier'ın bir import supplier'ı için toplam maruziyeti (exposure) **iki katmandan** oluşur:

| Katman | Kaynak | GL'de mi? | Nasıl hesaplanır |
|---|---|---|---|
| **A. Gerçek AP** | Purchase Invoice → GL Entry | ✅ Evet | Mevcut `supplier_detail` (değişmez) |
| **B. Ön ödeme (avans)** | Container `advance_70_payment_entry` (Payment Entry) | ✅ Evet | Party=supplier olan, henüz PInvoice'a allocate edilmemiş Payment Entry'ler → "supplier'da duran avans" |
| **C. Açık taahhüt (sanal)** | PI `agreed_total` + Container `balance_due_amount` (henüz PInvoice'a dönmemiş) | ❌ Hayır | `Σ CONFIRMED PI/CI agreed_total − ödenen avans − PInvoice'a dönen tutar` |

**Vendor Center'a yeni bölüm: "Import Exposure"** (mevcut Ledger/Orders sekmelerinin yanına):
- **Açık proformalar** (CONFIRMED PI, henüz CI olmamış) — taahhüt tutarı.
- **Yoldaki CI/Container'lar** — 70% ödendi mi (payment_70_status), 30% kalan (balance_due_amount), lojistik durumu (10 durum), ETA.
- **Toplam import exposure = B + C** (GL AP'den AYRI, "henüz faturalanmamış taahhüt" olarak etiketli).
- Her satır ilgili PI/CI/Container'a link (Desk'e değil, SPA sayfasına — CLAUDE.md Desk-yasağı).

**Yaşam döngüsü / GL kapanışı:**
1. PI CONFIRMED → C katmanına taahhüt girer (sanal).
2. 70% avans Payment Entry (party=supplier) → B katmanı; C'den 70% düşülür.
3. CI kesilir → PI SUPERSEDED; taahhüt CI'ya taşınır (miktar aynı).
4. Mal Uzbekistan'a teslim / mal kabul → CI'dan **Purchase Invoice** doğar (custom_commercial_invoice/container ref'leri v46 ile zaten var); avans Payment Entry bu PInvoice'a **allocate** edilir → B katmanı gerçek AP'ye (A) dönüşür; 30% GL'ye yazılır; C katmanından bu CI düşer.
5. Sonuç: teslim sonrası her şey standart GL AP (A) — sanal exposure sıfırlanır.

> Böylece **çift sayım olmaz**: bir tutar ya C (sanal taahhüt) ya A (gerçek AP) katmanındadır, ikisinde birden değil. Geçiş noktası = CI→PurchaseInvoice dönüşü.

### 3.1 Nakit / Banka — HER İKİSİ DE tam GL'de (16.07 netleştirmesi, DÜZELTİLMİŞ)

**Kayıt-dışı / gölge defter YOK.** Gerçek anlaşma `agreed_total`'dır ve her kuruşu resmi GL'ye girer:
- **Finansal borç (AP) = `agreed_total`** (gerçek). Purchase Invoice bu tutardan kesilir → GL Creditors.
- **`docs_total` = YALNIZCA gümrük beyan değeri** (düşük gösterilir, gümrük vergisini azaltmak için). **GL'ye / AP'ye HİÇ dokunmaz** — sadece ТН ВЭД / gümrük beyanı ve customs-cost hesabını besler. Muhasebe belgesi (agreed) ile gümrük belgesi (docs) bilinçli olarak ayrıdır.
- **Nakit vs banka = iki ayrı VARLIK hesabı**, ikisi de GL'de:
  - Nakit ödeme → **Nakit Kasa** hesabından Payment Entry (`paid_from = Kassa`) → GL: Kassa alacaklanır.
  - Banka ödeme → **Bank** hesabından Payment Entry (`paid_from = Bank`) → GL: Bank alacaklanır.
  - İkisi de standart Payment Entry → supplier'a allocate edilir. Kuruşu kuruşuna GL'de.

**İki boyut, karıştırma:**
1. **GL gerçeği:** supplier'ın tek bir AP (Creditors) bakiyesi var = `agreed_total − toplam_ödenen`. Bu tek hesap.
2. **Anlaşma earmark'ı (custom metadata):** bu borcun ne kadarı NAKİT, ne kadarı BANKA ödenmek üzere anlaşıldı + her yöntemden ne kadar ödendi. Bu, GL'nin ÜSTÜNDE bir izleme katmanı (Creditors tek hesap kalır); nakit/banka ayrımı Payment Entry'nin `paid_from` hesabından okunur.

**Her PI için tutulacak (yeni alanlar):** `bank_agreed`, `cash_agreed` (earmark; `bank_agreed + cash_agreed = agreed_total`), türetilenler `bank_paid`/`cash_paid` (ilgili Payment Entry'lerin paid_from hesabına göre), `bank_balance`/`cash_balance`, `bank_pct_paid`/`cash_pct_paid`. Avans her yöntemden ayrı Payment Entry olarak kaydedilir (tek `advance_70_payment_entry` yerine yöntem-etiketli satırlar).

**Vendor Center — tek GL AP + nakit/banka dökümü (hepsi GL'ye mutabık):**
| Gösterim | Kaynak | GL |
|---|---|---|
| **Toplam AP bakiyesi** | GL Creditors = `agreed_total − ödenen` | ✅ Gerçek GL |
| **↳ Nakit kısmı** (earmark) | `cash_agreed − cash_paid` (paid_from=Kassa) | ✅ GL'de (Kassa) |
| **↳ Banka kısmı** (earmark) | `bank_agreed − bank_paid` (paid_from=Bank) | ✅ GL'de (Bank) |
| **Import exposure** (§3, B+C) | henüz Purchase Invoice'a dönmemiş taahhüt | ❌ Sanal (faturalanınca AP'ye döner) |
| **docs_total** | gümrük beyanı | 🚫 GL dışı — muhasebe DEĞİL, sadece gümrük |

> Nakit + banka ödenen **her zaman** GL toplam ödemeye eşittir (`cash_paid + bank_paid = toplam_ödenen`) → kuruşu kuruşuna mutabık. Nakit/banka bir GÖLGE değil, aynı GL AP'nin ödeme-yöntemi dökümüdür.

**GL etkisi özeti:**
- **Purchase Order (senin "PI" karşılığın) → GL'ye SIFIR etki** (ERPNext'te PO muhasebe belgesi değil, sadece taahhüt).
- **Purchase Invoice** → AP'yi `agreed_total`'dan açar (GL Creditors). **`docs_total` buraya girmez.**
- **Payment Entry** (Kassa'dan nakit / Bank'tan banka) → GL'de varlık hesabını krediler, AP'yi kapatır.
- Sonuç: nakit de banka da tam GL'de; `docs_total` yalnız gümrük tarafında yaşar.

---

## 4. Backend değişiklikleri (WP taslağı)

| WP | İş | Bağımlılık |
|---|---|---|
| **WP-I1** | Patch: `Proforma Invoice` + `Proforma Invoice Item` doctype'ları (post_model_sync, idempotent) | — |
| **WP-I2** | Patch: CI'ya `proforma_invoice` Link alanı; PI status akışı | I1 |
| **WP-I3** | `api/imports.py`: PI CRUD + CONFIRM aksiyonu (70% avans Payment Entry taslağı, party=supplier) | I1 |
| **WP-I3b** | Patch + api: PI'ye `bank_agreed`/`cash_agreed` + yöntem-etiketli avans ödeme satırları (nakit/banka); türetilen bank/cash balance + % | I1 |
| **WP-I4** | `api/purchasing.py::supplier_detail`'e **üç ayrı bakiye**: banka (GL), nakit (gölge defter = `cash_agreed − cash_paid`), import exposure (B+C) — hiçbiri toplanmaz | I1,I2,I3b |
| **WP-I5** | CI → Purchase Invoice dönüşümünde avans allocation + exposure düşümü (mevcut v46 ref'leri kullanılır) | I4 |
| **WP-I6** | Frontend: Vendor Center'a "Import Exposure" sekmesi/kartı (Suppliers.vue) + PI/CI/Container link'leri | I4 |
| **WP-I7** | Frontend: Proforma Invoice list + form sayfaları (imports modülünde) | I3 |
| **WP-I8** | i18n (5 CSV) + guard testleri (exposure hesabı saf-Python birim testi: çift-sayım yok invariant'ı) | tümü |

**Kabul invariant'ları:**
- Bir tutar aynı anda hem `import_exposure` hem GL AP'de görünmez (çift-sayım yok) — saf birim testi.
- `bank_agreed + cash_agreed == agreed_total` her PI için (earmark denge kimliği) — saf birim testi.
- `cash_paid + bank_paid == GL toplam ödenen` (kuruşu kuruşuna GL mutabakatı; nakit de banka da GL'de) — saf birim testi.
- `docs_total` AP/GL'ye HİÇ girmez (yalnız gümrük beyanı); AP her zaman `agreed_total`'dan açılır — kontrol.
- Banka % ödendi + nakit % ödendi ayrı hesaplanır (paid_from hesabına göre); avans bir yöntemden ödenince yalnız o yöntemin bakiyesi/% değişir.
- CI→PurchaseInvoice sonrası exposure o CI için 0.
- PI/CI/Container tümü tek supplier üzerinden Vendor Center'da izlenebilir.
- Yeni endpoint'ler blueprint §2.0 sözleşmesi (has_permission + company scope).

---

## 4.1 ÇOK-TENANT GÜVENLİĞİ (sert kural — MSA'ya izole)

Stabler 6 tenant'ta ortak app kodu paylaşır. Bu iş **yalnız MSA'yı etkilemeli**:
- **`imports` modülü zaten gate'li:** `enable_imports` default `0`; `_assert_imports_access(company)` company'de kapalıysa `PermissionError`. Yeni PI/CI/exposure endpoint'leri bu gate'i AYNEN kullanır → diğer tenant'larda erişilemez.
- **Vendor Center riski:** `supplier_detail` **purchasing** modülünde (çoğu tenant'ta açık). Exposure + nakit/banka bloğu **MUTLAKA** `if module_map_for(company).get("imports"): …` arkasına alınır; değilse blok hiç hesaplanmaz ve dönüş şekli import-kapalı tenant'larda **birebir eskisi gibi** kalır.
- **Custom field/doctype'lar** tüm tenant DB'lerinde oluşur (migrate) ama pasif/boş → zararsız; `read_only=1, hidden=1` + module gate ile görünmez.
- **Kabul invariant'ı:** import-kapalı bir tenant'ta `supplier_detail` çıktısı bu işten ÖNCE ve SONRA aynı olmalı (regresyon testi: exposure anahtarları yalnız imports-açık company'de eklenir).

## 5. Riskler / açık sorular
1. **Import PI Group çok-supplier mı?** Öyleyse exposure grup değil supplier bazlı toplanır (zaten öyle planlandı). Netleştir.
2. **Avans Payment Entry party'si** kesinlikle supplier mı, yoksa şu an bir "on hesap" mı? Kod `advance_70_payment_entry` Link'i var ama party doğrulanmalı (yerel `bench` ile bir örnek container'a bak).
3. **Kur:** PI/CI genelde USD/foreign; exposure hem işlem hem base currency gösterilmeli (mevcut `outstanding_by_currency` deseni).
4. **Cost masking (K3):** exposure figürleri de `_imports_rules.py` cost-masking'ine tabi olmalı (yetkisiz kullanıcı taahhüt tutarını görmesin).
5. **Geriye dönük veri:** mevcut CI/Container'lar PI'siz — `proforma_invoice` opsiyonel bırakılır, exposure PI olmadan da CI'dan hesaplanır.

## 6. Önerilen ilk adım
WP-I4 (supplier_detail'e exposure bloğu) + WP-I8 (saf birim testi) **yeni doctype gerektirmeden** mevcut CI/Container'dan exposure'ı hesaplayıp Vendor Center'da gösterebilir — hızlı değer, çift-sayım invariant'ı burada kanıtlanır. Proforma doctype (I1-I3) ikinci dalga. Bu sıra, riski en aza indirir.

## WP-I15 (tasarım notu — implementasyon bekliyor): KTS / beyan-sonrası düzeltme
Gümrük, temizlenmiş GTD'nin kıymetini sonradan yukarı düzeltebilir (KTS) → ek boj
+ ek KDV + olası ceza. Akış önerisi: Customs Declaration'a `amendment_of` (Link,
kendi doctype'ına) + `amendment_reason`; ek boj farkı mevcut `create_additional_lcv`
ile stoğa (delta LCV), ek KDV Input VAT'a, ceza P&L gider (kapitalize EDİLMEZ,
IAS 2'de anormal maliyet). Guard: amendment yalnız cleared GTD'ye bağlanır;
orijinal GTD asla düzenlenmez (audit izi). Efor: patch(2 alan)+endpoint+test ~½ gün.
