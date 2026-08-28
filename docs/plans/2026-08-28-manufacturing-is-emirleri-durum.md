# Manufacturing — İş Emirleri yeniden tasarımı: bugünkü durum

**Tarih:** 2026-08-28 · **Ölçen:** Claude, Zafar'ın talebiyle
**Kaynak paket:** `Manufacturing interface and work orders.zip` (2026-08-24), Zafar'ın
Downloads klasöründe. **Bu depoda kopyası yok.**

Bu doküman bir karar değil, bir **envanter**. Yazılma sebebi: paketin repoda hiçbir
plan dokümanı yoktu, dolayısıyla "ne yapıldı" sorusu her seferinde arşivi açmayı
gerektiriyordu. Buradaki her satır 27–28 Ağustos'ta ya kodda ya prod'da ölçüldü.

---

## Beş yön, bugünkü hâli

| Yön | Durum | Kanıt |
|---|---|---|
| **1a** Yoğun vardiya defteri | KISMEN | `WorkOrders.vue:361` — tek filtre: durum. Tarih / hat / operatör filtresi yok, yoğunlaştırma uygulanmadı. |
| **1b** Kanban panosu | YOK | `pages/manufacturing/` altında kanban dosyası yok. |
| **1c** Hat × zaman planlama | **YOK** | Backend kayıtlı (`hooks.py:429` → `manufacturing.create_material_request_for_tomorrow_wo`) ama **hiç kayıt üretmemiş** — aşağıya bakınız. Planlama ekranı da yok. |
| **1d** Tam sayfa sipariş detayı | KISMEN | `WorkOrderDetail.vue` var (`4bc87d6`). Soyağacı tek blok: `:462-484` parti no + tüketilen malzeme listesi — **ağaç görünümü yok**. `suggest_wo_batch` bu sayfada değil, yalnız kioskta (`ManufacturingOperatorBoard.vue:644`). |
| **1e** Operatör kiosk 2.0 | VAR | `ManufacturingOperatorBoard.vue` (1 652 satır), numpad `292574a`. |
| — **Operasyon kartları** | **ÖLÜ** | Ölçümle iptal, aşağıya bakınız. |

## Operasyon kartları neden ölü

Bariz tasarım, detay sayfasında ERPNext rota operasyonu başına bir kart göstermekti.
İş emri koşturan tek kiracıda ölçüldü (anjan): **0 Work Order Operation, 0 BOM
Operation, 0 Workstation, 0 Job Card.** Operasyon kartları sistemdeki *her* siparişte
boş ızgara olurdu.

Bunun yerine kartlar, bu atölyenin gerçekten sahip olduğu ayrıştırmayı gösteriyor:
iki farklı iş yapan iki kişi (döküm ve paketleme), BOM rolle bölünmüş, rol başına bir
sapma kovası. Gerekçe kodda da duruyor: `composables/workOrderStages.js:1-12`.

## 1c düzeltmesi — "488 malzeme talebi" yanlıştı

Bu dokümanın ilk sürümü 1c'yi KISMEN sayıyordu, gerekçesi "backend canlı, anjan'da
488 malzeme talebi üretmiş"ti. **Yanlış.** 488, anjan'daki *toplam* Material Request
sayısı; hook'un ürettiği sayı değil.

Doğru ölçüm hook'un kendi imzasından okunur. `manufacturing.py`'de hook, oluşturduğu
her talebe `mr.work_order = doc.name` yazar — mükerrer üretimi o alandan engelliyor.
28.08, anjan, salt-okunur:

| Ölçüm | Değer |
|---|---|
| Material Request toplam | 488 |
| …`work_order` alanı dolu (**hook imzası**) | **0** |
| Tipe göre: Material Transfer / Purchase / Manufacture | 475 / 12 / 1 |
| 475 Material Transfer'ın sahipleri | 6 gerçek kullanıcı hesabı, `Administrator` **0** |

Yani **hook anjan'da tek bir malzeme talebi üretmemiş.** 488'in tamamı elle girilmiş
(en eskisi 2026-03-14, en yenisi bugün 09:07). İki sebep birlikte çalışıyor: hook
yalnız `planned_start_date >= yarın` ise ateşliyor (`manufacturing.py:2117-2118`) ve
emirlerin çoğu aynı gün açılıyor; ayrıca `mr.material_request_type` 2026-08-26'ya
kadar geçersiz bir değer (`"Transfer"`) taşıyordu, yani `insert` patlıyordu — D8'in
kendi yorumu bunu anlatıyor (`manufacturing.py:2128-2133`). Düzeltme iki gün önce
girdi ve o günden bu yana da tek kayıt üretmedi.

