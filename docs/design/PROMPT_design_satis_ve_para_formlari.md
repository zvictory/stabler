# Tasarım brief'i — Satış ve Para formları (4 ekran, tek oturum)

Bu dosyanın tamamını Claude'a (tasarım oturumu) yapıştır.
**Çıktı: kod değil, tasarım.**

**Zorunlu ek:**
- `docs/plans/2026-08-18-satis-ve-para-formlari-tasarim-kurulu-karari.md` — kurul kararı.
  Ekranların envanteri, 21 doğrulanmış P0, 48 D-maddesi ve 10 ADR orada, `dosya:satır`
  referanslarıyla. **Bu brief onu tekrar etmiyor; önce onu oku.**

**Oturum başlamadan Zafar'ın vermesi gerekenler** (bkz. §7.0 — bunlar olmadan §7'nin
1–4. teslimi üretilemez, çünkü kural K11 uydurma veriyi yasaklıyor):
gerçek bir SO taslağı, gerçek bir gönderilmiş SO, gerçek bir MSA faturası (koli taşıyan),
gerçek bir çapraz-kur gideri ve gerçek bir çapraz-kur transferi — her biri anonimleştirilmiş.

---

## 1 · Ürün ve kullanıcı

**Stabler** — Frappe/ERPNext üzerine kurulu, tek kod tabanını **7 kiracının** paylaştığı
bir Vue 3 SPA. Beş dil ship ediyor: `en, ru, uz, uzc, tr`.

Bu dört ekranı kullanan **dört** kişi var. Hepsi aynı tasarım dilini görüyor, hiçbiri
aynı soruyu sormuyor:

| Kim | Hangi ekran | Ne zaman açar | Cevabını aradığı soru |
|---|---|---|---|
| **Satışçı** | Satış Siparişi | müşteri telefondayken, günde onlarca kez | "Bu siparişi doğru fiyat ve yeterli stokla, konuşma bitmeden girebilir miyim?" |
| **Satış müdürü** | Satış Siparişi | sonradan, listeden gelerek | "Bu sipariş neden hâlâ açık? Teslim mi edilmedi, faturası mı kesilmedi, parası mı gelmedi?" |
| **MSA kasiyeri** | Satış Faturası | siparişsiz, doğrudan fatura — MSA'da Satış Siparişi **0**, Satış Faturası **4937** | "Kaç koli, kaç kilo, kaç para — ve müşteriye vereceğim kâğıtta aynı sayı mı yazacak?" |
| **Muhasebeci / kasa sorumlusu** | Gider, Transfer | gün içinde, para hareketi olduğunda | "Bu para hangi hesaptan çıktı, hangi kurla, ve postaladığımda defterde ne görünecek?" |

Kritik ürün gerçeği: **satışçı ile kasiyer aynı gün, dakikalar arayla SO ve SI ekranlarını
kullanıyor** — ve bugün ikisi farklı klavye davranışı, farklı toplam bloğu, farklı
kaydetme sözlüğü ve farklı satır ızgarası sunuyor.

---

## 2 · Bu dört ekranın tek işi

> **"Parayı doğru tutar, doğru kur ve doğru hesapla kaydet; postalamadan önce ne
> postalanacağını göster; sonradan açıldığında nerede takıldığını tek bakışta söyle."**

Dördü de aynı üç modun içinde yaşıyor:
- **Hızlı giriş (create/draft)** — hız ve hata önleme, klavye ağırlıklı.
- **Postalama anı** — geri alınamaz eylem; ne olacağı önceden görünür olmalı.
- **Takip (submitted)** — okunabilirlik; tek bakışta durum teşhisi.

---

## 3 · Mevcut durum

Kurul kararının §1 tablosuna bak: dört ekranın altı sözleşme üzerindeki durumu orada,
her hücre `dosya:satır` doğrulamalı. Burada tekrar edilmiyor.

