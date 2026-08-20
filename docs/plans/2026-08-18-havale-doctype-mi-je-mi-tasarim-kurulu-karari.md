# Havale: arka planda Journal Entry mi, doctype mi? Fazla mı ileri gittik?

**Tarih:** 2026-08-18
**Soru (Zafar):** "Bu havale işleminde arka planda Journal Entry mi kullanıyoruz
yoksa doctype mi oluşturuldu? Stabler'da yaptığımız transfer ve gider gibi arka
planda JE, SPA'da arayüz yeterliydi. Biz fazla ileri gitmedik mi?"
**Kurul:** ERPNext/Frappe uzmanı · muhasebe · SPA/ürün · operasyon-risk (dört sandalye)
**Karar:** doctype yerinde. Fazlalık başka yerde — ve orada gerçek.

---

## 1. Cevap: ikisi de var, biri diğerinin yerine geçmiyor

Ölçüm (2026-08-18, `main` @ `30f9d04`):

| Katman | Nerede | Ne yapıyor |
|---|---|---|
| Journal Entry | `stabler/api/remittance_accounting.py:211` | `"doctype": "Journal Entry"` — para **gerçekten** ERPNext defterine JE olarak yazılıyor |
| Doctype | `Remittance Transfer` (37 satır / 32 gerçek alan, `istable=0`) | JE'nin **üstündeki** durum makinesi |
| Doctype | `Remittance Event` (7 alan) | denetim izi |
| Doctype | `Remittance Settings` (10 gerçek alan) | şirket başına ayar |
| Çocuk tablo | `Remittance Cash Desk Account` (`istable=1`) | ayarın satırları — bağımsız doctype değil |

Yani "JE mi doctype mi" bir seçim değildi: **JE muhasebe, doctype ise JE'nin
tek başına tutamadığı şey.**

## 2. Transfer/gider karşılaştırması — neden aynı kalıp yetmedi

Karşılaştırma doğru kurulmuş. `stabler/api/money.py:205` gerçekten
`frappe.new_doc("Journal Entry")` diyor ve transfer/giderin **kendi doctype'ı yok**.
3.071 satırın tamamı JE'nin kendisini CRUD'luyor. Kurul bu kalıbı havaleye
uygulamayı ciddi ciddi denedi ve dördü de aynı duvara çarptı:

**Bir transfer tek anlık bir olay; bir havale günlerce süren bir sözleşmedir.**

| | Transfer / gider | Havale |
|---|---|---|
| Ömür | Tek an — kaydedildi, bitti | Kayıt → (gün/hafta) → ödeme veya iade |
| JE sayısı | 1 | 2 (kayıt + ödeme, ya da kayıt + iade) |
| Aradaki durum | Yok | **Beş bağımsız eksen** (aşağıda) |
| Yükümlülük | Yok | Alıcıya karşı, kapanana kadar açık |
| Sır | Yok | Alım kodu — kriptolu, kilitlenebilir |

Havale'nin beş durum ekseni — ölçülen, hatırlanan değil:

```
operational_status    Draft → Registered → Paid Out / Refunded / Expired
accounting_status     Unposted → Posted / Reversed / Posting Error
verification_status   Not Issued → Active → Locked → Consumed → Expired
refund_status         None → Requested → Approved → Rejected → Completed
code_locked           0/1  (+ code_locked_at)
```

Bunları JE üzerinde taşımanın tek yolu Journal Entry'ye özel alan (Custom Field)
eklemekti. Kurulun ERPNext sandalyesi bunu tek cümleyle kesti:

> Journal Entry, yedi kiracının **her** muhasebe kaydının paylaştığı doctype.
> Oraya `verification_status` ve `code_locked` eklemek, havalesi olmayan altı
> kiracının her gider fişine havale alanı iliştirmek demek. Bir `bench restart`
> hepsini vurur. Havale kendi tablosunu hak ediyor; alternatifi havaleyi
> paylaşılan çekirdeğe bulaştırmaktı.

Muhasebe sandalyesi ikinci gerekçeyi ekledi: **iki JE arasında yükümlülüğün
kendisi bir kayıt olmak zorunda.** Kayıt JE'si "alıcıya borçluyuz" der, ödeme
JE'si onu kapatır. Arada, kimin neyi ne zaman alacağını tutan bir belge yoksa
"açık havaleler" diye bir liste üretilemez — ancak JE satırlarından geriye doğru
tahmin edilir. O tahmin, kasada nakit sayılan bir yerde yapılacak iş değil.

