# Remittance Operations Center — Tasarım Kurulu Kararı (2026-08-16)

İncelenen: `Remittance Operations Center -standalone source-.html` (1827 satır),
`Imports module score cards design (3).zip` içinden.
Plan: `docs/plans/2026-08-16-remittance-operations-center.md`
Prompt ve kabul listesi: `docs/plans/PROMPT_remittance_design.md`

Kurul: muhasebe/treasury, güvenlik/multi-tenant, nakit operasyonu, UI/UX+a11y.
Başkan ölçümleri canlı tarayıcıda yapıldı (Chrome DevTools, 1440/1024/768/390px).

## KARAR: REJECT — v2 zorunlu, muhasebe modeli yeniden kurulacak

Ürün modeli, bilgi mimarisi, dört durum ekseni, tam make-whole refund, tek
seferlik pickup kodu ve deferred komisyon **doğru kurulmuş**. Sıfırdan tasarım
turu gerekmiyor; v1 örnek verisi ve görsel dili korunacak.

Ama iki P0 var ve ikisi de planın en sert iki kuralını ihlal ediyor: para
birimlerinin toplanmaması ve FX marjının ayrı deferred hesapta tutulması.
Bunlar cilalanacak kusurlar değil, muhasebe modelinin yeniden kurulmasını
gerektiriyor. Bu yüzden verdict ACCEPT-WITH-P1-FIXES değil REJECT.

**Başkanın düzeltmesi.** İlk turda "payout JE'si tutuyor, prototip kendi
içinde tutarlı" denmişti. Yanlıştı: denklik varsayılıp mid rate geriye doğru
türetilmişti. Kayıt yalnız açıklanmayan bir mid rate ile denkleşiyor; müşteri
kuruyla tam FX marjı kadar açık veriyor (aşağıda P0-2). Muhasebe kurul üyesi
19 kaydın tamamını bağımsız hesaplayarak bunu ve variance sütunundaki para
birimi karışımını (P0-1) ortaya çıkardı.

---

## ADR-001 — In-transit yükümlülüğünün para birimi

**Karar: receive currency.** (Zafar, 2026-08-16)

Prototip sessizce **send currency** modelini seçmişti. REM-0406 (TAS-C→BUX-1,
USD→EUR) zincirinden ölçülen gerçek davranış:

```
REGISTER  Dr Cash TAS-C 1,165.65 USD / Cr In-transit 1,150.00 USD
                                     / Cr Deferred commission 15.65 USD
PAYOUT    Dr In-transit 1,150.00 USD / Cr Cash BUX-1 1,049.26 EUR
          Dr Deferred commission 15.65 / Cr Commission income 15.65
                                     / Cr FX margin income 10.74 USD
```

Aritmetik doğrulandı: müşteri kuru 1.09601, iç kur 1.08578, fark × 1.049,26 EUR
= 10,73 ≈ 10,74 USD. Yani prototip **kendi içinde tutarlı** — hatalı değil,
farklı bir model.

| | Receive ccy (seçilen) | Send ccy (prototip) |
|---|---|---|
| Register–payout arası kur riski | Yok | Şirkette |
| FX marjı ne zaman bilinir | Register'da kilitlenir | Ancak payout'ta |
| Marj ile piyasa hareketi ayrılabilir mi | Evet | Hayır, tek kalemde karışır |
| Refund'da FX satırı | Zorunlu | Gereksiz |
| Mevcut `remittance.py` ile uyum | Uyumlu | Değişiklik gerektirir |

Gerekçe: borç, ödeneceği para biriminde tutulur. 72 saatlik pencerede risk küçük
olsa da, marjın piyasa hareketinden ayrılamaması mutabakatı kalıcı olarak
bulanıklaştırır. Mevcut backend zaten receive currency'de çalışıyor.

**Sonuç:** v2 prototipi register JE'sine `deferred FX margin` satırı eklemeli,
in-transit'i receive currency'de göstermeli, payout'u birebir kapatmalı ve
cross-currency refund'a FX satırı koymalı.

---

## P0 — kabulü bloke eden iki madde