Kısaca bugün: SO'nun **iki varyantı** var (Klasik varsayılan, Modern bayrak arkasında
kapalı); SI'ın **yazma ekranı Modern, okuma ekranı Klasik** ve ikisi arasında geçiş
zorunlu; Gider ve Transfer kendi modülünün (`/money`) **tek aykırıları** — beş kardeş
sayfa `ListToolbar` kullanırken bu ikisi elle "Apply" düğmesi taşıyor.

---

## 4 · Girdi: bugün ne çalışmıyor

Tam liste kurul kararında (21 P0 + 48 D). Tasarımı **doğrudan** ilgilendiren yedi tanesi:

**4.1 · Kur, dört ekranda dört farklı şey.** SO Klasik'te doğru yönde bir `MoneyInput`;
SO Modern'de **hiç giriş yok** — ama ekran "Kuru elle girin" diye uyarı basıyor;
Gider'de giriş var ama **değeri etiketiyle çelişiyor** (`1 USD =` etiketinin altında
`0.00` yazıyor, ipucunda `CBU: 12 953`); Transfer'de doğru ama başka bir mimariyle;
SI'da kur kavramı hiç yok. Bu, ekranın en pahalı hatasının (12 000 kat) tek göstergesi
olan kontrol.

**4.2 · Ekrandaki sayı ile deftere yazılan sayı ayrışıyor — üç ayrı yerde.**
SO Modern yapışkan çubukta **istemci hesabı** grand total'ı 24px kalın gösteriyor,
12 satır yukarıda sunucununki aynı etiketle duruyor. SI'da ekrandaki tek sayı **net**,
sunucu KDV'li grand total saklıyor ve ekranda KDV satırı **yok**. Gider'in taban-para
önizlemesi hatalı kurda `"0"` basıp yanlışı sakinleştiriyor. Bir muhasebeciye tek
ekranda iki farklı toplam göstermek, hangisinin doğru olduğundan bağımsız olarak
ekrana duyulan güveni bitirir.

**4.3 · Aksiyon çubuğu tasarlanmamış, türetilmiş.** SO Modern'de yedi düğme tek bir
`display:flex; gap:12px` satırında, **`ms-auto` yok, `flex-wrap` yok**: yıkıcı Delete
Submit'ten 12px uzakta, gönderilmiş durumda Cancel nötr "Close & release"in **soluna**
düşüyor, ve RU/UZC uzunluğunda beş düğme çubuktan taşıyor. Ayrıca "birincil" her durumda
farklı bir görsel dille anlatılıyor: taslakta `btn-primary`, gönderilmişte `btn-success`
— yani **rengin kendisi hiyerarşi taşıyor**. SI Modern'de aynı çubuk yalnız iki düğme;
Print / Waybill / Ödeme / İade / İptal **hiç yok**, hepsi başka ekrana gidiş-dönüş.

**4.4 · Postalamadan önce ne olacağı görünmüyor.** Gider ve Transfer'de satıra tıklamak
seni **doğrudan amend formuna** düşürüyor (salt-okunur yol yok), form içinde docstatus
rozeti yok, alt düğme "Save & close" diyor — ve o düğme postalanmış bir muhasebe belgesini
**onaysız** iptal edip yerine yenisini yazıyor. Eşik üstündeyse yenisi Taslak kalıyor ve
defter o tutar kadar eksiliyor; bunun tek anlatımı tıklama sonrası bir toast.
Karşılaştır: Havale ekranı bunu doğru yapıyor — `PostingPreview` postalamadan önce
yevmiyeyi gösteriyor.

**4.5 · Aynı sayılar tekrar ediyor, aynı kelimeler farklı anlamlara geliyor.** SO Modern'de
grand total üç, advance paid iki, delivered/billed % ikişer yerde; "Reserved" kelimesi tek
ekranda üç ayrı anlamda (rozet, sütun, bölüm başlığı). Yeni bir siparişte başlık **"0 items"**
derken alt bilgi **"Grand total · 1 item"** diyor. Hiçbiri yanlış değil — ama sayfa üç kez
aynı şeyi söylüyor ve bir kez kendisiyle çelişiyor.

