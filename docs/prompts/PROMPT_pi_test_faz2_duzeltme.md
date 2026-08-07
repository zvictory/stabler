# PROMPT — PI Canlı Test FAZ-2: temizlik + düzeltilmiş retest

> Antigravity'ye bu dosyanın tamamını yapıştır. Bu, yarım kalan bir testin **ikinci fazı**.
> Kod yazma/düzeltme YOK, `bench`/deploy/commit YOK. Sadece canlı tarayıcı testi + rapor.

---

## 0) Bağlam — FAZ-1'de ne oldu

`msa.erpstable.com` (Frappe + `stabler` Vue SPA, hash router, UI dili **Rusça**) üzerinde Proforma Invoice (PI) modülü canlı test edildi. Faz-1 kısmen tamamlandı; **kaynak kodla doğrulanmış** sonuçlar aşağıda. Bunları **tekrar test etme, tekrar raporlama** — sadece kalanları yap.

### Kesinleşmiş bulgular (kapalı, dokunma)
| # | Bulgu | Durum |
|---|---|---|
| B1 | `MoneyInput` ru locale'inde **noktayı binlik ayracı sayıp siliyor**: `4.50` → `450`. Virgül (`4,50`) doğru. | GERÇEK / MAJOR |
| B2 | Kaydedilmiş PI'da **Boxes/Box Weight değişince Qty yeniden hesaplanmıyor** (`loadDoc` her satıra `_qtyManual: true` yazıyor; sunucu da yalnızca `qty == 0` iken doldurur) | GERÇEK / MAJOR |
| B3 | `SUPERSEDED_BY_CI` status'ü UI dropdown'ında yok | GERÇEK / MINOR |
| B4 | Boxes/BoxWeight/Qty inputlarında `min` yok → **negatif değer kabul ediliyor** | GERÇEK / MINOR |
| B5 | Slash'lı PI No (`QA-TEST/PI/...`) kaydediliyor, URL `%2F` ile açılıyor | PASS |
| B6 | Fill from category matematiği doğru: `Boxes = boxes_per_container × Containers`, `Qty = Boxes × BoxWeight`, satır ve alt toplamlar tutarlı | PASS |
| B7 | Supplier değişince satırdaki eski kategori seçenek olarak kalıyor — bu **bilinçli** (`v-if="row.category && !categoryOptions.includes(row.category)"`), veri kaybını önlüyor | TASARIM GEREĞİ |

### Faz-1'in HATALI sonuçları (bunlar geçersiz, yeniden test edilecek)
- "Duplicate PI No'da hiçbir mesaj çıkmıyor" → toast'lar `role="alert"` ile render ediliyor **ama 3000 ms sonra kayboluyor**; snapshot geç alınmış olabilir. Ölçüm hatası ihtimali yüksek.
- "Tüm satırlar silinince toplamlar 0'a düşüyor, PASS" → ekranda görünen sadece computed footer. Kaydedilen değer kontrol edilmedi.
- "Formda Delete butonu yok" → **var**, akış iki adımlı (bkz. bölüm 1).
- "Buton tıklanamıyor (click-probe)" → ürün hatası değil, harness kısıtı. Çözüm: butonun **içindeki text düğümüne** tıkla. Bunu bulgu olarak raporlama.

### Prod'da duran test kayıtları (SİLİNECEK)
1. `QA-TEST-PI-20260805-01` — 1 satır, fiyatlar bozuk (450/280), status DRAFT, advance %50
2. `QA-TEST-FILL-20260805` — 13 satır, Mirha / BUFFALO COMPENSATED_6, 10 konteyner, 1 260 000 $
3. `QA-TEST/PI/20260805-02` — satırsız (boş), URL'de `QA-TEST%2FPI%2F20260805-02`

---

## 1) ÖNCE: doğru silme akışı (öğrenilmiş bilgi — deneme yapma, bunu uygula)

PI silme **üç tıklamalı**, iki ayrı katman:

1. Kayıt formunda en alttaki kırmızı **«Удалить»** (Delete) → **dry-run modalı** açılır, başlık **«Удалить проформу»**. Bu modal hiçbir şey yazmaz, sadece neyin silineceğini raporlar.
2. Bu modalın **footer'ındaki kırmızı «Удалить»** butonu → modal kapanır, **ikinci bir onay diyaloğu** açılır (`role="dialog"`, `aria-modal="true"`).
3. İkinci diyalogdaki **«Удалить безвозвратно»** (Delete permanently) → asıl silme.

