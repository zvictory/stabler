# Stabler Remittance Operations Center — Ürün ve Uygulama Planı (2026-08-16)

Kurul çıktısı. Kararlar Zafar tarafından tur tur kilitlendi; bu dosya o kararların
kanonik kaydıdır. Önceki backend çalışması:
`docs/plans/2026-07-03-remittance-staging-and-installment-cancel.md` (Bölüm 2).

## Neden

Backend Temmuz'da `Register → Payout → Refund` aşamalı modele geçirildi
(`stabler/api/remittance.py`, patch `v33`). Frontend hâlâ eski tek-adımlı formda:

| Sorun | Kanıt |
|---|---|
| Register'da artık kullanılmayan `payout_account` zorunlu | `NewRemittance.vue:158,377` |
| Tek seferlik pickup kodu kullanıcıya hiç gösterilmiyor | `NewRemittance.vue` — `pickup` geçmiyor |
| Payout ve Refund ekranı yok | `RemittanceTransfers.vue` (200 satır, salt liste) |
| Eşzamanlı çift payout riski | master kayıt ve row-lock yok; JE zinciri tek gerçek |

Yani bu bir "ekranı güzelleştirme" işi değil; modülün ana iş akışı yarım.

## Kapsam kararları (kilitli)

| Karar | Seçim |
|---|---|
| Ağ modeli | Tek şirket, **kendi şubeleri** arası nakit transfer ağı |
| Dış payout partneri | V1 dışında (partner prefund, due-to/due-from yok) |
| Para birimleri | USD, EUR, **USDT** |
| USDT | Yalnız ERPNext currency/kasa hesabı. Wallet, network, confirmation, tx-hash **yok**. UI "on-chain verified" iddiası taşımaz |
| Komisyon geliri | **Payout tamamlanınca** tanınır (register'da deferred) |
| Refund | Yalnız payout öncesi, **tam make-whole** (principal + komisyon). Partial refund ve fee retention yok |
| Kimlik doğrulama | Yalnız **ad + pickup code**. KYC iddiası yok |
| Maker-checker | Register/Payout kasiyer doğrudan post eder; **Refund manager onayı ister** |
| Görev ayrımı | Aynı kasiyer hem register hem payout yapabilir (audit trail zorunlu) |
| Kur ve komisyon | **Kasiyer formda elle girer**; son girilen değer bir sonrakinde varsayılan gelir. Girilen değer register'da quote'a dondurulur — ADR-009 |
| Komisyon yansıtma | Transfer bazında **Inclusive/Exclusive**, kayıt sonrası değişmez |
| Komisyon formülü | **Tek yüzde**, formda elle girilir (ör. %1 / %0,5). Sabit ücret yok, min/max yok — ADR-002, ADR-009 |
| Corridor kaydı | **Yok.** Kasiyer hedef kasayı seçer; gönderen kasa kendi şubesidir — ADR-009 |
| Yerel para birimleri | **Sisteme hiç girmez.** UZS/TRY/AED/RUB yok; gönderi iki tarafta da sert para birimi. Yerel nakit bozdurma bu modülün dışında — ADR-003 |
| Mid rate | **Yok.** Tek kur var: kasiyerin girdiği müşteri kuru. FX marjı ayrı hesaplanmaz — ADR-009 (ADR-004 iptal) |
| Pickup süresi | **72 saat**; süre dolunca otomatik para hareketi yok, refund kuyruğuna düşer |
| Kod güvenliği | Server-generated, 8 karakter, **hash-only**, tek kullanımlık, 5 yanlış denemede kilit |

Kapsam dışı: supplier remittance, dış partner settlement, incoming partner
transfers, blockchain, full KYC, partial payout/refund, customer self-service.

## Domain modeli

Journal Entry **ürün kaydı olmayacak** — yalnız muhasebe gerçeği kalacak.

- ~~**Remittance Corridor**~~ — **ADR-009 ile iptal.** Corridor bir kayıt değil,
  gönderinin iki ucudur: gönderen kasa (kasiyerin kendi şubesi) ve hedef kasa.
  Yüzde ve kur formda elle girilir, register'da dondurulur.

### ADR-002 — Komisyon tek yüzde, matrah anapara (2026-08-16)

Sabit ücret + yüzde + min/max modeli **iptal**. Tek fiyat alanı var:
`commission_pct` (ör. 1,00 veya 0,50). Nereden geldiği ADR-009'da — kasiyer girer.

Yüzde her zaman **anaparanın** yüzdesidir — tezgâha konan tutarın değil.

| Mod | Kasiyer ne yazar | Komisyon | Türetilen |
|---|---|---|---|
| Exclusive | anapara `P` | `yuvarla(P × p)` | müşteri öder `= P + komisyon` |
| Inclusive | tezgâh tutarı `T` | `yuvarla(T × p / (1+p))` | anapara `= T − komisyon` |

Tek yuvarlama vardır, üçüncü değer türetilir; `anapara + komisyon = müşteri öder`
kuruşta her zaman kapanır.

%1'de: Exclusive 1.000 → komisyon 10,00 → müşteri 1.010,00 verir.
Inclusive 1.000 → komisyon 9,90 → anapara 990,10. **İkisi de anaparanın tam %1'i.**

Reddedilen alternatif (brüt matrah): Inclusive'de komisyonu tezgâh tutarının
yüzdesi saymak. Aynı tarife iki farklı efektif fiyat üretiyordu (%1,0101 vs
%1,000) ve iki mod birbirinin tersi değildi — Inclusive 1.000'den çıkan 990
anaparayı Exclusive'e verince 999,90'a düşüyordu. "Komisyonumuz %1" cümlesi tek
şey anlatmalı.

**Anapara, her iki modda da görünür bir quote satırıdır.** Yüzdenin uygulandığı
sayı odur; kasiyer iki satırı gösterip müşteriye "şu, şunun %1'i" diyebilmeli.

### ADR-003 — Uluslararası corridor, yalnız sert para birimi (2026-08-16)

Gönderiler uluslararası şehirler arasındadır: Taşkent, İstanbul, Dubai, Moskova
ve sonradan eklenecekler.

Para birimleri **yalnız USD, EUR, USDT**. UZS, TRY, AED, RUB sisteme hiç
girmez; gönderi iki tarafta da sert para birimindedir. Müşteri Taşkent'te
yerel nakit getirirse bozdurma bu modülün dışında olur, transfere USD/EUR/USDT
girer.

Sonuçları: üç para biriminin üçü de iki ondalıklı, karışık minor unit sorunu
yok; currency filtresi üç değerde kalıyor; score card satırları değişmiyor.

**Bu ADR'nin corridor kaydına dair kısmı ADR-009 ile düştü.** Ayakta kalan tek
hüküm para birimi kısıtıdır: yalnız USD, EUR, USDT. Şehir çifti artık bir kayıt
değil, seçilen hedef kasanın etiketidir; aynı iki kasa arasında `USD → USD` de
`USD → EUR` de yapılabilir, ayrı bir tanım gerektirmez.

### ADR-004 — Mid rate kasiyer ekranında görünmez ~~(2026-08-16)~~

**İPTAL — ADR-009 ile yürürlükten kaldırıldı.** Mid rate diye bir kavram
kalmadığı için görünürlüğünü düzenlemeye de gerek kalmadı. Tek kur var: kasiyerin
girdiği müşteri kuru. Kayıt tarihçesi için burada bırakıldı.

### ADR-005 — Dört şehir tek Company (2026-08-16)

Karar Zafar'a soruldu, cevap: **tek Company, karmaşık olmasın.**

Taşkent, İstanbul, Dubai, Moskova tek ERPNext Company içinde yaşar. Kasalar
Company değil, **şube/kasa** seviyesidir (Branch + kasa başına ayrı nakit hesabı).

Sonuçları:
- **ADR-001 geçerli kalır.** In-transit tek şirket içi bir yükümlülük hesabıdır;
  şirketler arası due-to/due-from **yok**. Register ve payout aynı defterde
  kapanır, konsolidasyon adımı gerekmez.
- Ülke bazlı yasal defter Frappe'den **çıkmaz**. Bugün istenmiyor.
- Kabul edilen maliyet: bir ülke ileride ayrı tüzel kişilik gerektirirse bu bir
  migration'dır (yeni Company + inter-company hesapları + geçmiş bakiyelerin
  taşınması). Bugün ödenmeyen, ileride ödenecek bedel — bilinerek kabul edildi.

