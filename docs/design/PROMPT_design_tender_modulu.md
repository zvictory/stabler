# Tasarım brief'i — Mikas Tender modülü (16 ekran, iki aşama)

Bu dosyanın tamamını Claude'a (tasarım oturumu) yapıştır.
**Çıktı: kod değil, tasarım.**

**Zorunlu ek:**
- `docs/plans/2026-09-01-mikas-tender-tasarim-dili-tasarim-kurulu-karari.md` — kurul kararı.
  27 dosyalık envanter, numaralı 18 kusur (**biri çürütme turunda geri çekildi** →
  17 geçerli) ve ADR-301…307 orada, `dosya:satır` referanslarıyla. **Bu brief onu tekrar etmiyor; önce onu oku.**
- `docs/plans/2026-08-17-mikas-tender-workflow-formlari-tasarim-kurulu-karari.md` — önceki
  kurul. Büyük ölçüde uygulanmış; ADR-201/205/208 **kapalı kararlar**, yeniden açılmıyor.
- `docs/plans/stabler_modernist_design_guide.md` — `stbl-ds`'in kendi kılavuzu.
- `stabler/public/css/stabler-modernist.css` — tasarım sisteminin **tek** tanım dosyası
  (1038 satır). Token'lar 66-126, köprü katmanı 894-1017.

**Oturum başlamadan Zafar'ın vermesi gerekenler:** bkz. §7.0. Onlar olmadan §7'nin
B aşaması üretilemez.

---

## 1 · Ürün ve kullanıcı

**Stabler** — Frappe/ERPNext üzerine kurulu, tek kod tabanını **7 kiracının** paylaştığı
bir Vue 3 SPA. Beş katalog ship ediyor (`en, ru, uz, uzc, tr`), dördü seçilebilir.
Tender modülü **mikas** kiracısının: kamu ihalesi (UZEX), sourcing ve procure-to-pay.

Modülü **dört rol** kullanıyor. Hepsi aynı tasarım dilini görüyor, hiçbiri aynı soruyu
sormuyor. Kapılar `TenderNav.vue`'daki `v-if` ifadelerinden okundu:

| Kim | Gördüğü ekranlar | Ne zaman açar | Cevabını aradığı soru |
|---|---|---|---|
| **Direktör** | Direktör panosu, Süreç akışı, CRM, (+ herkese açık olanlar) | haftalık, yukarıdan | "Portföy nerede duruyor, hangi ihale takılmış, kim sorumlu?" |
| **Sourcing** | CRM, Benim ihalelerim, RFQ'lar, Sourcing çalışma alanı, PO kontrol | **her gün, işin merkezinde** | "Bu lot için yeterli teklif topladım mı, kimi kazandırıyorum, gerekçem yazılı mı?" |
| **Gümrükçü** | Gümrük kuyruğu | sevkiyat geldikçe | "Hangi PO'nun belgesi eksik, hangisi beyana hazır?" |
| **Lojistikçi** | Lojistik panosu | sevkiyat geldikçe | "Hangi konteyner nerede, hangisi sınırda bekliyor?" |
| **Dördü birden** | Operasyon masası, Genel bakış, Sözleşme panosu, **Belge merkezi** | günlük | "Bugün ne yapmam gerekiyor?" |

Belge merkezi tek ortak çalışma alanı ve **kenar çubuğundan** giriliyor, tender üst
çubuğundan değil (`Sidebar.vue:85`) — bu bilinçli, gerekçesi `Sidebar.vue:56-58`'de yazılı.

---

## 2 · Bu modülün tek işi

Bir kamu ihalesi lotunu **görülür**den **paraya** taşımak, ve her adımda *neden böyle
karar verildiğini* denetlenebilir bırakmak.

Zincir: ihale girişi → GO/NO-GO → RFQ gönderimi → teklif toplama → karşılaştırma →
**ödül kararı** (yazılı gerekçeyle) → PO → gümrük → lojistik → teslim → fatura → tahsilat.

Kritik nokta: **ödül kararı geri alınamaz ve denetlenir.** `Tender Sourcing Decision`
doctype'ı üç kuralı kendi içinde zorluyor — onay damgasını sunucu yazar, durum tek yönlüdür
(Taslak→Onaylı), ve kısa teklif kümesi (5 teklif / 2 ülke altı) yazılı gerekçe ister.
Tasarım bu kararın **ağırlığını** taşımalı: yanlışlıkla tıklanabilir görünmemeli.

---

## 3 · Mevcut durum