**4.6 · Boş, yükleniyor ve "bilinmiyor" durumları tasarlanmamış.** Gider ve Transfer
listeleri yüklenirken tablo başlığı kaybolup kart **boşlukta dönen bir spinner**a çöküyor.
SO Modern'de rezervasyon bölümü boşken hiç çizilmiyor, yani bölümler 1 → 2 → 3 gidip
**4 sen yazarken beliriyor**. Ve başarısız bir kredi sorgusu üçüncü bir durum bulamadığı
için **yeşil "Borç yok"** olarak çiziliyor.

**4.7 · Uzun RU/UZC metinleri hiç denenmemiş, ve SI'ın yeni dizeleri hiç çevrilmemiş.**
`BOXES`, `BOX KG`, `TOTAL KG`, `Save Draft`, `Save & Submit` — dördü de dört dilde **0 hit**.
SO Modern'de rezervasyon kartı başlığı `white-space: nowrap` + `text-overflow: ellipsis`,
yapışkan çubuk başlığı `text-transform: uppercase` + `letter-spacing: .14em` — +%40 metin
için mümkün olan en kötü ayar.

---

## 5 · Tasarım kısıtları — pazarlık dışı

Bunlar zevk değil, projenin hard-rule'ları (`CLAUDE.md` + `.claude/rules/10-frontend.md`).
Bir öneri bunlardan birini ihlal ediyorsa reddedilir.

- **K1 · Frappe Desk'e link yok.** Hiçbir yerde `/app/...`, "Open in Desk", yeni sekme.
  Eksik bir işlev varsa Stabler'ın içinde tasarlanır.
- **K2 · Para = `MoneyInput` + monospace.** Her parasal giriş `MoneyInput`, her parasal
  gösterim `font-monospace` ve sağa hizalı. Ham `<input type="number">` yok.
- **K3 · Tarih = `DateInput` / `formatDate`.** Görünen biçim daima `gg.aa.yyyy`. Ham ISO
  yok, yerel `<input type="date">` yok.
- **K4 · Bölge başına tek `btn-primary`.** İkincil aksiyonlar `btn-outline-secondary` /
  `btn-ghost-secondary`. **Renk asla ikinci birincil olarak kullanılmaz** — bugünkü
  `btn-success` "Create Invoice" bu kuralın ihlal örneğidir, kopyalanmaz.
- **K5 · Durum rozetleri merkezden.** `getStatusBadgeClass` / `StatusBadge.vue` ne diyorsa
  o. Sayfaya özel durum→renk haritası yok.
- **K6 · Tablolar varsayılan çizgili** (global CSS). Manuel `table-striped` eklenmez.
- **K7 · Beş dil**: en, ru, uz, uzc, tr. Her metin `t()` içinden geçer, her yerleşim en
  uzun dilde de durur. `EmptyState` başlıkları dahil.
- **K8 · Para birimi:** tutarlar **yalnız kendi işlem/hesap para biriminde**. İki parayı
  toplayan tek bir sayı üretilemez. **Tek belgelenmiş istisna:** Satış Siparişi'nin
  yapışkan alt çubuğundaki tek `≈` satırı — canlı kurdan türetilir, kur yoksa **hiçbir şey
  çizilmez**. Bu istisna başka ekrana kopyalanmaz.
- **K9 · Kur yönü.** Saklanan `conversion_rate` ERPNext yönünde kalır (`0,000082632`);
  **gösterim ve giriş daima `1 USD = 12 101,85 UZS` yönünde.** Bu iki yön karıştırılamaz.
- **K10 · Renk tek başına anlam taşımaz.** Her uyarı/hata renk + ikon + metin ile çift
  kodlanır. Kontrast WCAG AA. Dokunma hedefi ≥ 40px.
- **K11 · Uydurma veri yok.** Prototipte ve önerilerde yalnız §7.0'da verilen gerçek
  anonimleştirilmiş kayıtlar kullanılır.