### ADR-006 — Kasadan kasaya, hepsi gerçek GL hesapları (2026-08-16)

Gönderi **nakit**tir ve **kasadan kasaya** hareket eder. Ekrandaki hiçbir tutar
sanal alan değildir; her biri gerçek bir muhasebe hesabına yazar:

| Kalem | Hesap tipi | Nerede tanımlanır |
|---|---|---|
| Gönderen kasası | Asset → Cash yaprağı, **kasa başına ayrı** | Branch / kasa ayarı |
| Alıcı kasası | Asset → Cash yaprağı, receive currency'de | Branch / kasa ayarı |
| Receiver obligation (in-transit) | Liability yaprağı, receive currency | Remittance Settings |
| Deferred commission | Liability yaprağı | Remittance Settings |
| Commission revenue | Income yaprağı | Remittance Settings |

*(Deferred FX margin ve FX revenue hesapları ADR-009 ile kaldırıldı — beş hesap
üçe indi.)*

Kurallar:
- Hesaplar **koda gömülmez**, ayarlardan seçilir.
- Her kasanın, kullandığı **her para birimi için** ayrı bir nakit hesabı olmak
  zorundadır; yoksa o kasa o para biriminde gönderi alamaz/veremez. Eksikse hata
  gönderi kaydedilirken çıkar ve hangi hesabın eksik olduğunu söyler.
