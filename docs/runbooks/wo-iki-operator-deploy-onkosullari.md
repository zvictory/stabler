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

**Geçiş kararı (2026-08-27, Zafar):** geçmiş iş emirlerine operatör atanmayacak.
Özellik kesim tarihinden sonra açılan emirlerde başlar. Bu karar üç ön koşulun
kapsamını da değiştirdi — ölçülmüş yeni kapsam her birinin başında.

---

## Durum — kod deploy edildi, özellik uykuda

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

### Nerede duruyoruz — 2026-08-27

- Dal `main`'e girdi (`4d2ff67`) ve **prodüksiyona deploy edildi.** v97/v98/v99
  `patches.txt:101-103`.
- **Ön koşul 1 kapandı** (site site ölçüldü). **Ön koşul 4 anjan'da zaten
  sağlanmış** çıktı. **Ön koşul 2 ve 3 açık.**
- Özellik anjan'da **hiç çalışmıyor, ve bu güvenli hâl:** `material_consumption`
  kapalı olduğu sürece D2 guard'ı rol bazlı düşümü olan Finish'i tümüyle
  reddediyor. Deploy edilmiş olmak kullanılıyor olmak değildir — bu dosyanın
  baştaki uyarısı tam olarak buydu.
- Duman testinin 11 adımının **hiçbiri canlıda koşulmadı**; hepsi `genesis-test`
  verisi üzerinde ölçüldü.

## Geçiş kararı — yalnız yeni emirler

**2026-08-27, Zafar.** Geçmiş iş emirlerine operatör atanmayacak.

Sonuçları:

- **Geriye dönük doldurma yok.** 3741 tamamlanmış emir operatörsüz kalır ve öyle
  kalmalı. Sapma paneli onlar için anlamlı değil; okunmamalı.
- **Sapma paneli kesim tarihinden itibaren okunur.** Panelin iki-operatör ekseni
  ancak iki rolün de atandığı emirlerde vardır.
- **Ön koşul 3'ün kapsamı 866'dan 81'e indi** (aşağıda ölçüm).
- **Arada kalan 31 emir: eski sayılmıyor.** *(Karar 2026-08-27, Zafar.)* anjan'da
  31 adet gönderilmiş ama başlanmamış emir var; hepsi boş kabuk (transfer 0,
  üretim 0). Bunlar **başlatıldıkları anda operatör alacak** — toplu geriye dönük
  doldurma yok, iptal edip yeniden açma da yok. Atama `frappe.db.set_value` ile
  yazıldığı için (`manufacturing.py:1616-1619`) gönderilmiş emre de yapılabilir;
  `docstatus` kontrolü yok, o yüzden bu teknik olarak mümkün.

  Sınır burada net olmalı: **"eski" = başlamış veya bitmiş emir**, "yeni" =
  malzemesi henüz cehe verilmemiş emir. Kesim tarihi değil, emrin durumu
  belirliyor. Sebebi: bir emre operatör atamak ancak o operatörün yazacağı bir
  malzeme kaldıysa anlamlı; transferi çoktan yapılmış bir emirde atama, kimsenin
  yazmadığı bir role isim yazmaktır ve sapma panelini yalancı yapar.

## Ön koşul 1 — Migrate  ·  **kapandı (2026-08-27, ölçüldü)**

Prod'daki 21 sitenin stabler kurulu olan 8'inde — `anjan, dts, horeca, laminor,
mikas, msa, smartbox, zuma` — üç patch de Patch Log'da ve üç kolon da yerinde
(`Work Order.packaging_operator`, `Work Order.custom_finish_draft`,
`Item.custom_operator_role`). Kalan 13 sitede stabler kurulu değil; doğrulanacak
bir şey yok. Aşağıdaki prosedür **yeni açılan siteler** için geçerliliğini
koruyor.

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
anjan'daki güncel değer: **kapalı** (`material_consumption = 0`,
`backflush_raw_materials_based_on = "BOM"`).

**Bu opsiyonel bir tercih değil, doğruluk şartı.** ERPNext bu ayar kapalıyken
`stock_entry.py` içinde `get_unconsumed_raw_materials` yerine
`get_bom_raw_materials` seçiyor. Sonuç: rol bazlı tüketim fişleri düzgün kesilmiş
olsa bile, Finish aynı satırları **tekrar** listeliyor ve `consumed_qty` ikiye
katlanıyor. Hiçbir hata yükselmiyor.

2026-08-26 kontrollü ölçümü: iki operatör de doğru yazdı (20 / 10), ayar
kapatıldı, finish edildi → `consumed_qty 40 / 20`, `required_qty 20 / 10`. Sapma
paneli iki operatörü de yapmadıkları %100 aşımla suçladı. Ayar açık bırakılan
kontrol grubu temiz çıktı.