Operasyon sandalyesi üçüncüsünü: alım kodu bir sır. Sırrın kilit durumu,
kilitlenme zamanı ve kaç kez denendiği bir yerde durmak zorunda. JE'de duramaz.

**Dördü de aynı sonuca vardı: doctype fazlalık değil, gereklilik.** Fazla ileri
gidilen yer burası değil.

## 3. Fazlalık nerede: iki motor, sonlandırma tarihi yok

Asıl bulgu bu, ve dört sandalye birbirinden bağımsız olarak aynı yere işaret etti.

`Remittance Settings.remittance_engine` alanı `Legacy` / `V1` değerlerini
taşıyor, varsayılanı `Legacy`, `reqd: 1`. Bayrak baştan sona bağlı:
`patches.txt:94` → `patches/v90_remittance_engine_flag.py`,
`organization.py:314 remittance_engine_for()`, `stores/session.js:103-161`,
`router.js:591-606 REMITTANCE_V1_ROUTES`.

Yani bugün **yedi kiracının hepsi Legacy motorda** (`stabler/api/remittance.py`,
785 satır), V1 ise yanında tam olarak yaşıyor. Ölçülen yüzey:

| | satır | dosya |
|---|---|---|
| Python (api + doctype controller, testsiz) | 5.157 | 13 |
| Vue / JS | 8.201 | — |
| Test | 12.180 | — |

Bu rakamların bir kısmı iki kez ödeniyor — çünkü aynı iş iki motorda duruyor.
Bir bayrak, geçiş süresinin aracıdır; **geçiş tarihi olmadan bayrak kalıcı ikinci
bir kod tabanıdır.** Kurulun ortak tavsiyesi:

> Doctype'ı savunun, bayrağa tarih koyun. V1'in tüm kiracılarda açılacağı ve
> Legacy'nin silineceği tarih belirlenmeden bu modül küçülmez.

Not: `remittance_commands.py:153-158` alım kodu kriptosunu hâlâ `remittance.py`'den
alıyor — Legacy silinirken o parçanın taşınması gerekiyor, yoksa V1 de düşer.

## 4. Küçültme listesi — ve ölçümün üçünü nasıl çürüttüğü

Kurul doctype'ı savunurken beş alanı fazlalık saydı. Uygulamaya geçildiğinde her
biri tek tek ölçüldü ve **üçü ayakta kalmadı**. Bu bölüm kurulun listesini değil,
ölçümün sonucunu kaydeder — kurul kararı, kararın yanlış çıkan yarısını da
taşımak zorunda, yoksa aynı öneri altı ay sonra yeniden yapılır.

### Uygulandı

| Alan | Ne oldu |
|---|---|
| **`Remittance Event.company`** (ekleme) | `fe4b012` + patch v92. Bir alt sorgu koşulu (`_parent_company_condition`) ve bir özel `has_permission` silindi. İkincisi vardı çünkü paylaşılan yardımcı `doc.company` okuyup her event'te `None` bulur, boş-serbest dalına düşer ve **her satıra izin verirdi** |
| **`code_locked`** (silme) | `fe9f5e5` + patch v93. `_refuse_the_code` onu `verification_status = "Locked"` ile aynı `db_set`'te yazıyor, `unlock_pickup_code` aynı `db_set`'te siliyordu |

`code_locked`'ın bedava olmadığı da ölçüldü: Check olduğu için MariaDB ona
`NOT NULL DEFAULT 0` veriyordu ve kuyruk filtresi tek cümlede çalışıyordu.
Select'in böyle bir garantisi yok. (Frappe'nin `!=`'i `IFNULL(...)` ile yeniden
yazdığı sonradan ölçüldü — yani boş eksen kuyruktan düşmüyor, kuyruğa giriyor;
`79c0bbc` bu yanlış değişmezi düzeltti.)

### Uygulanmadı — gerekçe ölçümle

| Alan | Kurul ne dedi | Ölçüm ne dedi |
|---|---|---|
| `code_locked_at` | `code_locked` ile birlikte gider | **Hayır.** Select *kilitli olduğunu* söyler; *ne zaman* kilitlendiğini yalnız Datetime söyler. `RemittanceTransferDetail.vue:389` ekrana basıyor. Çiftin yalnızca yarısı fazlalıktı |
| `origin_city` / `destination_city` | Doğrulanmayan serbest metin, rapor üretmiyor | **Hayır.** `_SEARCH_FIELDS`'ta — "Semerkant'tan bugün ne geçti" aramasının ekseni. Üstelik anlık kopya: masa başka şehre taşınırsa geçmiş kayıt gerçekte geçtiği şehri korumalı |
| `register_base_rate` | JE donmuş kuru zaten taşıyor | **Hayır.** JE bu alandan **inşa ediliyor**, tersi değil (ADR-008, `_remittance_accounting.py:347`). Silmek, 9 basamaklı kesin bir kuru iki yuvarlanmış tutarın bölümünden geri türetmek olurdu — aynı gün düzeltilen row-4 kayan nokta hatasının tam olarak aynı sınıfı |