- **K12 · Tabler + `stbl-ds` dili.** Mevcut sınıflar (`card`, `datagrid`, `steps`,
  `badge bg-*-lt`, `ds-panel`, `ds-kpi`, `ti ti-*`) kullanılır; yeni bir tasarım sistemi
  getirilmez. Yeni bileşen önerirsen maliyetini açıkça yaz.
- **K13 · Paylaşılan sözleşmeleri değiştirirsen bedelini yaz.** `LineItemsEditor`,
  `MoneyInput`, `FormPage`, `useDocumentForm`, `fx.js` altı ila yirmi ekranda kullanımda.
- **K14 · `LineItemsEditor`'a koli öğretilmez.** Bu sınır bir testle kilitli ve devir
  notunda gerekçesi yazılı (`docs/plans/2026-08-18-HANDOFF-msa-direct-invoice.md`):
  ona koli öğretmek altı kiracının SO ekranına dokunmak olur. **Sütunlar ayrı kalabilir;
  klavye davranışı ayrı kalamaz** (bkz. S4).

---

## 6 · Karar vermeni istediğim asıl sorular

Bu oturumun işi yeni ekran çizmek değil. Dört ekranın bugün **ayrı ayrı yeniden icat
ettiği altı sözleşmeyi** tek yere indirmek. Altısı da tasarım kararı, altısı da senin.

### S1 · Kur bloğu — tek bileşen, beş ekran
Bir `ExchangeRateBlock` tasarla. Üç hâli olmalı: **bilinen kur** · **bilinmeyen kur**
(`null` — elle giriş zorunlu, ve bu *çıkmaz sokak olmamalı*) · **yerli para** (blok hiç yok).
Ayrıca dördüncü bir hâl: **stale/başarısız çekim** — bugün Transfer'de eski para çiftinin
kuru mavi `AUTO` rozetiyle otoriter görünüyor.

Cevaplaman gerekenler: giriş hangi yönde? (K9 gösterimi sabitliyor, girişi de aynı yöne
sabitlemek zorunlu mu, yoksa iki yön de kabul edilip normalize mi edilmeli?) · CBU ipucu
ile kullanıcının yazdığı değer çeliştiğinde ekran ne yapar? · bu blok SO'da başlık
alanlarının arasında mı, yapışkan çubukta mı, yoksa üçüncü bir yerde mi durmalı — ve
Gider/Transfer'de aynı yerde mi durmalı?

### S2 · Aksiyon çubuğu — dört durum, tek gramer
SO'nun sekiz aksiyonu (Save as draft, Submit & reserve, Create Invoice, Cancel, Amend,
Close & release, Delete, + admin stok-aşımı override), SI'ın on ikisi ve Gider/Transfer'in
dördü **dört durumun her biri için** nasıl *tek birincil + ikincil grup + "daha fazla"
menüsü*ne oturur?

Cevaplaman gerekenler: birincillik **konumla mı `btn-primary` ile mi** anlatılır? ·
yıkıcı grup nasıl ayrılır (bugün ayrılmıyor) · beş düğme + %40 uzun metin dar ekranda ne
yapar (sarar? menüye iner? hangisi menüye iner?) · "Cancel" kelimesinin iki anlamı
(formu terk et / belgeyi iptal et) nasıl ayrışır · SI'ın eksik dokuz aksiyonu (Print,
Waybill, Ödeme, İade, Didox, İlgili belgeler…) yazma ekranına mı gelir, yoksa yazma ile
okuma ekranı arasındaki geçiş mi tasarlanır?

### S3 · Postalama önizlemesi — geri alınamaz eylemin öncesi
Gider ve Transfer'de amend, postalanmış bir belgeyi iptal edip yenisini yazıyor; SI'da
gönderim GL + SLE + e-fatura yazıyor. Havale ekranında bunun için `PostingPreview`
bileşeni **zaten var**.