### 2026-08-27 — anjan'ın verisiyle runbook'un çeliştiği yer çözüldü

Çelişki şuydu: genesis-test'te anjan ile birebir ayarlarla, ayar kapalıyken
kısmi transfer tam BOM tüketimi üretiyordu (150 transfer → 200 tüketim), ama
anjan'ın canlı verisinde tüketim transfere eşitti — üstelik Finish fişlerinde
BOM'da hiç olmayan malzemeler vardı.

Popülasyon ölçümü — anjan, son 90 gün, Manufacture fişi olan **2010** iş emri:

| Ölçüm | Sonuç |
|---|---|
| Finish'ten önce transfer yapılmayan emir | **0 / 2010** |
| Tüketim = transfer (kalem kalem, miktar miktar) | **1919** (%95,5) |
| Tüketim ≠ transfer | **91** (%4,5) |
| Transfer edilmemiş bir kalemin Finish'te görünmesi | **hiç** |
| Transfer edilenden **fazla** tüketim | **hiç** |

91 farkın hepsi aynı yönde: kalem kümeleri birebir aynı, yalnızca daha **az**
tüketilmiş (45 → 40, 191 → 190, 1250 → 125). Yani artan malzeme, BOM'a tırmanma
değil.

Açıklama: anjan **her zaman önce transfer ediyor**, ve Finish fişi BOM'u değil
**transferi** yansıtıyor — operatörün yaptığı ikameler dahil. `MFG-WO-2026-04161`
bunun temiz örneği: BOM'daki R043/R049/R097 yerine R013/R251/r256/"masla Axirin"
transfer edilmiş, Finish tam o dördünü tüketmiş. `consumed_qty`'yi ikiye katlayan
BOM'dan-listeleme yolu, anjan'ın bugün kullandığı akışta **hiç uğranmıyor.**

**Geriye kalan gerçek bilinmeyen:** o 2010 emrin hiçbirinde rol bazlı tüketim
fişi yok — o fişler özelliğin kendisiyle geliyor. Ayar kapalıyken "rol bazlı
düşüm + Finish" kombinasyonunun anjan'da ne yapacağı hâlâ ölçülmedi. Ama bu
kombinasyonu D2 guard'ı zaten reddediyor, yani sessizce bozulamaz.

### Nasıl kapatılır — artık veritabanı kopyası gerekmiyor

Önceki plan "anjan DB'sinin bir kopyası üzerinde A/B" idi ve bu yüzden bloke
duruyordu. "Yalnız yeni emirler" kararı testi ucuzlattı, çünkü ayarı açmanın
çarpma alanı ölçülebilir hâle geldi:

| anjan iş emri durumu | Adet | Ayardan etkilenir mi |
|---|---|---|
| Completed / Cancelled / Closed | 4171 | hayır — kapalı |
| Not Started (transfer 0, üretim 0) | 31 | hayır — boş kabuk |
| Draft | 6 | hayır — gönderilmemiş |
| **In Process, malzeme cehte** | **1** | **evet** |

