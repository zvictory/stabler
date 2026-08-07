# Customer Center — Impeccable kritiği ve önerilen tasarım

**Tarih:** 2026-08-05
**Hedef:** `Customer Center - Modernist Tabler.dc.html` · `stabler/public/js/pages/sales/Customers.vue`
**Yöntem:** `/impeccable critique` — iki izole alt-ajan (A: tasarım incelemesi, B: deterministik dedektör + tarayıcı kanıtı)

---

## 0. Tek cümlelik teşhis

**Ekran alacakları mükemmel *gösteriyor*, ama alacak *işi* yapmıyor.**

Ekstre bloğu (devreden satırı, borç/alacak renkleri, yürüyen bakiye, koşullu kur satırı,
kapanış şeridi) kategorisinin en iyilerinden — bir denetçi ekrandan okuyabilir. Ama
ekstreyi çıkarınca geriye kalan (arama, iki select, dizin, detay kartı, beş sekme)
herhangi bir SaaS CRM'in gönderdiği master-detail deseni. Tahsilat işine dair
hiçbir şey yok: sıralama yok, kredi limiti yok, müşteri bazında yaşlandırma yok,
arandı/söz verdi/itirazlı durumu yok, not yok. Muhasebeci 8 saat çalışıp çıkıyor ve
arayüzde orada olduğuna dair hiçbir iz kalmıyor.

---

## 1. Design Health Score — 19/40 (Poor bandı)

| # | Nielsen sezgiseli | Puan | Kilit sorun |
|---|---|---|---|
| 1 | Sistem durumu görünürlüğü | 2 | Aramaya yazınca ağaç sessizce düzleşiyor ama "Ağaç" hâlâ aktif görünüyor; loading/empty/saved state yok |
| 2 | Sistem ↔ gerçek dünya | 3 | Alan sözlüğü çok iyi (Cari hesaplar, Devreden, Borç/Alacak, Vade aşımı); ama üç farklı para gösterimi (`сўм` / `UZS` / hiç) ve muhasebeciye gösterilen ham şema stringleri |
| 3 | Kullanıcı kontrolü ve özgürlük | 2 | Filtre temizleme yok, arama temizleme yok, ağaç kapatma yok (chevron ölü), tarih sıfırlama yok |
| 4 | Tutarlılık ve standartlar | 2 | Canlı kontroller görsel olarak birebir aynı ölü kontrollerin yanında; "Toplam alacak" aynı ekranda iki farklı sayıyı etiketliyor |
| 5 | **Hata önleme** | **1** | Adı konmuş pahalı hata — yanlış müşteriye tahsilat — hiç savunmasız: isim yankısı yok, bakiye yankısı yok, tek tık seçim |
| 6 | Hatırlamak yerine tanımak | 2 | `Cmd+K` 1700px aşağıda 10.5px gri ile duyuruluyor ve zaten yok; XLSX ekstre `⋯ Diğer` içinde saklı |
| 7 | **Esneklik ve verimlilik** | **1** | Kolon sıralaması yok (1 numaralı iş sıralama), toplu aksiyon yok, satırlar klavyeyle açılmıyor, 128 satır için sayfalama yok |
| 8 | Estetik ve minimalizm | 3 | Modernist dünya disiplinli kullanılmış; ama ekrandaki her etiket aynı 10px mono uppercase `#9099a6` nesnesi — 360 panelinde ~20 tanesi doku gibi okunuyor |
| 9 | **Hatadan kurtulma** | **1** | Hiç hata yüzeyi yok: başarısız yükleme yok, boş sonuç yok, "bu dönemde hareket yok" yok; tarih alanları doğrulamasız düz metin |
| 10 | Yardım ve dokümantasyon | 2 | `ds-kpi-q` şema dipnotları gerçek bir satır-içi dokümantasyon; ama "kümülatif" vs "kendi", "Devreden", konsolidasyon anahtarı hiç açıklanmıyor |