Cevaplaman gerekenler: bu dört ekranda "postalamadan önce ne olacak" nerede ve ne kadar
gösterilir? · her postalama mı önizleme hak ediyor, yoksa bir eşik mi var? · amend'in
"iptal + yeniden yaz" olduğu **düğmenin üstünde** mi yazmalı, diyalogda mı, ikisinde de mi? ·
onay eşiğini aşan bir kayıt için "bu postalanmayacak, onaya gidecek" uyarısı tıklamadan
**önce** nerede durur?

### S4 · Satır ızgarası — bir davranış, iki sütun kümesi
SO `LineItemsEditor` kullanıyor (↑/↓ sütun gezinme, Esc, Tab-ile-yeni-satır, Enter-ekle,
satır-içi doğrulama). SI'ın koli ızgarasında **hiç `@keydown` yok** ve K14 gereği
sütunlar birleşemiyor.

Cevaplaman gerekenler: ortak klavye ve doğrulama sözleşmesi nasıl tarif edilir ki iki
farklı sütun kümesi onu paylaşabilsin? · satır-içi hata nerede görünür (bugün SI'da form
seviyesinde, tıklama sonrası) · SO'nun editable/read-only iki farklı tablosu tek tabloya
mı inmeli?

### S5 · İki kullanım, tek yerleşim mi?
Hızlı giriş (katip, telefonda) ile takip (müdür, bir hafta sonra) aynı yerleşimi mi
paylaşmalı? Aynıysa hangi bölümler ikinci modda küçülür/katlanır; ayrıysa geçiş nerede
olur? Aynı soru SI için kasiyer↔okuma, Gider/Transfer için giriş↔denetim ekseninde.

### S6 · Liste ekranları — `/money` standardına dönüş
Gider ve Transfer listeleri `ListToolbar` + otomatik filtre + `SkeletonRows` +
`Pagination` + `StatusBadge` alacak. Ama Transfer listesinde bugün **From ve To hesabı
sütun bile değil** ve Gider'de en solda en işe yaramaz sütun (`#`, monospace belge no)
duruyor.

Cevaplaman gerekenler: her iki listede **sütun kümesi ne olmalı**, dar ekranda hangisi
düşer? · arama neyi arar (memo? payee? hesap? belge no?) · filtre kümesi ne (bugün yalnız
iki tarih; Kind, durum, hesap, tender, CI hepsi sütun olarak var ama filtre değil) ·
"onay bekleyenlerim" sorusu bu listeden nasıl cevaplanır?

**Her soru için en az iki farklı yol tasarla, ikisinin de artı/eksisini yaz, birini
gerekçesiyle öner.** S1, S2 ve S3 en pahalıları — oraya ağırlık ver.

---

## 7 · Teslim edilecekler

### 7.0 · Veri ön koşulu
Aşağıdaki 1–4 teslimi K11 gereği ancak gerçek kayıtlarla üretilebilir. Zafar'dan
istenecek beş anonimleştirilmiş ekstre: (a) 5–8 satırlı bir SO taslağı, biri stok
aşımlı; (b) %100 teslim / kısmen faturalanmış, bağlı faturası olan gönderilmiş bir SO;
(c) koli + kg taşıyan gerçek bir MSA faturası; (d) çapraz-kur bir gider (UZS defter,
USD ödeme hesabı); (e) çapraz-kur bir transfer. Ekstreler gelmeden 5–9 arası teslimler
üretilebilir; 1–4 bekler.

1. **Satış Siparişi — dolu create ekranı**, 1440px. Kur bloğu görünür hâlde.
2. **Satış Siparişi — dolu submitted ekranı**, 1440px. Müdürün "neden hâlâ açık"
   sorusunu kaydırmadan cevaplayacak hâliyle.
3. **Satış Faturası — dolu create ekranı** (koli ızgarası) **ve** aynı faturanın okuma
   hâli. İkisinin arasındaki geçiş tasarlanmış olarak.
4. **Gider ve Transfer** — liste + form, ikisi de dolu, çapraz-kur hâliyle.
5. **`ExchangeRateBlock` anatomisi** — dört hâl (bilinen · bilinmeyen · yerli para ·
   stale/hatalı çekim), beş ekranın her birinde nereye oturduğu.