**Tuzaklar:**
- Form'daki ve modal'daki buton **aynı isimde** (`Удалить`) → `getByRole("button", {name:"Удалить"})` ambiguous. Modal'dakini `.modal-footer` scope'undan veya «Отмена» ile aynı seviyeden seç.
- İkinci diyalogda odak **Cancel** üzerinde başlar (danger dialog) → **Enter'a basma, iptal eder.** Butona tıkla.
- Başarı kriteri: URL `#/imports/proformas` listesine döner + toast çıkar. **URL kayıtta kalıyorsa silme olmamıştır.**

---

## 2) RETEST listesi (Faz-1'in hatalı/eksik kalan kısmı)

### R-01 — Toast görünürlüğü (T-09 / T-21 tekrarı) · YÜKSEK
Toast ömrü 3 saniye. **Her tıklamadan sonra 1 saniye içinde** DOM/a11y snapshot al (veya tıklamadan hemen önce `role="alert"` dinleyicisi kur; `.toast-container` `body` altına Teleport ediliyor).
- **R-01a:** Yeni PI, PI No **boş** → Save → *"PI number (supplier ref) is required…"* toast'ı çıkıyor mu?
- **R-01b:** PI No = `QA-TEST-FILL-20260805` (mevcut kayıtla aynı) → Save → hangi mesaj çıkıyor? Frappe'nin ham "Duplicate entry" traceback'i mi, anlaşılır bir metin mi? Network'te `save_proforma` response'unun tam gövdesini kaydet.
- Beklenen: her iki durumda da toast **çıkmalı**. Çıkmıyorsa ancak o zaman bug.

