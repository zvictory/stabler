# Stabler · Teklif girişini onar + bağlantısız teklifleri sourcing'e getir

> **Devir belgesi.** Kullanıcı ekranı elle denedi ve teklif girişi **kaydedilemiyor**.
> Bölüm 0 bu kusuru kapatır; Bölüm 1 kullanıcının istediği yeni yeteneği ekler.
> Bölüm 0 bitmeden Bölüm 1'e geçme — kırık bir formun üzerine özellik eklenmez.
>
> **Önceki belgeler geçerli:** `PROMPT_tender_sourcing_phase2_handoff.md` (§0, §2),
> `PROMPT_landed_cost_at_quotation.md` (§1.7), `PROMPT_belge_merkezi.md` (§1.3),
> `PROMPT_seviye1_ihale_panosu.md` (§1.3), `PROMPT_rol_kuyruklari.md` (§0).

**Repo:** `~/frappe-bench-local/apps/stabler` · **Dal:** `design/modernist-operations-desk`
**Son commit:** `58f3cbc feat(tender): a document requirement that knows whose job it is`

**Not:** Rol kuyrukları (C2–C5) beklemede. Bu iş öncelikli, çünkü kullanıcı
bugün çalışamıyor. Bittiğinde `PROMPT_rol_kuyruklari.md`'ye dönülecek.

---

# BÖLÜM 0 — Teklif girişi kaydedilemiyor

## Belirti

`#/tender/sourcing?deal=CRM-DEAL-2026-00005` → "Teklif ekle" → tedarikçi, kalem,
miktar, oran girilip **Save draft**:

```
Row #1: Warehouse is mandatory for stock Item Y100
```

## Kök neden

`api/sourcing.py`:

- `_clean_quotation_items` satıra **`warehouse` koymuyor** (RFQ satırında var,
  teklif satırında yok).
- `save_supplier_quotation` başlıkta **`set_warehouse` atamıyor**.

ERPNext'in `BuyingController`'ı stok kalemi taşıyan satır için depo zorunlu
tutuyor. Yani **stok kalemi içeren hiçbir teklif kaydedilemiyor** — özellik
gönderildi ama hiç elle denenmedi.

## Yapılacak

**F1 — Depo başlıktan gelir, satıra ERPNext dağıtır.**
Başlığa `set_warehouse` ata; ERPNext bunu satırlara kendisi yayar. Satır bazında
tek tek yazmak, ileride kullanıcı satıra özel depo seçmek istediğinde iki kaynak
doğurur.

Depo sırayla şuradan okunur:
1. Çağıranın açıkça geçtiği `warehouse` (yeni, opsiyonel parametre)
2. Şirketin varsayılanı — `Company.default_warehouse`

Yardımcı **zaten var** ama yanlış evde: `api/installment.py:292
_company_default_warehouse(company)`. Taksit modülünden import etme —
`api/_common.py`'ye taşı ve iki çağıran da oradan alsın.

**F2 — Depo yoksa hata AÇIK olur.**
Şirkette varsayılan depo tanımlı değilse ham ERPNext hatası kullanıcıya
gösterilmez. Kendi mesajımız: hangi ayarın eksik olduğunu ve nereden
düzeltileceğini söyler.

> Ham çerçeve hatası kullanıcıya "Row #1" diye satır numarası söylüyor ama o
> satırda görünen alan **yok** — formda depo kutusu bile yok. Anlaşılmaz bir
> hatadır; bizim mesajımız o yüzden gerekli.

**F3 — Para birimi boş gelmesin.**
Çekmecede `CURRENCY` seçicisi `Select...` gösteriyor. Sunucu para birimini
zorunlu tutuyor, yani depo düzelir düzelmez ikinci hata gelir.

Varsayılan: şirketin para birimi (`session.currency`), kullanıcı değiştirebilir.
Zaten `newForm()` `currency.value` ile dolduruyor — **niye boş göründüğünü bul**:
büyük olasılıkla `list_currencies` cevabı `Select`'in beklediği şekilde değil
(dizi ↔ nesne uyuşmazlığı) ya da istek düşüyor ve `catch` bloğu devreye giriyor.

**F4 — Regresyon testi.**
`test_sourcing_api.py`'ye: kaydedilen belgede depo **var**; şirket varsayılanı
yoksa **bizim** mesajımız atılıyor; açıkça geçilen depo şirket varsayılanını
eziyor.

→ `fix(tender): a quotation you cannot save is not a feature`

---

# BÖLÜM 1 — Bağlantısız teklifler sourcing'de

## İstek

Kullanıcının kendi cümlesi:

> *"sourcing da biz standart quotation lari ekleyebilmemiz lazim, Purchasing
> bolumndeki diyelim unallocated quotations burada gorunmeli, istendiginde
> buradan edit yapalim sourcing workspace da"*

Gerçek iş akışı: teklif çoğu zaman Satınalma tarafında, ihaleden bağımsız olarak
giriliyor. Sonra "bu aslında şu lotun teklifiydi" deniyor. Bugün o teklifi lota
bağlamanın **hiçbir yolu yok** — ne Stabler'da ne de (Desk yasak olduğu için)
başka bir yerde. Etiketlenmemiş teklif politika sayımına girmiyor, yani 5/2
kuralı yanlış okuyor.

## Tasarım kararları

**U1 — "Bağlantısız" = etiketsiz, iptal edilmemiş, aynı şirket.**
`custom_crm_deal` boş **VE** `docstatus < 2` **VE** `company = seçili şirket`.
Başka şirketin teklifi hiçbir koşulda listelenmez.

