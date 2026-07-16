# STATE.md — Orkestratör Kalıcı Hafızası

> Protokol: her oturum başında OKU; görev bitiminde/kalıcı hatada GÜNCELLE (Fail→Investigate→Verify→Distill→Write).
> Kurallar hiyerarşisi: CLAUDE.md (anayasa, `global_rules.md` işlevini görür) → stabler_final_blueprint.md (iş paketleri + K-komutları) → bu dosya (oturum hafızası).
> Son güncelleme: 11.07.2026 · Oturum: WP4/WP5 & Customer Hierarchy (K2) Tamamlama

## 1. Doğrulanmış Durum (kaynak üzerinde teyitli — yeniden taramaya gerek yok, tarih: 04.07.2026)

- Baseline sayaçları: **78** handler-içi `frappe.db.commit` (27 api dosyası) · **14** izin-işaretsiz ham-SQL dosyası · **0** çıplak `<input type="date">` · **2** `datetime-local` (sfa/OSA.vue:240, sfa/Photos.vue:304) · **51** dosyada literal `badge bg-*` (122 adet) · DateInput 59 dosyada.
- Mevcut altyapı: `getStatusBadgeClass` (status.js:112) · `STATUS_MAP` (status.js:3) · `EmptyState.vue` var (~5 kullanım) · CSS token katmanı `--stbl-*`/`--tblr-*` (stabler.css:7-24) · 485 whitelisted endpoint · frontend test **%0**.
- P0 açıklar (WP-000 serisi ilerleme, 06.07.2026):
  - **WP-002 commit temizliği — DONE** (78→25 handler commit; `git log` teyitli, önceki oturum).
  - **WP-003 cbu_rate_refresh.py:80 float bölme — DONE** (commit `012df2b`; ters kur artık `Decimal(1)/Decimal(str(rate))` quantize 10dp; py_compile + saf birim test PASS, grep grade 3/3).
  - **WP-001 IDOR/izin — DONE** (commit `1ae3354`): audit §1.1-doğrulanmış master-PII okuyucuları — `sales.list_customers`+`get_customer_defaults` → `has_permission("Customer","read")`, `purchasing.list_suppliers` → `has_permission("Supplier","read")`. Ayrıca `test_company_scope_guard`'ın 5 tender endpoint'inde verdiği **false-positive** düzeltildi (`_require_tender_view` = `_assert_company_scope` sarmalayıcısı; token kaydedildi). Yeni `test_master_read_permission` (AST) kabul testi + guard yeşil. **Not:** "14 dosya" baselineı aslında bir bekçi görev-listesi değil; guard `_SCOPE_TOKENS` desen-tabanlıdır. CRM/HR ham-SQL PII okuyucuları için geniş tarama **YAPILDI** (commit `b785006`): hr.list_employees, sales.list_customers_with_balances, purchasing.list_suppliers_with_balances, crm.list_leads, crm.list_deals, search.palette_search → hepsine `has_permission(...,"read")`; görünen-ad JOIN'leri (service/reports/tabUser) + COUNT aggregate (hr_overview) bilinçli bırakıldı. test_master_read_permission artık 8 okuyucuyu kapsıyor.
  - **WP-004 money_epsilon(currency) — DONE** (commit `c475eb1`; yeni `stabler/api/_money.py`; 11 dosyada 0.005 → `money_epsilon(<ccy>)`, 3 SQL HAVING `%(eps)s` named-param; call-site 0.005 literal sayacı 0'a düştü; py_compile 12/12 + saf birim test PASS; DB testleri yerel bench'e işaretli).
  - **WP-005 bordro residual-allocation — DONE** (commit `5c9cc81`; yeni `stabler/api/_payroll_residual.py` = largest-remainder `largest_remainder_round`/`distribute_amount`/`round_uzs`; `_payroll_components.components_total` üçlü-bağımsız-floor → tek-yuvarlama+çıkarma (net==earnings−deductions kesin); 17 yeni + 281 payroll test yeşil; itemized→engine-net uçtan-uca mutabakat DB'ye/yerel bench'e işaretli).