### R-02 — Satırsız kayıtta tutar kalıyor mu (T-25 tekrarı) · YÜKSEK
`QA-TEST-PI-20260805-01` üzerinde:
1. Tüm satırları sil.
2. Prepayment uyarısı çıkarsa **Sync Totals** ile düzelt (butonun iç text'ine tıkla).
3. **Update & Save** → kaydet.
4. **F5 ile reload** et.
5. Şu değerleri oku ve yaz: header'daki **Agreed total** input'u, footer Agreed/Docs/Cash Difference, Bank Agreed, Cash Agreed.
- Beklenen (doğru davranış): hepsi 0.
- Şüphe: `agreed_total` ve `docs_total` **eski değerinde kalabilir** (sunucu bunları yalnızca belirli koşullarda sıfırlıyor). Kalıyorsa bu MAJOR veri bütünlüğü bug'ı — Network'teki `save_proforma` **response**'unu (`agreed_total`, `docs_total`, `cash_difference`) kanıt olarak ekle.
- Ayrıca: PI **listesinde** bu kayıt kaç ürün / kaç kutu / ne tutar gösteriyor?

### R-03 — İkinci kez "Fill from category" (T-17, hiç yapılmadı) · YÜKSEK
`QA-TEST-FILL-20260805` (13 satır, 10 konteyner) üzerinde tekrar **Fill from category** → aynı kategori (BUFFALO COMPENSATED_6), **Containers = 5**, BoxWeight 20, fiyatlar `4,50` / `2,80` (virgülle!) → Apply.
- Satır sayısı ne oldu: 13 mü, **26** mı?
- Beklenen iş mantığı: PI = N konteyner × kategori. Ekleme mi yapıyor, üzerine mi yazıyor, yoksa aynı ürünü ikinci kez mi ekliyor?
- Toplam artık kaç konteyneri temsil ediyor (10 mu, 15 mi, 5 mi)? Kullanıcı bunu ekranda **görebiliyor mu**?
- **Kaydetme.** Sayıları not al, sonra fazla satırları silip 13 satıra geri dön (kaydetmeden çık da olur).

### R-04 — Konteyner sayısı (`fcl`) bozuluyor mu · YÜKSEK · YENİ
Domain kuralı: **1 Vendor Category = 1 FCL**, `PI = N konteyner × kategori`. Kod, konteyner sayısını hiçbir header alanında tutmuyor; tek iz, satırlardaki **gizli `fcl` kolonu** ve onun toplamı (`SUM(fcl) → total_fcl`, PI listesi/raporları bunu kullanıyor). Grid'de bu kolon **görünmüyor**.
1. PI **listesinde** `QA-TEST-FILL-20260805` satırında FCL / konteyner benzeri bir kolon veya rakam var mı? Değeri kaç? (10 bekleniyor.) Ekran görüntüsü al.
2. Formda bir satırın **Boxes** değerini iki katına çıkar → **Update & Save** → listeye dön → aynı rakam **değişti mi**?
   - Beklenen kusur: `fcl` güncellenmiyor → konteyner sayısı gerçeği yansıtmıyor.
3. **Add row** ile elle bir satır ekle (kategori + ürün + Boxes 100 + BoxWeight 20 + fiyat `1,00`) → kaydet → listedeki FCL/konteyner rakamı yine değişmedi mi?
   - Beklenen kusur: elle eklenen satırın `fcl` değeri 0 kalıyor.
4. Sonucu şu soruyla bağla: **"Bu PI kaç konteyner?" sorusuna arayüz cevap verebiliyor mu?**

### R-05 — Satır sil + ekle + kaydet (T-16, hiç yapılmadı) · ORTA
`QA-TEST-FILL-20260805` üzerinde: 1 satır sil, 1 satır **Add row** ile ekle (fiyatları **virgülle** gir) → **Update & Save** → **reload** → satır sayısı, sıralama ve değerler doğru mu? Silinen satır gerçekten gitti mi, eklenen kaldı mı?

### R-06 — Kaydetmeden çıkış uyarısı (T-27, atlanmıştı) · DÜŞÜK
Bir alanı değiştir, kaydetmeden sol menüden başka bir sayfaya geç. Uyarı çıkıyor mu, değişiklik sessizce kayboluyor mu? (ESC tuşu da dene — form `useEscapeBack` ile listeye dönüyor.)

### R-07 — B1'in kapsamı (yeni, kısa) · ORTA
Nokta/virgül bug'ı (B1) sadece PI'da mı? **Aynı sayfada kalmadan** bir Purchase Invoice veya Payment Entry formu aç (`#/purchasing/invoices`, `#/money/...`), bir tutar alanına `4.50` yaz, alanı blur et ve okunan değeri yaz.
- Amaç: bu bug'ın uygulama genelinde mi olduğunu tek bir örnekle teyit etmek. **Hiçbir şey kaydetme** — sadece alanın gösterdiği değeri oku ve formu terk et.

---

## 3) SON: temizlik (zorunlu)

Bölüm 1'deki üç adımlı akışla, sırayla sil:
1. `QA-TEST/PI/20260805-02`
2. `QA-TEST-PI-20260805-01`
3. `QA-TEST-FILL-20260805`

Her biri için: dry-run modalının metnini (bloklayıcı/cascade var mı) not al, sil, sonra **PI listesinde arayarak gitmiş olduğunu doğrula**.
**Test sonunda prod'da `QA-TEST` ile başlayan tek bir kayıt kalmamalı.** Silinemeyen olursa neden silinemediğini (modal metni + hata) aynen raporla — API ile silmeye çalışma.

---

## 4) Kurallar
- Sadece gerçek tarayıcı. API'yi curl/fetch ile çağırıp "test ettim" deme; Network sekmesini yalnızca **gözlemlemek** için kullan.
- Kod değişikliği, `bench`, deploy, git YOK.
- Sadece `QA-TEST*` kayıtlarına dokun. R-07'de hiçbir şey kaydetme.
- Fiyatları **virgülle** gir (`4,50`) — nokta bug'ı (B1) zaten kapalı, tekrar tetikleyip testi kirletme.
- Bir adım 2-3 denemede olmuyorsa `BLOCKED` yaz ve devam et.
- Butonlar için: `getByRole` ile tıklama başarısız olursa **butonun içindeki text düğümüne** tıkla (Faz-1'de kanıtlandı). Bunu bulgu olarak raporlama, harness notu olarak yaz.

## 5) Rapor
`PI_TEST_FAZ2_RAPORU_<tarih>.md`:
1. **Özet** — R-01…R-07 sonuçları tek satırda + temizlik durumu.
2. **Tablo:** `ID | Ne test edildi | Beklenen | Gerçekleşen | Sonuç | Önem | Kanıt`
3. **Her FAIL için:** adım adım repro, ekran görüntüsü, `save_proforma` request payload + response, console hatası.
4. **R-04 için ayrı bölüm:** "Bu PI kaç konteyner?" sorusunun arayüzden cevaplanabilirliği — bulduğun rakamlar ve nerede bozulduğu.
5. **Temizlik teyidi** — silinen 3 kayıt, listede arama ekran görüntüsü.
6. **Harness notları** (ürün bugu olmayan, test aracı kaynaklı sorunlar) — ayrı başlık altında, bulgu tablosunun dışında.
