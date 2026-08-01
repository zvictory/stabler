# Tasarım brief'i — Satış Siparişi formu

Bu dosyanın tamamını Claude'a (tasarım oturumu) yapıştır.
**Çıktı: kod değil, tasarım.**

**Ekler:**
- `satis-siparisi-classic-spec.md` — ekranın tam envanteri (ne var, ne yapıyor).
  Buradaki "mevcut bölümler" sorusunun cevabı orada; bu brief onu tekrar etmiyor.
- `satis-siparisi-classic-prototip.html` — ekranın bugünkü hâlinin statik fotoğrafı,
  gerçek anjan verisiyle. Tarayıcıda aç. **Yerleşim referansıdır, piksel referansı değil.**

---

## 1 · Ürün ve kullanıcı

**Stabler** — Frappe/ERPNext üzerine kurulu, tek kod tabanını 7 kiracının paylaştığı
bir Vue 3 SPA. Bu ekranın sahibi kiracılar: **anjan** (dondurma üretimi, ana kiracı),
**dts** (endüstriyel kayış satışı), **horeca**.

Ekranı kullanan iki kişi var:

| Kim | Ne zaman açar | Cevabını aradığı soru |
|---|---|---|
| **Satışçı** | Müşteri telefondayken, günde onlarca kez | "Bu siparişi doğru fiyat ve yeterli stokla, konuşma bitmeden girebilir miyim?" |
| **Satış müdürü** | Sonradan, tek tek veya listeden gelerek | "Bu sipariş neden hâlâ açık? Teslim mi edilmedi, faturası mı kesilmedi, parası mı gelmedi?" |

Bu iki kullanım aynı ekranı paylaşıyor ve ekranın bugünkü hâli ikisini de aynı
yerleşimle karşılamaya çalışıyor.

---

## 2 · Bu ekranın tek işi

> **"Siparişi doğru fiyat, doğru kur ve yeterli stokla hızlıca kaydet; sonra bir hafta
> sonra açıldığında nerede takıldığını tek bakışta göster."**

İki mod:
- **Hızlı giriş (create/draft)** — hız ve hata önleme. Klavye ağırlıklı.
- **Takip (submitted)** — okunabilirlik. Tek bakışta durum teşhisi.

---

## 3 · Mevcut bölümler

`satis-siparisi-classic-spec.md`'ye bak — 16 bölüm, satır referanslarıyla.
Burada tekrar edilmiyor.

Kısaca: durum şeridi + 4 adımlı stepper → uyarı katmanı → 6 başlık alanı → kur
satırı → 5 hücreli özet datagrid → satır tablosu (5 slot) → çalışan toplam bloğu →
notlar → Fulfilment & Billing kartı → aksiyon çubuğu.

---

## 4 · Girdi: bugün ne çalışmıyor

Prototipi açtığında bunları göreceksin. Hiçbiri "bozuk" değil — hepsi çalışıyor ama
kullanıcıya iş çıkarıyor.

- **Aksiyon çubuğu tasarlanmamış, türetilmiş.** Şablonda yedi buton tanımlı ama
  görünürlükleri duruma bağlı, dolayısıyla aynı anda en fazla üçü çiziliyor —
  ve **hiçbir durumun yerleşimi tasarlanmış değil**. Sıralamayı şablondaki kaynak
  sırası ile iki `ms-auto` boşluğu belirliyor; bu boşluklar hangi butonların o an
  çizildiğine göre yer değiştiriyor. Sonuç: gönderilmiş bir siparişte yıkıcı
  **Cancel**, nötr **Close & release**'in *soluna* düşüyor. Ayrıca "birincil"
  aksiyon her durumda farklı bir görsel dille anlatılıyor: taslakta `btn-primary`
  (Submit), gönderilmişte `btn-success` (Create Invoice) — yani rengin kendisi
  hiyerarşi taşıyor.

- **Aynı sayılar üç ayrı yerde tekrar ediyor.** Grand total: özet datagrid'de (§7),
  çalışan toplam bloğunda (§9) ve Fulfilment kartının kendi datagrid'inde (§10a).
  Advance paid iki yerde. Delivered % ve Billed % hem datagrid'de hem ilerleme
  çubuklarında. Hiçbiri yanlış değil — ama sayfa üç kez aynı şeyi söylüyor.

