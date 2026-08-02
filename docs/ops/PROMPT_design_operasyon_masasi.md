# Tasarım brief'i · Stabler Operasyon Masası

Bu dosyanın tamamını Claude'a (tasarım oturumu) yapıştır. Çıktı: **kod değil, tasarım.**
Yüksek çözünürlüklü ekran tasarımı + tasarım kararlarının gerekçesi + geliştiriciye
teslim edilebilir spesifikasyon. Uygulama kodunu YAZMA — o iş ayrı bir oturumda,
bu tasarım onaylandıktan sonra yapılacak.

---

## 1. Ürün ve kullanıcı

**Stabler** — Özbekistan'da 7 şirkete hizmet veren çok kiracılı bir ERP (Frappe/ERPNext
üzerine kurulu Vue 3 SPA). Bu ekran **mikas** kiracısı için: sürekli devlet ihalesine
(UZEX) giren bir tedarik şirketi.

Tasarlanacak ekranın adı: **Operasyon Masası** (`/tender/desk`).

Kullanıcılar ve her birinin ekrandan beklediği tek cümle:

| Rol | Ekranı açtığında cevabını istediği soru |
|---|---|
| Genel Müdür | "Bugün neye müdahale etmeliyim, ne gecikiyor, kimde bekliyor?" |
| Sourcing sorumlusu | "Hangi lotlar için bugün teklif toplamalıyım?" |
| Gümrük | "Hangi beyan eksik evrak yüzünden duruyor?" |
| Lojistik | "Hangi teslimat gecikiyor, hangi PO yolda?" |
| Finans | "Hangi fatura vadesi geldi, hangi ödeme bekliyor?" |

Kullanım bağlamı: masaüstü tarayıcı, günde birkaç kez, çoğunlukla sabah ilk iş.
Diller: TR/RU/UZ/UZC/EN — **metin uzunlukları %40'a kadar şişebilir**, tasarım buna
dayanmalı (Rusça ve Kiril Özbekçe en uzun).

## 2. Bu ekranın tek işi

Klasik BI dashboard'u DEĞİL. Grafik ve KPI ikincil. Ekranın işi: **bugün yapılacak işleri,
kanıtıyla birlikte, tıklanabilir biçimde sıralamak.**

Her iş satırı beş soruyu aynı anda cevaplamak zorunda:
**ne · neden bugün · kim · ne zaman · hangi kayda gidiyor.**

"Neden bugün" kısmı tasarımın kalbi. Kuru bir sayı değil, kanıt cümlesi:
> "3/5 teklif toplandı · son tarih 2 gün sonra"
> "336 gün gecikme · UTY lot 2026-4325"

Kullanıcı bu satıra bakıp *işi anlamalı ve tıklayıp yapmaya gitmeli*.

## 3. Ekranın bölümleri (içerik sabit, yerleşim sana ait)

1. **Başlık** — tarih, şirket, aktif rol seçici, son güncelleme/yenile.
2. **Dört sayaç** — Bugün bitmeli · Geciken · Onayımda · Cevap bekliyor.
   Tıklanabilir; alttaki listeyi filtreler (basılı/seçili durumu belli olmalı).
3. **Bugünkü iş planı** — ana alan. 5–15 satır. Ağırlık burada.
4. **Karar / onay kutusu** — kullanıcının onayını bekleyen kararlar. Yan sütun.
5. **7 günlük takvim** — gün başına iş yoğunluğu, kritik günler işaretli.
6. **Ekip yükü** — yalnızca yönetici rollerinde görünür.

## 4. Girdi

Ekli prototipi aç: `operasyon-masasi-prototip.html` — mikas'ın 30 Temmuz 2026 tarihli
**gerçek** rakamlarıyla dolu, çalışan bir taslak. Bunu *yerleşim referansı* olarak kullan;
**taklit etme, geliştir.** Bilinen zayıflıkları:

- Görsel hiyerarşi düz — 12 satır birbirine çok benziyor, göz nereye gideceğini bilmiyor.
- Severity yalnızca ince renkli çubukla anlatılıyor; renk körlüğünde ayırt edilemez.
- Sağdaki karar kutusu ana listeden görsel olarak ayrışmıyor.
- Takvim ve ekip yükü şu an dekoratif; bilgi yoğunluğu düşük.
- Uzun Rusça metinlerde satırların ne olacağı test edilmemiş.
- Boş durumlar hiç tasarlanmamış (yeni kurulan şirkette bu ekran bomboş açılır).

