# MSA — açık sahip kararları

**Tarih:** 2026-07-23
**Bağlam:** `docs/plans/msaerp-parity/00-INDEX.md` sekiz açık sahip kararı
listelemişti. Bu belge onları tek yerde toplar, verilen kararı ve **gerekçesini**
kaydeder. Karar değiştirilebilir; ama kaydedilmeden değiştirilemez.

Ayrıca burada, listede olmayan ama uçtan uca test sırasında ortaya çıkan bir
karar daha var (D0) — çünkü canlı bir ayar test sırasında değiştirilip öylece
bırakılmıştı.

---

## D0 — Stok parti seçimi: son kullanma tarihine göre ✅ KARAR VERİLDİ

**Durum:** msa.erpstable.com üzerinde **aktif**.

```
Stock Settings.pick_serial_and_batch_based_on          = "Expiry"
Stock Settings.auto_create_serial_and_batch_bundle_for_outward = 1
```

**Nasıl oldu:** 2026-07-23 uçtan uca döngü testi sırasında, ERPNext 16'da stok
çıkışının parti bundle'ı üretebilmesi için değiştirildi. Test bitti, ayar kaldı.
Bu belge yazılana kadar hiçbir yere kaydedilmemişti.

**Karar:** Kalsın.

**Gerekçe:** Donmuş et raf ömrüne karşı satılır, satın alma tarihine karşı
değil. Sonra gelen bir parti pekâlâ daha erken bozulabilir (farklı üretim
tarihi, farklı tedarikçi), dolayısıyla giriş sırasına göre çıkarmak hâlâ
satılabilir malı yaşlandırırken bozulmak üzere olanı sevk eder. `Expiry`
ayarı ERPNext'in kendisini FEFO yapar.

**Sonucu — mimari:** `stabler/api/_fefo.py` ve `inventory.py`'deki parti uçları
artık **seçim motoru değil, görünürlük ve denetim katmanıdır.** Partiyi ERPNext
seçer; biz raf ömrünü gösterir, tahsisatı önizler ve süresi geçmiş stoğu
raporlarız. Bu daha sağlam bir iş bölümü: seçim mantığı ERPNext'in stok
motorunda tek yerde durur, biz onu ikinci kez uygulamayız.

**Kapsam:** Yalnızca msa. Ayar site bazlıdır; diğer 6 tenant etkilenmedi.
Başka bir tenantta açmadan önce o tenantın stok davranışını ölçün.

---

## D1 — İrsaliye / WMS ✅ KARAR VERİLDİ

**Karar:** Hayır. Satış Faturası = sevk belgesi modeli kalır (`update_stock=1`).

**Gerekçe:** Mevcut sadelik korunur. Ayrı bir sevk belgesi, imza/fotoğraf/plaka
kaydı ve depo yönetimi katmanı bugünkü operasyona değer katmıyor.

**Sonucu:** CI-packing planının **Faz 3'ü daralır**. "QC + zorunlu istisna
fotoğrafı" maddesi kapsam dışıdır — sevk tarafında yakalanacak bir belge
olmadığı için tutunacağı yer yok. Faz 3'ten geriye dört-TIR süpervizör matrisi
ve satır içi kabul çekmecesi kalır.

**Bilinen boşluk:** Sevkiyatta teslim kanıtı (imza, fotoğraf, araç plakası)
tutulmaz. Bir müşteri "mal gelmedi" derse elde fatura ve stok hareketinden
başka kanıt yoktur. Karar bilinçlidir; itiraz gelirse bu satır hatırlatılsın.

---

## D2 — Müşteri hiyerarşisi ve kredi limiti ✅ KARAR VERİLDİ

**Karar:** İkisi de gerekli — ana/alt müşteri yapısı **ve** kredi limiti.

**Bugünkü durum:** Kodda hiçbiri yok. Ne parent/child müşteri alanı, ne limit
alanı, ne kontrol. Sıfırdan yazılacak.

