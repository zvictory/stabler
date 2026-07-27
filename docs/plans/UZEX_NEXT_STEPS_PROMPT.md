# UZEX — SONRAKİ ADIMLAR Promptu (Cowork, model: Opus 4.8)
# Bağlam: WP-300..305 + 307 uygulandı ve bağımsız denetimden geçti (08.07.2026).
# Kalan: WP-308 (güvenlik fix'i), WP-306 (bid paketi), WP-309 (go-live doğrulama).
# Kullanım: "---" arası bloğu yeni Cowork oturumuna yapıştır.

---

Sen Stabler projesinin UZEX entegrasyonu kapanış orkestratörüsün. Çalışma klasörü: /Users/zafar/frappe-bench-local/apps/stabler. WP-300..305 ve 307 tamamlandı (git log: 22f70e7..991a3d5). Görevin: kalan 3 paketi bitirip entegrasyonu canlıya hazır hale getirmek.

## 0. BAŞLANGIÇ (atlanamaz)
Sırayla oku: `STATE.md`, `CLAUDE.md`, `docs/plans/2026-07-08-uzex-tender-integration.md`, `docs/plans/uzex-api-discovery-2026-07-08.md` (API şeması), `stabler_final_blueprint.md` BÖLÜM 2.0 (alt ajan önsözü). Mevcut kodu oku: `integrations/uzex/*` (client, _status, _parse, telegram, webhook), `tasks/uzex_poll.py`, `api/uzex.py`, `patches/v39_deal_uzex_fields.py`, `pages/tender/TenderIntake.vue`. Döngü mekaniği ORCHESTRATOR_PROMPT.md ile aynı: worktree'de Sonnet uygulayıcı + bağımsız Haiku doğrulayıcı, PASS'sız task kapanmaz, explicit-path commit, prod'a dokunmak ve git push YASAK.

## 1. WP-308 — Telegram webhook secret'ını ZORUNLU yap (İLK İŞ, küçük ama P1)
Bulgu: `integrations/uzex/webhook.py:47` — `uzex_telegram_secret` yalnızca TANIMLIYSA doğrulanıyor. Config unset ise `allow_guest` ucu kimliksiz POST kabul eder ve `_set_go_no_go` `ignore_permissions=True` ile Deal'e yazar.
Fix: secret unset VEYA başlık uyuşmaz ise `frappe.throw(..., frappe.PermissionError)` — "yoksa açık" değil "yoksa kapalı". Ayrıca yanlış-secret denemesini `frappe.log_error` ile kaydet.
Kabul: birim test 3 senaryo — (a) secret unset → 403, (b) yanlış başlık → 403, (c) doğru başlık → applied. `bench build` gerekmez (yalnız py).

## 2. WP-306 — Bid paketi üretimi + E-IMZO etüdü (insan onaylı gönderim)
Girdi: CRM Deal'in `custom_tender_intake` + `custom_bid_pricing` JSON'ları ve `custom_uzex_*` alanları (v39). Mevcut P&L motoru: `api/tender.py::_compute_bid_pnl`.
Yapılacak:
a. `api/tender.py`'ye `bid_package(deal)` endpoint'i (blueprint §2.0 sözleşmesi: has_permission + module gate) — başvuru veri setini tek JSON'da toplar: lot bilgisi, teklif fiyatı/marj dökümü (Остаток dahil), deadline, şirket bilgileri, eksik alan listesi (`missing[]` — paket eksikse insan görsün).
b. Doküman üretimi: teklif mektubu + fiyat teklifi tablosu (docx skill'i ile şablon; şirket adı/lot no/tutar alanları doldurulur; tarih dd.mm.yyyy). Dosyalar Deal'e File attachment olarak bağlanır. ÖNCE veriyi topla, SONRA docx skill'ini oku (araştırma-önce kuralı).
c. TenderIntake.vue veya BidPricing.vue'ya "Başvuru paketini hazırla" butonu (btn-outline-secondary; tek btn-primary kuralına dikkat) → paket üretilir, eksikler EmptyState/uyarı ile listelenir, dosyalar indirilebilir.
d. E-IMZO ETÜDÜ (kod değil, rapor): `public/js/lib/eimzo.js` didox akışının UZEX teklif imzasına uyarlanabilirliği — `docs/plans/uzex-eimzo-feasibility.md` (imza formatı, portal upload akışı, riskler, tavsiye).
SINIR: portala otomatik teklif GÖNDERİMİ YOK — paket hazırlanır, insan portalda imzalar/yükler. Bu bilinçli kapsam sınırı, ihlal etme.
Kabul: sahte deal ile paket üretimi E2E; eksik-alan senaryosu `missing[]` döner ve UI listeler; docx açılır ve alanlar dolu; 5 CSV harvest; Haiku doğrulayıcı PASS.

## 3. WP-309 — Lokal go-live doğrulaması + prod checklist (DEPLOY ETME)
Lokal sitede sırayla çalıştır ve çıktıları rapora koy:
a. `bench --site <lokal-site> migrate` → v39 temiz; ikinci `migrate` → 0 değişiklik (idempotency).
b. site_config'e test değerleri koy (`uzex_keywords: ["kabel"]` gibi) → `bench execute stabler.tasks.uzex_poll.fetch_and_store` → summary'yi kaydet; AYNI komutu ikinci kez koş → created=0 (dedupe invariant'ı CANLI veriyle kanıtla).
c. `fetch_lot` ucunu gerçek bir lot URL'siyle dene (500606 veya güncel bir lot) → alanlar doluyor mu.
d. Tender board'da 60sn auto-refresh'in çalıştığını doğrula (network sekmesi/log).
e. PROD İÇİN İNSAN CHECKLIST'İ üret (uygulama YOK — CLAUDE.md deploy prosedürüne referansla): site_config anahtarları (uzex_keywords, uzex_type_ids?, uzex_telegram_secret, telegram bot token/chat id — telegram.py'deki isimleriyle), Telegram `setWebhook` komutu (secret_token'lı), rsync+build+migrate adımları, ilk 48 saat izleme (Error Log'da "UZEX poll" başlıkları + custom_uzex_last_synced tazeliği), geri alma planı (hourly hook'u yorumlamak yeterli).
Kabul: b'deki ikinci koşu created=0; rapor `docs/plans/uzex-go-live-checklist.md` olarak kaydedilir.

## 4. KAPANIŞ
STATE.md'yi güncelle (§4 varlıklar, §6 açık döngüler: "UZEX resmi API başvurusu" açık kalır). Kapanış raporu: biten paketler, commit listesi, prod checklist'in yeri, kullanıcının atması gereken adımlar. Sonra DUR.

---

# Operatör Notları (Zafar için)
- Denetim özeti (08.07.2026): WP-300..305+307 kabul kriterlerinin tamamından geçti — gerçek API bulundu (apietender.uzex.uz, anonim), poller idempotent (lot_no unique dedupe), tek commit job sonunda, keyword flood-guard, bildirimler mükerrersiz, useAutoRefresh sızıntısız, 5 dil harvest edilmiş. Tek bulgu: webhook secret'ının opsiyonel olması (→ WP-308).
- Bonus: Opus oturumu WP-000 P0 serisini de commit'lemiş (WP-001..005: IDOR guard'ları, MONEY_EPSILON, CBU Decimal, bordro residual) + Didox EDO entegrasyonu. Yarınki stabler-security-guard raporunda sayaçların düştüğünü teyit et.
- Prod'a çıkış her zaman senin elinde: ajan yalnız checklist üretir, CLAUDE.md prosedürünü sen koşarsın.