### P0-1 · JE variance sütunu USDT ile USD'yi toplayıp tek sayı yazıyor
`recRows()`: `const varc = outg.concat(inc).filter(...).reduce((x, t) => x + (t.varc || 0), 0);`

Gerçekte iki variance var: **12,40 USDT** (REM-0409) ve **−3,20 USD**
(REM-0410). Üst tablo bunları üç satıra yayıyor ve TAS-C/USD hücresine
**9,20** yazıyor — bu sayı `12,40 USDT + (−3,20 USD)`'nin aritmetik toplamı.

| branch×currency | Üst tablo | Alt tabloda atfedilen | Açıklanamayan |
|---|---|---|---|
| TAS-C / USD | 9,20 | −3,20 (REM-0410) | **12,40** |
| SAM-1 / USDT | 12,40 | 12,40 (REM-0409) | 0 |
| BUX-1 / EUR | −3,20 | hiçbir şey | **−3,20** |

Ekran bunu kendi banner'ının altında yapıyor:
`Every figure belongs to one branch and one currency. Nothing is converted or
combined.` Uydurma dönüştürülmüş eşdeğer, planın tek pazarlıksız kuralı.

Sebep, `recExc()`'nin variance'ı yalnız origin+send currency'de üretmesi
(`br: c.o, cur: q.sc`), `recRows()`'un ise hem origin hem destination'da
saymasıdır. D19'daki "iki tablo uyuşmuyor" gözlemi bunun semptomuydu.

**Düzeltme:** variance `{currency, amount}` çifti olarak taşınsın, tek bir
(branch, currency) hücresine ait olsun, `reduce` ile asla toplanmasın; iki
tablo tek kaynaktan beslensin.

### P0-2 · Deferred FX margin hiçbir kayıtta yok; payout preview'u dengesiz
Dosyada `Deferred FX margin` diye bir hesap **mevcut değil**. "FX" yalnız dört
yerde geçiyor: recon sütun başlığı, score card etiketi ve iki kez
`{acc: 'FX margin income', dr: '', cr: fmt(q.fx), cur: q.sc}`.

Register JE'sinde FX bacağı olmadığı için payout'ta karşılıksız FX geliri
alacaklanıyor. Gönderim para birimi cinsinden, müşteri kuruyla:

| Transfer | Corridor | Dr | Cr | Fark |
|---|---|---|---|---|
| 0406 | USD→EUR | 1.165,65 | 1.176,39 | +10,74 |
| 0407 | USD→USDT | 2.621,00 | 2.628,80 | +7,80 |
| 0344 | EUR→USD | 3.134,00 | 3.160,32 | +26,32 |
| 0409 | USDT→USD | 1.815,90 | 1.822,21 | +6,31 |

Fark her satırda tam `q.fx`. Kayıt ancak açıklanmayan bir mid rate
varsayılırsa denkleşiyor — ve `mid` ne quote'ta, ne frozen quote sekmesinde,
ne audit log'da, ne reconciliation'da görünüyor. Kasiyere "Exactly what will
be recorded" başlığı altında dengesiz yevmiye gösteriliyor.

### P0-2b · In-transit iki ekranda iki farklı para biriminde
Prototip `in-transit`i geçtiği **beş yerin hepsinde** send currency'de tutuyor
(`jesOf` register/payout/refund, `payVals`, `rfVals` — hepsi `cur: q.sc`), ve
`recRows()` de öyle topluyor. Ama Operations kartı yükümlülüğü **alım para
biriminde** gösteriyor (`group(transit, t => COR[t.cor].rc, t => Q(t).gets)`).

| | USD | EUR | USDT |
|---|---|---|---|
| Operations "In transit" | 6.614,55 | 7.152,27 | 2.082,48 |
| Reconciliation "Open in-transit" | 14.458,25 | 3.278,00 | 2.200,00 |

Aynı yükümlülük, iki ekran, aralarında mutabakat kalemi yok. ADR-001 bunu
receive currency lehine çözüyor; her iki ekran da tek kaynaktan beslenmeli.

---

## Kapatılması zorunlu — v2 tasarım turu