6. **Aksiyon çubuğu anatomisi** — dört ekran × dört durum (create / taslak / gönderilmiş /
   iptal): düğme kümesi, hiyerarşi, yıkıcı grubun ayrımı, dar ekran davranışı.
7. **Postalama önizlemesi** — S3'ün cevabı, en az iki ekranda gösterilmiş (biri amend).
8. **Satır bileşeni**, dört varyantta: normal · stok aşımı · iskontolu · uzun Rusça ürün
   adı. Ve koli varyantı (SI), aynı klavye sözleşmesiyle.
9. **Boş, hata, iskelet ve "bilinmiyor" durumları** — satırı olmayan taslak · yükleme
   hatası · yükleniyor · **bakiyesi sorgulanamamış müşteri** (bugün yeşil "Borç yok"
   çiziliyor; üçüncü durum senin tasarlayacağın şey).
10. **Dar ekran** — 768px ve 390px'te SO create, SI create ve Gider listesi. Satır
    tablosu ve aksiyon çubuğu ne yapıyor?
11. **Tasarım tokenları** — kullandığın aralık, tipografi ölçeği ve renk rollerinin
    listesi, Tabler / `stbl-ds` değişkenlerine eşlenmiş.
12. **Karar notu** — S1–S6'nın her biri için iki yol, karşılaştırma, öneri ve gerekçe.
    Kısa tut.

---

## 8 · Başarı ölçütü

Beş soru. Beşi de "evet" olmalı.

1. **Satışçı**, müşteri telefondayken 5 satırlık bir siparişi 60 saniyede girip
   onaylayabiliyor mu — ve satırlardan biri stokta yetersizse bunu **submit'e basmadan
   önce** fark ediyor mu?
2. **Satış müdürü**, bir hafta önceki bir siparişi açtığında neden hâlâ açık olduğunu üç
   saniyede söyleyebiliyor mu — kaydırmadan, tablo okumadan?
3. **MSA kasiyeri**, ekranda onayladığı tutarın müşteriye vereceği kâğıtta ve deftere
   yazılanla **aynı** olduğuna bakarak emin olabiliyor mu?
4. **Muhasebeci**, postalamadan önce hangi hesaptan ne çıkacağını ve hangi kurun
   kullanılacağını görüyor mu — ve yanlış kur girerse ekran ona bunu **postalamadan önce**
   söylüyor mu?
5. Bir kullanıcı bu dört ekranın **birinde** kur girmeyi, satır eklemeyi, kaydetmeyi ve
   bir belgeyi iptal etmeyi öğrendiğinde, diğer üçünde **aynı şeyi yapmayı yeniden
   öğrenmek zorunda kalmıyor** mu?

Beşincisi bu oturumun asıl işi.

---

## 9 · Yapma

- **Kod yazma.** Vue bileşeni, `.js`, `.py` üretme. Çıktı tasarım.
- **Yeni alan / özellik uydurma.** Ekranda ve doctype'ta olmayan bir veri alanı önerme.
  (Yeniden düzenleme, birleştirme, gizleme, **ve bugün yazılıp okunmayan bir alanı
  görünür kılma** serbest — koli sayısı tam olarak böyle bir alan.)
- **Desk'e benzetme.** Frappe Desk'in form düzeni referans değil, kaçınılan şey.
- **Dört ekranı ayrı ayrı tasarlama.** Bu briefin varlık sebebi, S1–S6'nın dördünde de
  aynı cevabı vermesi.
- **Bugünkü hâli taklit etme.** Kurul kararı bugünün fotoğrafı, hedef değil.
- **Bir kusuru "cilalayarak" çözme.** Kurul kararındaki P0'ların çoğu görsel değil
  mimari: kur iki değişkende, toplam iki kaynakta, yetki hiçbir yerde. Tasarımın bunları
  **görünür** kılması, gizlemesi değil, isteniyor.