Modül tasarım sisteminin **çoğunlukla** içinde — `TenderPage.vue:12`
`class="tender-page stbl-ds"` `/tender/*`'ın büyük kısmını sarıyor — ama **27 dosyanın
17'si sıfır `ds-*`**. Onlar yalnızca köprü katmanının yeniden derisini alıyor, yani Tabler
görünüyorlar.

**İki ekran sarmalın tamamen dışında:** `RfqPrint.vue` ve `BidPricing.vue`'da
`TenderPage` **0** kez geçiyor — orada `stbl-ds` hiç uygulanmıyor, köprü katmanı bile.

Üç lehçe bir arada:
- `ds-*` — tasarım sistemi. Referans: `TenderCrm.vue` (107 kullanım).
- **çıplak Tabler** — 17 dosya, `SourcingWorkspace.vue` (1039 satır) dahil.
- **`tgm-*`** — yalnız `TenderMasterDrawer.vue`'da; bu dosya `components/` altında,
  yukarıdaki 27'lik kümenin **dışında** (46 kullanım; `<style scoped>` 658'de
  başlıyor, dosya 777 satır → 119 satırlık blok). En yeni ve en kritik form. 15 sınıfının
  9'unun `ds-*`'ta **adı** karşılık buluyor, ama **değerleri tutmuyor**: `.tgm-drawer`
  720px / z-index 1050 iken `.ds-drawer` 542px / z-index 41; `.tgm-drawer-title` 18px iken
  `.ds-drawer-title` 22px; `.ds-form-section` `.tgm-sec`'in yapmadığı çerçeve, kenar
  boşluğu ve arka plan ekliyor. Yani bu bir bul-değiştir işi **değil**.

Rota sayısı: `router.js`'te 18 `/tender` girdisi, 2'si yönlendirme → **16 ekran**.
Ayrıca rotası olmayan gömülü bileşenler var: `TenderIntake`, `BidPricing`,
`TenderDocumentsPanel`, `TenderExecutionFlow`, `TenderWorkspaceTabs`.

---

## 4 · Bugün ne çalışmıyor

**Kurul kararının §2'sinde kusurlar `dosya:satır` ile duruyor (biri çürütme turunda geri
çekildi). Burada tekrarlanmıyor.** Tasarım açısından en belirleyici dördü:

- **Karşılaştırma tablosu taşıyor.** 9 sütun + satır başına 4 aksiyon düğmesi, ve dosyada
  `table-responsive` hiç geçmiyor. Bu, sourcing kullanıcısının günde onlarca kez baktığı
  ekran.
- **Ödül paneli 1039 satırlık bir ekranın üçüncü işi.** Karşılaştırma, "atanmamış teklifleri
  eşleştirme" ve ödül kararı aynı dosyada, alt-rota veya sekme olmadan.
- **Akış iki yerden kopuk.** PO panosundan sourcing'e veya RFQ'ya **0** bağlantı;
  `TenderIntake` zincirin hiçbir yerinde değil (yalnız `PoControlBoard` içinde gömülü).
  *(Üçüncü sandığım kopukluk — "RFQ listesine giriş yok" — yanlıştı: `TenderNav.vue:56`
  bağlıyor.)*
- **Hata ile boş ayırt edilemiyor.** `RfqList.vue`'da catch yalnız bir toast atıp satırları
  boşaltıyor; sonra gerçek boş listenin `EmptyState`'i çiziliyor. Toast kaybolduğunda
  kullanıcının ekranında "hiç RFQ yok" yazıyor — oysa sunucu hata döndü.

---

## 5 · Tasarım kısıtları — pazarlık dışı

Bunlar **kural**, soru değil. Her biri bir dosyaya bağlı.

**5.1 · `.claude/rules/10-frontend.md`'nin dokuz mandası**
1. Frappe Desk'e yönlendirme **yok** — `/app/...` linki, `window.open`, hiçbiri.
2. Tablolar varsayılan çizgili; `table-striped` elle eklenmez.
3. Para **yalnız** `MoneyInput`; ondalık sayısı **yalnız** `moneyFractionDigits(currency)`.
4. Tarih **yalnız** `DateInput` + `formatDate()`; görünen format `dd.mm.yyyy`.
5. Görsel bölge başına **tek** `.btn-primary`. Renk ikinci bir primary değildir.
6. Tutarlar **yalnız kendi işlem para biriminde**. Taban/USD çevrimi yok.
7. Durum rozetleri **yalnız** `getStatusBadgeClass`'tan. Sayfa yerel renk haritası yok.
8. Liste ekranları `ListToolbar` + otomatik uygula (Uygula/Yenile düğmesi yok), arama
   yer tutucusu `⌘K` ile biter.
