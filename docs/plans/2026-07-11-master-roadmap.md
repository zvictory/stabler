# STABLER MASTER ROADMAP — Tüm Cepheler Tek Plan

**Tarih:** 2026-07-11 · **Kaynaklar:** STATE.md, erp_roadmap.md, todo.md, docs/plans/*, MSA migration serisi, canlı kod doğrulaması (envanter ajanı raporu)
**Kiracılar:** anjan (ana prod) · dts · **horeca** · laminor · **mikas** (tender) · smartbox + **msa** (kurulum bekliyor)

---

## 0. Tek Bakışta Durum

| Cephe | Kod | Deploy | Kalan kritik iş |
|---|---|---|---|
| A. MSA Imports (WP1-6b) | ✅ %90 | ❌ | Kurulum + WP7 + ETL + cutover |
| B. LCV Birleştirme | ⚠️ 3 ayrı yol | — | Tek motora birleştirme (yeni) |
| C. Tender/Mikas (UZEX) | ✅ tamam | ❌ | Go-live checklist yürütme + resmi API başvurusu |
| D. Service/Horeca | ✅ tamam | ⚠️ kısmi | Postgres migration runbook'u + RN mobil repoint + kill-switch 2 |
| E. EDO/Didox | ⚠️ B4 only | ✅ B4 | B0 keşif cevapları (kiracı EDS/IKPU) → B5+ |
| F. Çapraz borçlar | — | — | E2E %0, 1.117 çevirisiz anahtar ×4 dil, manuel deploy, bayat dokümanlar |
| G. FAZ-1 Retail (offline POS vb.) | ❌ | — | Başlamadı — bilinçli ertelendi |

**Bir kerelik düzeltme:** STATE.md ve stabler_wiki.md kodun gerisinde (WP-104 parti-2 bitmiş ama "bekliyor" görünüyor; wiki "tek stabler site" diyor). Bu roadmap ile senkronlanmalı; `graphify update .` koşulmalı.

---

## 1. LCV Gerçeği ve Birleştirme Kararı (yeni iş kolu B)

Bugün üç landed-cost yolu var:
1. **Imports LCV motoru** (WP3/6b): Container Cost Line → GRN → lcv_math → taslak LCV + LandedCostReview ekranı. Saf mantık kiracı-bağımsız ama giriş kapısı `enable_imports`.
2. **Tender JSON'u** (v35): `PO.custom_landed_charges` Long Text — BidPricing/PoControlBoard marj hesabında okunuyor; **gerçek LCV üretmiyor**, stok değerlemesine binmiyor (sadece fiyatlama analizi).
3. **Generic Purchasing LCV** (2026-06-11 planı §C): hiç yazılmadı — artık yazılmamalı, imports motoru genelleştirilecek.

**B-planı (2-3 hafta, MSA cutover'ı beklemez):**
- B1. `lcv_math` + LandedCostReview'u modül-bağımsız hale getir: maliyet kaynağı arayüzü (Container Cost Line **veya** `custom_landed_charges` JSON **veya** serbest satır girişi) → aynı önizleme → aynı taslak LCV. Kapı: `enable_imports` VEYA yeni `enable_landed_cost` toggle.
- B2. Tender akışı köprüsü: PO'daki JSON satırlarını Purchase Receipt sonrasında tek tıkla gerçek LCV'ye dönüştür (Mikas: analizden gerçek stok maliyetine geçiş).
- B3. `imports_lcv_expense_account` → `Stabler Settings`'te genel landed-cost hesabına terfi; rol: LCV oluşturma Imports Manager/System Manager (Director hariç — sahip kararı).
- Kazanç: tüm kiracılara FAZ-2'nin "landed cost" maddesi kapanır; tek motor, tek test seti.

## 2. Horizon 1 — ŞİMDİ (0-4 hafta)

| # | İş | Cephe | Sahibi | Not |
|---|---|---|---|---|
| 1 | WP1-6b commit + anjan deploy + **msa'ya stabler kurulumu** | A | Zafar (Antigravity) + runbook | desk_gate kararı kurulum öncesi |
| 2 | MSA go-live konfigürasyonu: BRV/tier verisi, LCV hesabı, `has_batch_no`, IKPU backfill | A | Zafar + küçük WP | |
| 3 | **Mikas/UZEX go-live checklist yürütme**: lokal bench doğrulama → prod config (site_config, python-docx, Telegram setWebhook) → poller dry-run | C | Zafar (checklist hazır, yürütülmemiş) | Resmi UZEX API başvurusu paralel başlasın |
| 4 | **Horeca migration runbook'u koş** (8 adım, idempotent, "DO NOT RUN" işaretli — artık zamanı) + RN mobil repoint durumu netleştir | D | Zafar + 1 ajan desteği | Kill-switch 2 sayacı repoint'ten sonra başlar |
| 5 | WP7: masraf PI'larına konteyner/CI referans alanları + **Container Cost Ledger** raporu + vendor kesiti | A | ajan | Vendor Center izlenebilirlik sorusunun cevabı |
| 6 | CI STUFFED→GRN otomatik hook + K2 kalanı (parent toplu tahsilat, kredi kontrol hook'u, 14 PE dağıtımı) | A | ajan | |
| 7 | STATE.md/wiki senkronu + graphify update + bu roadmap'in tek gerçek kaynak ilanı | F | ajan (küçük) | |

## 3. Horizon 2 — SONRA (4-10 hafta)

| # | İş | Cephe |
|---|---|---|
| 8 | **B-planı: LCV birleştirme** (B1-B3) — tüm kiracılara landed cost | B |
| 9 | MSA Faz 3 ETL: taze dump (hâlâ açık R1!) → `stabler_msaerp_ref` → masters → açık zincir → dry-run #1 | A |
| 10 | EDO B0 keşif cevapları (kiracı başına EDS anahtarı/IKPU/ТТН ihtiyacı anketi) → B5 ТТН/Akt tasarımı | E |
| 11 | **Playwright E2E iskeleti** (FAZ-0 borcu): kritik 5 akış — login, SI oluştur, POS satış, imports CI→GRN, customer hierarchy | F |
| 12 | Çeviri kampanyası: 1.117 anahtar ×4 dil — ajanla toplu taslak + insan gözden geçirme (kiracı görünürlüğü yüksek modüller önce: sales, money, imports) | F |
| 13 | todo.md artıkları: sales raporu CSV/XLSX, taksit tahsilat makbuzu yazdırma, geciken taksit listesi | G/F |

## 4. Horizon 3 — DAHA SONRA (10+ hafta)

| # | İş | Cephe |
|---|---|---|
| 14 | MSA dry-run #2-3 → freeze mekanizması → **cutover + hypercare** (plan §8-9) | A |
| 15 | FORGE/ATLAS PRD kararı (batch/serial derinliği + 3D depo) — MSA batch deneyiminden sonra değerlendir | G |
| 16 | FAZ-1 Retail: offline POS, Z-report, rapor zamanlama — kiracı talebine göre önceliklendir | G |
| 17 | Deploy otomasyonu: en azından tek komut deploy + site-bazlı health check; blue-green FAZ-3 | F |
| 18 | xarid.uzex.uz / dxarid (devlet ihaleleri) ayrı keşif | C |

## 5. Bağımlılık Grafiği (kritik yol)

```
msa kurulum ──► MSA go-live config ──► ETL dry-run ──► cutover
     │
     └──► WP7 + K2 kalanı (kurulumdan bağımsız kodlanır, kurulumla test edilir)

LCV birleştirme (B) ── bağımsız; Mikas PR akışı canlıysa B2 hemen değer üretir

Mikas go-live ── yalnız operasyonel adımlar (kod hazır)
Horeca runbook ── yalnız operasyonel (kod hazır) ──► kill-switch 2 (30 gün sonra)

E2E iskeleti ── her cutover'ın sigortası; Horizon 2'de şart
```

## 6. Zafar'ın Masasındaki Kararlar/Eylemler (kod değil)

1. desk_gate kararı (msa kullanıcıları Desk kullanıyor mu?) — kurulum öncesi
2. Taze MSAERP production dump (R1 — 5 haftadır açık)
3. UZEX resmi API başvurusu
4. Horeca runbook yürütme onayı + RN mobil repoint bilgisi
5. Muhasebeci imzaları: VAT-LCV dışı, agreed-GL görünürlüğü (K3), tek period-close rejimi
6. EDO anketi: hangi kiracıda EDS anahtarı/IKPU hazır
7. Parity denetimindeki 8 sahip kararı (00-INDEX.md §Sahip Kararı)

---
*Bu doküman tüm cephelerin tek gerçek kaynağıdır; her horizon kapanışında güncellenir. Detay planlar: MSA → 2026-07-09 serisi; Tender → uzex-go-live-checklist; Horeca → 2026-06-12 runbook; EDO → EDO_integratsiya_yol_xaritasi.*