- **Stok aşımı yalnız kırmızı metinle anlatılıyor.** Satırdaki `120 avail · …`
  yazısı `text-danger` oluyor, başka hiçbir işaret yok — renk körlüğünde tamamen
  kaybolur. Ayrıca **uyarı satırda, karar sayfanın en altında**: submit butonu
  kilitleniyor ama kullanıcı neden kilitli olduğunu görmek için yukarı kaydırmak
  zorunda.

- **Kur satırı yanlış yerde.** Yabancı para yoksa tamamen kayboluyor; varken de altı
  başlık alanının arasına `col-md-3` genişliğinde sıkışıyor. Oysa **yanlış kur bu
  ekranın en pahalı hatası** — 12 000 katı bir tutar farkı üretiyor ve tek göstergesi
  bu küçük kutu.

- **İskonto sütunları bir switch'in arkasında.** Açıldığında satır tablosuna iki sütun
  daha giriyor ve tablo yatayda taşıyor; kapalıyken iskontonun varlığı satırda hiç
  görünmüyor (yalnız toplam bloğundaki yeşil "− tutar" satırından anlaşılıyor).

- **Boş ve yükleniyor durumları tasarlanmamış.** Satırı olmayan bir taslakta tablo
  boş gövdeyle çiziliyor — ne bir yönlendirme, ne bir "ilk ürünü ekle" çağrısı.
  Müsaitlik yüklenirken satırda tek başına küçük bir spinner dönüyor.

- **Uzun RU/UZC metinleri hiç denenmemiş.** Beş dil var; Rusça ve Kiril Özbekçe
  metinler İngilizce'ye göre %40'a kadar şişiyor. "Close & release reserved stock" gibi
  butonlar ve `1 Korobka = 20 Dona` gibi satır içi metinler bu dillerde ne oluyor,
  bilinmiyor.

- **İki kullanım tek yerleşimi paylaşıyor.** Hızlı giriş modunda gereksiz olan
  Fulfilment kartı yok, ama takip modunda gereksiz olan başlık alanlarının tamamı
  hâlâ ekranın üstünde ve dikey alanın yarısını yiyor.

---

## 5 · Tasarım kısıtları — pazarlık dışı

Bunlar zevk değil, projenin hard-rule'ları. Bir öneri bunlardan birini ihlal ediyorsa
reddedilir.

1. **Frappe Desk'e link yok.** Hiçbir yerde `/app/...` bağlantısı, "Open in Desk"
   düğmesi, yeni sekme açma yok. Eksik bir işlev varsa Stabler'ın içinde tasarlanır.
2. **Para = `MoneyInput` + monospace.** Her parasal giriş `MoneyInput`, her parasal
   gösterim `font-monospace` ve sağa hizalı. Ham `<input type="number">` yok.
3. **Tarih = `DateInput` / `formatDate`.** Görünen biçim daima `gg.aa.yyyy`. Ham ISO
   dizesi yok, yerel `<input type="date">` yok.
4. **Bölge başına tek `btn-primary`.** İkincil aksiyonlar `btn-outline-secondary` /
   `btn-ghost-secondary`. Renk asla "ikinci birincil" olarak kullanılmaz.
5. **Durum rozetleri merkezden.** Sayfaya özel durum→renk eşlemesi yok;
   `getStatusBadgeClass` ne diyorsa o.
6. **Tablolar varsayılan çizgili** (global CSS). Manuel `table-striped` eklenmez;
   istisna gerekiyorsa `table-no-stripe`.
7. **Beş dil**: en, ru, uz, uzc, tr. Her metin `t()` içinden geçer, her yerleşim
   en uzun dilde de durur.
8. **Tabler CSS dili.** Mevcut sınıflar (`card`, `datagrid`, `steps`, `badge bg-*-lt`,
   `progress-bar`, `ti ti-*`) kullanılır; yeni bir tasarım sistemi getirilmez.
9. **Kur yönü.** Saklanan `conversion_rate` ERPNext yönünde kalır (`0,000082632`);
   **gösterim daima `1 USD = 12 101,85 UZS`**. Bu iki yön karıştırılamaz.
