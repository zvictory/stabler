# Fiskal Kasa (ОФД / Virtual Kassa) Entegrasyonu — Fizibilite ve Karşılaştırma Raporu

**Tarih:** 2026-08-05 · **Durum:** karar bekliyor · **Kapsam:** Stabler POS, tüm Özbekistan tenant'ları

---

## 1. Yönetici özeti

**Önerilen yol: A — kayıtlı bir Virtual Kassa (ВК) sağlayıcısının API'si üzerinden fiskalizasyon.**
Kendi ВК'mızı OFD'ye kaydettirmek (yol B) teknik olarak mümkün ama aylarca süren bürokrasi,
yıllık ödeme, sertifika yönetimi ve **yasal sorumluluğun bize geçmesi** anlamına geliyor —
7 kiracılı ortak bir uygulamada bu orantısız bir risk.

Ancak rapor sırasında yapılan iki ölçüm, işin sırasını değiştiriyor:

> **Bulgu 1 — Stabler POS bugün üretimde kullanılmıyor.**
> anjan'da **0 adet POS Profile** var, 8 POS faturasının **hepsi iptal** (docstatus=2, 29.07.2026 —
> tek günlük test), 0 POS Payment Session. Gerçek satış hacmi normal Sales Invoice üzerinden:
> **14.436 onaylı fatura** (10.03.2026 – 04.08.2026). Diğer 6 sitede POS faturası hiç yok
> (msa'da yalnızca 1 POS Profile tanımlı, kullanılmamış).
> ⇒ Kasiyerin bugün yaşadığı "çift giriş", Stabler POS ile fiskal cihaz arasında **değil**.
> Önce POS'un fiilen devreye alınması gerekiyor; fiskalizasyon onun üstüne gelir.

> **Bulgu 2 — İКПУ (MXIK) altyapısı anjan'da hiç yok.**
> `custom_ikpu_code` alanı **7 siteden yalnızca msa'da** tanımlı (msa: 50 satış kaleminin
> 27'sinde dolu = %54). anjan'da alan **hiç yok**, 303 satış kaleminin **%0**'ında İКПУ var.
> Fiskal çek İКПУ'suz gönderilemez — hem OFD spesifikasyonu (`SPIC`) hem de sağlayıcı API'si
> (`classifier_class_code`) bu alanı zorunlu tutuyor.
> ⇒ Hangi yol seçilirse seçilsin, **ilk iş İКПУ + paket kodu + KDV oranı veri altyapısı.**

**Karar için gereken tek bilgi:** anjan'ın kasiyeri bugün hangi kayıtlı kassaya vuruyor
(hangi sağlayıcı, sözleşme kimde). O sağlayıcı zaten API sunuyorsa iş 2–3 haftaya iner;
sunmuyorsa sağlayıcı değiştirme maliyeti tabloya girer.

**Tahmini iş yükü (yol A, sağlayıcı belli olduktan sonra):**
İКПУ veri altyapısı ~1 hafta · POS'un fiilen devreye alınması ~1 hafta ·
fiskal entegrasyon + vardiya/Z-rapor + çek ekranı ~2–3 hafta.

---

## 2. Yasal ve teknik çerçeve

### 2.1 Kim kimdir

| Terim | Açılım | Kim |
|---|---|---|
| **ОФД** | Оператор фискальных данных | DUK **"Yangi texnologiyalar"** (Ilmiy-axborot markazi), Soliq Qo'mitasi altında. Portal: **ofd.uz** |
| **ВК** | Виртуальная касса | Reestre kayıtlı kassa **yazılımı** (bulut/yerel). 41 kayıtlı sağlayıcı var |
| **онлайн-ККМ** | Онлайн касса | Reestre kayıtlı kassa **donanımı** |
| **ФМ / ВФМ** | Фискальный модуль / виртуальный ФМ | Kassaya bağlı fiskal modül; `TerminalID` bunun numarası |
| **ФП** | Фискальный признак | OFD'nin döndürdüğü 12 haneli fiskal belge — çekin geçerlilik kanıtı |
| **Kayıt portalı** | — | **txkm.soliq.uz** (başvuru, CSR, sertifika, reestr) |

### 2.2 `ofd-soliq.ioka.uz` hakkında — kullanıcının sorusunun cevabı

**Hayır, orası resmi OFD değil.** Teknik olarak ne olduğu:

- `ofd-soliq.ioka.uz` = 466 baytlık bir Vite SPA kabuğu, tek bir JS bundle
  (`/assets/index-RUsg2WMP.js`, 764 KB) içinde bütün içerik gömülü.
- Sitedeki tüm görseller ve veri kaynağı `https://ofd.uz/media/source/…` — yani içerik
  **ofd.uz'dan aynalanmış**.
- `ioka.uz`, ofd.uz'un kendi marketplace reestrinde **"IOKA TRAVEL" MCHJ** (kayıt no 62,
  tescil 29.08.2024) olarak geçiyor. Yani ioka, OFD'nin *kendisi* değil, OFD reestrindeki
  bir **katılımcı**.