### D1 · Muhasebe modeli ADR-001'e çekilecek
Register/payout/refund posting preview'ları ve Journal entries sekmesi yukarıdaki
üç kalıba uyacak. Operations kartındaki "FX margin" rakamları artık register'da
üretilen bir kayda dayanacak — bugün dashboard, hiçbir postingin üretmediği bir
büyüklüğü raporluyor.

### D2 · Payout ekranı geçerli pickup kodunu basıyor
`1438| payHint: '...the valid code for ' + t.id + ' is ' + t.code`, render
`880|`. Hiçbir flag ile gate'lenmemiş — yalnız kendi düzyazısı "prototype"
diyor. Altı satır yukarısı bunu yalanlıyor: `874| The code is never displayed on
this screen.` Silinsin; `t.code` payout viewmodel'ine hiç girmesin.

### D3 · Tek seferlik kod ekranından onaysız çıkılabiliyor
Ack kapısı yalnız `1499| leaveRcpt` içinde ve sadece `Done` butonunu bağlıyor.
`1807-1808| goOps/goTr/goRec/goNew` koşulsuz. Canlı doğrulandı: `Transfers`
sekmesine tıklayınca ekran terk ediliyor, kod kalıcı olarak kayboluyor.
Vue'da `beforeRouteLeave` + `beforeunload` gerekir — **bead'in DoD'una yazılsın**,
aksi hâlde port sırasında unutulur.

