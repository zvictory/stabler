# WP-104 Parti-2 — StatusBadge Prompt (Cowork, model: Sonnet)
# Kalan 5 (A)-tipi dosya. StatusBadge.vue zaten var (parti-1, commit f0e066e).
# Kullanım: "---" arası bloğu yeni Cowork oturumuna yapıştır. Bağımsız Haiku doğrulayıcı ile.

---

Sen Stabler SPA'sında merkezi status rozet refaktörünün 2. (son) partisini uyguluyorsun.
Çalışma klasörü: /Users/zafar/frappe-bench-local/apps/stabler. SALT bu partideki 5 dosyaya + status.js'e dokun.

## 0. BAŞLANGIÇ (oku, uydurma)
1. Oku: `STATE.md` (D-7/D-8/D-9 + WP-104 parti-1 kaydı), `CLAUDE.md` ("Centralized status codes"), `stabler_final_blueprint.md` §1.3.
2. Oku ve deseni öğren: `stabler/public/js/components/StatusBadge.vue` (parti-1'de kuruldu — props: doctype reqd, status, docstatus; string yolu STATUS_MAP[doctype][status], numeric yol STATUS_MAP.docstatus[n]), `composables/status.js` (STATUS_MAP, getStatusBadgeClass, getDocstatusLabel).
3. Parti-1 commit'ini (f0e066e) referans al: EHFStatus/OneCSyncLog (string status) ve InstallmentCalendar (docstatus) nasıl taşındı — birebir aynı deseni uygula.

## 1. Dosyalar ve DOĞRULANMIŞ sınıflandırma (yine de kodu OKU, teyit et)
Grep zemini (09.07): şu 5 dosya `statusClass/badgeClass` içeriyor. Üç desen var:

**Desen 1 — docstatus haritası (sayısal → StatusBadge docstatus yolu):**
- `service/Visits.vue:34` — `statusClass(docstatus)`: 1→bg-green-lt, 2→**bg-danger-lt**, else bg-secondary-lt. Ayrıca `statusLabel(docstatus)` (satır 28).
  ↳ Taşı: `<StatusBadge doctype="Visit" :docstatus="visit.docstatus" />`. Yerel statusClass+statusLabel'ı sil.
  ↳ "RENK UYUŞMAZLIĞI" NOTU (parti-1 raporundan): docstatus 2 burada `bg-danger-lt`, merkezi STATUS_MAP.docstatus'ta muhtemelen `bg-red-lt`. Bu, parti-1'deki EHF/1C ile AYNI kasıtlı normalizasyon (danger==red, light-tint). Taşı ve raporda "kasıtlı ton normalizasyonu: bg-danger-lt → bg-red-lt" diye belirt. Merkezi haritayı Visits'e uydurmak için DEĞİŞTİRME.
- `remittance/RemittanceTransfers.vue:65` — `docstatusClass(s)`: 0→yellow,1→green,2→red. ↳ `<StatusBadge doctype="Remittance Transfer" :docstatus="tr.docstatus" />` (2 kullanım yeri: satır 127 + 171). Yerel sil.

**Desen 2 — zaten merkezi fonksiyonu saran ince wrapper (gerçek ihlal DEĞİL, sadeleştir):**
- `marketing/PromoPlans.vue:105` — `statusClass(status){ return getStatusBadgeClass("Promo Plan", status) }`. Sabit harita YOK, zaten merkezi. ↳ `<StatusBadge doctype="Promo Plan" :status="r.status" />`, wrapper'ı sil. Sıfır davranış değişimi.
- `marketing/Claims.vue:51` — aynı, `getStatusBadgeClass("Marketing Claim", status)`. ↳ `<StatusBadge doctype="Marketing Claim" :status="r.status" />` (2 yer: satır 152 + 184), wrapper'ı sil.
  ↳ Bunlar STATUS_MAP'e YENİ anahtar gerektirmez (zaten "Promo Plan"/"Marketing Claim" kullanıyorlar — var olduğunu teyit et; yoksa ekle).

**Desen 3 — docstatus + AYRI domain-state haritası (dikkat):**
- `installment/Contracts.vue:150` — `docstatusClass(s)` (0→yellow,1→green,2→red) → docstatus yolu, taşı: `<StatusBadge doctype="Installment Contract" :docstatus="c.docstatus" />`.
  ↳ AMA satır 153 `scheduleStateClass(state)` (paid/partial/overdue/upcoming → renk) AYRI bir şey: bu bir ödeme-planı durum enum'u, doctype docstatus'u DEĞİL. Karar: bu gerçek bir status enum'u → STATUS_MAP'e `"Installment Schedule State"` anahtarı ekle (paid=green, partial=yellow, overdue=red, upcoming=blue — mevcut renklerle bire bir) ve `<StatusBadge doctype="Installment Schedule State" :status="row.state" />` kullan. Böylece merkezi kalır. scheduleStateClass'ı sil.

## 2. STATUS_MAP'e eklenecekler (yalnız gerçekten eksik olanlar)
Her taşınan doctype için STATUS_MAP'te anahtar olduğundan emin ol; yoksa ekle (renk semantiği: taslak=secondary, beklemede/kısmi=yellow, aktif=blue/azure, tamam=green, iptal/başarısız=red). docstatus yolu için STATUS_MAP.docstatus zaten var (parti-1). Yeni user-facing string (yeni status değeri) → 5 CSV'ye (en/ru/uz/uzc/tr) harvest.

## 3. KABUL (bağımsız Haiku doğrulayıcı koşturur)
- 5 dosyanın hiçbirinde yerel statusClass/badgeClass/docstatusClass/scheduleStateClass/statusLabel fonksiyonu kalmadı; hepsi `<StatusBadge>` kullanıyor.
- `grep -rIln 'statusClass|badgeClass|statusColor' stabler/public/js/pages --include='*.vue' | wc -l` → **2** (yalnız crm/Deals + crm/Leads kaldı; onlar (B) dinamik-renk, MEŞRU, DOKUNMA).
- Her taşınan sayfa direct-URL refresh ile açılıyor (form-hardening deseni); rozetler görünüyor.
- STATUS_MAP yeni anahtarları 5 CSV'de harvest'li.
- Agent OS gate: `APP_ROOT=$(pwd) agent-os/loop/guardrails/verify.sh` → GATE PASS. `bench build --app stabler` exit 0.
- git add -A yok (explicit path); dekoratif rozetlere ve (B) dosyalarına dokunulmadı.

## 4. KAPANIŞ
Commit "WP-104(parti-2): Visits, RemittanceTransfers, PromoPlans, Claims, Contracts → StatusBadge" + trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
Ratchet: `agent-os/loop/goals/status-badge-no-growth.md` predicate eşiğini `-le 7` → `-le 2` DÜŞÜR ve nota ekle: "2 = kalıcı taban (crm/Deals + Leads, meşru dinamik-renk). WP-104 tamamlandı." (agent-os untracked, commit gerektirmez.)
Rapor: sınıflandırma × aksiyon tablosu, yeni STATUS_MAP anahtarları, Visits ton normalizasyonu notu, güncel grep sayısı (=2).
Sonra: `graphify update .` koştur (graf tazeliği goal'ü — API maliyeti yok). DUR.

---

# Operatör Notu (Zafar için)
- Parti-2 WP-104'ü BİTİRİR: 5 gerçek dosya taşınır, geriye yalnız 2 meşru (B) dosya kalır → ratchet tabanı 2.
- Üç desen bilinçli ayrıldı: Visits/Remittance (docstatus), PromoPlans/Claims (zaten wrapper — kolay), Contracts (docstatus + ayrı schedule-state enum'u → yeni STATUS_MAP anahtarı).
- Visits'teki "renk uyuşmazlığı" gerçek bir sorun değil; parti-1'deki danger→red light-tint normalizasyonunun aynısı.
- StatusBadge zaten var; bu parti yeni bileşen kurmaz, sadece kullanır.