- Sitede reestrler, SSS, çek sorgulama (`/check?t=<terminalId>&r=<paymentNo>&c=<fiscalSign>&h=<hash>`)
  ve entegrasyon sayfası var — hepsi ofd.uz muadili.

**Ama:** `/integration` sayfasından linklenen teknik belge **gerçek ve güncel** —
«Технологическая инструкция … ЭТП / ЭПС / ОФД, **версия 6.5**». Yani *belge* doğru,
*alan adı* yetkili değil. Resmî kaynak olarak **ofd.uz** ve **soliq.uz** kullanılmalı;
sözleşme, sertifika ve reestr işlemleri **txkm.soliq.uz** üzerinden yürür.

### 2.3 v6.5 spesifikasyonunun iki şeması — hangisine düşüyoruz

| | §2.1 — Fiskalizasyon ЭТП tarafında | §2.2 — Fiskalizasyon ВК tarafında |
|---|---|---|
| Kimin için | Marketplace (ЭТП) ve ödeme sistemleri (ЭПС) | Fiziksel/bulut kasa yazılımı |
| Çeki kim üretir | Platformun kendisi, OFD'ye doğrudan | Kassa yazılımı (ВК) |
| **Stabler POS** | ✗ | **✓ bu şema geçerli** |

Stabler bir marketplace değil, mağaza kasası. Dolayısıyla **§2.2** uygulanır — ya kendi ВК'mız
oluruz (yol B), ya kayıtlı bir ВК'nın arkasına geçeriz (yol A).

### 2.4 Doğrudan OFD protokolü (yol B'nin gerektirdiği her şey)

```
POST https://test.ofd.uz/emp/v3/receipt      # tek çek
POST https://test.ofd.uz/emp/v3/dreport      # gün sonu (Z) raporu
wss://test.ofd.uz/ws/emp/v3/receipt          # toplu, binary, 16 bayt RequestId öneki
```

- **Gövde:** `ReceiptInfo` JSON → `ReceiptSeq`, `IsRefund`, `ReceiptType` (satış/iade=0,
  avans=1, kredi=2), `Items[]` = `{Name, Barcode, Labels[], SPIC, Units, PackageCode,
  GoodPrice, Price, VAT, VATPercent, Amount}`, `Location`, `PickupPointInfo`,
  `DateTime` ("YYYYMMDDHHMMSS"), `FiscalSign` (12 hane).
- **İmza:** JSON → **PKCS#7 / CMS Attached**, `-nocerts`, DER çıktı:
  ```
  openssl cms -sign -nodetach -binary -in ReceiptInfo.json -text \
      -outform der -out ReceiptInfo.p7b -nocerts -signer user-etp.crt -inkey user-etp.key
  ```
- **Taşıma:** `Content-Type: application/octet-stream`, TLS — OFD kök sertifikası
  (`test.ofd.uz-root.crt`) trust store'a kurulmalı.
