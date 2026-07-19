# KassaBot v2 — Shadow Mode + akıllı Özbekçe serbest-metin girişi

**Sahip:** mikas · module-gated (`money`/`tender`) · **Tarih:** 2026-07-19 · **Tasarım:** Opus (senior)
> v1 (as-built) = `docs/KASSABOT_FEATURES.md` — bot `execute_action → money.py` ile **gerçek GL'e** yazıyor.
> **v2 bu dokümanda** — bot **shadow deftere** yazar, GL'e/ERPNext'e **DOKUNMAZ**.

## 0. Pivot — neden shadow?
Mevcut bot her işlemi anında gerçek Journal Entry olarak postluyor. Sen bunu istemiyorsun:
kassir botla kendi işlemlerini yazsın ama bu **hiçbir yere (ERPNext/Stabler GL) dokunmasın**;
gün başında gerçek Stabler kasa bakiyeleri **sync** edilsin (finansist izinli), kassir gün boyu
kirim/chiqim/konversiya yazsın, sistem shadow'da **çalışan bakiye** tutsun, gün sonu finansist
gerçekle **mutabakat** yapsın. Yani bot = **gölge kasa defteri + akıllı giriş**, muhasebe motoru değil.

## 1. Prensip
- Bot **hiçbir GL entry, Payment Entry, Journal Entry ÜRETMEZ.** Yalnızca `Kassa Shadow Entry` yazar.
- Gerçek muhasebe Stabler'da kalır; shadow onun **ayna/denetim** katmanıdır.
- Gün başı **opening** = gerçek Stabler kasa bakiyelerinden sync (sadece finansist).
- Çalışan bakiye = `opening ± bugünkü shadow entry'ler` (kassa + para birimi başına).

## 2. Roller (net ayrım)
| Rol | Yapabildiği |
|---|---|
| **Kassir** | Sadece kendi işlemlerini **yazar** (kirim / chiqim / konversiya / kassadan-kassaga). Bakiye **sync edemez**, başka kassir'in verisini görmez. |
| **Admin (System Manager)** — *finansist yerine, şimdilik* | Gün başı **opening sync** + gün sonu **mutabakat**. (Ayrı "Kassa Finansist" rolü sonraki fazda; şimdilik admin.) |

> **KİLİTLİ KARAR (2026-07-19):** Shadow defter **asla GL'e yazmaz** (saf shadow). "Promote-to-GL" **kapsam dışı**. Sync/mutabakat **şimdilik admin**, finansist rolü sonraya.

## 3. Gün başı bakiye sync (finansist kontrollü)
- `sync_kassa_opening(company, date)` — gerçek Stabler kasa leaf'lerinin bakiyesini (`money.account_balance`) o günün shadow **opening**'i olarak snapshot'lar.
- **Tetik:** yalnızca finansist (admin buton / bot komutu). İstenirse gün başı zamanlanır ama **finansist onayına** kadar bekler. Kassir tetikleyemez.
- Idempotent: gün içinde entry yoksa re-sync opening'i günceller; entry varsa uyarır (mutabakatı bozmamak için).

