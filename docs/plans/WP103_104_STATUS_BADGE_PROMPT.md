# WP-103 + WP-104 İlk Parti — StatusBadge Prompt (Cowork, model: Sonnet)
# Kullanım: "---" arası bloğu yeni Cowork oturumuna yapıştır. Bağımsız Haiku doğrulayıcı ile.
# NOT: "3 tender badge'i taşı" ISTEĞI YANLIŞ ÇIKTI — o 3'ü dekoratif (KPI/bayrak), status değil.
#       Bu prompt doğru işi yapar: önce StatusBadge kur (WP-103 yapılmamış), sonra GERÇEK
#       status eşlemesi olan dosyalardan küçük bir partiyi taşı; dekoratifleri bırak.

---

Sen Stabler SPA'sında merkezi status rozet refaktörünün ilk partisini uyguluyorsun.
Çalışma klasörü: /Users/zafar/frappe-bench-local/apps/stabler. SALT bu partideki dosyalara dokun.

## 0. BAŞLANGIÇ (oku, uydurma)
1. Oku: `STATE.md` (özellikle D-7/D-8 dersleri), `CLAUDE.md` (Striped tables / Centralized status codes blokları), `stabler_final_blueprint.md` §1.3 (WP-103/104 spec).
2. Oku ve deseni öğren: `stabler/public/js/composables/status.js` — `STATUS_MAP` (satır 3), `getStatusBadgeClass(doctype, status)` (satır 143), `getDocstatusLabel(docstatus)` (satır 169). Bunlar ZATEN VAR; yeniden yazma.
3. `components/` altında MoneyInput.vue / DateInput.vue gibi mevcut basit bileşenlerin stilini örnek al.

## 1. WP-103 — StatusBadge.vue oluştur (önce bu; şu an YOK)
Dosya: `stabler/public/js/components/StatusBadge.vue`.
- Props: `{ doctype: String (reqd), status: String, docstatus: Number|null }`.
- Template: `<span class="badge" :class="cls">{{ label }}</span>`.
- `cls` = `getStatusBadgeClass(doctype, status)`; eşleşme yoksa `"bg-secondary-lt"` + dev modunda `console.warn("STATUS_MAP missing:", doctype, status)` (yalnız import.meta.env.DEV).
- `label` = `status` doluysa `t(status)`; boş ve `docstatus` verilmişse `getDocstatusLabel(docstatus)`.
- i18n: `t` mevcut composable'dan (`composables/i18n.js`). Yeni görünür string yok (status değerleri zaten harvest'li).
Kabul: birim/görsel test — bilinen doctype+status doğru sınıf; bilinmeyen status → bg-secondary-lt + warn; docstatus yolu label döndürür.

## 2. WP-104 İlk parti — SINIFLANDIR, sonra SADECE gerçek olanları taşı
Aday 10 dosya (statusClass/badgeClass computed'ı olanlar):
  remittance/RemittanceTransfers · crm/Deals · crm/Leads · admin/compliance/EHFStatus ·
  admin/compliance/OneCSyncLog · marketing/PromoPlans · marketing/Claims ·
  installment/InstallmentCalendar · installment/Contracts · service/Visits

**Her dosyayı önce sınıflandır (rapora yaz):**
- (A) SABİT harita: status → renk/sınıf sayfa içinde sabit kodlanmış (ör. `case "Paid": return "bg-green"`). → GERÇEK hedef, taşı.
- (B) DİNAMİK renk: renk doctype kaydının kendi `color` alanından geliyor (ör. `statusClass(statusByName[x]?.color)` — CRM Deals/Leads böyle). → MEŞRU, DOKUNMA (StatusBadge bunu karşılamaz; sahte eşleme uydurma).

**Bu ilk partide YALNIZCA en fazla 3 adet (A) tipi dosyayı taşı.** Muhtemel (A) adayları: EHFStatus, OneCSyncLog, InstallmentCalendar — ama SEN kodu okuyup teyit et, benim listeme güvenme.
Taşıma: sayfadaki sabit status→sınıf haritasını `STATUS_MAP`'e uygun doctype anahtarı altında ekle (renk semantiği: taslak=secondary, beklemede=yellow, kısmi=orange, aktif/işlemde=blue/azure, tamam=green, iptal/başarısız=red, dondurulmuş=purple), sayfadaki yerel `statusClass/badgeClass` fonksiyonunu sil, `<StatusBadge :doctype=".." :status="row.status" />` kullan.

**DOKUNMA:** dekoratif rozetler — BidPricing.vue'daki "Margin/Markup %" KPI etiketleri ve PoControlBoard.vue'daki "Cheapest (landed)" bayrağı status DEĞİL; bunlar Tabler utility rozeti olarak kalır. (B) tipi dinamik-renk sayfaları da bırak.

## 3. KABUL (bağımsız Haiku doğrulayıcı koşturur)
- `components/StatusBadge.vue` var ve WP-103 kabul testleri geçer.
- Taşınan her (A) dosyada yerel status→sınıf haritası kalmadı; `<StatusBadge>` kullanılıyor; sayfa direct-URL refresh ile açılıyor (form-hardening deseni).
- STATUS_MAP'e eklenen status'lar 5 CSV'de (en/ru/uz/uzc/tr) harvest'li.
- `grep -rIln 'statusClass|badgeClass|statusColor' stabler/public/js/pages --include='*.vue' | wc -l` sayısı DÜŞTÜ (10 → ≤7).
- Dekoratif rozetlere ve (B) dosyalarına dokunulmadı.
- Agent OS gate yeşil: `APP_ROOT=$(pwd) agent-os/loop/guardrails/verify.sh` → GATE PASS.
- CLAUDE.md ihlali yok (git add -A yok, inline yeni harita yok).

## 4. KAPANIŞ
Değişen dosyaları explicit stage et; commit "WP-104(parti-1): <dosyalar> → StatusBadge; WP-103 StatusBadge.vue" + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
Rapora: sınıflandırma tablosu (her 10 dosya A/B), taşınanlar, yeni STATUS_MAP anahtarları, güncel statusClass dosya sayısı.
Sonra: `agent-os/loop/goals/status-badge-no-growth.md` predicate eşiğini yeni sayıya (≤7 gibi) DÜŞÜR — ratchet. DUR.

---

# Operatör Notu (Zafar için)
- Bu, Agent OS sentineli'nin yakaladığı bulgunun DOĞRU kapanışı. Sentinel "125 badge" demişti;
  araştırınca çoğu dekoratifti — gerçek borç 10 statusClass dosyası. Prompt bunu hedefliyor.
- WP-103 (StatusBadge bileşeni) blueprint'te WP-104'ün ön koşuluydu ve yapılmamıştı; bu prompt ikisini birleştiriyor.
- Parti küçük (≤3 dosya) bilinçli — ratchet: her parti eşiği düşürür, sistem büyümeyi yakalar.