- Kasa bakiyesi kasiyerin fiziksel sayımına eşit olmalıdır — bu yüzden kasa
  hesabı kasa başına ayrıdır, şube başına değil.
- **USDT normal kasa gibi taşınır** (karar: Zafar, 2026-08-16). Ayrı bir cüzdan
  hesabı, zincir entegrasyonu, borsa API'si **yok**. USDT kasası da USD ve EUR
  kasası gibi bir Cash yaprağıdır ve bakiyesi elle mutabık kılınır.
  - Tek fark denetimdedir, muhasebede değil: USD/EUR kasası fiziksel sayımla,
    USDT kasası cüzdan ekranındaki bakiyeyle karşılaştırılır. Aynı ekran, aynı
    hesap tipi, farklı kanıt. Reconciliation kanıt alanını buna göre etiketler.
  - Ön koşul: ERPNext'te **USDT bir Currency kaydı olarak tanımlanmalı**,
    ondalık hassasiyeti açıkça belirlenmeli (öneri: 2 — USD/EUR ile aynı, yuvarlama
    kuralı tek kalsın). Bu, ilk USDT gönderisinden önce doğrulanır.

### ADR-007 — Inclusive ve Exclusive birbirinin tersi DEĞİLDİR (2026-08-16)

**Ölçülmüş bulgu, tahmin değil.** 55.000 tutar üzerinde çalıştırılan round-trip
testi (`scratchpad/comm2.py`): Inclusive ile hesaplanan anaparayı Exclusive'e geri
verdiğinde sonuç **~%1 oranında bir kuruş sapıyor**.

| pct | Sapan tutar | Azami sapma |
|---|---|---|
| 0,50 | 274 / 55.000 | **0,01** |
| 1,00 | 545 / 55.000 | **0,01** |

- Sapma **her zaman tam bir minor unit**, asla daha fazla. Büyük tutarlarda da,
  küçük tutarlarda da çıkıyor — bu bir "küçük tutar" sorunu değil.
- Sebep yapısal: kuruşa yuvarlama, iki yönü matematiksel olarak tersinemez yapıyor.
  Komisyonu önce hesaplayıp anaparayı türetmek ile anaparayı önce hesaplayıp
  komisyonu türetmek **aynı sayıda hata veriyor** (274/545, birebir). Yani
  formülü değiştirmek çözmüyor.

**Karar — matematiği düzeltmeye çalışma, tasarımı buna göre kur:**
1. Register anında **üçlü saklanır**: `principal`, `commission`, `tendered`.
   Tek doğruluk kaynağı budur. Hiçbir okuma yolunda yeniden hesaplanmaz —
   makbuz, detay, refund, mutabakat hepsi saklanan değeri okur.
2. Inclusive/Exclusive **bir görünüm anahtarı değil, bir girdi konvansiyonudur**.
   Kasiyer tutarı yazdıktan sonra modu değiştirirse bu **yeni bir fiyat teklifidir**;
   ekran sayıların değiştiğini açıkça söyler. "Aynı işlem, başka gösterim" diye
   sunulursa kasiyer bir kuruşluk oynamayı hata sanar.
3. Yuvarlama modu **HALF_UP**, para birimi başına 2 hane. Tek kural, dallanma yok.