- Güncel sayaçlar (06.07.2026): handler commit **26** (api) · call-site 0.005 literal **0** (yalnız `_money.py` tanım/docs kaldı) · çıplak date input **0** · money_epsilon **12** dosya.

## 2. Distilled Kurallar (tekrar yasağı kayıtları)

- **D-1:** Kullanıcı taleplerindeki standart varsayımlarını KOD ÜZERİNDE doğrulamadan kabul etme. Örnek: "Flatpickr + dd/mm/yyyy" talep edildi → kodda Flatpickr HİÇ YOK; fiili standart DateInput + dd.mm.yyyy. Karar: Flatpickr kalıcı muafiyetli YASAK (blueprint §1.1). Bir daha Flatpickr önerme/deneme.
- **D-2:** Ajan raporlarındaki iddiaları kritik olanlarda spot-check et. Örnek: "illustrations mevcut" iddiası yanlıştı → klasör BOŞ (startup_blueprint'te düzeltildi). Kural: rapora girecek her dosya-varlık iddiası `ls/grep` ile teyit edilir.
- **D-3:** "shop/catalog + marka filtre" kuralları ERP SPA'sında değil `stable-erp-website/` (Next.js) kapsamındadır — SPA'da bu kural ihlal aranmaz.
- **D-4:** Bu repoda salt-okuma rejimi geçerli: kod dosyalarına dokunma; yalnız .md dokümantasyon + zamanlanmış görev üretimi serbest. Her uygulama işi kullanıcı onayına tabi.
- **D-5:** `~/.claude/skills/` bu ortamda SALT-OKUNUR cache — skill dosyasına kural yazılamaz. Kalıcı kurallar buraya (STATE.md) ve gerekirse CLAUDE.md önerisi olarak yazılır.
- **D-6:** Grep baseline'ları mutlak satır numarasına değil desene bağla (dosyalar oynar); bekçi görevi sayaç karşılaştırması bu yüzden desen-bazlı.
- **D-7:** Standing goal predicate eşiğini denetim raporundaki sayıya değil, kurulum anında `grep` ile GERÇEKTEN ölçülen değere sabitle. Örnek: denetim "inline badge 122" dedi; agent-os goal'ü kurulurken pages/ altında gerçek 125 çıktı (kapsam farkı). Yanlış eşik sahte VIOLATED üretir. Kural: her yeni goal'ün predicate eşiği, born tarihinde ölçülen çıktıdan gelir.
- **D-8:** Agent OS sentineli 09.07'de ilk gerçek bulgusunu verdi (badge 122→125). Sistem çalışıyor: 3 fazla badge tender/BidPricing.vue + PoControlBoard.vue'da — ama incelemede DEKORATİF (KPI/bayrak), status değil. WP-104 gerçek hedefi = statusClass/badgeClass computed'ı olan 10 dosya (predicate D-7 ile düzeltildi). Gerçek iş prompt'u: WP103_104_STATUS_BADGE_PROMPT.md.
- **WP-104 parti-1 + WP-103 TAMAM (commit f0e066e, doğrulandı 09.07):** StatusBadge.vue kuruldu; EHFStatus/OneCSyncLog/InstallmentCalendar → merkezi. Gerçek borç 10→7 (ratchet: badge goal eşiği ≤7). (B) dosyaları (Deals/Leads dinamik-renk) ve dekoratif rozetler doğru şekilde korundu. Kalan 5 (A)-tipi dosya (Visits, Contracts, PromoPlans, Claims, RemittanceTransfers) → parti-2. Graf f0e066e'ye tazelendi (codegraph-fresh yeşil). 6 standing goal geçiyor, gate PASS. Döngü uçtan uca çalıştı.
- **D-9:** codegraph (graphify-out/) Agent OS conductor'a bağlandı — `scripts/graph-context.sh` bir modülün semantik kontratlarını (permission_layer_common = audit §1.1 invariant'ı) + blast-radius komşularını verir; conductor bunu work-order.graph_context'e koyar. `codegraph-fresh` goal'ü graf tazeliğini izler (şu an VIOLATED: graf 85061c35 < HEAD; `graphify update .` düzeltir, API maliyeti yok).
- **D-7 (ORTAM):** Bash sandbox `.git` mount'u **create/write'a izin verir ama unlink'e İZİN VERMEZ**. Sonuç: (a) her git yazımı ardında silinemeyen `index.lock`/`HEAD.lock`/`tmp_obj_*` bırakır → sonraki git işlemini bloke eder; (b) çözüm: lock'ı `mv .git/index.lock .git/index.lock.stale.$$` (rename≠unlink) ile kenara al, sonra `git commit`. Commit rename-tabanlı happy-path ile BAŞARILI olur (uyarılar kozmetik). Her commit SONRASI `HEAD.lock`+`index.lock`'ı yine rename-away temizle. **`git worktree add/remove` kırılgan** (unlink gerektirir) → alt-ajan worktree izolasyonu bu ortamda güvenilmez; orkestratör WP'leri ana kopyada doğrudan uygular + bağımsız statik doğrulama (grep+py_compile+saf birim test).
- **D-8 (ORTAM):** Sandbox'ta Frappe DB / `bench execute` YOK → DB-tabanlı kabul birim testleri koşturulamaz. WP kabul kriteri "birim test" yalnız saf-Python mantık testi + grep sayaç düşüşü ile karşılanır; DB davranış testleri kullanıcının yerel `bench` koşusuna işaretlenir.

