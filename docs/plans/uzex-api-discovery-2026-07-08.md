# UZEX etender — API Keşif Raporu (WP-300)

**Tarih:** 08.07.2026 · **Yöntem:** Claude in Chrome — `etender.uzex.uz/lot/500606` + `/lots/2/0` canlı, `performance.getEntriesByType('resource')` + fetch/XHR interceptor ile gerçek istekler yakalandı. **Kod üretilmedi** (bu bir araştırma paketi).

## 1. Özet karar

**Erişim stratejisi (b) seçildi: SPA'nın kendi public JSON uçlarının read-only kullanımı.** `etender.uzex.uz` Angular SPA'sı, kimlik doğrulama GEREKTİRMEYEN bir REST API'sine (`apietender.uzex.uz`) konuşuyor; lot listeleme ve lot detayının tamamı anonim erişimle geliyor. WP-302 poller'ı bu iki ucu saatlik, nazik (tek IP, düşük hacim) çağırır. Resmi API başvurusu (a) paralel/uzun vadeli seçenek olarak açık kalır (sözleşme garantisi için); ama WP-302'yi bloke etmez.

## 2. Doğrulanmış uçlar (etender)

Base: **`https://apietender.uzex.uz/api/`** · Auth: **yok** (anonim) · CORS: tarayıcıdan same-origin proxy; **sunucudan (Frappe) çağrıda CORS yok** ama olası UA/Referer filtresine karşı client browser-benzeri `User-Agent` + `Referer: https://etender.uzex.uz/` göndermeli (swagger.json anonim fetch'te boş dönmüştü → filtre şüphesi).

### 2.1 Lot listeleme (poller keşif ucu)
```
POST https://apietender.uzex.uz/api/common/TradeList
Content-Type: application/json
Body: {"TypeId": 2, "From": 1, "To": 20, "System_Id": 0}
```
- `TypeId` — tender türü: **1**=Eng yaxshi taklifni tanlash · **2**=Tender · **3**=Hadli kelishuv (hadli) · **5**=Master-plan · **6**=Hujjat muhokamasi. (Poller ilgili türleri döngüyle çeker.)
- `From`/`To` — 1-tabanlı satır aralığı (sayfalama). Yanıttaki `total_count` toplam sayıyı verir → From/To ile sayfalanır.
- `System_Id` — alt sistem seçici (etender için gözlemlenen: `0`).

**Yanıt:** düz JSON dizisi (`200`, len=To−From+1). Öğe şeması:
```
{ rn, id, display_no, total_count, name, start_date, end_date, clarific_date,
  cost, seller_name, seller_tin, seller_id, region_name, district_name,
  category_name, currency_id, currency_name, currency_code123, currency_codeabc }
```
Örnek: `id=497638, display_no="26111006497638", name="...elektron tender",`
`end_date="2026-07-08T11:47:09", cost=6300000000, seller_name="...", seller_tin="201140445", currency_codeabc="UZS"`.

### 2.2 Lot detay (durum senkron ucu)
```
GET https://apietender.uzex.uz/api/common/GetTrade/{id}/0
```
`{id}` = liste yanıtındaki `id` (lot sayfası URL'i de `etender.uzex.uz/lot/{id}`). İkinci segment `0` = dil/varyant (0 gözlemlendi).

**Yanıt (tek nesne):** `id, display_no, start_date, end_date, clarific_date, start_cost,`
`valuation_id/name, products, budget_products (JSON str), consider, consider_procedure,`
`description, pledge_name, pledge_value, advance_payment_perc, term_payment_days,`
`term_online_days, type_name, status_id, status_name, languages, contacts (JSON str),`
`rest_time, customer_name` (+ diğerleri).

### 2.3 Yardımcı uçlar (poller için gerekmiyor, bilgi)
`Common/GetNotifications`, `Common/GetPopup`, `common/GetTopStats/0`, `common/GetMapStats`,
`libs/GetCurrentVersion`, `Libs/GetFormOption`, `Libs/GetCurrenciesForProposal`,
`xarid-api-trade.uzex.uz/Lib/GetCurrentTime` (sunucu saati).

## 3. CRM Deal alan eşlemesi (WP-301 v39 → bu uçlar)

| Deal alanı (custom_uzex_*) | Kaynak (TradeList / GetTrade) |
|---|---|
| `lot_no` (dedupe) | `display_no` (ör. 26111006497638) |
| `portal` | sabit `etender` (xarid/dxarid ayrı — §5) |
| `status` | GetTrade `status_id` + `status_name` (ham; merkezi eşleme WP-303) |
| `deadline` | `end_date` (ISO, **timezone yok → Tashkent UTC+5 varsay**) |
| `start_price` | TradeList `cost` / GetTrade `start_cost` |
| `customer_org` | `seller_name` (+ `seller_tin`) / GetTrade `customer_name` |
| `last_synced` | poller başarı zamanı |
| (Deal.title) | `name` |

**Not:** UZEX'te "seller" = satın alan/buyurtmachi (tender açan kurum) — bizim tarafımızda müşteri/organizasyon. İsim yanıltıcı, alan içeriği doğru.

## 4. Poller tasarım girdileri (WP-302)
- Tür döngüsü: `TypeId ∈ {1,2,3,5,6}`, her biri için `From/To` sayfalama, `total_count`'a kadar.
- İdempotent upsert anahtarı: `display_no` → `custom_uzex_lot_no` (UNIQUE, v39).
- Detay/durum: yalnız izlenen (Deal'i olan) lotlar için `GetTrade/{id}/0` — liste zaten status vermiyor, detay veriyor.
- Tarih ayrıştırma: `"%Y-%m-%dT%H:%M:%S"`, tz-naive → `Asia/Tashkent`.
- Nazik polling: saatlik, tek IP, tür başına makul `To` sınırı (ör. son 50), cache; agresif tarama YOK.
- Dayanıklılık: portal erişilemez/şema değişirse `custom_uzex_last_synced` güncellenmez + `frappe.log_error`; UI stale gösterir (CBU stale-rate deseni). Şema-tolerans: `.get()` ile alan eksikliğine dayan.

## 5. Açık uçlar / takip
- **xarid.uzex.uz + dxarid.uzex.uz (devlet alımları):** ayrı keşif gerekiyor; büyük olasılıkla farklı host (`xarid-api-*`) ve muhtemelen kimlik/oturum gerektirir. WP-302 önce etender ile devreye alınır; xarid/dxarid ikinci tur.
- **Resmi API başvurusu (a):** sözleşme garantisi için UZEX'e entegrasyon talebi paralel yürütülür (belgelenmemiş uç değişebilir → §Risk 1).
- **UA/Referer filtresi:** poller'ın gerçek çağrısında doğrulanmalı (yerel `bench execute` ile bir kez); 403 gelirse `User-Agent`+`Referer` başlıkları eklenir.
- **site_config anahtarları (WP-302):** `uzex_endpoint` (= `https://apietender.uzex.uz/api`), gerekirse `uzex_user_agent`. Token YOK (anonim) — resmi API gelirse `uzex_token` eklenir.