### D4 · Refund onayı ile nakit çıkışı tek adıma çökmüş
Canlı doğrulandı: Finance Manager rolünde `Approve refund` tek tıkta
"Refunds paid" 1→2 yapıyor. `1282| patch(id, {refund:'Completed',
op:'Refunded', ...})`. Ara `Approved`-ama-ödenmemiş durumu yok, nakit sayım
onayı yok. Payout bunu doğru yapıyor (cash-count checkbox'sız post etmiyor);
refund'da aynı kapı yok. Durum makinesi zaten iki adım için tasarlanmış
(`1183-1188| RFB.Approved`, `1271| 'Pay refund cash to sender'`) — kod
kısa devre yapıyor. Onay (yetki) ile ödeme (kasa) ayrılsın.

### D5 · `allowed_actions` hiç yok; aksiyonlar üç yerde kopyalanmış kuraldan türüyor
Plan: *"UI ana aksiyonu backend'in `allowed_actions` cevabından alır."* Dosyada
0 hit. Aynı kural `1631`, `1751`, `1247`'de kopyalanmış. Türetilen sonuçlar
doğru — sorun şekil ve sürüklenme riski. Sample data'ya
`allowed_actions:['payout','request_refund']` girsin, satır aksiyonları onu
map'lesin.

### D6 · Manager-only aksiyonlar kasiyere buton olarak sunuluyor
`1249-1252` (`Approve refund`, `Reject`, `Unlock`) hiçbiri `isMgr()` kontrol
etmiyor; engelleme yalnız handler'da. Oysa refund ekranı doğru deseni zaten
kullanıyor (`1409-1410| rfIsMgr`, `rfGate`). Prototip kendi içinde çelişiyor;
`rfVals` deseni kazansın. D5 uygulanırsa kendiliğinden çözülür.

### D7 · 390px'te modül navigasyonu ve ana aksiyon erişilemez
Ölçüldü: sekme şeridi **52px** genişlikte, içinde 385px sekme — hiçbir etiket
tam görünmüyor. `New Transfer` `x=376 → right=514`, 390px viewport'un dışında.
Sayfa yatay taşma vermiyor çünkü şerit kendi içinde kırpıyor; basit overflow
kontrolü bu hatayı gizliyor. VFC v2'de düzeltilen kusurun tekrarı.

### D8 · Mobil dokunma hedefleri
Ölçüldü (390px): `.snav` drawer menü satırları **238×33px**; kuyruk satırlarındaki
`REM-0412` referans butonları **62×19px** (`270| <button class="mono"
style="border:0;background:transparent;padding:0">`). `<768px` media query'si
`.btn`/`.fbtn`/`.seg > button`'ı 40px'e çıkarıyor ama bu iki sınıfı kapsamıyor.
VFC v3 devir notunda yazılan `min-height: 40px` maddesi burada tekrar ihlal.

### D9 · Payout'ta alıcı adıyla arama yok
Canlı doğrulandı: `"No transfer found for 'Dilnoza Yusupova'. Enter a full
Remittance ID..."`. `1481| T.find(x => x.id === key || x.ref === key)` — tam
eşleşme veya hiç. Makbuzunu kaybetmiş alıcı için kasiyer Transfers sekmesine
gidip ID kopyalamak zorunda: 2 ekran, 6+ tık, gişedeki en sık işlemde.
Find kutusu alıcı/gönderen adını da eşleştirsin, birden çok sonuçta kısa
seçim listesi dönsün.

### D10 · Pagination yok
Plan Imports'tan `Pagination` yeniden kullanımını şart koşuyor
(plan satır 152). Transfers ekranında yalnız sayaç var
(`341| {{ trCount }} of {{ trTotal }}`), sayfa kontrolü hiç yok.

### D11 · Kuyruklar aciliyete göre sıralı değil
`1231-1242| queueOf()` yalnız filtreliyor, dataset sırasını koruyor. "Expiring
< 12h" kuyruğunda 1 saati kalan satır, 11 saati kalanın altında durabiliyor.
Tek işi triyaj olan bir kuyrukta bu, en acil satırı gözden kaçırtır.

### D12 · Reconciliation'da tarih/vardiya kapsamı yok
`1591-1616| recRows()` yalnız şube ve currency filtreliyor; `cashIn`/`payOut`/
`refOut` tüm tarihleri topluyor (mock veri 6–16 Ağustos). Kasiyer vardiya
sonunda kendi kasasını kapatamıyor — ekran yapısal olarak "bugün ne oldu"
sorusuna cevap veremiyor. Transfers'taki `trFrom`/`trTo` deseni buraya da gelsin,
varsayılan "bugün".

### D27 · Reddedilmiş yevmiyeli payout gelir sayılıyor
`mtd = list.filter(t => op(t) === 'Paid Out' && t.paidAt && isThisMonth(...))`
— `acct` filtresi yok. REM-0409 `acct:'Posting Error'` ve exception'ı
*"Payout journal entry rejected: destination cash account closed for the
period."* Buna rağmen "Recognized this month" kartındaki **USDT 15,90'ın
tamamı** ve "Paid out today" USD 3.791,00'in **1.791,00'i** bu reddedilmiş
kayıttan geliyor. Aynı hata `recRows()`'daki `recog` ve `fx` sütunlarında:
SAM-1/USDT satırı hem `recog 15,90` hem `varc 12,40` gösteriyor.
Gelir tanıma yalnız `acct === 'Posted'` üzerinden yapılsın.

### D28 · Register'ı kaydedilmemiş transfer payout kuyruğunda
`payout:` filtresi `Posting Error`'ı dışlıyor ama `Unposted`'ı dışlamıyor.
REM-0414 (`op:'Registered', acct:'Unposted'`) "Ready for payout" kuyruğunda ve
`Pay out` butonu aktif — var olmayan bir yükümlülüğü borçlandırır. Üstelik
`jesOf` ona Posted bir Register JE gösteriyor ve `detAxes` Accounting notuna
`Journal entries mirror the master record` basıyor. Plan transition ile JE
submit'i aynı transaction'a koyuyor; `Registered + Unposted` mümkün olmamalı.

### D29 · ~~Komisyon min/max clamp'i quote kırılımını sessizce bozuyor~~ — KONUSUZ

**2026-08-16, ADR-002 ile düştü.** Sabit ücret ve min/max clamp iptal edildi;
komisyon tek yüzde. Clamp diye bir şey kalmadığı için bu bulgu geçersiz.
Aşağıdaki metin kayıt için duruyor.


`let comm = r2(c.fixed + pctFee); if (comm < c.min) comm = c.min; ...`
Quote paneli "Fixed fee" ve "Percentage fee"yi **clamp öncesi** gösteriyor.
Örnek veride tetiklenmiyor (19 kaydın hepsi kontrol edildi) ama erişilebilir:
C2'de 20,00 USD → 3,00 + 0,22 = 3,22 → min 5,00'e çekilir; ekranda 3,00 + 0,22
yazarken gönderen 25,00 öder. `fixed + pct + adjustment = commission` her zaman
ekranda kapanmalı.

### D30 · Mid rate hiçbir yerde görünmüyor
`fx = r2(base * (1 - c.rate / c.mid))` yalnız `c.mid` ile doğrulanabilir; `mid`
ne quote'ta, ne frozen quote sekmesinde, ne audit log'da, ne reconciliation'da
var. FX marjı denetlenemiyor. Ayrıca frozen quote sekmesinde transferin FX
marjı hiç yok — yalnız payout anında ortaya çıkıyor. Register'da doğduğuna
göre orada görünmeli.

### D31 · İade formu uygunsuz transfer için de render ediliyor
`rfForm: s.step === 'form'` — `eligible` ile kapılanmıyor ve markup'ta iki blok
kardeş `sc-if`, birbirini dışlamıyor. Prototipte `Paid Out`'a ulaşan yol yok,
ama Vue'ya birebir taşınırsa "iade edilemez" uyarısıyla çalışan iade formu aynı
anda ekranda olur. `rfForm = eligible && step === 'form'`.

### D32 · İade onay handler'ında durum yeniden doğrulaması yok
`approveRefund(id)` rol kontrolü yapıyor, operasyonel durum kontrolü yapmıyor.
Planın kabul testlerinde `concurrent payout–refund` açıkça var; onay anında
master row-lock altında durum yeniden doğrulanmalı.

### D33 · Para birimi hassasiyeti ve kur hassasiyeti sabit kodlu
`fmt` her şeyi 2 haneye, `c.rate.toFixed(4)` her kuru 4 haneye sabitliyor —
USDT dahil. Plan: *"Currency precision metadata'dan, kur yüksek hassasiyetle
tutulur."*

---

## ~~Karar gereken — komisyon yüzde matrahı~~ — KARARA BAĞLANDI

**2026-08-16: ADR-002.** Ürün sahibi komisyon modelini değiştirdi — sabit ücret
ve min/max iptal, **tek yüzde**. Matrah `GROSS_TENDERED` değil, **anapara**.
Aşağıdaki `commission_basis` alanı ve `GROSS_TENDERED` önerisi **geçersizdir**;
tek konvansiyon var, seçenek yok. Gerekçe ve reddedilen alternatif:
`2026-08-16-remittance-operations-center.md` → ADR-002.

Geçerliliğini koruyan tek madde, aşağıdaki 4. kural: `pays` ve `commission`
birincil, üçüncü değer türetilir. Kalan metin kayıt için duruyor.

### Eski metin (geçersiz)

`pctFee = r2(amt * c.pct / 100)` her iki modda da **brüt tezgâh tutarı**
üzerinden. 1.200,00 inclusive → komisyon 12,80, alıcı 1.187,20. Sonuç:
Inclusive birim başına daha pahalı (%1,0782 efektif vs Exclusive %1,0667).
Alternatif (yüzdeyi net principal üzerinden çözmek) 12,69 verirdi.

**Benimsenen varsayılan: `GROSS_TENDERED`.** Gerekçe: kasiyerin fiziksel olarak
saydığı tek rakam odur, denklem çözmeden deterministiktir ve `base + comm =
pays` eşitliğini kuruşta bozmaz (prototip 19 kaydın hepsinde bu eşitliği
sağlıyor). Ama bu bir seçimdir, kendiliğinden doğru değildir — corridor
tarifesinde açık alan olarak durmalı.

Backend'in tanımlaması gerekenler:
1. `commission_basis`: `GROSS_TENDERED` | `NET_PRINCIPAL`, quote snapshot'ına
   dondurulur.
2. Yuvarlama sırası: `pctFee` → `comm = fixed + pctFee` → min/max clamp →
   `pays`/`base` türetilir.
3. Clamp toplam komisyona mı yalnız yüzde bileşenine mi uygulanır (prototip
   toplama uyguluyor).
4. Değişmez: `pays` ve `commission` yuvarlanan iki birincil değer,
   `base = pays − commission` **türetilir**, asla bağımsız yuvarlanmaz.
   Exclusive `pays = amount + commission`; Inclusive `pays = amount`.
5. Inclusive'de `commission >= amount` reddedilir (aksi hâlde `base <= 0`).
6. Quote ve makbuz matrah etiketini taşır: "0,90% of 1.200,00 (amount
   tendered)".

