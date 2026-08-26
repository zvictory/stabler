# Runbook — Work Order iki-operatör özelliğinin deploy ön koşulları

> **Neden bu dosya var:** Bu özelliğin kodu `main`'de ve testleri yeşil, ama
> **kodu deploy etmek tek başına hiçbir şey yapmıyor.** Dört adet kod-dışı adım
> var ve bunlardan biri atlanırsa sistem hata vermiyor — sessizce yanlış sayı
> üretiyor. Bir `bench migrate` ile bitecek bir iş sanılıp yarım bırakılması,
> tam da bu dosyanın engellemek için yazıldığı şey.
>
> İkinci sebep: 2026-08-26'da v97, v98 ve v99'un **hiçbir sitede hiç migrate
> edilmemiş** olduğu keşfedildi. Özellik haftalardır yazılıyordu ve prodüksiyonda
> uykudaydı; her test zarif-bozulma yolunu koşuyordu, o yüzden süit de yeşildi.

**Operatör:** Zafar. Prodüksiyon deploy'u her zaman açık onay gerektirir.

---

## ⛔ Şu an deploy edilemez

2026-08-26 uçtan uca doğrulaması (`genesis-test.local`, gerçek rollerle, gerçek
stok fişleriyle) dört adet P0 buldu. Dördü de **sıradan kullanım yolunda**
tetikleniyor, hatalı kullanımda değil.

| Kod | Ne oluyor | Tetikleyici |
|---|---|---|
| D1 | Finish, iki-rol guard'ını atlıyor; ilk basan diğerinin malzemesini üstüne alıyor | İki operatör farklı hızda çalışınca |
| D2 | `consumed_qty` ikiye katlanıyor | `material_consumption` **kapalıyken** — yani varsayılanda |
| D7 | Ölçülen kişi kendi sapma barajını yeniden yazabiliyor, her iki rol için | İsteyen istediğinde |
| D8 | İleri tarihli üretim emri gönderilemiyor | İleri tarih **+** en az bir kalem WIP'te eksik |

