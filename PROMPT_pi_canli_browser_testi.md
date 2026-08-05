# PROMPT — msa.erpstable.com Proforma Invoice (PI) CANLI BROWSER TESTİ

> Antigravity'ye bu dosyanın tamamını yapıştır. Kod yazma/düzeltme YOK — sadece canlı test + rapor.

---

## 0) Görev tanımı ve sınırlar

Sen bir QA test mühendisisin. **Canlı (production) tenant `msa.erpstable.com`** üzerinde, gerçek bir tarayıcı oturumu açarak **Proforma Invoice (PI)** modülünün uçtan uca CRUD akışını test edeceksin.

**KESİN KURALLAR**
- Sadece **gerçek tarayıcı** üzerinden test et. API'yi curl/requests ile doğrudan çağırarak "test ettim" deme. (Ağ trafiğini sadece *gözlemlemek* için DevTools Network kullan — bu serbest.)
- **Hiçbir kod değişikliği yapma.** `bench`, `migrate`, `restart`, deploy, git commit YOK. Repoyu sadece okumak için kullanabilirsin.
- Prod veri: **sadece kendi oluşturduğun test kayıtlarına dokun.** Başka hiçbir PI / CI / container kaydını açıp değiştirme veya silme.
- Test kayıtlarının PI numarası mutlaka `QA-TEST-` ön ekiyle başlasın (aşağıda birebir verildi).
- Bir adım hata verirse **DURMA** — hatayı kanıtıyla kaydet, sonraki adıma geç. Aynı başarısız aksiyonu 2-3 kereden fazla tekrarlama.
- Her adımda **ekran görüntüsü** al. Her kaydetmede DevTools Network'ten `save_proforma` isteğinin **request payload + response**'unu kopyala. Console'daki tüm error/warning'leri topla.

---

## 1) Sistem bilgisi (test öncesi bilmen gerekenler)

**Uygulama:** Frappe/ERPNext üstünde çalışan `stabler` custom app'i. Arayüz `/stabler` altında bir Vue SPA, **hash router** kullanıyor.

**İlgili URL'ler**
| Sayfa | URL |
|---|---|
| PI listesi | `https://msa.erpstable.com/stabler#/imports/proformas` |
| Yeni PI | `https://msa.erpstable.com/stabler#/imports/proformas/new` |
| Mevcut PI | `https://msa.erpstable.com/stabler#/imports/proformas/<PI_NO>` |
| Vendor Category yönetimi | `https://msa.erpstable.com/stabler#/inventory/vendor-categories` |
| PI ↔ CI sapmaları | `https://msa.erpstable.com/stabler#/imports/discrepancies` |
| Imports dashboard | `https://msa.erpstable.com/stabler#/imports/dashboard` |

**Doctype:** `Proforma Invoice` — **autoname = `field:supplier_pi_ref`**, yani kaydın adı/URL'i, girdiğin "PI No. (supplier ref)" değeridir. (Bu yüzden aynı PI No. ikinci kez kullanılamaz ve özel karakterler URL'i etkiler — test edilecek.)

**Header alanları:** Supplier*, Company*, PI Date, PI No. (supplier ref)*, Import PI Group, Currency, Incoterm, Incoterm Location, Port of Loading, Port of Discharge, Status (DRAFT / CONFIRMED / CANCELLED), Prepayment Base (Agreed total | Docs only), Advance % (slider), Bank Agreed, Cash Agreed, Remarks.

**Items grid kolonları:** `Vendor Category | Product Code/Name | Boxes | Box Weight | Quantity (KG) | Agreed Price | Docs Price | Agreed Total | Docs Total | Invoiced (KG) | Remaining Bal (KG)`
Butonlar: **Fill from category**, **Add row**, **Sync Totals**, **Save Proforma** / **Update & Save**, uyarı çıkarsa **Sync Prepayment Totals**, altta **Delete**.

**"Fill from category" modalı alanları:** Category, **Containers**, Box weight (kg), Agreed price, Docs price → **Apply**.