Aynı uyarı ADR-001 kayıtları için: üç bacağı bağımsız yuvarlarsan denge
bozuluyor (RMT-2026-0401: 880,47 + 7,54 + 12,00 = 900,01 ≠ 900,00). Bir bacak
türetilmiş plug olmalı.

---

## İyileştirilmesi istenen — v2'de mümkünse

- **D13** Inclusive/Exclusive seçim anında açıklamasız. Toggle (`703-710`) iki
  kelimeden ibaret; anlamı yalnız Quote panelinde dipnot olarak
  (`1521`) ve seçim yapıldıktan sonra görünüyor. Toggle'ın altına tek satır
  düz Türkçe/İngilizce açıklama.
- **D14** 20.000 üstü tutar çıkmaz sokak: `1552| "Amounts above 20,000.00 need
  Finance Manager pre-approval"` — ama bu onayı isteyecek hiçbir buton yok.
  Ya escalation aksiyonu eklensin ya mesaj kaldırılsın.
- **D15** Payout'ta kimliğin "ad" yarısı hiç kaydedilmiyor. Alıcı adı yalnız
  gösteriliyor (`839| Name must match the document`), teyit girdisi yok. Refund
  ise gönderen adını yazdırıp doğruluyor (`1382-1383`). Plan kimliği "ad + kod"
  diyor; sistem yalnız kodu zorluyor. Nakit sayım checkbox'ına benzer bir
  "receiver identity checked" teyidi.