10. **Renk tek başına anlam taşımaz.** Her uyarı/hata durumu renk + ikon + metin ile
    çift kodlanır. Kontrast WCAG AA.
11. **Uydurma veri yok.** Prototipte ve önerilerde yalnız ekteki gerçek anjan
    rakamları kullanılır.

---

## 6 · Karar vermeni istediğim asıl soru

**Aksiyon çubuğunun mimarisi ve iki modun ilişkisi.**

a) Yedi butonluk küme — Save changes, Submit, Create Invoice, Cancel, Amend,
   Close & release, Delete — **dört durumun her biri için** nasıl *tek birincil
   aksiyon + ikincil grup + "daha fazla" menüsü*ne oturur? Hangi aksiyon hangi
   durumda birincil, ve birincillik nasıl anlatılır — konumla mı, `btn-primary` ile
   mi? (Spec §11'de dört durumun bugünkü buton kümeleri var. İpucu:
   `canCreateInvoice` yalnız `per_billed < 100` iken açılıyor, yani gönderilmiş bir
   siparişte "Create Invoice" çoğu zaman *tek anlamlı sonraki adım*.)

b) **Hızlı giriş** ve **takip** modları aynı yerleşimi mi paylaşmalı, yoksa
   ayrışmalı mı? Aynıysa hangi bölümler ikinci modda küçülmeli/katlanmalı;
   ayrıysa geçiş nerede oluyor?

**En az iki farklı yol tasarla**, ikisinin de artı/eksisini yaz, birini gerekçesiyle öner.

---

## 7 · Teslim edilecekler

1. **Dolu create ekranı** — 1440px. Ekteki `SAL-ORD-2026-13678` verisiyle (7 satır,
   579 000 UZS).
2. **Dolu submitted ekranı** — 1440px. `SAL-ORD-2026-08415` verisiyle (22 satır,
   %100 teslim / %97 fatura, bir bağlı fatura).
3. **Aksiyon çubuğu anatomisi** — create / draft / submitted / cancelled dört
   durumun her biri için buton kümesi ve hiyerarşi.
4. **Satır bileşeni**, dört varyantta: normal · stok aşımı · iskontolu · uzun Rusça
   ürün adı.
5. **Kur bloğu** — bilinen kur, bilinmeyen kur (`null`), yerli para (blok hiç yok)
   üç hâli.
6. **Boş, hata ve iskelet durumları** — satırı olmayan taslak · yükleme hatası ·
   yükleniyor.
7. **Dar ekran** — 768px'te aynı iki ekran. Satır tablosu nasıl davranıyor?
8. **Tasarım tokenları** — kullandığın aralık, tipografi ölçeği ve renk rollerinin
   listesi (Tabler değişkenlerine eşlenmiş).
9. **Karar notu** — §6'daki iki yol, karşılaştırma, öneri ve gerekçe. Kısa tut.

---

## 8 · Başarı ölçütü

İki soru. İkisi de "evet" olmalı:

1. **Satışçı, müşteri telefondayken 5 satırlık bir siparişi 60 saniyede girip
   onaylayabiliyor mu** — ve satırlardan biri stokta yetersizse bunu *submit'e
   basmadan önce* fark ediyor mu?
2. **Satış müdürü, bir hafta önceki bir siparişi açtığında neden hâlâ açık olduğunu
   üç saniyede söyleyebiliyor mu** — kaydırmadan, tablo okumadan?

---

## 9 · Yapma

- **Kod yazma.** Vue bileşeni, `.js`, `.py` üretme. Çıktı tasarım.
- **Yeni alan / özellik uydurma.** Ekranda olmayan bir veri alanı önerme; envanterde
  ne varsa onunla çalış. (Yeniden düzenleme, birleştirme, gizleme serbest.)
- **Desk'e benzetme.** Frappe Desk'in form düzeni referans değil, kaçınılan şey.
- **Paylaşımlı sözleşmeleri değiştirme.** `fx.js` altı ekranda, `MoneyInput` ve
  `LineItemsEditor` daha fazlasında kullanımda. Bunların API'sini değiştiren bir
  öneri getireceksen bedelini açıkça yaz.
- **Prototipi taklit etme.** O bugünün fotoğrafı, hedef değil.