## 4. Shadow doctype — `Kassa Shadow Entry`
Alanlar: `kassir` (Link), `company`, `entry_date`, `op_type` (Kirim/Chiqim/Konversiya/Kassalararo), `from_kassa`/`to_kassa` (Link kasa leaf), `currency`, `amount`, `rate` (konversiyada), `counterparty` (kimdan/kimga), `purpose` (izoh), **`raw_text`** (kassir'in yazdığı ham metin), **`parsed_json`** (ayrıştırma sonucu), `created_at`, `status` (Qoralama/Tasdiqlangan/Mutabaqatlangan), `correction_of` (düzeltme zinciri). **GL'e link YOK.** company-scoped, `money`/`tender` gate.
- Ayrıca `Kassa Shadow Opening` (kassa+currency+date+opening_amount+synced_by) — günlük açılış snapshot'ı.

## 5. Akıllı Özbekçe serbest-metin (intent + slot) — çekirdek
Kassir tam cümle yazar; bot **niyeti** ve **slotları** çıkarır, eksikse **tek** soru sorar.

**Niyet (kelime → op):**
- Kirim ← "kirdi, keldi, oldim, tushdi, kirim, qabul qildim"
- Chiqim ← "chiqdi, berdim, to'ladim, masraf, xarajat, chiqim"
- Konversiya ← "konvert, almashtir, ayirboshla, valyuta, aylantirdim"
- Kassalararo ← "kassaga o'tkaz, ko'chir"

**Miktar + para birimi (suffiks/kısaltma):**
- `s` / `som` / `so'm` → UZS · `d` / `dollar` / `$` → USD · `e` / `euro` / `€` → EUR
- `ming` / `k` → ×1 000 · `mln` / `m` → ×1 000 000 · `mlrd` → ×1 000 000 000
- kelime sayılar (mevcut parser'da var: "yuz ming", "besh yuz ming"…)
- Örnekler: `100mln` → 100 000 000 (para birimi yoksa **UZS varsayılan** ama düşükse sor) · `100d` → 100 USD · `100ming s` → 100 000 UZS · `1,5 mln` → 1 500 000

**Slot çıkarımı** (kalan metinden): counterparty (kimdan/kimga), purpose (izoh), rate ("... kurs 12900").
- `"100mln aldim Aliyevdan ijara uchun"` → Kirim · 100 000 000 UZS · kimdan=Aliyev · izoh=ijara
- `"100ming s chiqdi ijaraga"` → Chiqim · 100 000 UZS · izoh=ijara · (kimga? → **tek soru**)
- `"500d ni somga aylantirdim 12900 kurs"` → Konversiya · USD→UZS · 500$ @ 12 900

**Eksik-slot = TEK soru:** amount var, counterparty yoksa → sadece **"Kimdan oldingiz?"** (eski "kasa seç / miktar seç" zinciri YOK). Belirsizse (ör. para birimi) **asla tahmin etme**, tek net soru sor.

**Ham metin + confirm echo:** her entry `raw_text` + `parsed_json` saklar. Onay:
> Yozganingiz: «100mln aldim» → **Kirim 100 000 000 UZS**, kimdan: Aliyev, izoh: ijara. Tasdiqlaysizmi? ✅ / ✏️

## 6. Az soru / konuşma akışı
- **Varsayılan yol = serbest metin.** Adım-adım menü yalnızca *fallback* (slot eksik veya kullanıcı butona basarsa).
- "giriş" / "masraf" + serbest metin → botun gerisini kendi çıkarması.
- Menüdeki "Kassa seç / Miktar seç" zorunlu zinciri kalkar; sadece belirsizlikte devreye girer.

## 7. Zenginleştirmeler (isteklerine eklediklerim)
1. **Çalışan bakiye** her entry sonrası: "Qoldiq: Som 26 991 567 · PK 3 000 000 · USD 5 244".
2. **Son işlemi geri al / düzelt** (shadow olduğu için güvenli) — düzeltme yeni `correction_of` entry'si yaratır, üzerine yazmaz (audit).
3. **Gün sonu özeti** — bot para birimi başına kirim/chiqim/net + shadow closing basar; finansiste "mutabakat" bildirimi.
4. **Fark (discrepancy) bayrağı** — shadow closing ≠ beklenen gerçek → kırmızı işaret; finansist inceler.
5. **Onay eşiği** — büyük tutar açık onay ister; küçük tutar hızlı geçer.
6. **Değişmez audit** — raw_text + parse + kassir + zaman; düzeltme zinciriyle izlenir.
7. **Kiril + Latin girişi** kabul; çıktı Özbekçe latin (veya kullanıcı dili).
8. **CBU kuru** konversiyada otomatik önerilir (mevcut cbu refresh); kassir farklı kur yazarsa onu kullanır ve işaretler.
9. **Mini App** (`/kassa`) shadow entry'leri + çalışan bakiye + günlük mutabakat durumunu gösterir.
10. ~~Promote-to-GL~~ — **KAPSAM DIŞI** (karar: saf shadow, GL'e asla yazmaz). Not olarak duruyor; gerekirse ileride ayrı bir proje olarak tartışılır.

## 8. Güvenlik / gating
- `money`/`tender` module-gate + company (mikas). Kassir kendi kassası; finansist tüm mikas kasaları.
- Bot GL'e yazamaz (kod yolu yok). Promote fazı ayrı, finansist-gated, maker-checker.
- Telegram token/secret/initData asla loglanmaz (mevcut kural).

## 9. Kararlar
1. ✅ **KİLİTLİ:** Saf shadow — GL'e **asla** yazmaz. Promote-to-GL kapsam dışı.
2. ✅ **KİLİTLİ:** Sync/mutabakat **şimdilik admin (System Manager)**; ayrı "Kassa Finansist" rolü sonraki fazda.
3. *Açık:* Opening sync sadece admin-buton mu, zamanlı+onay mı? (öneri: admin-buton + opsiyonel zamanlı-öneri — S2'de netleşir.)
4. ✅ **KİLİTLİ (öneri kabul):** mikas'ta **tam shadow** (v1 gerçek-GL yolu mikas botunda kaldırılır).

## 10. WP kırılımı
- **WP-S1** `Kassa Shadow Entry` + `Kassa Shadow Opening` doctype'ları (GL-link yok, gated).
- **WP-S2** `sync_kassa_opening` (admin-gated, System Manager). Finansist rolü faz-2.
- **WP-S3** Akıllı serbest-metin motoru: intent + suffiks(s/d/e) + slot + eksik-slot tek-soru + raw_text/parsed_json (saf, unit-testli — mevcut `_flow.parse_amount`'ı genişletir).
- **WP-S4** Bot akışını shadow'a bağla (execute_action → shadow write; GL çağrıları kaldırılır), çalışan bakiye + confirm echo.
- **WP-S5** Gün sonu özet + mutabakat + discrepancy bayrağı; Mini App shadow görünümü.
- ~~WP-S6 promote-to-GL~~ — **kapsam dışı** (saf shadow).

## Riskler
- Kullanıcılar shadow ≠ gerçek olduğunu bilmeli (net etiket: "Bu defter muhasebeye yazmaz").
- Serbest-metin belirsizliği → asla tahmin etme, tek soru (mevcut ilke korunur).
- Opening sync yanlış günde çalışırsa mutabakat kayar → tarih + idempotent guard.
- Promote fazı (yapılırsa) gerçek GL'e yazar → maker-checker + finansist-gate şart.