**D1 ile etkileşimi — dikkat:** İrsaliye olmadığı için stok, Satış Faturası
submit edildiği anda çıkar. Dolayısıyla **kredi kontrolü SI submit'te
çalışmalıdır**; yalnızca Sipariş aşamasında kontrol edilirse mal çoktan gitmiş
olur. Sipariş aşamasında uyarı, fatura aşamasında engel doğru kurgu.

**D4 ile etkileşimi — dikkat:** Excel toplu aktarım kalıcı özellik olacaksa
(D4), toplu yüklenen satışların kredi kontrolünü **atlamaması** gerekir. Toplu
yollar limit kontrolünü delen klasik açıktır.

---

## D3 — MSAERP'teki 7 günlük ödeme kuralı ⏳ AÇIK

Eski sistemde bu kuralın **üç farklı uygulaması** var ve birbirini tutmuyor.
Hangisi doğru kabul edilecek, veya kural tamamen yeniden mi tanımlanacak?

Karar verilmeden ödeme otomasyonu yazılamaz — hangi davranışı taklit
edeceğimiz belirsiz.

---

## D4 — Excel toplu satış/tahsilat aktarımı ✅ KARAR VERİLDİ

**Karar:** Kalıcı özellik. Kullanıcılar canlıda da Excel'den toplu satış ve
tahsilat yükleyebilecek.

**Sonucu — bu bir defalık script değil, ürün:** doğrulama (satır satır, yüklemeden
önce), anlaşılır hata raporu, kısmi başarı davranışı, ve geri alma yolu gerekir.
Kalıcı bakım yükü kabul edilmiştir.

**Bağımlılık:** D2 kredi kontrolü bu yoldan da geçmelidir (yukarıya bakınız).

---

## D5 — Vendor Category göçü ⏳ AÇIK

MSAERP'teki tedarikçi kategorileri Stabler'a nasıl taşınacak? Birebir mi,
yeniden mi tanımlanacak?

---

## D6 — Banka ekstresi parser önceliği ⏳ AÇIK

Bugün yalnızca 1C ClientBank Exchange formatı destekleniyor. MT940 / SWIFT /
OFX ne zaman, hangi sırayla? Yoksa hiç mi?

---

## D7 — Mali yıl kurulum sahipliği ⏳ AÇIK

Fiscal Year açılışını kim yapacak — Stabler mı yönetsin, yoksa muhasebe
ERPNext üzerinden mi kursun?

---

## D8 — SPA kural ihlali temizliği ⏳ AÇIK

`docs/plans/msaerp-parity` altında listelenen SPA kural ihlalleri (Desk
yönlendirmesi, çıplak tarih girişi, merkezî olmayan statü eşlemesi vb.) ne
zaman toplu temizlenecek?

---

## Kararların işe etkisi (özet)

| Karar | Açtığı iş | Kapattığı iş |
|---|---|---|
| D0 | FEFO görünürlük UI'ı (raf ömrü sütunu, SKT uyarı sayfası) | Satış belgesine parti yazma kodu — gerek kalmadı |
| D1 | — | CI-packing Faz 3'ün QC + fotoğraf kısmı |
| D2 | Müşteri hiyerarşisi + kredi limiti + SI submit kontrolü | — |
| D4 | Excel aktarım ürünü (doğrulama, hata raporu, geri alma) | Tek kullanımlık ETL scripti |

**Sıradaki iş, bu kararlara göre:**

1. FEFO görünürlük UI'ı — D0'ın doğal devamı, backend hazır
2. CI-packing Faz 2 (çoklu GTD çıkış kapıları, bağımsız TIR takibi) — hiçbir
   karara bağlı değil
3. CI-packing Faz 3 (daraltılmış: TIR matrisi + kabul çekmecesi)
4. D2 — müşteri hiyerarşisi ve kredi limiti (ayrı plan gerekir)
5. D4 — Excel aktarım ürünü (ayrı plan gerekir)

D3, D5, D6, D7, D8 karara bağlanana kadar planlanamaz.