## 5. Tasarım kısıtları — pazarlık dışı

- **Uydurma veri yok.** Prototipteki rakamlar gerçek; yeni sayı icat etme. Yerleşim için
  daha fazla satıra ihtiyacın olursa "örnek" olarak açıkça etiketle.
- **Para** her zaman monospace + para birimi kodu (сўм / UZS, USD). Hizalama sağa.
- **Tarih** gg.aa.yyyy. Göreli ifade ("2 gün gecikme") kanıt metninde serbest,
  ama mutlak tarih de erişilebilir olmalı.
- **Bölge başına tek birincil buton.** Aksiyonlar satırın kendisidir; her satıra buton koyma.
- **Severity çift kodlu olmalı** — renk + biçim (ikon/etiket/konum). Sadece renk yasak.
- **Tıklanan her satır bir kayda gider.** Tasarımda hedefi belli et (lot, PO, fatura).
- Kurumsal ERP tonu: sakin, yoğun, güvenilir. Tüketici uygulaması neşesi değil.
- Erişilebilirlik: WCAG AA kontrast, klavye ile gezinilebilir sıra, 40px+ dokunma hedefi.

## 6. Karar vermeni istediğim asıl soru: tema

Şu an iki gerçek var ve çelişiyorlar:

- Onaylanan **sunum koyu temalı** ve müşteri onu beğendi. Prototip de koyu.
- **Uygulamanın tamamı açık temalı** (Tabler CSS): Dashboard, CRM, Purchasing, Finance —
  onlarca ekran. Tek ekranı koyu yapmak tutarsızlık üretir.

Üç yolu da **tasarla ve karşılaştır**, sonra birini gerekçesiyle öner:

- **A · Açık tema, yüksek yoğunluk** — mevcut Tabler diliyle tam uyum. Ayrıcalık hissini
  tipografi, boşluk ve hiyerarşiyle kur, renkle değil.
- **B · Koyu tema, izole ekran** — sunumdaki his birebir. Sonucunu göster: kullanıcı
  CRM'den buraya geçtiğinde ne hissediyor?
- **C · Çift tema** — aynı bileşenler, token seviyesinde açık/koyu. Maliyeti ve
  bakım yükünü dürüstçe söyle.

Kararı ben vereceğim; sen üçünü de göster ve net bir öneri yap.

## 7. Teslim edilecekler

1. **Ana ekran tasarımı** — Genel Müdür rolü, dolu durum, masaüstü (1440px).
2. **Rol varyantı** — aynı ekran Sourcing rolünde (daha az sayaç, farklı satırlar).
3. **Üç tema karşılaştırması** (bölüm 6) + gerekçeli öneri.
4. **İş satırı bileşeni** — anatomi çizimi + tüm durumlar: geciken · bugün · yaklaşan ·
   bilgi · hover · odaklanmış (klavye) · uzun Rusça metin.
5. **Boş ve hata durumları** — "bugün iş yok" (bu iyi bir haber, öyle görünsün) ·
   "bu rol için yetki yok" · "şirket seçilmedi" · yükleniyor (iskelet).
6. **Mobil/dar ekran** (768px) — sütunlar nasıl yığılıyor, ne gizleniyor.
7. **Tasarım tokenları** — renk, tipografi ölçeği, boşluk, yarıçap, gölge; isimlendirilmiş
   ve geliştiricinin doğrudan kullanabileceği biçimde.
8. **Tasarım kararları notu** — her önemli seçim için tek cümle gerekçe.

## 8. Başarı ölçütü

Bu tasarım şu testi geçmeli: **Genel Müdür ekranı üç saniye görüp bugün ilk hangi işe
bakacağını söyleyebiliyor mu?**

Geçemiyorsa yerleşim yanlıştır — daha fazla renk veya ikon eklemek çözmez.

---

## Ekler

- `operasyon-masasi-prototip.html` — çalışan taslak, gerçek mikas verisi (bu klasörde).
- İstersen mevcut uygulamanın açık temasını görmek için: Stabler SPA Tabler CSS
  kullanıyor; kart/tablo/rozet dili oradan geliyor.

## Yapma

- Kod yazma (Vue/React/HTML implementasyonu bu oturumun işi değil).
- Yeni veri veya yeni özellik uydurma — kapsam bölüm 3'teki altı bölümdür.
- Prototipi birebir kopyalama; o bir başlangıç noktası, hedef değil.
- Grafik/chart ekleme — bu ekran iş listesi, analiz ekranı değil.