Havadaki tek emir: `MFG-WO-2026-01168` (`Smes NONLI STAKAN`, 2500 transfer
edilmiş, 2026-04-27'den beri `produced_qty = 0`). Dört aydır hareketsiz.

### Ne yapıldı — 2026-08-27 17:53

Ayar **açıldı** (`material_consumption 0 → 1`, anjan; `Manufacturing Settings`
`modified = 2026-08-27 17:53:25`). Zafar'ın açık onayıyla ve komutu Zafar
çalıştırarak — prod'a yazma ajana kapalı.

Planın iki adımı **bilerek atlandı**, ikisi de yazmayı azaltmak için:

- **Sentetik test emri oluşturulmadı.** İlk plan "tek bir yeni emri baştan sona
  koştur" diyordu. Bu, canlı stok defterine sahte hareket yazmak demek; iptal
  edilse bile iptal edilmiş belge ve değerleme izi kalır. Gerek de yok: anjan
  günde ~18 emir açıyor ve 7 günlük ortalamayla **saatte 0,69 Manufacture fişi**
  gönderiyor — yani ~1,5 saatte bir. **Bir sonraki gerçek emir testin kendisi.**
- **`MFG-WO-2026-01168` kapatılmadı.** Kapatmak 2500 birimi yarı mamulde asılı
  bırakır; bu muhasebe sonucu olan bir iş kararı, teknik bir adım değil. Ölçüm de
  gerektirmiyor: transfer = BOM olduğu için o emir bir gün bitirilirse ayar açık
  da kapalı da olsa aynı miktarı tüketir.

### Doğrulama — açık uç

Ayar açıldıktan sonra **biten ilk emirler** şu üç ölçüte karşı okunacak; taban
çizgisi yukarıdaki 2010 emirlik tablo:

| Ölçüt | Taban (ayar kapalıyken) | Bozulursa |
|---|---|---|
| Tüketim = transfer | 1919 / 2010 | ayarı geri kapat |
| Finish'te transfer edilmemiş kalem | **hiç** | ayarı geri kapat |
| Transfer edilenden fazla tüketim | **hiç** | ayarı geri kapat |

Geri alma tek komut — aynı `set_value` çağrısında `1` yerine `0`, ardından
`bench --site anjan.erpstable.com clear-cache`.

Üçü de bozulmazsa Ön koşul 2 kapanır ve sıra Ön koşul 3'e geçer.

Ayar **kapalı olarak geliyor.** Yeni bir tenant'ta ilk yapılacak iş bu.

## Ön koşul 3 — Item rolleri doldurulmalı

`Item.custom_operator_role` → `Production` (döküm) veya `Packaging` (paketleme).

**Durum 2026-08-27: 866 aktif kalemin 0'ında dolu.**

"Yalnız yeni emirler" kararı kapsamı küçültüyor — geçmişte kullanılıp artık
üretilmeyen kalemin rolüne gerek yok. Ölçülmüş kümeler (anjan):

| Küme | Adet |
|---|---|
| Aktif kalem kataloğu | 866 |
| Tüm zamanlarda WO'da tüketilmiş ayrık kalem | 394 |
| Son 90 günde tüketilmiş ayrık kalem | 324 |
| Son 30 günde üretilen 132 ürünün BOM'larındaki ayrık kalem | 230 |
| **Şu an açık 32 emrin BOM'larındaki ayrık kalem** | **81** |

Yani "başlamak için 866 satır" değil, **81 satır** — tek bir ürün hattıyla
başlanacaksa daha da az. 31 emrin eski sayılmaması kararı (yukarıda) bu 81'i
**başlangıç kümesi olarak sabitliyor**: rolü doldurulması gereken ilk şey, o
emirler başlatıldığında karşılaşılacak kalemler. Rol alanı `frappe.db.set_value` ile yazıldığı için
gönderilmiş emirlerde de doldurulabilir; hepsini önden doldurmak şart değil,
ürün ürün genişletilebilir.

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

**Durum 2026-08-27: kapandı — sekiz tenant'ın hepsi ölçüldü, hepsi temiz.**
`Manufacturing Manager` rolü taşıyıp `Manufacturing User` taşımayan **aktif
kullanıcı hiçbir sitede yok.**

| Site | Mfg Manager | Eksik rol | Work Order |
|---|---|---|---|
| anjan | 15 | 0 | 4181 |
| dts | 4 | 0 | 0 |
| horeca | 2 | 0 | 0 |
| laminor | 2 | 0 | 0 |
| mikas | 5 | 0 | 0 |
| msa | 6 | 0 | 0 |
| smartbox | 4 | 0 | 0 |
| zuma | 3 | 0 | 0 |

Sağ kolon ayrıca şunu söylüyor: **üretim modülünü bugün fiilen yalnız anjan
kullanıyor** — diğer yedi tenant'ta tek bir iş emri bile yok. Bu özelliğin
risk yüzeyi tek tenant. `Manufacturing Settings` zaten site başına ayrı olduğu
için Ön koşul 2'deki ayar denemesi de yalnız anjan'ı etkiler.

Yeni açılan tenant'ta bu kontrol yine yapılmalı — rol dağılımı devralınan bir
şey değil.

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

**Sıra bağımlılığı — bozmayın.** Adım 1–4 Ön koşul 3 doldurulmadan koşulamaz:
hiçbir kalemin rolü yokken 4. adım kesin başarısız olur, çünkü her satır
operatörün değil vardiya amirinin listesine düşer. Adım 5–11 ayrıca Ön koşul
2'yi bekler. Duman testinin tamamı bu iki ön koşula bağlı.

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
anketi **2026-08-27 itibarıyla hâlâ gönderilmedi.** Блок 1 (цеха/линии) cevapsız,
цех/линия/смена kolonları boş.

- **Duruş sebepleri kataloğu** — mockup'taki 16 kod uydurma. Gerçek liste anketle
  gelecek.
- **Kanban panosu** ve **hat × zaman planlama** — ikisi de "hat" ekseni üstüne
  kurulu. Anketin 1. bloğu gelmeden çizilecek bir şey yok.
