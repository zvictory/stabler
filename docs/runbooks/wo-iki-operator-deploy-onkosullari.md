# Runbook — Work Order iki-operatör özelliğinin deploy ön koşulları

> **Neden bu dosya var:** Bu özelliğin testleri yeşil, ama **kodu deploy etmek
> tek başına hiçbir şey yapmıyor.** Dört adet kod-dışı adım
> var ve bunlardan biri atlanırsa sistem hata vermiyor — sessizce yanlış sayı
> üretiyor. Bir `bench migrate` ile bitecek bir iş sanılıp yarım bırakılması,
> tam da bu dosyanın engellemek için yazıldığı şey.
>
> İkinci sebep: 2026-08-26'da v97, v98 ve v99'un **hiçbir sitede hiç migrate
> edilmemiş** olduğu keşfedildi. Özellik haftalardır yazılıyordu ve prodüksiyonda
> uykudaydı; her test zarif-bozulma yolunu koşuyordu, o yüzden süit de yeşildi.

**Operatör:** Zafar. Prodüksiyon deploy'u her zaman açık onay gerektirir.

---

## Durum — kod tarafı hazır, deploy onayı bekliyor

2026-08-26 uçtan uca doğrulaması dört P0 bulmuştu; sonraki turlarda üç tane daha
çıktı. 2026-08-27 itibarıyla aşağıdakilerin hepsi düzeltildi ve her biri
mutasyonla doğrulandı — düzeltmeyi geri al, tam bir test düşsün.

| Kod | Neydi | Commit |
|---|---|---|
| D1 | Finish iki-rol guard'ını atlıyordu | `238592a` |
| Part 3 | İlk basan, diğerinin malzemesini üstüne alıyordu | `7beeb77` |
| D2 | Ayar kapalıyken `consumed_qty` ikiye katlanıyordu | `e08dc1d` |
| D7 | Ölçülen kişi kendi ve diğerinin barajını yeniden yazabiliyordu | `cc5fec7` |
| D8/D9 | İleri tarihli emir gönderilemiyordu; MR iptali her hatayı yutuyordu | `ab3f770` |
| XSS | Kalem adı her operatörün ekranına script sokabiliyordu | `b509b1f` |
| D4 | Fire miktarı girmek Finish'i tamamen düşürüyordu | `5a0fa33` |

**Sapma paneli artık güvenilir girdiye sahip.** Daha önce değildi: `consumed_qty`
başkasının belgesi olabiliyordu (D1/D2), `required_qty` ölçülen kişi tarafından
düzenlenebiliyordu (D7). Üçü de kapandı.

D4 ölçüldüğünde beklenenden farklı çıktı: sessiz bir yanlış sayım değil, sert bir
ret. ERPNext `fg_completed_qty == mamul satırı + process_loss_qty` denkliğini
doğruluyor (`stock_entry.py:747`), yani fire yazıp mamul satırını tam bırakmak
Finish'i hiç geçirmiyordu. Bozuk hiçbir şey kaydolmuyordu — vardiya sadece
kapanamıyordu, ve tek çıkış yolu fireyi gizlemekti. Asıl sayıları bozan sürüm o.

D8 aylarca ayakta kaldı çünkü **bir test onu doğru diye iddia ediyordu.**
`test_tomorrow_wo_material_request_creation` Material Request'i tamamen mock'ladığı
için atama hiç doctype'a karşı doğrulanmıyor, sonra test bozuk değeri bekliyordu.
Yerine gerçek `insert` koyuldu; ayrıca canlı meta'dan seçenekleri okuyup doctype'ın
sunmadığı hiçbir literali kabul etmeyen ucuz bir kontrol eklendi.

### 2026-08-27 uçtan uca doğrulaması

`genesis-test.local`, gerçek rollerle, gerçek uç noktalardan, sonunda geri alındı
(`MFG-WO-2026-00008`: iki rol atanmış, malzeme WIP'te, paketleyici düşmüş,
dökümcü düşmemiş):