9. Yükleme = `SkeletonRows`, çıplak spinner değil.

**5.2 · Mimari kısıtlar**
- **ERPNext'e dokunulmaz** (ADR-307). Bu iş için yeni doctype, yeni alan veya yeni patch
  **gerekmiyor** — ihtiyaç duyulan her şey mevcut alanlarda var. Tasarımın bir yerde yeni
  alan gerektirdiğini düşünüyorsan, onu bir **soru** olarak işaretle; sessizce varsayma.
  (Repo yeni Custom Field eklemeyi yasaklamıyor — v68 ve v83 patch'leri ekliyor. Yasak
  olan, bu iş kapsamında bunu gerekçesiz yapmak.)
  Bilinen tek sınır durumu: CRM'de "RFQ gönderildi mi" göstergesi. Bu **yeni alan
  gerektirmiyor** — `sourcing.list_rfqs`'in bugün yaptığı gibi mevcut `custom_crm_deal`
  üzerinden sayılabilir; ama `crm_board`'ın `sourcing`'i çağıramaması yüzünden
  (`sourcing.py:35` `tender`'ı import ediyor → döngü) birkaç satır `stabler/api` işi
  gerektiriyor. Tasarımı çiz; uygulanması Zafar'ın kararı.
- **Rol kapıları değişmez** ve kapı **uçta** durur, navigasyonda değil. Gerekçesi bir
  olayla `tender.py`'nin `_require_any_tender_view` docstring'inde yazılı: menü gizlese
  bile URL'yi bilen kullanıcı 200 alıyordu.
- **Gümrük kuyruğu ve lojistik panosu salt-okuma projeksiyondur (R3).** Kart sürükleyerek
  ilerletme **eklenmez** — kartı ilerleten şey gerçek belge/sevkiyat olayıdır.
- **`Tender Sourcing Decision`'a ikinci bir yazma yolu açılmaz.**
- **`awardPanelMode` kararı tek fonksiyonda kalır**, şablona dağıtılmaz — bir reload
  hatası tam bu yüzden çıkmıştı (`SourcingWorkspace.vue:52-71`).
- **Belge gereksinim listesinin tek yazarı belge merkezidir**, pinli testle korunuyor.
  İkinci bir düzenleme yeri eklenmez.

**5.3 · Veri kısıtları**
- **Karşılaştırma tablosu iki para birimini birlikte gösterir**: teklifin kendi kuru
  (`r.currency`) ve lot'un taban kuru. Tek kura indirilmez — farklı ülkelerden gelen
  teklifleri kıyaslamanın tek yolu bu.
- **Politika sayısı sunucudan gelir** (`_procurement_policy.py` → `tender_views().policy`),
  ekrana yazılmaz. 5 ve 2 rakamları tasarımda **sabit metin olarak geçmez**.
- **Sunucu sayfalaması yok**: `list_rfqs` ve `tender_quotations` tüm satırları döndürüyor
  (`limit_page_length=0`). Tasarım sayfalama varsaymaz; ama politika tabanı (≥5 teklif)
  tabloların küçük kalacağını söylüyor.
- **Karanlık mod yok** (`stabler.html:3` sabit `light`). İcat edilmez.

**5.4 · i18n**
- `t("...", {name})` interpolasyonu var; **çoğul desteği yok**. "1 teklif / 5 teklif"
  ayrımı yapılamaz — metinler bunu gerektirmeyecek şekilde kurulur.
- Uzama ölçüldü: en kötü **3.75×** (`RFQs` 4 → uz `Narx so'rovlari` 15).
  **Sabit genişlikli nav maddesi, rozet veya düğme tasarlanmaz.** Her etiket en az 4 kat
  uzayabilecek şekilde denenmiş olmalı.
- `uzc` (Kiril Özbekçe) seçilemiyor ama hâlâ render ediliyor — kırılmamalı.

---

## 6 · Karar vermeni istediğim asıl sorular

**Her soru için en az iki farklı yol tasarla, ikisinin de artı/eksisini yaz, birini öner
ve nedenini söyle.** "Duruma göre" bir cevap değil.

### S1 · Üç lehçe teke nasıl iner?
İki ayrı soru, karıştırma:

**(a) Adı eşleşen 9 sınıf.** `ds-*`'ta aynı işi yapan bir sınıf var ama **ölçüleri farklı**
(720px↔542px, z-index 1050↔41, başlık 18px↔22px, bölüm çerçevesi var↔yok). Hangi değer
kazanır? Çekmecenin 720px'e mi ihtiyacı vardı, yoksa 542px yeterli mi? Bu karar
`ds-drawer`'ı kullanan **diğer** ekranları da etkiler — `TenderCrm.vue:578-721`'de çalışan
bir örnek duruyor, ona bak.

**(b) Karşılığı olmayan 6 sınıf.** `tgm-file-chip/-list/-name`, `tgm-sec-num`,
`tgm-drawer-dialog/-content`. Son ikisi Bootstrap modal iskeletidir — `ds-drawer` kendi
iskeletini getirdiği için bunlar **yeniden adlandırılmaz, silinir**. Kalan dördü `ds-*`'ın
gerçek eksiği mi? Eksikse `ds-*`'a ne eklenmeli?

**Ek bir mimari sorun, çözümünü senden beklemiyorum ama tasarımın onu görmesi gerek:**
`.ds-drawer`'ın z-index'i 41; Bootstrap modal bandı 1040+. Çekmece, `LandedChargesEditor`
gibi modallarla aynı sayfada yaşıyor.

### S2 · Karşılaştırma tablosu dizüstüne nasıl sığar?
9 sütun (Tedarikçi · Ülke · Toplam · Sticker · Landed tahmini · Teslim toplamı · Geçerlilik ·
Durum · Aksiyonlar) + satır başına 4 düğme, üstelik iki para birimi zorunlu.
Sütun önceliği mi? Satır genişletme mi? Ayrı detay mı? Yatay kaydırma mı?

### S3 · Ödül paneli nerede yaşar?
Bugün 1039 satırlık ekranın içinde üçüncü iş. Ayrı adım/rota mı, aynı sayfada bir aşama mı?
Kısıt: karar geri alınamaz, gerekçe zorunlu, ve `awardPanelMode` tek fonksiyonda kalmalı.
Tasarım bu ağırlığı nasıl gösterir — onay adımı, özet önizleme, başka bir şey?

### S4 · Belge merkezi nerede durur?
Bugün kenar çubuğunda müstakil, çünkü dört rolün de ortak alanı. Bu doğru mu, yoksa lot
bağlamına mı girmeli? Girerse dört rol ona nasıl ulaşır?

### S5 · Zincir nerede görünür?
"RFQ gönderildi · teklif alındı · sonuç ne" bugün hiçbir üst ekranda görünmüyor. Bu üç
durum CRM kartında mı, PO panosunda mı, ikisinde birden mi? Ve **tek bir satırda** nasıl
anlatılır?

### S6 · Rol kuyrukları kanban mı liste mi?
Gümrükçü ve lojistikçi salt-okuma projeksiyon görüyor — sürüklenemez. Sürüklenemeyen bir
kanban yanıltıcı mı? Liste daha mı dürüst?

### S7 · İhale girişi tek form mu, adımlı mı?
`TenderMasterDrawer` 777 satır ve büyüyor. Çekmece içinde sekme/adım bölünmesi mi, tek
uzun kaydırma mı? Kısıt: yedi alanın sahibi bu form, ve belge listesi **buraya girmez**.

---

## 7 · Teslim edilecekler

### 7.0 · Veri ön koşulu
Uydurma veri yasak. İki dal var, Zafar hangisinin işlediğini söyler:
- **(a) Gerçek kayıt varsa:** anonimleştirilmiş bir ihale lotu — intake'i, en az 5
  teklifi (en az 2 ülkeden), bir ödül kararı, bir PO.
- **(b) Yoksa:** `stabler/tests/` fixture'ları kullanılır ve **her ekran durumu "sentetik"
  etiketiyle** teslim edilir. 2026-08-28 ölçümü mikas prod'da 0 CRM Deal / 0 RFQ / 0 teklif
  diyordu; bugünkü durum doğrulanmadı.

### 7.1 · Aşama A — bileşen dili (önce bu, tek başına onaylanır)
`stbl-ds`'i **genişlet**, yenisini icat etme. Teslim:
1. Mevcut `ds-*` envanterinden tender'ın kullanacağı alt küme — her biri dolu/boş/hata/
   dar-ekran hâliyle.
2. **Önce mevcut `ds-*` denenir** (ADR-303 düzeltildi): `ds-table` 5 dosyada, `ds-panel`
   7'de, `ds-kanban` 1'de zaten kullanılıyor. Karşılaştırma tablosu, ödül paneli ve rol
   kuyruğu için **önce bunların yetip yetmediğini göster**. Yeni bileşen ancak somut bir
   boşluk kanıtlanırsa gerekçelenir — ve gerekçesi teslimatta yazılı olur.
3. `tgm-*` için S1'in iki dallı cevabı: adı eşleşen 9 sınıfın uzlaştırılmış değerleri +
   karşılıksız 6 sınıfın kaderi (2'si silinir).
4. Form gramerinin tamamı: bölüm başlığı, alan, zorunluluk işareti, ipucu, hata, çok
   satırlı metin, para, tarih, tipeahead, çoklu seçim, dosya eki çipi.
5. Buton hiyerarşisi — bölge başına tek primary kuralıyla, tender'ın gerçek aksiyon
   kümeleri üzerinde gösterilmiş.
6. Durum grameri: yükleniyor / boş / hata / yetkisiz, dördü de ayrı.

### 7.2 · Aşama B — 16 ekran
ADR-209'un düzeltilmiş sırasıyla: **(1)** ihale girişi çekmecesi → **(2)** sourcing üçlüsü
(`SourcingWorkspace`, `QuotationEntryDrawer`, `rfq/*`) → **(3)** belge merkezi →
**(4)** post-win panoları (`PoControlBoard`, `DeclarantQueue`, `LogistBoard`) →
**(5)** oksüz kalanlar (`BidPricing`, `TenderIntake`, panolar).

Her ekran için: masaüstü + dar ekran · dolu + boş + hata · ve ekranın **kabul ölçütü**
(hangi durumda hangi eleman görünür) — bu ölçüt uygulama diliminde teste çevrilecek (ADR-306).

### 7.3 · Akış haritası
S5'in cevabı bir çizim olarak: bir lot'un intake'ten tahsilata yolculuğu, hangi rolün
hangi noktada ne gördüğü, ve **iki** kopukluğun (kusur 14 ve 16) nasıl kapandığı.

> Kusur 15 ("`RfqList`'e akış içinden giriş yok") çürütme turunda **geri çekildi** —
> `TenderNav.vue:56` `/tender/rfq`'ya bağlıyor.

---

## 8 · Başarı ölçütü

Tasarım şu sayıları hareket ettirebiliyorsa başarılı — hepsi bugün ölçülmüş durumda.
Her satır, **hiçbir şey yapmayan bir değişiklikle sağlanamayacak** biçimde yazıldı:

| Ölçü | Bugün | Hedef | Neden hile yapılamaz |
|---|---:|---:|---|
| `TenderMasterDrawer`'da `tgm-*` | 46 | 0 | **ve** aynı dosyada `ds-drawer` + `ds-form-section` > 0, **ve** çekmece `data-size="lg"` taşıyor — sınıfları silip stilsiz bırakmak geçmez |
| Sıfır `ds-*` taşıyan tender dosyası | 17 | 0 | **ve** `RfqPrint` ile `BidPricing` bir `.stbl-ds` atası kazanıyor |
| `SourcingWorkspace`'te `table-responsive` | 0 | ≥1 | **ve** 1280px'de tablonun taşmadığını gösteren bir mount testi var |
| `PoControlBoard`'dan sourcing/RFQ bağlantısı | 0 | ≥1 | — |
| `RfqList`'te hata ≠ boş | aynı | ayrı | bir mount testi başarısız çağrıyı taklit edip iki durumun **farklı eleman** çizdiğini iddia ediyor; bugün de bir toast var, toast bu ölçütü geçmez |
| Bileşen mount eden tender spec'i | 0/5 | ≥1 ekran başına | — |
| `stabler/` dışı değişen dosya | 0 | 0 | **ve** değişen doctype JSON'u 0, **ve** yeni patch 0 — bugün doğru, ama bir Custom Field patch'i eklenirse kırılır |

Ve bir nitel ölçüt: **sourcing kullanıcısı ödül kararını yanlışlıkla veremiyor olmalı.**

---

## 9 · Yapma

- **Yeni tasarım sistemi icat etme.** `stbl-ds` var; genişletilir, değiştirilmez.
- **Tabler'ı atma.** Sistem onun üstüne kurulu, paleti onun (`stabler-modernist.css:7-11`).
- **Karanlık mod ekleme.** Yok, ve bu iş onu getirmiyor.
- **5 ve 2 rakamlarını ekrana yazma.** Sunucudan geliyorlar.
- **Taban para birimine çevrilmiş tek bir toplam gösterme.**
- **Gümrük/lojistik panolarına sürükle-bırak ekleme.**
- **Belge gereksinimlerini ikinci bir ekrandan düzenletme.**
- **Sabit genişlikli etiket, rozet veya nav maddesi tasarlama** — 3.75× uzuyorlar.
- **ERPNext alanı, doctype'ı veya patch'i önerme.**
- **Kod yazma.** Bu oturumun çıktısı tasarım.
