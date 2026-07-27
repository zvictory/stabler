# UZEX Tender Entegrasyonu — Boşluk Analizi ve Plan (WP-300 serisi)

**Tarih:** 08.07.2026 · **Tetikleyici:** etender.uzex.uz/lot/500606 tarzı başvuruların otomasyonu + CRM'de anlık durum talebi
**Bağlantılar:** [[../Tender_ERP_Stabler_implementation_spec|Tender spec]] · [[2026-06-12-tender-orders-board]] · [[../stabler_wiki]] · [[../../STATE.md|STATE.md]]

## 1. Mevcut Durum (kod üzerinde doğrulandı)

**Güçlü zemin — tender iç yönetimi olgun:** `api/tender.py` (1167 satır, 18 endpoint): SO kanban board, PO kontrol board'u, bid P&L hesabı (НДС/биржа komisyonu/vergiler → Остаток), tender intake + deadline risk motoru (`_milestone`: good/warn/risk), rol pencereleri (director/sourcing/declarant/logist), landed cost + ТН ВЭД. Veri modeli: **1 CRM Deal = 1 tender/lot** — SO/PO/Supplier Quotation `custom_crm_deal` ile bağlı. 7 SPA sayfası (`pages/tender/`).

**Boşluklar:**

| # | Boşluk | Kanıt |
|---|--------|-------|
| G1 | Portal entegrasyonu SIFIR — repoda `uzex/etender/xarid` geçen tek kod satırı yok; plan dosyasında açıkça kapsam dışı bırakılmış | `2026-06-12-tender-orders-board.md:168` |
| G2 | Lot girişi tamamen elle (intake formu); portal'dan otomatik Deal oluşturma yok; spec F2 `intake_lead`+Telegram planlı ama yapılmamış | Tender spec F2 |
| G3 | "Anlık durum" yok: tüm tender sayfaları load-once — `setInterval`/`frappe.realtime` hiçbir yerde yok | `pages/tender/*` grep |
| G4 | Teklif/başvuru gönderimi manuel (portal'da elle) | — |
| G5 | Portal deadline'ı ile intake deadline'ı el senkronu — unutulursa risk motoru kör | `tender.py:800` |

**Kopyalanacak hazır desenler (repoda mevcut):** `integrations/didox/client.py` (HTTPS-guard'lı urllib REST client, site_config token, Submission doctype + retry_count) · `tasks/cbu_rate_refresh.py` (idempotent zamanlanmış poller) · `integrations/uzpay/` + `arca/webhook.py` (inbound webhook) · `public/js/lib/eimzo.js` (E-IMZO tarayıcı imzası — didox için zaten kullanılıyor).

## 2. UZEX Tarafı — Araştırma Sonucu (08.07.2026)

- `etender.uzex.uz/lot/...` sayfaları **client-rendered Angular kabuğu** (fetch boş dönüyor) → SPA arkada bir JSON API'sine konuşuyor; **kamuya açık geliştirici dokümantasyonu yok**.
- UZEX ekosisteminde sistem-başına Swagger'lı API'ler mevcut: `charm-api.uzex.uz/index.html`, `api-yarmarka.uzex.uz/index.html` — yani `api-etender.uzex.uz` benzeri bir uç büyük olasılıkla var ama belgelenmemiş (WP-300 doğrulayacak; swagger.json uçları anonim fetch'te boş döndü — muhtemelen UA/erişim filtresi).
- Devlet alımları 05.01.2022'den beri tek sistemde: `xarid.uzex.uz` (+ `dxarid.uzex.uz`); ayrıca bilgi portalı `xarid.uz`. Kurumsal/birja tenderleri `etender.uzex.uz`.
- **Erişim stratejisi (sıralı):** (a) UZEX'e resmi entegrasyon/API başvurusu (en sağlıklı, hesap zaten var), (b) SPA'nın kendi JSON uçlarının read-only kullanımı (DevTools ile haritalama — WP-300), (c) fallback: sayfa HTML'i yerine `xarid.uz` bilgi portalı/açık veri kaynakları.
- **İlke kararı:** İzleme/senkron read-only otomatikleşir; **teklif GÖNDERİMİ otomatikleşmez** (E-IMZO imzası + hukuki sorumluluk → insan onayı zorunlu; sistem paketi hazırlar, insan imzalar/gönderir).

## 3. Hedef Mimari

```
[UZEX portalları] ←(hourly poll / webhook)— integrations/uzex/client.py
      → Deal upsert (lot_no dedupe) → CRM Deal (+custom_uzex_* alanları)
      → durum değişimi → Notification + Telegram (WP-303/307)
      → SPA: CRM kanban + tender board'ları canlı chip/countdown (WP-304/305)
İnsan: git/gitme kararı → intake → bid pricing → paket (WP-306) → portalda İMZALI gönderim (manuel)
      → sonuç poller'la geri okunur → Deal won/lost otomatik işaretlenir → mevcut SO board devralır
```

## 4. İş Paketleri (task listesine #13–#20 olarak açıldı)

| WP | İş | Bağımlılık | Kestirim |
|----|----|-----------|----------|
| WP-300 | API keşfi (DevTools haritalama + Swagger inceleme + UZEX resmi başvuru) | — | 2-3 gün |
| WP-301 | Veri modeli: Deal custom alanları (`custom_uzex_lot_no` dedupe anahtarı, portal, portal_status, deadline, start_price, customer_org, last_synced) + patch | — | 1 gün |
| WP-302 | `integrations/uzex/` client + saatlik poller → idempotent Deal upsert | 300, 301 | 1 hafta |
| WP-303 | Durum eşleme (portal→Deal Status/intake.result) + değişim bildirimleri + deadline<48s uyarı | 302 | 3 gün |
| WP-304 | SPA: Deal kartında portal_status chip + countdown; TenderIntake'e "lot URL yapıştır → otomatik doldur" | 302 | 4 gün |
| WP-305 | Tender sayfalarına canlı yenileme (`useAutoRefresh` 60sn polling; v2: frappe.realtime) | — (bağımsız) | 2 gün |
| WP-306 | Bid paketi üretimi + E-IMZO uyarlanabilirlik etüdü — insan onaylı gönderim | 301 | 1 hafta |
| WP-307 | intake_lead webhook + Telegram yeni-lot bildirimi (spec F2 borcu) | 302 | 4 gün |

Kabul invariant'ları: poller ikinci koşuda 0 duplicate Deal (lot_no dedupe); portal erişilemezse sessiz çökme yok — son senkron zamanı UI'da görünür (stale uyarısı, CBU stale-rate deseni); tüm yeni endpoint'ler blueprint §2.0 sözleşmesine uyar.

**Hızlı kazanım sırası:** WP-305 (bağımsız, 2 gün, "anlık" hissini hemen verir) + WP-301 → WP-300 sonucuna göre WP-302.

## 5. Riskler
1. Belgelenmemiş API'nin değişmesi → client'ta şema-tolerans + sözleşme testi; resmi API başvurusu paralel yürür.
2. Erişim engeli/rate-limit → saatlik nazik polling, tek IP, cache; kesinlikle agresif scraping yok.
3. Oto-gönderim beklentisi → bilinçli kapsam dışı (bkz. §2 ilke kararı) — kullanıcıya net anlatılır.