### Çalışılmış örnek — Taşkent → İstanbul, USD→EUR, %1, Inclusive

Girdi: tezgâh tutarı 1.000,00 USD · kasiyerin girdiği kur 1 USD = 0,9250 EUR.
Türetilen: komisyon 9,90 · anapara 990,10 · alıcı 915,84 EUR.
Etkin komisyon anaparanın %0,9999'u. Baz para birimi USD.

```
REGISTER  Dr Cash on hand – TAS-C          1.000,00 USD   base 1.000,00
          Cr Deferred commission                9,90 USD  base     9,90
          Cr Receiver obligation – IST      915,84 EUR    base   990,10

PAYOUT    Dr Receiver obligation – IST     915,84 EUR     base   990,10
          Cr Cash on hand – IST-1                915,84 EUR base  990,10
          Dr Deferred commission             9,90 USD     base     9,90
          Cr Commission revenue                    9,90 USD base     9,90

REFUND    Dr Receiver obligation – IST     915,84 EUR     base   990,10
          Dr Deferred commission             9,90 USD     base     9,90
          Cr Cash on hand – TAS-C                1.000,00 USD base 1.000,00
```

Üç kalem, üç kayıt: **alacak → komisyon → verecek.** Üçü de baz para biriminde
kuruşu kuruşuna dengeleniyor. Refund müşteriye tezgâha koyduğu 1.000,00 USD'nin
tamamını geri veriyor.

**Yükümlülüğün baz değeri anaparaya eşit olmak zorunda** (990,10 = 1.000,00 −
9,90). Kod bunu satırın `exchange_rate` alanını yuvarlayarak türetmemeli; baz
değeri **doğrudan anapara olarak yazmalı**, kuru ondan türetmeli. Tersi yapılırsa
915,84 × yuvarlanmış kur bir kuruş kayabilir ve yevmiye dengelenmez.

**Dikkat — çapraz kur kaydı yalnız bazda dengelenir**, para birimi bazında değil.
Bu ERPNext'in normal davranışıdır; eski notlardaki "hem bazda hem para birimi
bazında dengelenir" ifadesi yalnız aynı para birimli transferler için doğrudur.

### ADR-008 — Payout ve refund **register kurunu** kullanır (2026-08-16)

Karar: Zafar. Receiver obligation hangi baz kurla açıldıysa **aynı kurla kapanır**.

- Register anında transferde `register_base_rate` saklanır. Payout ve refund
  yevmiye satırları bu kuru kullanır — **günün kuru değil**.
- Sonucu: payout kaydı register bacağının birebir aynası olur. Payout anında
  realised FX gain/loss satırı **yoktur**; kasiyer ekranında açıklanamayan kuruş
  farkı çıkmaz.
- Register ile payout arasındaki gerçek piyasa hareketi kaybolmaz — receiver
  obligation yabancı para cinsinden parasal bir kalem olduğu için **dönem sonu FX
  revaluation'da** unrealised gain/loss olarak görünür. Doğru yer orasıdır.
- Refund de register kuruyla kapanır; müşteriye tezgâha koyduğu tutarın tam olarak
  kendisi geri verilir (yukarıdaki örnekte 1.000,00 USD).

**Uygulama tuzağı:** ERPNext yevmiye satırında `exchange_rate`'i varsayılan olarak
**bugünün kuruyla doldurur**. Kod bu alanı satır bazında açıkça saklanan kura
set etmek zorundadır. Bunu doğrulayan bir test şart: register'dan sonra kur
değiştirilip payout yapıldığında obligation bakiyesinin **tam sıfırlandığı**
gösterilmeli. Bu test yoksa hata sessizdir — payout çalışır, geriye kuruşluk bir
artık bakiye kalır ve aylar sonra mutabakatta bulunur.

- **Remittance Transfer** — sender/receiver adı, quote snapshot,
  Inclusive/Exclusive, sender pays, explicit fee, receiver gets, expiry,
  pickup-code hash, attempt/lock, kullanıcı+şube audit'i, bağlı JE'ler.
- **Remittance Event** — append-only: Register, failed code attempt,
  lock/unlock, Payout, Refund request/approval/completion.

### Muhasebe