Ortak ders: kurul bu üçünde de **"aynı olgu iki yerde"** dedi. Üçünde de ikinci
yer aynı olgu değildi — biri zaman, biri arama ekseni ve tarihsel anlık görüntü,
biri de türetilenin değil türetenin kendisi.

## 5. Karar

1. **Doctype kalıyor.** Transfer/gider kalıbı havaleye uymuyor; gerekçe yukarıda
   ölçülü olarak duruyor. Bu bir aşırı mühendislik değildi.
2. **Bayrağa tarih koymak Zafar'ın kararı.** Bunu kurul veremez — hangi kiracının
   ne zaman V1'e geçeceği iş kararıdır. Karar verilene kadar modül küçülmez, ve
   asıl fazlalık (§3) burada duruyor, alanlarda değil.

   > **Kapandı — 2026-08-20. Karar: Legacy motor silindi.**
   >
   > Kurul bu maddeyi bir göç maliyeti varsayarak açık bıraktı: belge yazıldığında
   > "yedi kiracının hepsi Legacy'de" idi, yani sonlandırma tarihi koymak yedi
   > tenantı taşımak demekti. **Ölçüm bunu çürüttü.** 2026-08-20'de filoda havale
   > modülü yalnız zuma'da açıktı ve zuma **V1** koşuyordu; diğer yedi kiracıda
   > modül kapalı, sıfır transfer, sıfır ayar kaydı. Legacy motorun tek bir
   > kullanıcısı yoktu, yani sonlandırma maliyeti sıfırdı — kurulun elinde
   > olmayan olgu buydu.
   >
   > Silinen: `stabler/api/remittance.py` (yedi whitelisted uç), iki Legacy Vue
   > ekranı, iki anahtarlayıcı sarmalayıcı, ve `remittance_engine` bayrağının
   > kendisi — doctype alanı, `organization.py` çözümleyicisi ve ucu, `session.js`
   > durumu, `router.js` kapısı, ayar ekranının seçicisi.
   >
   > Bir şey bilerek silinmedi: `_assert_ready_for_v1`, artık
   > `_assert_ready_for_remittance` adıyla ve koşulsuz. İçindeki iki kontrol
   > (en az bir kasa masası, ve JE koruma alanlarının bu sitede var olması) motora
   > değil şirkete ve siteye bakıyordu; bayrak gidince tetikleyicileri kalmayacaktı.
   > Zuma zaten V1 olduğu için koşulsuz hale gelmesi filoda hiçbir davranışı
   > değiştirmedi.
   >
   > Sütun düşüren yama **yazılmadı**: depoda sütun düşüren tek bir yama yok, ve
   > sekiz kiracıda geri dönüşü olmayan DDL koşmanın işlevsel karşılığı sıfır.
   > Alan doctype JSON'ından çıkarıldı; sütun MariaDB'de öksüz kalıyor ve bunu
   > hiçbir kod okumuyor.
   >
   > **Motoru silmek verisini silmiyor.** Legacy'nin damgaladığı Journal Entry'ler
   > diskte kalabilir, ve iptal koruması onları kapsamaya devam ediyor — o yüzden
   > `remittance_cancel_guard`'ın "master satırı olmayan havale" dalı ve testleri
   > duruyor, yalnız gerekçeleri "iki motor var" yerine "eskisinin kodu yok"
   > olarak yeniden yazıldı.
3. **Küçültme uygulandı ve kapandı**: beş maddeden ikisi landing yaptı, üçü
   ölçümle reddedildi (§4). Her ikisi de doctype'a dokunduğu ve patch getirdiği
   için `make check` yeterli sayılmadı; `make test-bench` her temiz sha'da koştu.
4. Bu belge `docs/backlog.md`'ye kuyruk olarak değil, ölçülmüş bulgu olarak girer.
   FX tolerans presizyonu uyuşmazlığı oraya ayrıca yazıldı — bilerek
   değiştirilmedi, çünkü daraltmak yedi kiracının her JE/PE'sinde neyin kitaplanacağını
   değiştirir ve önce üretimde o aralığa düşen gerçek bir kalıntı var mı ölçülmeli.