- **Yanıt:** `Code` (0 = kabul · 1 = I/O hatası → **yeniden gönder** · 2 = PKCS#7 format
  hatası · 3 = PKCS#7 yapı hatası …), `Message`, `TerminalID`, `FiscalSign`.
- **9 adımlı kabul süreci:** OFD'ye dilekçe → sözleşme → OFD entegrasyon kılavuzu + API
  kimlik bilgileri → **test sertifikası** + 4 tip test çeki (satış, iade, avans, kredi) +
  kullanıcı kılavuzu → OFD *zaklyucheniye* → **yıllık ödeme** → Soliq Qo'mitasi'na reestr
  dilekçesi → **prod sertifika** → fiskalizasyon.
- **Kayıt API'si:** `https://txkm.soliq.uz/api/txkm-api/` — `POST /auth/login` (Bearer),
  `/emr-api/application/add[/test]`; başvuru dosyaları: `csr_file`, `cadastre_rent_file`,
  `application_file`, `sale_point_region`.

---

## 3. Üç yolun karşılaştırması

| Kriter | **A — Kayıtlı ВК sağlayıcısı API'si** | **B — Kendi ВК'mız (doğrudan OFD)** | **C — Fiziksel online-KKM köprüsü** |
|---|---|---|---|
| Reestr / sertifika kimde | Sağlayıcıda | **Bizde** (CSR, test+prod sertifika, reestr kaydı) | Cihaz üreticisinde |
| Bürokrasi süresi | Sözleşme + hesap açılışı (günler–haftalar) | **9 adım, aylar** (v6.5 §onboarding) | Cihaz alımı + kayıt (haftalar) |
| Yıllık ücret | Sağlayıcı aboneliği — *fiyat teklifi alınmalı* | OFD'ye yıllık ödeme (v6.5 adım 6) + sertifika yenileme | Cihaz + servis sözleşmesi |
| PKCS#7 / CMS imzalama | Yok — sağlayıcı yapar | **Bizde** (OpenSSL, anahtar saklama, yenileme) | Yok |
| Stabler tarafı teknik iş | Orta — sağlayıcı JSON'u + durum takibi | **Yüksek** — protokol, imza, hata kodları, kuyruğu, Z-rapor | Orta — köprü servisi + sürücü |
| **Yasal sorumluluk** | Sağlayıcıda | **Bizde** — hatalı çek doğrudan bizim yükümlülüğümüz | Cihaz sahibi işletmede |
| Çok kiracılılık (7 site) | İyi — şirket başına hesap/ФМ | Zor — her şirket için ayrı sertifika + reestr kaydı | Zor — her kasa için donanım |
| Offline davranış | Sağlayıcının yerel sürücüsü kuyruklar (`receipts_notsended`, `resendUnsent`) | Kendi kuyruğumuzu yazarız (`Code=1` → resend) | Cihaz kuyruklar |
| İade / avans / kredi çeki | Hazır (`module_operation_type` 3/4, avans, kredi) | Kendimiz kurarız (`ReceiptType` 0/1/2) | Hazır |
| Vardiya / Z-rapor | Sağlayıcıda hazır (açılış/kapanış/X/Z) | **Bizde** (`/emp/v3/dreport`) | Cihazda |
| Vendor lock-in | Orta — sağlayıcıya bağımlılık | Yok | Yüksek — donanıma bağımlılık |
| Bulut SPA'ya uygunluk | **Kısmen** — aşağıdaki uyarıya bakın | İyi (sunucu→sunucu) | Zayıf (yerel cihaz) |

### ⚠ Yol A hakkında kritik teknik uyarı — "bulut API" beklentisi yanlış çıktı

İncelenen tek **herkese açık** sağlayıcı dokümantasyonu (Multikassa / Multibank, Postman
koleksiyonu: `docs-virtual-kassa.multibank.uz`) fiskal uç noktaları **`http://localhost:8080/api/v1/…`**
üzerinde tanımlıyor — yani fiskalizasyon, kasiyerin makinesinde çalışan **yerel fiskal sürücü**
tarafından yapılıyor. Bulut tarafında (`api.multibank.uz`) yalnızca stok/nomenklatura/raporlama
servisleri var; **satış çeki yerelden gidiyor**.

Sonuç: yol A pratikte "sunucudan REST çağırma" değil, **tarayıcı → `localhost:8080` köprüsü**.
Bu çalışır (Chrome `http://localhost`'u güvenli origin sayar, karışık-içerik engeline takılmaz),
**ama Safari bunu engeller** ve her kasa makinesine sürücü kurulumu gerekir. Yani yol A ile yol C
mimari olarak birbirine yakınlaşıyor; fark bürokratik (kimin reestr kaydı kullanılıyor), teknik değil.

Bu, sağlayıcı seçiminde **birinci eleme kriteri** olmalı: *"sunucudan sunucuya, gerçek bulut
fiskalizasyon API'si sunuyor musunuz, yoksa yerel sürücü mü şart?"*

### Multikassa API'sinin somut yüzeyi (yol A'nın gerçek maliyeti)

Satış çeki gövdesi (`POST /api/v1/operations`, `module_operation_type: 3`):

```jsonc
{
  "module_operation_type": "3",
  "receipt_sum": 4000000,
  "receipt_gnk_receivedcash": 0,
  "receipt_gnk_receivedcard": 4000000,
  "receipt_gnk_time": "2023-06-26 13:58:28",
  "items": [{
    "classifier_class_code": "01905007001000000",   // ← İКПУ / MXIK — ZORUNLU
    "product_name": "Cola",
    "product_barcode": "4011548030707",
    "product_price": 20000,
    "product_vat_percent": 12,                       // ← KDV oranı — ZORUNLU
    "product_package": "1433173",                    // ← paket kodu — ZORUNLU
    "product_package_name": "dona",
    "product_mark": false,                           // markirovka ürünü mü
    "product_label": "0104011548…",                  // markalı ise DataMatrix
    "product_discount": 0,
    "count": 1,
    "commitent_tin": "123456789"                     // komisyon satışında
  }],
  "location": { "Latitude": 41.29, "Longitude": 69.21 }
}
```

İade çeki (`module_operation_type: 4`) **orijinal çekin kimliğini** ister:

```jsonc
"RefundInfo": { "TerminalID": "", "ReceiptSeq": "", "DateTime": "", "FiscalSign": "" }
```

⇒ Her fiskal çekin `TerminalID + ReceiptSeq + DateTime + FiscalSign` dördülüsü **kalıcı olarak
saklanmak zorunda**; iadeler onsuz yapılamaz.

Ayrıca vardiya zorunlu: `module_operation_type` 1 = açılış, 2 = kapanış, X raporu ayrı;
`/api/v1/zReport`, `/api/v1/unsentCount`, `/api/v1/resendUnsent` ile kuyruk yönetimi.
İКПУ tarafı için de hazır uçlar var: `/api/v1/products/by_params?text=…` (tasnif araması),
`/api/v1/products/get_package?mxik=…` (paket kodu), `/api/v1/products/check?mxikCode=…`.

---

## 4. Kayıtlı Virtual Kassa sağlayıcıları (ofd.uz reestri, 41 kayıt)

Reestr `ofd.uz` verisinden çıkarıldı (ioka aynası üzerinden, JS bundle'dan tam liste).
"API" sütunu **yalnızca herkese açık dokümantasyon** bulgusudur — boş olması API yok demek
değil, *kamuya açık dokümanı bulunamadı* demektir.

| # | Ürün | Üretici | Tescil | Site | Açık API dokümanı |
|---|---|---|---|---|---|
| 1 | Виртуал касса V 2.02 | НИЦ «Янги технологиялар» | 13.01.2020 | ofd.uz | — |
| 2 | Штрих-М: Кассир V.5.0 | Bar Code Texnologies | | bct.uz | — |
| 3 | E-POS | E-POS SYSTEMS | | uzpos.uz | — |
| 4 | POS2K V5.0 | SOFT TECH SOLUTIONS | | softtech.uz | — |
| 5 | Oxymed-Retail | NIKA FARM SERVIS | | | — |
| 6 | F-KASSA | FOM GROUP | | | — |
| 7 | Set Retail-10 | Soft Business Group | | | — |
| 8 | Artix | Point of Sale Systems | | pos.uz | — |
| 9 | PILL | Tetrasoft Group | | virtualpos.uz | — |
| 10 | REGOS:VCR | REGOS SOFTWARE | | | — |
| 11 | R_keeper 7 | Soft Business Group | | | — |
| 12 | VIPOS | RIG | | | — |
| 13 | XPOS | Point of Sale Systems | | | — |
| 14 | i-cash windows | Bestpos | | | — |
| 15 | Mobil Kassa 0.1 | NEWTECH SOLUTIONS | | | — |
| 16 | i-cash mobile | Bestpos | | | — |
| **17** | **Micros24** | **RAHMAT TECH** | | **multikassa.uz** | **✓ Postman (yerel sürücü)** |
| 18 | Smart one V.1.0.84 | POS TECHNOLOGIES | | smartone.uz | — |
| 19 | QPOS 1.1 | | | | — |
| 20 | YPOS | Your Soft | | | — |
| 21 | AvvalPos | | | | — |
| 22 | MyBux POS | | | | — |
| 23 | AnorKassa 1.0.0 | ANOR BANK | | | — |
| 24 | POSCODE 1.0.1 | Zero One Number | | | — |
| 25 | Invan Pos v1.0 | Invan Soft | | invan.uz | — |
| 26 | Jowi Retail v1.00 | SNTS | | jowi.uz | — |
| 27 | ERA fiscal | Ягона маркировкалаш… | | new-era.uz | — |
| 28 | mDokon-POS V1 | AUTOMATION SOURCE | | | — |
| 29 | iiko Fiscal | Zetta Group | | | — |
| 30 | E-POS Cashdesk | E-POS SYSTEMS | | uzpos.uz | — |
| 31 | Venkon 1.0 | Venkon Group | | | — |
| 32 | AUDIT APTEKA | AUD-IT SOFT | | | — |
| 33 | SIMURG | Гаров тараққиёт НКМ | | txkm.uz | — |
| 34 | E-Pos Mobile | E-POS SYSTEMS | | | — |
| 35 | Hippo.uz | ART OF BUSINESS ASSISTANCE | | hippo.uz | — |
| 36 | Business 1.0.1 | CENTER FOR DIGITAL TECHNOLOGY AND INNOVATION | | smartpos.uz | — |
| 37 | Les Fiscal | Perspective-view | 19.05.2025 | | — |
| 38 | TS POS | Joha Pos Service | 15.10.2025 | | — |
| 39 | iiko cloud | Software Integrator | 19.11.2025 | | — |
| 40 | Virtual Kassa | АЖ «Soliq-servis» | 30.04.2026 | | — |
| 41 | Biznex | Deep Space | 15.06.2026 | biznex.uz | — |

**Kısa liste (görüşülecek 4 sağlayıcı):**

1. **Multikassa / Micros24 (RAHMAT TECH)** — tek doğrulanmış açık dokümantasyon; ödeme
   sistemleri (Click / Payme / Uzum), markirovka, İКПУ katalog aramaları, stok, vardiya —
   hepsi kapsanmış. Kısıt: fiskalizasyon yerel sürücüden.
2. **АЖ «Soliq-servis» — Virtual Kassa (#40)** — devlet iştiraki, en yeni kayıt (30.04.2026);
   bulut mimarisi olma ihtimali en yüksek aday, sorulmalı.
3. **E-POS SYSTEMS (#3/#30/#34)** — reestrde üç ayrı ürünle, olgun oyuncu.
4. **Biznex (Deep Space, #41)** — en yeni (15.06.2026), muhtemelen modern/bulut-öncelikli.

Her biriyle görüşmede sorulacak **5 eleyici soru**:
① Sunucudan sunucuya bulut fiskalizasyon API'si var mı, yoksa yerel sürücü şart mı?
② Tek hesap altında **çok şirket + çok satış noktası (ФМ)** yönetilebiliyor mu?
③ İade çeki için orijinal çek kimliği (`FiscalSign` vb.) API'den geri dönüyor mu?
④ Vardiya açma/kapama ve Z-raporu API'den yapılabiliyor mu, yoksa manuel mi?
⑤ Yıllık ücret modeli: kasa başına mı, çek başına mı, şirket başına mı?

---

## 5. Stabler tarafındaki iş yükü (yoldan bağımsız — her koşulda gerekli)

### 5.1 Önkoşul: İКПУ / paket / KDV veri altyapısı ⛔ **bugün yok**

- `custom_ikpu_code` alanı `stabler/hooks.py:384-391`'de tanımlı ama **yalnızca msa'da**
  kurulu (ölçüm: 7 siteden 1'i). anjan'da alan yok, 303 satış kaleminin %0'ında değer var.
- Gerekli alanlar: **İКПУ (MXIK, 17 hane)**, **paket kodu** (`PackageCode` / `product_package`),
  **KDV oranı**, **birim**. Bugün yalnızca birincisi (kısmen) mevcut.
- Doldurma yolu: sağlayıcının katalog arama uçları (`/products/by_params?text=…`,
  `/get_package?mxik=…`) veya `tasnif.soliq.uz`. Bu tek başına bir alt proje.

### 5.2 POS'un fiilen devreye alınması ⛔ **bugün yok**

- anjan'da **0 POS Profile** → `list_pos_profiles` boş dönüyor (`stabler/api/pos.py:148`),
  yani POS ekranı bugün hiçbir şirkette çalışır durumda değil.
- 8 POS faturası (29.07.2026) tamamı iptal — tek günlük test.
- Fiskalizasyondan **önce** POS'un gerçek satışı taşıması gerekiyor; aksi halde entegrasyon
  kullanılmayan bir ekrana bağlanmış olur.

### 5.3 Entegrasyon noktası — tek choke point

`stabler/api/pos.py:293` `build_paid_pos_invoice(...)` hem nakit yolunu
(`create_pos_invoice`, `pos.py:330`) hem QR/online yolunu
(`stabler/integrations/uzpay/common.py` `finalize_session_to_invoice`) kapsıyor;
ikisi de buradan submit edilmiş Sales Invoice döndürüyor. Fiskal tetikleyici buraya
(veya `is_pos` filtreli bir `Sales Invoice on_submit` doc_event'ine) konursa **POS satışlarının
%100'ü** yakalanır.

### 5.4 Yapılacaklar listesi

| # | İş | Referans / desen |
|---|---|---|
| 1 | Satır bazında İКПУ + paket kodu + KDV oranı + birim'i sepete ve faturaya taşı | `pos.py:253` `_assemble_pos_invoice` bugün yalnızca `item_code/qty/uom/rate/warehouse` yazıyor |
| 2 | `Item`'a paket kodu ve KDV oranı alanları; İКПУ alanını tüm UZ sitelerine yay | `hooks.py:384` `custom_ikpu_code` deseni |
| 3 | Fiskal çek durumu tutan doctype: durum, `retry_count`, hata, `TerminalID`, `ReceiptSeq`, `FiscalSign`, `DateTime`, QR URL | `Didox Submission` / `EHF Submission` deseni; retry: `integrations/didox/client.py:47`, `didox/submit.py:73` |
| 4 | Çek (fiş) ekranı + QR — bugün **hiç yok** (POS'ta yalnızca `d-print-none` header ve `ti-receipt-off` boş-durum ikonu var) | QR üretimi hazır: `integrations/uzpay/common.py:216` `qr_svg_data_uri(text)` |
| 5 | Vardiya kavramı: açılış / kapanış / X / Z raporu | Bugün yok — yeni doctype + POS ekranı |
| 6 | İade yolunu fiskal iade çekine bağla; orijinal çek kimliğini kullan | `stabler/api/sales.py:1797` `create_direct_sales_return` |
| 7 | Nakit yolunda idempotency + kuyruk/retry (online yol zaten idempotent) | `frappe.enqueue` + `didox/hooks.py:19` deseni |
| 8 | Modül kapısı: `enable_fiscal` **default 0** | `stabler_company_modules.json` + `api/organization.py:76-138` `_MODULE_FIELDS`/`_MODULE_ROLES` + `router.js` `meta.module` |
| 9 | Şirket başına konfig: TIN, `TerminalID`/ФМ, satış noktası (adres + bölge kodu), kasiyer kimlikleri | `Stabler POS Gateway` child-table deseni (`stabler_pos_gateway.json`, `istable: 1`) |
| 10 | Sırlar: sağlayıcı token / sertifika | `frappe.conf` (uzpay/didox deseni) veya `Password` alanı (`Stabler Timepay Credential`) — **DB'de düz metin asla** |

**Çok kiracılılık kuralı:** hiçbir yerde tenant adına dallanma yok
(`if company == "anjan"` yasak). Tüm değişkenlik `Stabler Company Modules` + şirket başına
konfig satırından okunur — `CLAUDE.md` "Tenant & feature ownership" bölümü.

---

## 6. Riskler ve açık sorular

| Risk | Etki | Azaltma |
|---|---|---|
| **Yerel sürücü zorunluluğu** (yol A'nın gerçek mimarisi) | Bulut SPA vaadi bozulur; her kasa makinesine kurulum; Safari'de çalışmaz | Sağlayıcı seçiminde 1. eleme sorusu; bulut API'si olan sağlayıcı bulunamazsa yol B yeniden değerlendirilir |
| **İКПУ verisi yok** | Fiskal çek hiç gönderilemez | Veri altyapısını ilk faz yap; sağlayıcının katalog API'sinden toplu eşleştirme |
| **POS üretimde kullanılmıyor** | Entegrasyon boşa gidebilir | Önce POS Profile + gerçek kullanım; fiskalizasyon ikinci faz |
| Yol B'de sertifika yönetimi | Sertifika süresi dolarsa **satış durur** | Seçilirse: süre takibi + alarm; ama bu risk tek başına yol A lehine güçlü argüman |
| İade zinciri kopması | Orijinal `FiscalSign` kaybolursa iade çeki kesilemez | 3 numaralı doctype'ta dörtlüyü kalıcı sakla, asla silme |
| Offline satış | Fiskal çek kesilemeyen satış = yasal ihlal | Kuyruk + `resendUnsent` muadili; kuyruk dolu iken kasiyere görünür uyarı |
| Diğer 6 tenant | Gereksiz karmaşa / yanlış tenant'a sızma | `enable_fiscal` default **0**, yalnızca perakende satan tenant'ta aç |

**Cevaplanması gereken sorular:**

1. anjan kasiyeri bugün **hangi kayıtlı kassaya** vuruyor? (sağlayıcı adı + sözleşme)
2. 7 tenant'tan hangileri gerçekten perakende nakit satış yapıyor? (ölçüm: POS faturası
   hiçbirinde yok; muhasebe teyidi gerekiyor)
3. anjan'ın kaç fiziksel satış noktası / kasası var? (fiyatlandırma buna bağlı)
4. Markirovka (etiketli ürün) satışı var mı? (dondurma → süt ürünü markirovkası gündemde)
5. Yıllık bütçe tavanı nedir?

**Doğrulanmamış kalemler** (bilinçli olarak boş bırakıldı — kaynaksız rakam yazılmadı):
sağlayıcı yıllık ücretleri, OFD yıllık ödeme tutarı, sertifika ücretleri. Bunlar ancak
sağlayıcı ve OFD'den yazılı teklifle netleşir.

---

## 7. Öneri ve sonraki adım

**Öneri: Yol A**, ama iki ön koşulla ve şu sırayla:

1. **Faz 0 — Keşif (bu hafta, kod yok).** anjan'ın mevcut kassa sağlayıcısını öğren.
   Kısa listedeki 4 sağlayıcıya §4'teki 5 eleyici soruyu sor, yazılı teklif al.
2. **Faz 1 — Veri altyapısı (~1 hafta).** İКПУ + paket kodu + KDV oranı alanlarını UZ
   tenant'larına yay, anjan'ın 303 satış kalemini doldur. *Bu faz sağlayıcı seçiminden
   bağımsız — beklemeden başlanabilir.*
3. **Faz 2 — POS'u devreye al (~1 hafta).** POS Profile, ödeme yöntemleri, gerçek kullanım.
4. **Faz 3 — Fiskal entegrasyon (~2–3 hafta).** §5.4 listesi, `build_paid_pos_invoice`
   üzerinden, `enable_fiscal` default kapalı.

**Yol B yalnızca şu durumda:** hiçbir sağlayıcı sunucudan sunucuya bulut API'si sunmuyorsa
ve yerel sürücü kabul edilemezse. O zaman v6.5'in 9 adımlı süreci başlatılır — ama bu
kararın **aylar** ve **kalıcı yasal sorumluluk** anlamına geldiği baştan kabul edilmeli.

---

## Ek A — Kaynaklar

- «Технологическая инструкция … ЭТП / ЭПС / ОФД, версия 6.5» — ofd.uz `/integration`
  sayfasından linklenen resmî belge (§2.1 / §2.2 şemaları, `emp/v3/receipt`, PKCS#7, hata kodları)
- [ofd.uz](https://ofd.uz) — resmî OFD portalı; Virtual Kassa ve online-KKM reestrleri
- [soliq.uz — Onlayn NKM](https://soliq.uz/page/onlayn-nkm?lang=ru) — vergi idaresi bilgi sayfası
- `https://txkm.soliq.uz/api/txkm-api/swagger-ui.html` — kassa kayıt/sertifika API'si
- [docs-virtual-kassa.multibank.uz](https://docs-virtual-kassa.multibank.uz/) — Multikassa
  Virtual Kassa Postman koleksiyonu (uç noktalar, satış/iade gövdeleri)
- [multibank.uz — Virtual Kassa](https://multibank.uz/small-buisness/services/virtual-kassa/) ·
  [multikassa.uz](https://multikassa.uz/virtual-kassa/) · [rhmt.uz/pos](https://rhmt.uz/pos/)
- [moysklad.uz — Onlayn kassalar 2026](https://www.moysklad.uz/poleznoe/shkola-torgovli/online-kassa-v-uzbekistane/) —
  pazar genel görünümü (üçüncü taraf, teyit gerekir)

## Ek B — Ölçüm çıktıları (prod, salt-okunur, 05.08.2026)

```
POS kullanımı (tüm siteler)
  site                     is_pos!=0   onaylı SI   POS Profile   Payment Session
  anjan.erpstable.com          8         14436          0              0     ← 8'i de iptal
  dts.erpstable.com            0             0          0              0
  horeca.erpstable.com         0             0          0              0
  laminor.erpstable.com        0             0          0              0
  mikas.erpstable.com          0             0          0              0
  msa.erpstable.com            0          4935          1              0
  smartbox.erpstable.com       0             1          0              0

anjan Sales Invoice dağılımı
  is_pos  docstatus  adet   ilk           son
     0        0        12   2026-08-04    2026-08-04   (taslak)
     0        1     14436   2026-03-10    2026-08-04   (onaylı)
     0        2       738   2026-03-12    2026-08-04   (iptal)
     1        2         8   2026-07-29    2026-07-29   (POS — hepsi iptal)

custom_ikpu_code alanı (Custom Field varlığı)
  anjan 0 · dts 0 · horeca 0 · laminor 0 · mikas 0 · msa 1 · smartbox 0

İКПУ doluluk
  msa   : 50 satış kaleminin 27'sinde dolu (%54)
  anjan : 303 satış kalemi, alan yok (%0)
```