Bu, 1c'nin durumunu KISMEN'den **YOK**'a taşır: ne ekran var, ne de backend'in
ürettiği bir şey.

Ara ölçüm olarak "hook'un gerçek payı 475" de yanlıştı — 475 sayısı MR *tipini*
sayıyor, hook imzasını değil.

## Prod ölçümleri (anjan, salt-okunur, 27–28.08)

| Ölçüm | Değer | Ne söylüyor |
|---|---|---|
| Manufacture girişi | 3 725 | üretim kaydediliyor |
| …`process_loss_qty > 0` | **0** | fire hiç kaydedilmiyor |
| Downtime Entry | **0** | duruş hiç kaydedilmiyor |
| Workstation / WO Op / BOM Op / Job Card | **0 / 0 / 0 / 0** | rota katmanı hiç kullanılmıyor |
| Gönderilmiş iş emri | 3 789 | 28.08 öğleden sonra; sabah 3 787'ydi — sayı akıyor |
| …`operator` atanmış | 13 | |
| …`packaging_operator` atanmış | **0** | rol ataması pratikte kullanılmıyor |
| `Material Consumption for Manufacture` fişi | **0** | rol bazlı tüketim yolu hiç kullanılmamış (her docstatus) |
| Aktif kalem / `custom_operator_role` dolu | 866 / **0** | iki-operatör ön koşulu 3 hâlâ açık |
| Hook'un ürettiği Material Request | **0** | yukarıdaki 1c düzeltmesi |
| Girişleri yapan ilk iki hesap | 3 688 / 3 725 | iş, operatör ekranından değil **Desk'ten yönetici eliyle** giriliyor |

## Bu turda kapanan iş

- **Rol kapsamı.** `work_order_detail` bir operatöre yalnız kendi rolünün satırlarını
  veriyordu ama iki operatör adını da filtresiz gönderiyordu — diğer rol, "üzerinde iş
  olmayan bir aşamaya atanmış kişi" gibi, yani yanlış kurulmuş BOM şeklinde görünüyordu.
  `manufacturing.py` artık `items_scoped_to_role` yolluyor; `workOrderStages.js:48,63`
  bunu `itemsHidden`'a çeviriyor.
- **Kanıt:** `test_wo_role_scoping_integration` 43 test, `test_wo_operator_roles` 22
  test — bench'te, canlı DB ile, hepsi yeşil (28.08).
- **Malzeme hazırlığı float düzeltmesi:** `composables/materialReadiness.js`, epsilon +
  `settle()`.

## E1 ölçümü (28.08 akşamı) — soru sanıldığı gibi değil

"Operatörler kiosk'u reddetti mi, yoksa hiç ulaşamadı mı?" diye ölçüldü. **İkisi de değil.**

| Ölçüm | Sonuç |
|---|---|
| İş emrine `operator` olarak atanan hesap | 5 (`alikxan199225`, `qwerty00…03`) |
| …hepsi var, etkin, giriş yapmış mı | **evet** — `qwerty00` ve `qwerty03` en son **27.08 19:39–19:40** |
| …90 günlük aktivite kaydı | `qwerty03` 76 satır — gerçekten aktif |
| Kiosk rotasında rol kapısı (`/manufacturing/line`) | **yok** — giriş yapan herkes erişebilir |
| `Line A Operator` rolünü kod okuyor mu | **hayır** — depoda yalnız eski UAT kanıt JSON'larında geçiyor |
| …bu rolü kim taşıyor | 5 hesap: Zafar, Odilbek ve iki geliştirici. **Sahada kimse yok.** |

Yani erişim engeli yok, rol engeli yok, ret de yok. Asıl tablo üretim kaydını **kimin
yazdığında**:

| Hesap | Manufacture girişi | Son giriş | Rolleri |
|---|---|---|---|
| `ashuraliyevbegzod867` | **3 349** | **bugün 10:47** | Stock/Manufacturing/System Manager |
| `alikxan199225` | 507 | 26.08 | Manufacturing Manager (+ 3 iş emrinde operatör) |
| `xalilovodilbek01` | 32 | 26.04 | (geliştirici) |
| `qwerty01` / `qwerty03` / `qwerty00` / `qwerty02` | 7 / 7 / 4 / 1 | 04–07.2026 | Manufacturing User |