- **D16** "Owner" = kaydı açan kişi (`1565`), hiç yeniden atanmıyor. Aciliyet
  saatler sonra doğduğunda vardiyada olmayan biri görünüyor. Ya kolon
  "Registered by" olsun ya gerçek atama kavramı gelsin.
- **D17** Toplam komisyon tek satırda yok; kasiyer müşteriye okurken ekranın iki
  ayrı yerine bakıyor (`1522-1523` vs `727`).
- **D18** "Recognized this month" kartı ay bazlı finans metriği; diğer dört kart
  bugün bazlı. Reconciliation'a taşınsın, Operations gün içi kalsın.
- **D19** Reconciliation kendi içinde mutabık değil: branch×currency tablosunda
  BUX-1/EUR varyansı −3,20 ve TAS-C/USD 9,20; exception listesi −3,20'yi
  REM-0410/TAS-C/USD'ye yazıyor ve 9,20 için satır yok.
- **D20** `Pay out` primary butonu yalnız `payLocked`'a bağlı (`911`);
  doğrulanmamışlık ve nakit teyidi tıklama sonrası toast'la yakalanıyor
  (`1471`). Davranış doğru, affordance yanlış — Vue'ya kopyalanacak template bu.
- **D21** `client_request_id` / aggregate version hiçbir ekranda temsil
  edilmiyor (0 hit). Payout receipt ve audit sekmesine `Request ID` satırı.
- **D22** Exceptions kartı "Expired / refund due 2" derken kuyrukta 1 satır var;
  bir exception `Aug 16, 23:20` ile gelecekte tespit edilmiş.
- **D23** Beşinci kart (`EXCEPTIONS`) masaüstünde tek başına ikinci satırda
  kalıyor — VFC v3'te lifecycle strip'e çevrilerek çözülen sorun.
- **D24** Sample data'da `1154| sender:'Zafar Umarov'`. Gerçek PII yok ama
  değişsin.
- **D25** `role="tab"` üzerinde hem `aria-pressed` hem `aria-selected`
  (`146-148`); `aria-pressed` toggle-button özelliği, `role=tab`'da geçersiz.
  Ayrıca detay alt-sekmeleri (`415| class="mtab"`) hiç `role="tablist"`
  kullanmıyor — görsel olarak aynı iki grup ekran okuyucuda farklı duyuruluyor.