| Adım | Ölçülen |
|---|---|
| Ayar kapalı + rol bazlı düşüm var → Finish | Reddedildi, `Manufacturing Settings`'e yönlendirdi |
| Önizleme, dökümcü | `items=[PROBE-MILK]`, `sweep_risk=[]` |
| Önizleme, paketleyici | `items=[]`, `sweep_risk=[PROBE-MILK]` |
| Paketleyici, onaysız Finish | Reddedildi, kalemi **adıyla** söyledi |
| Dökümcü → paketleyicinin planı | Reddedildi |
| Dökümcü → kendi planı | Geçti; denetim: `PROBE-MILK: 20.0 -> 21.0` |
| Yönetici, fireyle Finish (8 sağlam, 2 fire) | `fg_completed_qty=10`, mamul satırı `8`, `process_loss_qty=2`, `produced_qty 0 → 8` |

Süit: `make check` yeşil, `test_manufacturing_kiosk` 67,
`test_wo_role_scoping_integration` 41, **sıfır atlama**.

Sıfır atlama önemli: bu dosya daha önce üç sessiz atlamayla koşuyordu.
`_a_submitted_work_order` sitedeki ilk gönderilmiş emri alıyordu — 100/100
tamamlanmış olanı — ve ERPNext bitmiş emir için stub kurmayı reddettiğinden
"ne tüketilmemiş kaldı" sorusu hep boş dönüyordu. Üç test yeşil tik verip hiçbir
şey kanıtlamıyordu; arkasında payı kalan 13 emir duruyordu.

### Hâlâ yapılmadı

- **Hiçbir şey push edilmedi.** Dal: `fix/wo-finish-posts-around-the-guard`.
- Yalnız `genesis-test.local` üzerinde doğrulandı. Diğer siteler koşulmadı.
- **Prodüksiyon deploy'u Zafar'ın açık onayını bekliyor.** Bir `bench restart`
  tüm stabler tenant'larını aynı anda etkiler.
- Aşağıdaki dört ön koşul **hâlâ geçerli** — hiçbiri kodla çözülmedi. Özellikle
  Ön koşul 2: D2 guard'ı bozulmayı engelliyor, ayarı gereksiz kılmıyor. Ayar
  kapalıyken rol bazlı düşüm zaten tümüyle reddediliyor, yani özellik çalışmıyor.

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

2026-08-27'de eklenen adımlar — hepsi canlıda tekrar edilmeli, çünkü hepsi
`genesis-test` verisi üzerinde ölçüldü:

7. Yalnız **bir** operatör malzemesini yazsın, diğeri beklesin. Yazan kişi Finish
   diyaloğunu açsın → **diğerinin kalemleri adıyla listelenmeli** ve onay kutusu
   tikli değilken Confirm **kapalı** olmalı. Tik atınca açılmalı ve geçmeli.
8. Bir operatör diğerinin bir kaleminde miktar değiştirmeyi denesin →
   **reddedilmeli**. Kendi kalemini değiştirsin → geçmeli, ve emrin zaman
   çizelgesinde `kalem: eski -> yeni` satırı görünmeli.
9. Fire miktarı girip bitir → **geçmeli**. `produced_qty` yalnız sağlam miktar
   kadar artmalı, fire kadar değil.
10. İleri tarihli bir emir gönder → Material Request `Material Transfer` türüyle
    oluşmalı; emir gönderilebilmeli.
11. `Manufacturing Settings`'te ayarı kapat ve rol bazlı düşümü olan bir emri
    bitirmeyi dene → **reddedilmeli**, ve mesaj hangi kutunun açılacağını
    söylemeli. Ayarı geri aç.

---

## Bloke — bunlar anjan'dan veri bekliyor

Kod tarafı değil. `docs/uat/2026-08-24-wo-two-operators/faz0-anjan-anketa.md`
anketi **henüz gönderilmedi** (2026-08-26).

- **Duruş sebepleri kataloğu** — mockup'taki 16 kod uydurma. Gerçek liste anketle
  gelecek.
- **Kanban panosu** ve **hat × zaman planlama** — ikisi de "hat" ekseni üstüne
  kurulu. Anketin 1. bloğu gelmeden çizilecek bir şey yok.