**Dürüst not:** 19/40 görsel işi olduğundan kötü gösteriyor. Açık neredeyse tamamen
**davranışsal tamlık ve sayısal doğruluk**ta yoğunlaşıyor — kompozisyon, tipografi
ve ekstre hiyerarşisinde değil. Ölü kontroller, toplam çelişkisi, sıralama ve state
kapsamı düzeltilse tek bir renk/radius/font boyutu değişmeden **28–30** bandına çıkar.

### Bilişsel yük: 8 maddenin 5'i başarısız → kritik

| Madde | Sonuç |
|---|---|
| Tek odak | **FAIL** — Cockpit'te dört eşit bilgi bloğu, hiçbiri birincil işaretli değil |
| Parçalama (chunking) | PASS |
| Gruplama | PASS — `gap:1px` grid tekniği sayfanın en iyi yapısal hamlesi |
| Görsel hiyerarşi | **FAIL** — Üç 28px, beş 20px, iki tablo dolusu 14px mono sayı; hepsi tek etiket muamelesiyle |
| Tek seferde tek şey | PASS |
| Minimum seçim | **FAIL** — 8 karar noktasının 7'sinde >4 görünür seçenek |
| Çalışma belleği | **FAIL** — Hangi "Toplam alacak" gerçek, gösterilen parent bakiyesi kendi mi kümülatif mi |
| Aşamalı açığa çıkarma | **FAIL** — İlk ekstre satırı ~900px aşağıda; panelin var olma sebebi en son açığa çıkıyor |

---

## 2. Deterministik kanıt (Assessment B)

### Dedektör

| Dosya | Bulgu | Kural |
|---|---|---|
| Customer Center | 6 | `side-tab` ×6 |
| Tender CRM (kalibrasyon) | 2 | `side-tab` ×2 |
| Stabler Dashboard (kalibrasyon) | 2 | `side-tab` ×2 |

Tarayıcı içi dedektör: **52 anti-pattern** — `undersized-ui-text` ×35, `side-tab` ×12,
`tiny-text` ×4, `all-caps-body` ×1.

**Yanlış pozitifler (bu pinlenmiş tasarım sistemi için):**
- `side-tab` (12) — 3px sol/üst şerit burada dekor değil, **anlam taşıyor**
  (`over>=60 ? DANGER : over>=30 ? WARN : transparent`). Kalibrasyon dosyaları aynı
  deseni kullanıyor → sistem konvansiyonu. **Ama içinde gerçek bir bulgu saklı:**
  kodlama yalnızca renkle yapılıyor, kırmızı-yeşil renk körü kullanıcı `DANGER` ile
  `WARN` şeridini ayıramıyor.
- `all-caps-body` (1) — mono eyebrow breadcrumb, brief'in imzası.
- 0 border-radius, kısıtlı palet, 42px yoğunluk, gölgesizlik — hiçbir kural şikâyet
  etmedi, etseydi reddederdim.

**Gerçek bulgu:** `tiny-text` + `undersized-ui-text` tek başına brief'e uygun; asıl
kusur **kesişim** — 10px **VE** 2,71–2,88:1 kontrast.

### Kontrast (canlı ölçüm, WCAG AA = 4,5:1 normal / 3:1 büyük)

| Renk çifti | Oran | Sonuç |
|---|---|---|
| `#9099a6` → `#ffffff` | **2,88** | ✗ (dosyada 36 kullanım) |
| `#9099a6` → `#f6f8fb` | **2,71** | ✗ |
| `#9099a6` → `#fbe7e7` (kırmızı bakiye panelindeki `BAKIYE` etiketi) | **2,43** | ✗ sayfanın en kötüsü |
| `#9099a6` → `#eef4fb` (seçili satır) | **2,60** | ✗ |
| `#667382` → `#eef2f7` (rozet metni) | **4,30** | ✗ normal boyutta |
| `#f76707` → `#ffffff` (`41 gün`) | **3,04** | ✗ 12,5px'te |
| `#667382` → `#ffffff` | 4,84 | ✓ |
| `#1c7a3a` → `#eaf7ec`, `#206bc4` → `#eef4fb` | 4,88 / 4,79 | ✓ |