**In-transit yükümlülüğü receive currency'de taşınır** — kilitli karar, 2026-08-16.
Alıcıya borç hangi para biriminde ödenecekse yükümlülük o para biriminde açılır.
Sonuçları: FX marjı register'da kilitlenir ve ayrı bir deferred FX hesabında bekler;
register–payout arasında kur riski oluşmaz; payout birebir kapanır; refund'da FX
satırı gerekir. Gerekçe ve reddedilen alternatif:
`docs/plans/2026-08-16-remittance-design-council-decision.md`.

Örnek — TAS-C → BUX-1, USD→EUR, gönderen 1.165,65 USD, alıcı 1.049,26 EUR:

```
REGISTER   Dr origin cash/bank      1,165.65 USD
           Cr receiver obligation               1,049.26 EUR   ← receive ccy
           Cr deferred commission                  15.65 USD
           Cr deferred FX margin                   10.74 USD

PAYOUT     Dr receiver obligation   1,049.26 EUR
           Cr destination cash/bank             1,049.26 EUR   ← FX'siz, birebir
           Dr deferred commission      15.65 USD
           Cr commission revenue                   15.65 USD
           Dr deferred FX margin       10.74 USD
           Cr FX revenue                           10.74 USD

REFUND     Dr receiver obligation   1,049.26 EUR
           Dr deferred commission      15.65 USD
           Dr deferred FX margin       10.74 USD
           Cr origin cash/bank                  1,165.65 USD   ← tam make-whole
           (yükümlülük EUR, iade USD → FX satırı zorunlu; P&L sıfır kalır)
```

- Foreign account için `exchange_rate=1` fallback **yasak**.
- Currency precision metadata'dan, kur yüksek hassasiyetle tutulur.
- Generic JE cancel/amend, bağlı transition varsa **bloklanır**; reversal yalnız
  domain aksiyonuyla.
- Her command `client_request_id` ile idempotent, master row-lock altında.

### Durum eksenleri (ayrı gösterilir)

- **Operational:** Draft → Registered → Paid Out / Refunded / Expired / Exception
- **Accounting:** Unposted → Posted → Reversed / Posting Error
- **Verification:** Not Issued → Active → Locked → Consumed / Expired
- **Refund:** None → Requested → Approved/Rejected → Completed

UI ana aksiyonu backend'in `allowed_actions` cevabından alır; kendi status
tahmini yapmaz.

### ADR-009 — Corridor kaydı yok; yüzde ve kur formda elle girilir (2026-08-16)

Karar: Zafar — *"corridor ayrıca hesaplanmıyor, basit devletten devlete gönderi
olacak, alacak, komisyon, verecek şeklinde, komplike olmasın."*

**Ölen kavramlar:**
- `Remittance Corridor` doctype'ının tamamı — şehir çifti başına fiyat, limit,
  kur, readiness makinesi. Yok.
- `Remittance City` doctype'ı. Şehir, kasanın (Branch) bir etiketidir; ayrı bir
  Link hedefi değil.
- **Mid rate**, dolayısıyla ADR-004'ün tamamı.
- **Deferred FX margin** ve **FX revenue** hesapları. Beş GL hesabı **üçe** indi.

**Yerine gelen:**
- Kasiyer corridor değil, **hedef kasayı** seçer. Gönderen kasa zaten kendi
  şubesidir, seçilmez.
- `commission_pct` ve — para birimi değişiyorsa — **kur, formda elle girilir.**
  Her ikisi de **son girilen değer bir sonraki gönderide varsayılan olarak
  gelir** (kullanıcı bazında hatırlanır; bir kasiyerin girdiği oran diğerinin
  ekranını değiştirmez).
- Girilen yüzde ve kur, register anında transferde **dondurulur** (ADR-007'deki
  üçlü + kur). Sonradan hiçbir ekran yeniden hesaplamaz, ADR-008 gereği payout ve
  refund aynı kuru kullanır.

**Kabul edilen bedel — açıkça yazılıyor:** FX marjı artık ayrı bir gelir kalemi
olarak görünmüyor. Kurul bunu daha önce "denetlenemez" diye kusur saymıştı; bu
sadeleştirme o bulgunun üstüne biniyor. Marj kaybolmuyor — verdiğimiz EUR'nun
bize maliyeti ile müşteriden aldığımız USD arasındaki fark, EUR hesaplarının
dönem sonu değerlemesinde FX kazancı olarak ortaya çıkıyor. Yani **kâr görünür,
ama "gönderi marjı" olarak değil, "FX kazancı" olarak.** Gönderi bazında marj
raporu istenirse bu karar geri açılmalı.