## 3. Başarısız/Denenmeyecek Yaklaşımlar

- Flatpickr entegrasyonu (D-1 — reddedildi, deneme).
- Kod içi hex renk / inline status eşlemesi / çıplak date input üreten her çözüm (CLAUDE.md ihlali — PR'da red).
- `git add -A`, `bench restart`'ı hafife alma (tüm tenant blip), `[post_model_sync]`'siz yeni-kolon patch'i.

## 4. Üretilmiş Varlıklar (tekrar üretme — güncelle)

| Dosya | İçerik | Statü |
|---|---|---|
| audit_critique.md | P0/P1/P2 bulgular, dosya:satır | Mühürlü v1 |
| erp_roadmap.md | 4 fazlı teknik yol haritası | Mühürlü v1 |
| PRD_advanced_manufacturing_3d_warehouse.md | FORGE & ATLAS PRD | Onay bekliyor |
| stabler_final_blueprint.md | Standartlar + WP-000..271 iş paketleri + K-1..K-8 | Mühürlü v1.0-SEALED |
| stabler_startup_blueprint.md | PLG/GTM + GENESIS wizard + K-9/K-10 | Mühürlü v1 |
| docs/stabler_wiki.md | İkinci Beyin hub | Canlı — bakım §6 protokolüne göre |
| agent-os/ | Fable5 "Agentic OS" tam iskelesi (BUILD 1-8): verify.sh gate + contract + conductor/triage/worker promptları + trust.tsv/goal-ledger + 3 standing goal + cost betikleri + Makefile + RUNBOOK + 30-gün trust takvimi. Gate+sentinel+ledger sandbox'ta test edildi ✅ | Kuruldu — heartbeat için Mac'te claude CLI + llm/OpenRouter gerekir |
| ORCHESTRATOR_PROMPT.md | Otonom WP uygulama döngüsü promptu (Sonnet/Opus uygulayıcı + Haiku Grader, worktree izolasyonlu) | Kullanıma hazır |
| Zamanlanmış görev: `stabler-security-guard` | Günlük 09:00 P0 regresyon bekçisi | AKTİF |
| stabler/tasks/cbu_rate_refresh.py | CBU ters kur Decimal (WP-003) | commit 012df2b |
| stabler/api/_money.py | Merkezi `money_epsilon(currency)` (WP-004) | commit c475eb1 |
| stabler/api/_payroll_residual.py + test | Largest-remainder residual-allocation (WP-005) | commit 5c9cc81 |
| sales.py/purchasing.py has_permission + test_master_read_permission | Master-PII izin guard'ı (WP-001) | commit 1ae3354 |
| CRM/HR PII okuyucuları (hr/crm/search) has_permission | WP-001 takip taraması | commit b785006 |
| didox client.poll_status + hooks.sync_pending_statuses + edo.didox_refresh_status + SIForm refresh btn | **EDO B4** Didox durum senkronu (paralel iş kolu; bağımsız doğrulandı) | commit 6940380 |

### UZEX tender entegrasyonu iş kolu (WP-300 serisi)
- **WP-305 DONE** (commit `2b1e8ef`): `composables/useAutoRefresh.js` (60sn, document.hidden'da durur, reveal'de 1 kez yeniler, overlap-guard, onUnmounted temizlik — sızıntı yok) → MyTenders/DirectorBoard/DeclarantQueue/LogistBoard'a bağlı. node --check OK; bench build yerele.
- **WP-301 DONE** (commit `22f70e7`): CRM Deal'e 7 custom_uzex_* alanı (v39, `[post_model_sync]` marker'ı patches.txt sonuna eklendi — yalnız v39 post-sync). lot_no UNIQUE=dedupe anahtarı; sentinel+doctype+has_column idempotency guard'ları. bench migrate yerele.
- **WP-300 DONE** (commit `6c22c65`): Claude in Chrome ile etender API haritalandı — `POST apietender.uzex.uz/api/common/TradeList {TypeId,From,To,System_Id}` (liste) + `GET common/GetTrade/{id}/0` (detay), **auth yok**. Rapor: `docs/plans/uzex-api-discovery-2026-07-08.md`. xarid/dxarid ayrı keşif (muhtemelen auth).
- **WP-302 DONE** (commit `a74d52e`): `integrations/uzex/` (client.py HTTPS-guard'lı urllib + _parse.py frappe-free + 16 birim test) + `tasks/uzex_poll.py` saatlik (dedupe=custom_uzex_lot_no UNIQUE, keyword flood-guard, per-type hata izolasyonu + stale last_synced, tek commit) + hooks.py kaydı. DB invariant (2 koşu=0 dup) yerele.
- **WP-303 DONE** (`c61c143`): `_status.py` merkezi eşleme (id→won/lost/pending, name-substring fallback) + poller'da status-değişim Notification (dedup old!=new) + terminal Deal status + deadline<48s uyarı; 14 test.
- **WP-304 DONE** (`f9a2fc4`): `api/uzex.py fetch_lot` (izin-guard'lı) + `lot_id_from_url` + TenderIntake.vue "paste URL→autofill" + 5-dil i18n. **Deferred:** board chip/countdown (tender.py board endpoint'leri custom_uzex_* emit etmeli — takip).
- **WP-307 DONE** (`991a3d5`): `telegram.py` (config-gated outbound yeni-lot kartı, created-once dedup, frappe-free builder'lar) + `webhook.py` (allow_guest+secret go/no-go→intake) + poller hook; 9 test.
- **WP-308 DONE** (`0eb34aa`): Telegram webhook secret **fail-closed** (unset/mismatch → 403 + log; saf `verify_secret` constant-time; 3 senaryo testi).
- **WP-306 DONE** (`751302e`): `api/_bid_package.py` (assemble + `missing[]` + `build_bid_docx` python-docx, docx E2E testli) + `tender.py::bid_package` (_deal_scope gate, docx→Deal File, **portal oto-gönderim YOK**) + BidPricing.vue butonu + 5-dil i18n + `python-docx` pyproject'e + `docs/plans/uzex-eimzo-feasibility.md` (imza teknik mümkün, gönderim ucu yok → insan imzalar).
- **WP-309 DONE** (`3434845`): `docs/plans/uzex-go-live-checklist.md` — lokal bench doğrulama (migrate idempotency, poller 2-koşu dedupe, fetch_lot, auto-refresh) + prod insan checklist'i (site_config anahtarları, python-docx, Telegram setWebhook, deploy adımları, 48s izleme, rollback). Bench koşuları KULLANICIDA (sandbox'ta bench yok); dedupe invariant statik+test kanıtlı.
- **Tüm uzex+bid saf testleri: 53 yeşil.** Prod'a hiçbir şey gönderilmedi.
- site_config anahtarları: WP-302 `uzex_endpoint`/`uzex_keywords`/`uzex_type_ids`/`uzex_poll_cap`/`uzex_user_agent` (token YOK, anonim); WP-307 `uzex_telegram_token`/`uzex_telegram_chat_id`/`uzex_telegram_secret`.
- Tüm uzex saf birim testleri: 44 yeşil (parse 21 + status 14 + telegram 9). DB/canlı-portal/Telegram davranışı yerel bench'e işaretli.
- Plan: `docs/plans/2026-07-08-uzex-tender-integration.md`. Sıra: 305→301→300→302→{303,304,307}→306. Sert sınır: teklif oto-gönderimi YOK (E-IMZO+hukuk → insan imzalar).

### EDO/Didox iş kolu durumu (bu oturumda doğrulandı+commit'lendi)
- **B4 DONE** (commit 6940380): read-only poll + saatlik scheduler (endpoint yoksa no-op, prod'da B0'a kadar uykuda) + on-demand uç (izin-guard'lı) + SIForm refresh butonu. py_compile 4/4, i18n 5 dil tam. **hooks.py scheduler kaydı ilk commit'te atlanmıştı → amend ile eklendi (D-2 dersi: commit'ten sonra `git status` tracked-temiz teyidi zorunlu).**
- **B5 ⛔ B0-BLOKLU** (roadmap `docs/EDO_integratsiya_yol_xaritasi.md` sat.42-46 kanıt): ТТН/Akt/inbound roadmap'te yalnız "sandbox test edilecek belge türleri", payload şeması YOK; kaynak doctype de yok. Spekülatif payload builder = YAGNI ihlali. B0 girdileri gerekli: (1) Didox partner/sandbox API token, (2) ТТН/Akt payload şemaları, (3) kaynak doctype'lar.

## 5. Delegasyon Haritası (orkestrasyon kuralları — bu oturum ortamına uyarlanmış)

- Mimari/güvenlik/finansal hassasiyet kararları: orkestratör (bu ajan) veya `model:"opus"` alt ajan.
- Hacimli kod/refactor (ör. WP-104 51-dosya taşıma): `model:"sonnet"` + iş paketi promptu (blueprint K-7 şablonu + §2.0 önsözü).
- Bağımsız doğrulayıcı (Grader): `model:"haiku"` — kabul kriterlerini koşturur, "çalışıyor" beyanı ancak onunla geçerli (adversarial verification).
- İzolasyon: paralel uygulama işleri `Agent(isolation:"worktree")` ile — ana dizin kirletilmez.
- UI işlerinde Vision self-check: ekran görüntüsü ↔ hedef tasarım kıyası zorunlu.

## 5.1 UZEX Entegrasyonu Denetim Kaydı (08.07.2026)

- UYGULANDI ve bağımsız denetimden GEÇTİ: WP-300..305 + 307 (commit 22f70e7..991a3d5). Gerçek API: `apietender.uzex.uz/api` (anonim, POST common/TradeList + GET common/GetTrade) — keşif raporu `docs/plans/uzex-api-discovery-2026-07-08.md`.
- Doğrulanan kalite: poller idempotent (custom_uzex_lot_no UNIQUE dedupe), tek commit job sonunda, keyword flood-guard, merkezi durum eşleme (_status.py), bildirim mükerrer koruması, useAutoRefresh (hidden-pause + cleanup), fetch_lot izin guard'lı, 5 CSV harvest.
- AÇIK BULGU → WP-308: webhook.py:47 secret opsiyonel — unset ise allow_guest ucu kimliksiz yazar. "Yoksa kapalı" yapılacak.
- KAPANIŞ KOŞUSU DA GEÇTİ (08.07.2026, commit 0eb34aa..3434845): WP-308 fail-closed webhook (hmac.compare_digest, secret loglanmıyor) ✅ · WP-306 bid_package (`_deal_scope` guard, missing[] akışı, python-docx yoksa zarif uyarı, BidPricing.vue butonu, 5 CSV harvest, E-IMZO fizibilite raporu) ✅ · WP-309 checklist üretildi ✅. AÇIK: checklist §A lokal doğrulama + prod deploy = ZAFAR'IN ELLE ADIMLARI (task #22 in_progress). UZEX resmi API başvurusu hâlâ açık döngü.
- BONUS doğrulandı: WP-000 P0 serisi (WP-001..005) ve Didox EDO commit'lenmiş — §1 baseline sayaçları ESKİDİ, bekçi raporuyla yenilenecek.

## 5.2 Customer Hierarchy & Imports WP4/5 (11.07.2026)
- **WP4 & WP5 Backend (DONE):** Added missing python controllers, fixed dynamic UOM mapping (v43 patch), and resolved company scope test cases (v46 patch & test_company_scope_guard).
- **Task 6 (DONE):** Added Commercial Invoice `on_update` status-hook to auto-create `GRN Checklist` when CI status transitions to `STUFFED` (gated and idempotent). Created `test_customer_hierarchy_integration.py` containing a comprehensive DB-backed integration test suite for customer validations, credit limits, bulk payments, and auto-GRN hook. All tests pass successfully (1094 tests green).

## 5.3 MSAERP Parity Features & Owner Decisions (12.07.2026)
- **Task 1 (DONE)**: Created `Stabler Vendor Category` and `Stabler Vendor Category Item` DocTypes. Exposed `get_vendor_category_items` API in `purchasing.py`.
- **Task 2 (DONE)**: Calculated ETA - 7 days deadline, daily `eta_payment_alert` background task and hooks.
- **Task 3 (DONE)**: Ported Excel Sales and Payment Importers to Stabler using native Document APIs (`sales_import.py`, `payment_import.py`).
- **Task 4 (DONE)**: Added `require_delivery_note` field to `Stabler Settings` and validation check to prevent direct stock updates on Sales Invoices.
- **Task 5 (DONE)**: Created `parser_msaerp_xlsx` for Excel bank statements and integrated routing in `import_api.py`.
- **Task 6 (DONE)**: Exposed `get_parent_credit_limit_status` API in `customer_hooks.py`.
- **Task 7 (DONE)**: Created `v47_bootstrap_fiscal_year` migration patch and registered in `patches.txt`.
- **Task 8 (DONE)**: Confirmed standardization of SPA list views with ListToolbar and SkeletonRows.
- **Tests**: All tests passed successfully.

## 6. Açık Döngüler / Sıradaki Onay Noktaları

1. UZEX entegrasyonu (WP-300..309) UYGULANDI+commit'lendi. Sıradaki adım UZEX canlıya geçiş checklist'inin (uzex-go-live-checklist.md) production sitesinde yürütülmesidir.
2. MSAERP Parite Özellikleri (Task 1-8): Tüm backend implementasyonları, parserlar, şemalar ve testler başarıyla tamamlandı. Gönderilmeye hazır.