`#9099a6` **hiçbir zeminde AA geçmiyor.** Bir muhasebe ekranının tüm etiket katmanını
o renk taşıyor: kolon başlıkları, KPI etiketleri, 360 alan anahtarları, şema dipnotları,
ağaç açma üçgenleri, "borç yok" anlamına gelen `—`.

### Dokunma hedefleri (brief'in kendi kuralı: ≥44px)

| Element | Ölçü |
|---|---|
| Sidebar modül linkleri ×11 | 248 × **41,8** |
| Sidebar alt linkler ×5 | 227 × **34,3** |
| Ağaç / Düz / Sadece bakiyeli / Yalnız açık kalemler | × **42** |
| **Ekstre belge linkleri ×6** (SINV-…, PAY-…) | 112 × **18,8** — ve `<span>`, tab sırasında **yok**, `role` yok, `href` yok |

Ekstredeki 6 belge linki gerçek kusur: mavi + `cursor:pointer` ile link gibi okunuyor
ama klavye/ekran okuyucu kullanıcısı onlara **hiç ulaşamıyor**.

### Kesilen metin

**1320px'te** — tasarımın kendi ilan ettiği `min-width` — *En yüksek borçlular*
tablosunun isim kolonu **28px**'e çöküyor:

```
ANJAN Holding                        → A…
ZDEMO Oʻzbekiston temir yoʻllari AJ  → Z…
[TEST-E2E] June medical customer     → […
```

Tablonun adı "kim size en çok borçlu" ve desteklenen minimum genişlikte **kimin**
olduğunu göremiyorsunuz. Hiçbirinde `title` yok, hover yedeği de yok.

1620px'te bile sol listede 3 isim kesiliyor (isim kolonu 160px): iki farklı ZDEMO
tüzel kişiliği tarama kolonunda birbirinden ayırt edilemiyor.

### Dar ekran

`min-width:1320px` + sıfır media query. `<meta viewport>` responsive vaat ediyor,
shell iptal ediyor.