**3 856 girişin 3 856'sı iki Desk hesabından.** En büyük üretici
(`ashuraliyevbegzod867`, tüm girişlerin %90'ı, bugün hâlâ yazıyor) **hiçbir iş emrinde
operatör olarak atanmamış**. Atanmış olan `qwerty0X` hesapları Mart–Temmuz arasında
toplam 19 giriş yapıp durmuş.

### Bunun bıraktığı soru

Tüm üretim verisi tek klavyeden giriyor. İki okuması var ve ikisi zıt iş gerektiriyor:

1. **Sahada gerçekten tek kişi var** → kiosk, çoklu operatör, vardiya devri, operatör
   başına KPI — hepsi olmayan bir organizasyonu varsayıyor. İki paket de küçültülmeli.
2. **Sahada operatörler var ama verileri kâğıttan tek kişi giriyor** → bu tam olarak
   kiosk'un çözdüğü darboğaz, ve iki paket de doğru işi hedefliyor; eksik olan yayılım.

Ölçüm bu ikisini ayırt edemez — `ashuraliyevbegzod867`'un bir veri giriş görevlisi mi
yoksa üretimi tek başına yürüten kişi mi olduğu **organizasyon bilgisi**, veri değil.
Zafar'ın cevaplaması gereken tek soru budur; 1b, 1c, fire/duruş kataloğu ve
operator-dashboard'un geleceği bu cevaba bağlı.

### Yan bulgu: ölü rol — **silindi 2026-08-28**

`Line A Operator` prod'da duruyordu, beş geliştirici/yönetici hesabında, ve hiçbir kod
onu okumuyordu. Zafar'ın talimatıyla silindi.

Silmeden önce ölçüldü: rol sekiz kiracıdan **yalnız anjan'da** vardı, **0 DocPerm**,
**0 Custom DocPerm**, 0 workflow referansı, ve `Has Role` satırlarının hepsi `User`
ebeveynliydi (Role Profile yok). Yani hiçbir yere izin vermiyordu; kaldırılması
kimsenin erişimini değiştirmedi. Depoda fixture olarak tanımlı olmadığı için `migrate`
geri getirmez.

Rol kaldırılan beş hesap — geri almak gerekirse: `zvictory2001@gmail.com`,
`brightik1@gmail.com`, `hikmatulloh@mail.com`, `xalilovodilbek01@gmail.com`,
`zafar@stable.uz`.

Silme sırasında ilgisiz bir hata ortaya çıktı ve `docs/backlog.md`'ye yazıldı: `uzc`
dili sekiz kiracıda da `Language` kaydı olarak yok, bu yüzden `language="uzc"` taşıyan
altı hesabın `User` belgesi hiçbir doğrulanmış yoldan kaydedilemiyor. Rol, bu yüzden
`User.save()` yerine `Has Role` satırları doğrudan silinerek kaldırıldı.

## KARAR — 2026-08-28 akşamı, Zafar

Soru soruldu, cevap geldi: **sahada operatörler var, verilerini kâğıttan tek kişi
giriyor.** Yani kiosk doğru darboğazı hedefliyor; eksik olan kod değil yayılım.
İki paketin de sorusu buydu, ikisi de bu cevaba bağlanır.

Bunun bağladığı şeyler:

- **1b kanban ve 1c planlama meşru** — "tek kişi var" okuması geçerli olsaydı
  yazılmamaları gerekiyordu.
- **Fire/duruş kataloğu meşru** — 0 Downtime Entry bir organizasyon eksikliği
  değil, kaydedecek ekranın olmaması.
- **operator-dashboard'un backend sorusu açık kalır** ve artık gerçek bir soru.

### Uygulanan — 1a (`f227f62`)

Vardiya defterine üç filtre: **hat** (`wip_warehouse`), **operatör** (iki rol de),
**tarih aralığı** (iki uçtan kapsayıcı). Üçü de ölçülerek seçildi:

| Boyut | Neden bu kolon |
|---|---|
| hat | anjan'da 0 Workstation var; beş `WIP.n-Bo'lim` bölümü 557 emir taşıyor. Workstation'a bağlanan bir filtre hiçbir şeye bağlanmış olurdu. |
| operatör | `operator` **OR** `packaging_operator` — ikisi aynı emirde çalışıyor; tek kolon okuyan filtre paketleme operatörüne "işin yok" derdi. |
| tarih | `planned_start_date` datetime; bitiş `< ertesi gece yarısı` karşılaştırılıyor, yoksa "bugünü" soran vardiya sorumlusuna boş liste dönerdi. |

Where-clause `_wo_filters.build_work_order_filters`'a çıktı — filtre listesinde
asıl risk sorgunun *genişlemesi*: boş liste görünür bir hata, uzun liste yoğun bir
ekranda iyi bir gün gibi okunur. Kendi-satırların guard'ı filtre olarak değil
guard olarak geçiyor ve testler her kombinasyonda ayakta kaldığını pinliyor.

### Uygulanan — 1d, ve neden ağaç çizilmedi (`a78c7ac`)

Soyağacı ağacı **çizilmedi**, ve bu bir eksik değil karar. Ölçüm:

| Ölçüm (anjan, salt-okunur) | Değer |
|---|---|
| Malzeme transfer satırı | 23 851 |
| …`batch_no` taşıyan | **0** |
| Gönderilmiş iş emri | 3 789 |
| …`custom_batch_no` taşıyan | **0** |
| Başka bir emrin mamul deposundan gelen tüketim satırı | **23 848** |
| Kalem başına aday üretici emir | ort. **14,9** · en fazla **171** |

Yapı gerçek — neredeyse her girdi içeride üretilmiş — ama hangi emrin ürettiğini
söyleyecek bağ yok. En yakın önceki emri seçerek ağaç çizilebilirdi ve **çözülmüş
bir zincirle birebir aynı görünürdü**. O ağacın okunduğu an geri çağırmadır, ve
tahmin eden bir izlenebilirlik bilmediğini söyleyenden kötüdür: tahmin aramayı
bitirir. Bu yüzden panel kökeni işaretliyor, adayları sayıyor, **ebeveyni asla
adlandırmıyor** — aday sayısı 1 olduğunda bile, çünkü o "şimdilik 1"dir ve o kalem
için ikinci emir açıldığı gün, etiket basıldıktan sonra yalan söylemeye başlar.

Durumu değiştiren şey parti kaydetmek, ve `set_wo_batch` / `suggest_wo_batch`
kiosk'tan beri **vardı** — yalnız kiosk'tan erişilebiliyordu. Bu sayfayı açan
yönetici, formu hiç görmemiş olan kişiydi. Artık görüyor; eksik parti boş bir alan
değil sarı bir uyarı rozeti olarak duruyor (`wo_genealogy` 3 789 emrin hepsinde boş
olan bir kolonu döndürüyordu).

Operasyon kartlarını öldüren ölçümün aynısı, ters sonuç: orada yapı da yoktu,
burada yalnız kayıt yok.

## Kalan iş ve neyi beklediği

| Yön | Durum | Bekleyen |
|---|---|---|
| 1a | **BİTTİ** (`f227f62`) | — |
| 1d | **BİTTİ** — parti yakalama + dürüst köken | ağaç, parti kaydı birikene kadar |
| 1b kanban | YAPILMADI | kararla açıldı, sırada |
| 1c planlama | YAPILMADI | **önce hook düzeltilmeli** — `work_order` dolu MR = 0/488 |
| Fire/duruş | YAPILMADI | kararla açıldı |

## Eski engel kaydı — kapandı

Ekranların hepsi çalışıyor; kullanan yok. 3 725 üretim girişinin 3 688'i iki yönetici
hesabından, fire ve duruş sıfır, paketleme operatörü hiç atanmamış.

**Karar gereken:** operatörler kiosk'a alınacak mı, yoksa yöneticinin Desk akışı kabul
edilip o mu iyileştirilecek? Fire/duruş kataloğu, 1b kanban ve 1c planlama ekranı — üçü
de bu cevaptan sonra anlam kazanıyor. Cevap "yönetici" ise 1b ve 1c yazılmamalı.

Bu soru, `operator-dashboard` paketinin sorusuyla (bkz.
`2026-08-28-operator-dashboard-durum.md`) **aynı sorudur** ve birlikte cevaplanmalıdır.