**Beklenen matematik (doğrulanacak formüller)**
- Satır: `Quantity (KG) = Boxes × Box Weight` (kullanıcı Qty'yi elle değiştirmediyse)
- Satır: `Agreed Total = Qty × Agreed Price` , `Docs Total = Qty × Docs Price`
- Alt toplam: `Agreed Total = Σ satır agreed`, `Docs Total = Σ satır docs`, `Cash Difference = Agreed − Docs`
- Fill from category: `satır Boxes = kategorideki boxes_per_container × Containers`, ayrıca gizli bir `fcl` alanı `(boxes_per_container / toplam_boxes_per_container) × Containers` olarak hesaplanıp kaydediliyor (ekranda kolon yok — **kaydolup olmadığını ve mantıklı olup olmadığını sorgula**).
- Sunucu kuralı (kaydetmeyi bloke eder): **`|Bank Agreed + Cash Agreed − Agreed Total| ≤ 0.5`** değilse hata: *"Bank Agreed + Cash Agreed (X) must equal Agreed Total (Y)."*
- Sunucu: `cash_difference = agreed_total − docs_total`.

**Çağrılan API'ler (Network'te izle):** `stabler.api.imports.save_proforma`, `...proforma_detail`, `...list_vendor_categories`, `...vendor_category_detail`, `...list_pi_groups`, `stabler.api.inventory.list_items`, `...delete_proforma_invoice`.

---

## 2) Test verisi (birebir bunu kullan)