D8'in bu özellikle ilgisi yok — üstüne inşa edilen zeminde vardı
(`material_request_type = "Transfer"` geçersiz bir değer, `hooks.py`'de Work Order
`on_submit`'e bağlı). Ama modülün sıradan planlamayı desteklememesi anlamına
geliyor, o yüzden aynı kapıdan geçiyor.

D8'in ikinci koşulu kulağa dar geliyor ama değil: transfer adımı malzemeyi WIP'e
emir **başlarken** taşıyor, **planlanırken** değil. Yani planlama anında her
kalem zaten eksik — biri depoyu elle önceden doldurmadıkça. Pratikte her ileri
tarihli emirde sağlanıyor. Kesin koşulu da yazıyorum çünkü depoyu önceden
doldurulmuş bir örnekle test eden biri emrin gönderildiğini görüp bu dosyanın
yanıldığını sanabilir.

Kancanın kendi içinde `if not doc.wip_warehouse: return` diye üçüncü bir çıkış
var ama **ulaşılamaz**: ERPNext `validate_warehouse()`'u `on_submit`'ten çağırıp
`wip_warehouse`'u zorunlu kılıyor (`work_order.py:786-793`). O kontrolün iki
bypass'ı var — `skip_transfer` ve `track_semi_finished_goods` — ve Stabler
ikisini de hiçbir yerde set etmiyor, yani her emirde doctype varsayılanı 0.
Dal **ERPNext'in tasarımı gereği değil, bizim yapılandırmamız gereği** ölü: biri
ileride `skip_transfer` desteği eklerse uyanır ve tetikleyici şekil değiştirir.

Yönetici bu duvara **kaydederken değil, gönderirken** çarpıyor. Yani bedeli bir
tıklama değil, doldurduğu formun tamamı.

**D8'in yapılandırmayla geçici çözümü yok.** `skip_transfer = 1` gerçekten
D8'den kaçıyor — ölçüldü — ama mekanizması şu: ERPNext `skip_transfer` açıkken
`wip_warehouse`'u **siliyor**, kanca da boş depoda erken dönüyor. Yani iki koşul
bağımsız değil, biri diğerini kuruyor. Ve `skip_transfer` "Material Transfer for
Manufacture adımı hiç olmasın" demek — oysa iki-operatör tasarımının tamamı o
transferin üstünde duruyor: `_assert_roles_are_both_or_neither` o purpose'a
bağlı, ve rol bazlı yazım malzemenin WIP'te durduğunu varsayıyor. **D8'den kaçan
tek yapılandırma, bu özelliği kapatan yapılandırma.** Düzeltilmesi gerekiyor,
etrafından dolaşılması değil.

Bir uyarı daha, aynı kod bloğu hakkında: `"Transfer"` → `"Material Transfer"`
düzeltmesi **tek başına yapılırsa açık yaratır.** O literal şu an iptal
döngüsünün çalışmasını engelleyen tek şey; düzeltildiği anda döngü, MR iptal
yetkisi *olan* yöneticiler için çalışmaya başlar ve miktar düzeltmek yan etki
olarak onaylanmış satın alma belgesi iptal eder — üstelik oradaki
`except Exception: pass` her hatayı yutar. Literal, yutulan exception ve loglama
aynı commit'te gitmeli.

**Kapı:** dördü de düzelmeden ve uçtan uca doğrulama tekrar koşup temiz çıkmadan
deploy yok. `make check` bu iş için yeterli kanıt değil — hepsi DB davranışı.

---

## Ön koşul 1 — Migrate

```bash
bench --site <site> migrate
```

Üç patch: `v97_work_order_packaging_operator`, `v98_item_operator_role`,
`v99_work_order_finish_draft`. Üçü de idempotent, üçü de `table_exists` ile
korunuyor.

Doğrulama — `has_column` tablo yoksa `False` **döndürmez**, `TableMissingError`
fırlatır, o yüzden önce tabloyu sor:

```bash
bench --site <site> execute frappe.db.table_exists --args '["Work Order"]'
```

`True` ise `Work Order.packaging_operator`, `Work Order.custom_finish_draft` ve
`Item.custom_operator_role` kolonlarının varlığını kontrol et. `False` ise o site
bu doctype'ı taşımıyor ve doğrulanacak bir şey yok — bu bir başarısızlık değil.

## Ön koşul 2 — `material_consumption` AÇIK olmalı

`Manufacturing Settings` → **Allow Continuous Material Consumption**.

**Bu opsiyonel bir tercih değil, doğruluk şartı.** ERPNext bu ayar kapalıyken
`stock_entry.py` içinde `get_unconsumed_raw_materials` yerine
`get_bom_raw_materials` seçiyor. Sonuç: rol bazlı tüketim fişleri düzgün kesilmiş
olsa bile, Finish aynı satırları **tekrar** listeliyor ve `consumed_qty` ikiye
katlanıyor. Hiçbir hata yükselmiyor.

2026-08-26 kontrollü ölçümü: iki operatör de doğru yazdı (20 / 10), ayar
kapatıldı, finish edildi → `consumed_qty 40 / 20`, `required_qty 20 / 10`. Sapma
paneli iki operatörü de yapmadıkları %100 aşımla suçladı. Ayar açık bırakılan
kontrol grubu temiz çıktı.

Ayar **kapalı olarak geliyor.** Yeni bir tenant'ta ilk yapılacak iş bu.

## Ön koşul 3 — Item rolleri doldurulmalı

`Item.custom_operator_role` → `Production` (döküm) veya `Packaging` (paketleme).

v98 bilerek **hiçbir varsayılan atamadı ve hiçbir şey doldurmadı.** Sebebi
patch'in kendi docstring'inde yazılı: bu bilgi veritabanında yok, sahadaki
insanların kafasında. Ölçü birimine göre tahmin etmek denendi ve yanlış —
kullanımdaki 112 malzemenin 55'i yanlış operatöre düşüyordu. Şeker kg cinsinden
ve dökümün, ambalaj filmi de kg cinsinden ve paketlemenin.

Boş rol kaybolmuyor: o satır kimsenin operatör listesine düşmüyor, vardiya
amirinin listesine düşüyor ve kiosk onu sesli sayıyor. Yani eksik doldurmak
sessiz bir hata değil, görünür bir eksik.

## Ön koşul 4 — Vardiya amirine iki rol birden

**Karar (2026-08-26, Zafar):** vardiya amiri hem `Manufacturing Manager` hem
`Manufacturing User` rolünü alır.

Sebep: `_is_mfg_manager()` `Manufacturing Manager` rolünü kabul ediyor, ama
ERPNext'in Work Order DocPerm'inde o rol için write yetkisi **yok** — write
`Manufacturing User`'a verilmiş. Sadece `Manufacturing Manager` taşıyan biri
`list_work_orders` ham SQL kullandığı için **tüm panoyu görüyor**, bir satıra
tıklıyor ve `PermissionError` alıyor. Atama endpoint'leri ve `work_order_detail`
o kullanıcı için ölü.

Alternatif — Work Order doctype'ına `Manufacturing Manager` izni eklemek — yedi
tenant'ı birden etkileyeceği için reddedildi.

---

## Deploy sonrası duman testi

Onay geldiğinde, canlıda şu sırayla:

1. Yönetici bir emre iki operatörü de atar.
2. Yarı atanmış bir emirde transfer denenir → **reddedilmeli**, ve mesaj eksik
   rolü adıyla söylemeli.
3. Malzeme transferi yapılır.
4. Her operatör kendi panosunu açar → **sadece kendi rolünün** satırlarını
   görmeli. Diğerininkini görüyorsa Ön koşul 3 eksiktir.
5. Her operatör kendi malzemesini yazar. Oluşan fişte başlıktaki `to_warehouse`
   ve her satırdaki `t_warehouse` **boş olmalı** — tüketilen malzeme hiçbir
   depoya girmez.
6. Emir bitirilir, sapma paneli açılır.

5. adım bu özelliğin ana riski: ERPNext'in `make_stock_entry`'si tüketim fişinin
başlığına `fg_warehouse` yazıyor. Boş olmayan bir `t_warehouse` görürsen dur —
ham süt mamul deposuna giriyor demektir.

---

## Bloke — bunlar anjan'dan veri bekliyor

Kod tarafı değil. `docs/uat/2026-08-24-wo-two-operators/faz0-anjan-anketa.md`
anketi **henüz gönderilmedi** (2026-08-26).

- **Duruş sebepleri kataloğu** — mockup'taki 16 kod uydurma. Gerçek liste anketle
  gelecek.
- **Kanban panosu** ve **hat × zaman planlama** — ikisi de "hat" ekseni üstüne
  kurulu. Anketin 1. bloğu gelmeden çizilecek bir şey yok.