| Genişlik | Davranış |
|---|---|
| 1280 (13" MacBook) | 40px yatay taşma, `+ Yeni müşteri` kısmen kesik |
| 900 | 420px taşma; **4 kontrol tamamen ekran dışı**: `XLSX ekstre`, `+ Yeni müşteri` (birincil CTA), `Rezerve stok`, `Raporlar`. 248px sidebar viewport'un %27,5'ini yiyor, daralmıyor |

### Odak ve tab sırası

- 52 odaklanabilir eleman, **pozitif `tabindex` yok**, DOM sırası görsel sırayla birebir. İyi.
- Her elemanda görünür odak halkası var — **ama neredeyse hepsi Chromium varsayılanı**.
  Tek yazılmış odak stili müşteri satırlarında (`outline: 2px #206bc4`).
- DS stylesheet `:focus-visible` token'ları tanımlıyor ama DC'de **tek bir `class=`
  yok** (%100 inline stil), dolayısıyla DS'in erişilebilirlik konvansiyonları bu
  yüzeye hiç ulaşmıyor.
- Arama input'unun erişilebilir adı yok (sadece placeholder).

---

## 3. Önerilen Customer Center — 7 hamle

### Hamle 1 — Sol pane bir **dizin** değil, bir **kuyruk** olsun

Muhasebecinin günü "vadesi geçenleri aşağı doğru eritmek". Ekran ona alfabetik bir
dizin veriyor.

- Üç kolon başlığı da sıralanabilir; **varsayılan sıra `vade aşımı desc`**.
- Ağaç/Düz artık *sıralama* değil, sıralamadan bağımsız bir **gruplama** modu:
  ağaçta parent'lar kendi içinde en riskli çocuk üstte olacak şekilde sıralanır.
- 128 satır için sayfalama ya da harf atlama.
- Yapışkan parent başlıkları.

### Hamle 2 — **Tahsilat durumu** birinci sınıf alan olsun

Bu, ürünün en büyük eksiği: ekran parayı okuyabiliyor ama **işi hatırlayamıyor**.

Müşteri başına bir durum + bir temas günlüğü:

```
Aranmadı · Arandı 03.08 · Söz verdi 12.08 · İtirazlı · Eskale
```

Cockpit KPI'ı da buna döner:

> ~~Vadesi geçmiş · 312,4 mln · en eskisi 41 gün · 18 müşteri~~
> **Vadesi geçmiş · 312,4 mln · 18 hesap · 11'i bu hafta arandı · 4 söz verdi · 3'ü sözünü tuttu**

Bu, AR *görüntüleyicisi* ile AR *çalışma alanı* arasındaki fark. Teknik maliyeti düşük:
`Customer`'a 2 custom field (`collection_state`, `promised_date`) + bir child table
(`Customer Collection Log`) ya da tek bir yeni doctype.

### Hamle 3 — **Tek toplam, tek isim**

Ekranda üç farklı "Toplam alacak" var ve hiçbiri diğerini açıklamıyor:

| Nerede | Değer |
|---|---|
| KPI | `1 214,3 mln` |
| Liste footer'ı (aynı etiket) | `1 425 854 910` |
| "Pay" kolonu paydası | KPI'ı kullanıyor → 6 satırın payı toplamı **%117,4** |

Ayrıca ANJAN Holding sol listede `412 800 000` (kendi), 360 panelinde `825 600 000`
(kümülatif) — 400px arayla, hiçbir işaret olmadan.

**Kural:** kitap toplamı sayfada **tam bir kez** görünür. Diğer her toplam açıkça bir
alt küme olarak etiketlenir — `Görünen`, `Kümülatif`, `Kendi`. Parent satırı ikisini
birden basar:

```
ANJAN Holding        825 600 000
                     412 800 000 kendi
```

Sıralama/filtre toplamları `list`'ten hesaplanır, `C`'den değil. Sıralamada parent'lar
kendi çocuklarıyla aynı listede yarışmaz.

### Hamle 4 — Kimlik **aksiyonun içinde** olsun

Yanlış müşteriye tahsilat, bu üründe adı konmuş pahalı hata. Şu an sıfır savunma var:
`Ödeme al` ikincil bir buton, müşteri adından ~1000px uzakta, dördüncü butonu bir
`✕` kapatma olan bir kümenin üçüncüsü.

- Buton etiketine kimliği koy: **`Ödeme al · ANJAN Trade LLC · 214 600 000`**
- `✕`'i para butonlarının yanından al, panelin sol üstüne `← Cari hesaplar` olarak koy
  (HANDOFF zaten böyle söylüyordu).
- Aramada ağaç düzleşince çocuk satır parent'ını kaybediyor — tam da üzerinde işlem
  yapılacağı anda. Düz sonuçlarda parent adını satırda tut:
  `CUST-0002 · Bayi · ANJAN Holding`.

### Hamle 5 — Cockpit **çıkmaz sokak** olmasın

Yaşlandırma merdiveni ve en yüksek borçlular şu an dekoratif: müşteri seçilince ikisi
de kayboluyor, yani kredi bağlamı ile hesap işi asla yan yana gelmiyor.

- Her yaşlandırma kovası **tıklanabilir bir filtre** olsun (`31–60 gün` → listeyi filtrele).
- En yüksek borçlular satırı zaten seçim yapıyor — iyi; ama 360 moduna geçince
  sıkıştırılmış bir **risk şeridi** olarak kalsın.
- Test/pasif partiler (`[TEST-E2E] …`) üretim şeklindeki bir sıralamadan dışlansın.

### Hamle 6 — Ekstre = ihraç edilen belgenin **kendisi**

Ekrandaki ekstre ile XLSX aynı nesne olsun: aynı dönem, aynı konsolidasyon bayrağı,
aynı açılış ve kapanış. "İhraç et" ekrandakinin çıktısıdır, ikinci bir sorgu değil —
aksi hâlde ikisi çelişebilir ve denetçiye giden dosya belirsizliği devralır.

Ayrıca ekstre erişimi `⋯ Diğer` menüsünden çıksın: bu, muhasebecinin 5. en sık işi ve
şu an ekrandaki en görünmez kontrol.

### Hamle 7 — Ölçülebilir düzeltmeler (görünüşü hiç değiştirmeden)

| Sorun | Düzeltme | Etki |
|---|---|---|
| `#9099a6` etiket katmanı 2,43–2,88:1 | `#667382`'ye çevir | 4,84:1 → AA geçer, **görünüm aynı kalır** |
| Rozet metni `#667382` on `#eef2f7` 4,30:1 | Rozet zeminini `#e9ecf1`'e koyulaştır ya da metni `#5a6675` yap | AA |
| `41 gün` `#f76707` 3,04:1 @12,5px | Metin tonunu `#9a4d06` yap (brief'te zaten var) | AA |
| 42px kontroller | 44px | Brief'in **kendi kuralı** |
| Ekstre belge linkleri `<span>` | `<button>` ya da `<a>`, 44px hedef | Klavye + ekran okuyucu erişimi |
| Vade aşımı sadece renkle | Renk + ikon/metin niteleyici | Renk körlüğü |
| `min-width:1320px`, 0 media query | ~1100px'e kadar responsive; En yüksek borçlular dar ekranda kolon yerine yığın | 13" laptop'ta yatay kaydırma biter |
| İsim kolonu 160px, `title` yok | `title` ekle + kolonu genişlet | İki ZDEMO tüzel kişiliği ayırt edilebilir |
| Tek etiket muamelesi (~20 etiket, 3 farklı bilgi rütbesi) | İki seviyeli etiket: birincil (mono 10px `#667382`) / ikincil (11px sentence-case) | Bilişsel yük |
| Konsolidasyon anahtarı `<span>` | `role="switch"` + `aria-checked` + klavye | "Bu bakiyede hangi hareketler var" iddiasını taşıyan kontrol |

---

## 4. Korunacaklar (dokunma)

1. **Ekstre bloğu.** Devreden pseudo-satırı aynı grid'de, italik gri; borç `#b32424` /
   alacak `#1c7a3a`, boş taraf `—`; yürüyen bakiye ink 600; kapanış şeridi iki kolonu
   da toplayıp bölüm-başlığı çizgisinin altına koyuyor. Koşullu kur satırının sadece
   USD satırının altında çizilmesi, bunu belgeyi anlayan birinin yazdığının kanıtı.
   Kategoride bunu doğru yapan neredeyse yok.
2. **Kalıcı 2-pane.** Muhasebeci 128 satırlık kitapta yerini hiç kaybetmiyor;
   taramaya dönmek sıfır yeniden yönelme maliyeti. Değiştirdiği yüzeye göre gerçek
   bir iyileştirme.
3. **`gap:1px` grid ayırıcı sistemi.** 0 radius brief'inde risk, kutu içinde kutudan
   oluşan bir sayfa. Bunun yerine KPI şeridi, yaşlandırma merdiveni, bakiye bandı ve
   alan grid'i tek grid + 1px boşluk; şiddet 3px üst şeritle taşınıyor. Çizgi
   gürültüsü olmadan yoğunluk.
4. **`ds-kpi-q` şema dipnotları.** "Bu sayı nereden geliyor" sorusuna satır-içi cevap.
   Ama **6 kullanım fazla** — 1–2'ye in, imza olsun, duvar kâğıdı değil. Özellikle
   birincil iş akışının son satırındaki `include_children = 1`'i kaldır (leaf
   müşteride zaten anlamsız).
5. **Cockpit'in kapanış cümlesi** — "Soldaki listeden bir müşteri seçin…" — yüzeydeki
   tek gerçek onboarding ve işe yarıyor.

---

## 5. Prototip artefaktı vs gerçek tasarım sorunu (dürüst ayrım)

Kritikteki bazı bulgular DC'nin statik bir maket olmasından kaynaklanıyor, üründe zaten
çalışıyor. Ayırmak önemli:

| Bulgu | Sınıf |
|---|---|
| Grup/Bölge select'leri filtrelemiyor | **Maket artefaktı** — Vue'da çalışıyor |
| Ağaç chevron'u ölü | **Maket artefaktı** — Vue'da `toggleExpand` var |
| 5 sekmenin hepsi ekstre gösteriyor | **Maket artefaktı** |
| `Test Stable Co` seçilince ANJAN'ın ekstresi çıkıyor | **Maket artefaktı** (`LEDGER` modül sabiti) |
| Konsolidasyon anahtarı çalışmıyor | **Maket artefaktı** — ama `role="switch"` eksikliği **gerçek** |
| Loading/empty/error state yok | **Gerçek** — Vue'da da spinner var, skeleton yok, boş sonuç yok |
| Kolon sıralaması yok | **Kısmen gerçek** — Vue'da ad/bakiye var, **vade aşımı yok** |
| Üç farklı "Toplam alacak" | **Gerçek tasarım sorunu** |
| Kontrast, 42px, `min-width:1320`, `title` yokluğu | **Gerçek** |
| Tahsilat durumu / temas günlüğü yokluğu | **Gerçek ve en büyük eksik** |
| Kredi limiti yokluğu | **Gerçek** |
| Yanlış müşteriye tahsilat savunmasızlığı | **Gerçek** |

---

## 6. Uygulama sırası

| # | İş | Nerede | Maliyet |
|---|---|---|---|
| 1 | Kontrast + 44px + `title` + belge linklerini `<button>` yap | DC + Vue | Küçük |
| 2 | Toplamları tek isimlendir; parent satırında kendi+kümülatif | DC + Vue + `list_customers_with_balances` | Küçük |
| 3 | `Ödeme al` etiketine kimlik; `✕` → `← Cari hesaplar` | DC + Vue | Küçük |
| 4 | Vade aşımı kolonu + sıralanabilir başlıklar, varsayılan `overdue desc` | Vue + `only_overdue` param | Orta |
| 5 | Yaşlandırma kovaları tıklanabilir filtre | Vue + `ar_aging` | Orta |
| 6 | Responsive: `min-width` 1320 → ~1100, dar ekranda borçlular yığını | DC + Vue | Orta |
| 7 | Ekstre = XLSX aynı nesne | `export_report_xlsx` + `customer_ledger` | Orta |
| 8 | **Tahsilat durumu + temas günlüğü** | Yeni doctype/field + Vue + cockpit KPI | Büyük |
| 9 | Kredi limiti + ödeme koşulu ihlali bayrağı | Custom field + Vue | Büyük |

1–3 tek bir commit'te gider ve puanı ~19 → ~23 çıkarır.
4–7 ile ~28.
8–9 ürünü "AR görüntüleyicisi"nden "AR çalışma alanı"na taşır.

---

## 7. Cevaplanması gereken sorular

1. **Muhasebecinin günü "vadesi geçen listesini eritmek" ise, varsayılan sıra neden
   ağaç sırası?** Sol pane bir *kuyruk* olsaydı — vade aşımına göre sıralı, işlenen
   satırlar listeden düşen, "bugün kalan" sayacı olan — ne değişirdi?
2. **Ekran parayı okuyabiliyor ama işi hatırlayamıyor.** Müşteri bakiyesinin yanında
   bir tahsilat durumu taşısa ve cockpit fatura yerine *onları* saysaydı, "Vadesi
   geçmiş 312,4 mln" yerine "18 hesap · 11'i bugün arandı" daha mı yararlı olurdu?
3. **Ekranda üç "Toplam alacak" var. Hangisi doğru?**
4. **Parent bakiyesi bir panelde kümülatif, 400px ötede kendi.** Holding satırı ikisini
   birden bassa ve konsolidasyon anahtarı *ekstrenin* hangisini kullandığını görünür
   şekilde kontrol etse?
5. **Denetçinin ve müşterinin eline geçen şey ekstre.** Ekrandaki ekstre ile XLSX'in
   *aynı nesne* olması için ne gerekir?