| Alan | Değer |
|---|---|
| PI No. #1 | `QA-TEST-PI-20260805-01` |
| PI No. #2 (slash testi) | `QA-TEST/PI/20260805-02` |
| Supplier | Vendor Category'si **tanımlı olan** bir tedarikçi seç (aşağıya bak) |
| PI Date | bugün |
| Currency | `USD` |
| Incoterm | `CIF` , Location: `Tashkent` |
| Port of Loading / Discharge | `Shanghai` / `Tashkent` |
| Containers | **10** |
| Box weight | `20` kg |
| Agreed price | `4.50` |
| Docs price | `2.80` |
| Status | `DRAFT` (yalnız T-14'te CONFIRMED denenecek) |

**Supplier seçimi:** Önce `#/inventory/vendor-categories` sayfasını aç, hangi tedarikçilerde kategori ve kategori içinde kaç kalem (`boxes_per_container`) tanımlı olduğunu **not al** (ekran görüntüsü + tablo). **En az 5-6 kalemi olan bir kategori** varsa onu kullan. Yoksa: kategoriden 3-4 kalem gelsin, kalanı **Add row** ile elle ekleyip toplam **5-6 satıra** tamamla. Hangi yolu seçtiğini raporda yaz.

---

## 3) Test senaryoları (sırayla çalıştır)

### A. Keşif
- **T-01** Login ol, üstteki **şirket (company) seçicisinin dolu** olduğunu doğrula. Boşsa PI sayfası ne yapıyor? (kategori/ürün listeleri boş mu geliyor?)
- **T-02** `#/imports/proformas` listesini aç: kolonlar, filtreler, arama, sayfalama, boş/skeleton yükleme davranışı. Console error var mı?
- **T-03** `#/inventory/vendor-categories`: kategori listesi, kategori detayı, kalem sayısı ve `boxes_per_container` değerlerini not al.

### B. Create (oluşturma)
- **T-04** Yeni PI formunu aç (`/new`). Tüm header alanlarını doldur (bölüm 2). **Supplier seçmeden** "Fill from category"ye bas → *"Select a supplier first."* uyarısı çıkmalı.
- **T-05** Supplier seç → **Vendor Category** dropdown'ının satırlarda o tedarikçiye ait kategorilerle dolduğunu doğrula.
- **T-06** **Fill from category** → Category seç, **Containers = 10**, Box weight = 20, Agreed price = 4.50, Docs price = 2.80 → **Apply**.
  - Her satır için `Boxes = boxes_per_container × 10` doğru mu? (kategori sayfasından aldığın değerlerle elle çarpıp karşılaştır)
  - `Quantity (KG) = Boxes × 20` doğru mu?
  - `Agreed Total`/`Docs Total` satır bazında doğru mu?
  - Alt toplamlar (Agreed Total / Docs Total / Cash Difference) doğru mu?
- **T-07** Satır sayısı 5-6 değilse **Add row** ile elle satır ekle: kategori seç, ürün seç, Boxes/Box Weight/fiyatları gir. Ürün seçince Description ve UOM otomatik doluyor mu?
- **T-08** **Prepayment bloğu:** Bank Agreed + Cash Agreed toplamının Agreed Total'a eşit olduğunu kontrol et. Bilerek Bank Agreed'ı 100 azalt → sarı uyarı çıkmalı, **Sync Prepayment Totals** butonu düzeltmeli. Uyarı varken kaydetmeye çalış → engellenmeli ve mesaj net olmalı.
- **T-09** **PI No. boş bırakıp** kaydet → *"PI number (supplier ref) is required…"* uyarısı çıkmalı.
- **T-10** PI No. = `QA-TEST-PI-20260805-01` ile **Save Proforma**. Network'te `save_proforma` payload + response'unu kaydet. URL kayıt adına dönüşüyor mu? Toast çıkıyor mu?

### C. Kalıcılık / reload
- **T-11** Sayfayı **F5 ile yenile**. Form dolu mu geliyor, yoksa boş "New" mi? (bilinen regresyon sınıfı — kritik)
- **T-12** Kayıt URL'ini **yeni sekmeye yapıştırarak** aç. Aynı sonuç mu?
- **T-13** Kaydedilen tüm değerleri tek tek karşılaştır: header alanları, her satırın Boxes / Box Weight / Qty / Agreed Price / Docs Price, alt toplamlar, Bank/Cash. **Kaybolan veya yuvarlanan alan var mı?** (özellikle gizli `fcl` alanı ve `category` metni)

### D. Update (güncelleme)
- **T-14** Bir satırın **Boxes** değerini değiştir (ör. 500 → 550). **Quantity (KG) otomatik güncelleniyor mu?** (Not: reload sonrası otomatik hesabın devre dışı kalması bekleniyor olabilir — davranışı aynen raporla, tutarsızlığı BUG olarak işaretle.) Aynısını **Box Weight** için yap (20 → 22).
- **T-15** Bir satırın **Agreed Price** ve **Docs Price**'ını değiştir → satır ve alt toplamlar anında güncelleniyor mu? Bank/Cash otomatik takip ediyor mu, yoksa uyarı mı çıkıyor? **Sync Totals** butonunu dene.
- **T-16** Bir satırı **sil**, yeni bir satır **ekle** → **Update & Save**. Sonuç doğru kaydedildi mi? (reload ile doğrula)
- **T-17** **Containers'ı 10'dan farklı bir değere** ayarlamak için ikinci kez "Fill from category" (Containers = 10) çalıştır → satırlar **çoğaltılıyor mu, üzerine mi yazıyor**? Beklenen davranışı ve gerçekleşeni yaz. (Temizle: fazla satırları sil, 5-6 satıra dön.)
- **T-18** Status'u `DRAFT` → `CONFIRMED` yap ve kaydet. Sonra tekrar düzenlemeye izin veriliyor mu? Doctype'ta `SUPERSEDED_BY_CI` durumu var ama UI dropdown'ında yok — **not düş**. Test sonunda status'u `DRAFT`'a geri al.
- **T-19** Currency'yi `USD` → `EUR` yapıp kaydet, geri `USD` yap. Kolon başlıkları ve tutarlar tutarlı mı?
- **T-20** Prepayment Base'i `Docs only` yap, Advance % slider'ını 30 → 50 çek, kaydet, reload et → değerler kalıcı mı? Slider'ın hesaplara etkisi var mı, yok mu — gözlemle.

### E. Sınır / hata durumları
- **T-21** **Aynı PI No.** (`QA-TEST-PI-20260805-01`) ile ikinci bir PI oluşturmayı dene → hata mesajı anlaşılır mı, yoksa ham Frappe "Duplicate entry" traceback'i mi?
- **T-22** PI No. = `QA-TEST/PI/20260805-02` ile ikinci bir PI oluştur (slash içeren ad). Kaydediliyor mu? Kaydettikten sonra **URL, reload ve listeden açma** çalışıyor mu? (autoname = PI No. olduğu için kritik)
- **T-23** Sayı formatı: bir fiyat alanına **virgüllü** `4,75` gir, bir Boxes alanına `abc` ve negatif `-5` gir. Ne oluyor? Kaydedilen değer ne?
- **T-24** Çok büyük değer: bir satıra Boxes = `999999` gir → hesap/format bozuluyor mu?
- **T-25** Tüm satırları silip kaydet → Agreed Total ne oluyor? (eski değerde takılı kalıyor mu?)
- **T-26** Supplier'ı **kaydettikten sonra değiştir** → satırlardaki Vendor Category seçenekleri yeni tedarikçiye göre güncelleniyor mu, eski kategoriler satırlarda kalıyor mu?
- **T-27** Formu kaydetmeden başka sayfaya geç / ESC'e bas → veri kaybı uyarısı var mı?

### F. Alt sistem etkileri
- **T-28** PI listesinde yeni kayıt görünüyor mu; listedeki tutarlar form ile aynı mı?
- **T-29** `#/imports/dashboard` ve `#/imports/discrepancies` sayfalarını aç → yeni PI beklenen şekilde yansıyor mu, hata veriyor mu?
- **T-30** Form altındaki **"Commercial Invoices — Fulfillment Summary"**, **"Shipment match"**, **"Linked Commercial Invoices & Containers"**, **"Advance Payments"** panelleri: CI'sı olmayan bir PI'da boş durum (empty state) düzgün mü, yoksa hata/`NaN`/sonsuz spinner mı?

### G. Delete + temizlik
- **T-31** `QA-TEST/PI/20260805-02` üzerinde **Delete**'e bas → **dry-run** modalı ne diyor? Bloklayıcı/cascade listesi doğru mu? Modalı ekran görüntüsüyle kaydet, sonra **gerçekten sil**.
- **T-32** `QA-TEST-PI-20260805-01`'i de aynı şekilde sil. **Test sonunda prod'da QA-TEST ile başlayan hiçbir kayıt kalmamalı.** Silinemeyen bir şey varsa raporda açıkça belirt.

---

## 4) Rapor formatı (çıktı)

Şu yapıda bir markdown raporu üret (`PI_CANLI_TEST_RAPORU_<tarih>.md`):

**1. Özet** — kaç test, kaç PASS / FAIL / BLOCKED; en kritik 5 bulgu tek cümlelik madde halinde.

**2. Test tablosu**

| ID | Senaryo | Beklenen | Gerçekleşen | Sonuç | Önem | Kanıt |
|---|---|---|---|---|---|---|

Önem: `BLOCKER / MAJOR / MINOR / COSMETIC`. Kanıt: ekran görüntüsü adı + varsa console/network kesiti.

**3. Bulgu detayları** — her FAIL için: adım adım tekrar üretme (repro), gerçek/beklenen, ekran görüntüsü, Network isteğinin payload+response'u, console hatası. **Çözüm önerisi yaz ama kodu değiştirme.**

**4. Hesaplama doğrulama tablosu** — 10 container senaryosu için satır bazında: `boxes_per_container | ×10 = Boxes | Box Weight | beklenen Qty | ekrandaki Qty | Agreed Price | beklenen Agreed Total | ekrandaki | ✓/✗`.

**5. Eksikler / UX notları** — çalışıyor ama eksik/kafa karıştırıcı olanlar (ör. FCL kolonunun ekranda olmaması, `SUPERSEDED_BY_CI` durumunun UI'da bulunmaması, Containers alanının sadece modalda olup formda görünmemesi, reload sonrası Qty otomatik hesabının durması vb.).

**6. Test verisi temizliği** — silinen kayıtlar ve prod'da kalan artık var mı.

---

## 5) Çalışma disiplini
- Her adımdan önce ne yapacağını, sonra ne gördüğünü kısa kısa logla.
- Belirsizlik olursa **varsayımını yazıp devam et**, durup soru sorma.
- Tarayıcı 2-3 denemede yanıt vermezse o adımı `BLOCKED` işaretle ve devam et.
- Sonuç: **sadece rapor**. Kod düzeltmesi, PR, commit yok.