## Doctype şartnamesi

Sadeleşmiş hâli **tek yeni ayar doctype'ı**. Ev düzenine uyuyor:
`vehicle_finance_settings` ile aynı kalıp — `autoname: field:company`, Section
Break'ler, GL hesapları `Link → Account`.

### `Remittance Settings` (Company başına bir kayıt)

**Hesaplar** — üçü de reqd:
`receiver_obligation_account` · `deferred_commission_account` ·
`commission_income_account`, hepsi `Link → Account`.

**Politika:** `default_quote_expiry_hours` (Int, 72) · `max_code_attempts`
(Int, 5) · `lockout_minutes` (Int) · `require_refund_approval` (Check, default 1).

**Kasa hesapları** — `cash_desk_accounts`, child table:

| Alan | Tip | Not |
|---|---|---|
| `branch` | Link → Branch | reqd — kasa |
| `city` | Data | kasanın şehri, serbest metin etiketi |
| `currency` | Link → Currency | reqd |
| `account` | Link → Account | reqd, kasa+para birimi başına ayrı |
| `evidence_type` | Select | `Counted` / `Wallet balance` — ADR-006 |

Doğrulama: `(branch, currency)` tekil. Kasa başına ayrı hesap şart — defter
bakiyesi fiziksel sayıma eşit olsun diye.

**Tek engelleyici doğrulama:** üç hesap dolu değilse veya kasiyerin şubesinde
gönderi para biriminin hesabı yoksa gönderi kaydedilemez. Hata mesajı hangi
hesabın eksik olduğunu ve nereden düzeltileceğini söyler.

### USDT'nin ERPNext v16'daki gerçek maliyeti

USDT sıradan kasa olarak taşınacak (Zafar), üç mekanik ön koşul var:

1. **`Currency` kaydı gerekiyor.** Frappe sabit listeyle gelir; USDT elle
   eklenmeli, `smallest_currency_fraction_value = 0.01`, number format USD/EUR
   ile aynı. → *engel değil, tek seferlik kurulum.*
2. **Kur sağlayıcısı yok.** Bizde sorun çıkmıyor: kuru kasiyer giriyor ve yevmiye
   satırına elle yazıyoruz, `get_exchange_rate`'e hiç sormuyoruz.
   → *tasarım gereği nötralize.*
3. **Dönem sonu FX revaluation.** `Exchange Rate Revaluation`, USDT cinsinden
   hesaplar için güncel kur arar; `Currency Exchange` kaydı yoksa ya patlar ya
   saçmalar. → *kabul edilen maliyet: ayda bir elle USDT `Currency Exchange`
   kaydı.* Unutulursa dönem kapanmaz — runbook'a girmeli. ADR-009 FX marjını
   revaluation'a taşıdığı için bu madde artık **kâr rakamını da etkiliyor**,
   yalnız kapanışı değil.


## UI / UX

### Navigasyon

1. **Operations** — varsayılan açılış (bugün `/remittance` → `/remittance/new`,
   bu değişecek)
2. **Transfers**
3. **Reconciliation**
4. Tek primary action: **New Transfer**

### Operations

Scorecards: Registered today · In transit / ready payout · Paid out today ·
Commission + FX revenue · Exceptions.
"All currencies" görünümünde USD/EUR/USDT **ayrı satır**; sahte toplam yok.

Kuyruklar: Ready for payout · Expiring within 12 hours · Expired / refund
required · Refund awaiting approval · Locked pickup code · Accounting exception.

Satır: reference, sender, receiver, route (origin kasa → hedef kasa), sender
pays, receiver gets, age/expiry, owner, next action.

### New Transfer

1. Hedef kasa (gönderen kasa kasiyerin kendi şubesidir, seçilmez)
2. Send/receive currency
3. Sender/receiver adı
4. Amount + Inclusive/Exclusive + **commission %** + (para birimleri farklıysa)
   **kur** — ikisi de elle girilir, son değer varsayılan gelir (ADR-009)
5. **Quote:** principal, commission, sender hands over, uygulanan kur,
   receiver gets, expiration time
6. Final review ve Register
7. **Tek seferlik pickup-code receipt**

Kasiyer commission / in-transit / accounting **hesabını** seçmez — ayarlardan
gelir. Yüzdeyi ve kuru ise girer.

### Pickup-code receipt