- **D26** New Transfer ekranında iki primary buton görünüyor (global header
  `New Transfer` + `Register transfer`); form doldurulurken header primary'si
  ghost/disabled olsun.

---

## Tasarım hatası değil — implementation prompt'una taşınacak

Bunlar prototipte düzeltilmez; production Vue'nun farklı davranması gerekir.

- **I1** Kod karşılaştırması client-side (`1459| if (entered === t.code)`).
  Production'da `authorizePayout(id, code) → {ok, attempts_left, locked}`
  server çağrısı; kod hiçbir zaman viewmodel'e girmez.
- **I2** Ham `type="number"` tutar (`700`) ve `type="date"` (`330`, `332`)
  → `MoneyInput` / `DateInput`. Prototip Vue bileşenlerini gömemez; kimse bu
  markup'ı kopyalamasın.
- **I3** Dört eksenli durum gösterimi (`405-412`), debit/credit posting preview
  mini-tabloları ve pickup-code receipt paneli — mevcut bileşen setinde
  karşılığı **yok**. Gerçek yeni bileşen maliyeti; reuse gibi gösterilmesin.
- **I4** Tek düz props torbası (`1819| ...trVals(), ...detVals(), ...`)
  `rc.code` ve `payHint`'i her render'da global scope'a sokuyor. Vue'da ekran
  başına composable; pickup kodu asla paylaşılan store'a girmesin.
- **I5** Tabler CDN + Google Fonts (`20-24`) Stabler bundle'ına taşınmasın.

## Ayrı bead — üretimde bugün var olan güvenlik açığı

Tasarımdan bağımsız, `main` üzerinde şu an canlı:

- `stabler/api/remittance.py:356` pickup kodunu Journal Entry custom field'ına
  **plaintext** yazıyor. Karşılaştırma `hmac.compare_digest` ile sabit zamanlı
  (`:431`) — doğru; ama sır, JE okuma yetkisi olan herkesin görebileceği
  şekilde diskte duruyor. Plandaki hash-only kararı hiçbir yerde uygulanmamış.
- `:232` `pickup_code: str | None = None` parametresini kabul ediyor, `:331`
  onu kullanıyor — çağıran taraf kodu seçebiliyor, server-generated garantisi yok.

---

## Doğrulanan ve geçen maddeler

Kayıt için — bunlar kontrol edildi ve doğru bulundu, tekrar sorgulanmasın.

Currency ayrımı her ekranda (toplama yok, uydurma çevrim yok) · komisyon
register'da deferred, payout'ta gelir · refund tam make-whole, P&L 0,00 ·
kasiyer kur/komisyon/in-transit hesabı seçemiyor · Inclusive/Exclusive
matematiği gerçekten değişiyor (1.212,80→1.200,00 vs 1.200,00→1.187,20) ·
pickup kodu liste/drawer/timeline/audit/data-attribute/console/storage
kanallarının hiçbirine sızmıyor (yalnız `880| payHint` defekti) · detay ekranı
kodu "unavailable" gösteriyor, "masked" değil · 5 denemede input ve butonlar
gerçekten kilitleniyor, tek çıkış manager unlock · permission-denied gerçek ve
"nothing was posted" diyor · refund her zaman manager onayı istiyor · kasiyer
aynı transferde register+payout yapabiliyor (plana uygun) · terminal durumlarda
yasak aksiyon sunulmuyor · çift payout yok · Desk linki 0 · etiketsiz kontrol 0,
isimsiz ikon butonu 0, `:focus-visible` global · pickup kodu input'u benzersiz
erişilebilir ada sahip ve sayaç `aria-live="polite"` · durum yalnız renkle
anlatılmıyor · `100dvh` kullanılmış, `100vh` yok · geniş tablolar kendi
`.scrollx` kabında · durum rozetleri tek merkezi sözlükten (`OPB/ACB/VRB/RFB`)
· skeleton, empty, inline validation, permission-denied dördü de gerçekten
bağlı · tek kompakt yoğunluk, card-inside-card yok, gradient/progress bar yok ·
768px ve 1440px'te taşma yok, 40px altı hedef yok.