**U2 — Bağlama parayı DEĞİŞTİRMEZ.** Sadece etiket yazar. Bu yüzden
**kesinleşmiş (submitted) teklif de bağlanabilir** — gerçek hayattaki asıl vaka
bu: alıcı teklifi Satınalma'da girip göndermiş, sonra lota bağlanıyor.

**U3 — ONAYLI bir karara bağlı teklif ÇÖZÜLEMEZ.**
Yanlış bağlanmış bir teklif çözülebilmeli (`detach`), ama teklif onaylanmış bir
`Tender Sourcing Decision`'ın `selected_quotation`'ı veya `cheapest_quotation`'ı
ise çözme **reddedilir**. Aksi hâlde denetlenebilir bir ihale kararı, artık var
olmayan bir kayda işaret eder.

**U4 — Bağlamak sayımı otomatik değiştirir.** Politika rozetleri (5 teklif /
2 ülke) ve landed sıralaması hep türetiliyor; bağlandığı anda doğru sayıyı
gösterirler. Hiçbir yere sayaç yazma.

**U5 — Düzenleme mevcut yolu kullanır.** `get_supplier_quotation` uç noktası
**zaten var** (`api/sourcing.py:208`). Çekmecenin düzenleme yolu Task 2'de
bilerek kapatılmıştı çünkü bu uç nokta yoktu; artık var, aç.
Kural değişmiyor: **kesinleşmiş teklif düzenlenemez**, satırlar eklenmez
**değiştirilir**.

**U6 — Etiketsiz teklif listesi ARAMA ile gelir, hepsi birden değil.**
Bir şirkette yüzlerce etiketsiz teklif olabilir. Panel varsayılan olarak son
20'yi gösterir, tedarikçi/numara araması ile daraltılır. Sayfayı sınırsız
listeye boğmak, panelin kapatılmasıyla sonuçlanır.

## Dosyalar

**Değişecek**
- `api/sourcing.py` — `list_unassigned_quotations`, `attach_quotation_to_deal`, `detach_quotation_from_deal`
- `public/js/pages/tender/SourcingWorkspace.vue` — "Bağlantısız teklifler" paneli + satır düzenleme
- `public/js/components/QuotationEntryDrawer.vue` — düzenleme yolunu aç (`quotation` prop'u geri gelir)
- `tests/test_sourcing_api.py`, `tests/test_sourcing_spa.py`
- 5 × CSV

## Görev sırası

**U-A · Uç noktalar.** Üç kapı deseni aynen (`_require_tender` →
`_assert_company_scope` → `_require_tender_view("sourcing")` → kayıt izni).
Çözmede onaylı-karar kontrolü.
→ `feat(tender): attach a quotation that was raised in Purchasing`

**U-B · Panel.** "Bağlantısız teklifler" — arama, tedarikçi, ülke, toplam,
tarih, docstatus rozeti, "Bu lota bağla" düğmesi. Boşsa panel görünmez.
→ `feat(tender): the quotations nobody linked, where sourcing can see them`

**U-C · Düzenleme.** Karşılaştırma tablosundaki taslak satırlarda "Düzenle";
çekmece `get_supplier_quotation` ile dolar. Kesinleşmiş satırda düğme yok
(devre dışı değil — **yok**; tıklanamayan düğme soru doğurur).
→ `feat(tender): edit a draft quotation where you are already looking at it`

**U-D · i18n + kapılar.** 5 CSV, `make check`, `make test` (0 düşen),
`npm run test:js`, `bench build`.
→ `feat(tender): unallocated quotations release`

## Kabul kriterleri

- [ ] Stok kalemi içeren bir teklif **kaydedilebiliyor** (Bölüm 0 regresyonu).
- [ ] Şirkette varsayılan depo yoksa **bizim** mesajımız çıkıyor, ham ERPNext
      hatası değil.
- [ ] Para birimi çekmece açılır açılmaz dolu geliyor.
- [ ] Bağlantısız panelde başka şirketin teklifi **hiçbir koşulda** görünmüyor —
      testle kanıtla.
- [ ] Kesinleşmiş bir teklif lota bağlanabiliyor.
- [ ] Onaylı bir ihale kararına bağlı teklif **çözülemiyor**; hata sebebi
      söylüyor.
- [ ] Bağladıktan sonra politika rozetleri (5/2) ve landed sıralaması
      kendiliğinden güncelleniyor — hiçbir yerde saklı sayaç yok.
- [ ] Taslak teklif workspace'ten düzenlenebiliyor; satırlar **değişiyor**,
      eklenmiyor.
- [ ] Kesinleşmiş teklifte "Düzenle" düğmesi yok.
- [ ] `sourcing` görünümü olmayan kullanıcı üç uç noktadan da 403 alıyor.

---

# Çalışma şekli

- Görev başına bir commit; TDD: düşen test → RED → uygula → GREEN → commit.
- Her görev sonunda dur ve göster.
- `git add` ile **yol** ver, dizin verme.
- `make fix`'i tüm ağaçta koşturma.
- Test silme; hedefi yaşayan bir davranışsa uyarla.
- `make test` her görev sonunda **0 düşen modül** vermeli
  (`docs/ops/known-test-debt.md` sıfır borç diyor, öyle kalsın).

# Bundan sonra

`PROMPT_rol_kuyruklari.md` → C2: gümrük kuyruğunun kulvarlı hâle gelmesi.