Büyük monospace Remittance ID + pickup code, receiver adı ve alacağı tutar,
copy/print, zorunlu "I handed/saved the code" acknowledgement. Sayfa kapandıktan
sonra plaintext **bir daha gösterilmez**.

### Payout

Remittance ID ile bul → receiver/route/exact receive amount göster → tek
erişilebilir pickup-code input → payout branch/account confirmation → cash
confirmation + exact posting preview → Payout → receipt.

### Refund

Yalnız Registered/Expired transfer. Sender adı doğrulaması, zorunlu gerekçe,
principal + fee tam iade preview, manager approval, refund posting ve code
invalidation.

### Transfers

Search (reference/sender/receiver/kasa), status + currency + tarih +
expiry + exception filtreleri, compact striped table. Finansal bulk action ve
multi-select **yok**. Drawer salt-okunur preview; full detail ayrı sayfa:
quote, durum eksenleri, stage timeline, Journal Entries, code attempts, refund
approval, audit.

### Reconciliation

Register cash-in · open in-transit liability · payout/refund cash-out ·
deferred/recognized commission · master ↔ JE variance ·
aged/expired transfers. Currency ve branch bazlı exception listesi.

Imports'tan `ScoreCard`, `FilterChips`, `StatusIcon`, `ListToolbar`,
`Pagination`; Vehicle Finance'tan Operations-first queue ve immutable event
timeline dili. Tek kompakt desktop density; mobilde 40px hedefler.

## API, yetki, geçiş

Yeni additive API: `stabler.api.remittance.v1` — quote/create draft, register,
find/authorize payout, payout, request/approve/refund, manager unlock,
detail/list, operations summary, reconciliation exceptions.

Her mutation `client_request_id`, aggregate version ve `allowed_actions` döner.
State transition ile JE submit **aynı transaction'da**, master row lock altında.

| Rol | Yetki |
|---|---|
| Remittance Viewer | Masked liste/detail ve raporlar |
| Remittance Cashier | Draft, Register, Payout |
| Remittance Finance Manager | Ayarlar ve hesap eşlemesi, locked code açma, Refund onay/post, domain reversal |
| Remittance Auditor | JE, event ve reconciliation salt-okur |

Erişim = company permission ∩ `enable_remittance` ∩ rol ∩ belge izni.

### Rollout

- Company setting `remittance_engine = JE Legacy | Transfer V1`, varsayılan
  **JE Legacy**.
- Mevcut Register/Payout/Refund JE zincirlerinden additive master kayıt üretilir.
- Duplicate terminal stage, missing Register veya dengesiz transfer otomatik
  düzeltilmez → **Migration Conflict**.
- Mevcut plaintext pickup kodları hash'e çevrilir, doğrulandıktan sonra
  plaintext temizlenir.
- Eski endpoint imzaları compatibility wrapper olarak korunur.
- Önce owner company, sonra module-disabled leakage testi, sonra ikinci company
  smoke. Production deploy ayrıca açık onay ister.

## Kabul testleri

Same/cross-currency Register → Payout · Register → full Refund · USD/EUR/USDT
precision · Inclusive/Exclusive tek yüzde ile ve **iki modun oda dönüşü**
(Inclusive'in ürettiği anapara Exclusive'e verilince aynı tezgâh tutarına
dönmeli) · `anapara + komisyon = müşteri öder` her para biriminde kuruşta
kapanmalı, sıfır ondalıklı UZS dahil · komisyonun yalnız
payout'ta gelir olması · 72 saat expiry · 5 hatalı kod → lock, manager unlock ·
concurrent payout–payout ve payout–refund · same-key replay ve payload conflict ·
Cashier/Manager/Viewer/Auditor permissions · wrong-company ve module-disabled
direct API · generic JE cancellation koruması · master ↔ JE reconciliation ·
legacy migration conflict · pickup plaintext/hash sızıntısı yok · currency-safe
scorecards · no Desk links · MoneyInput/DateInput · status centralization ·
loading/skeleton/empty/error/permission-denied · 1440/1024/768/390px · klavye
erişilebilirliği.

## Varsayımlar

- USDT yalnız ERPNext currency/account bakiyesi; on-chain doğrulama yok.
- Gönderiler tek legal company içindeki kasaları bağlar (ADR-005).
- Vergi ve komisyon hesapları company configuration'dan gelir; üretim öncesi
  yerel muhasebe onayı gerekir.
