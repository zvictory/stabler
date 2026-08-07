# Stabler · Ölçüm aletini onar, artıkları topla, sonra Seviye 1 ihale panosu

> **Devir belgesi.** Belge Merkezi commit'leri sağlam (`042bf01`…`ce9f721`).
> Ama test kapısının kendisi bozuk: `make test` repoyu okumuyor. O düzelmeden
> hiçbir "yeşil" ölçümüne güvenilemez, o yüzden Bölüm 0'ın ilk maddesi o.
>
> **Önceki belgeler geçerli, okumadan başlama:**
> `PROMPT_tender_sourcing_phase2_handoff.md` (§0 kurallar, §2 tuzaklar),
> `PROMPT_landed_cost_at_quotation.md` (§1.7), `PROMPT_belge_merkezi.md` (§1.3).

**Repo:** `~/frappe-bench-local/apps/stabler` · **Dal:** `design/modernist-operations-desk`
**Son commit:** `ce9f721 feat(tender): document centre release`

**Bu turda karar sorulmayacak.** Kullanıcı iki açık kararı verdi (§0.3, §0.4).
Belgede bir yerde tereddüt edersen dur ve sor — ama planlanmış bir karar noktası
yok.

**Duman testleri bu turda SENDE DEĞİL.** Landed akışının ve Belge Merkezi'nin
tarayıcı testini kullanıcı kendisi yapacak. Sen `bench migrate` + `bench build`
ile ekranın açılabilir olduğundan emin ol, orada bırak.

---

# BÖLÜM 0 — Önce ölçüm aletini onar

## 0.1 ⚠️ `make test` repoyu okumuyor

Son koşuda `make test`, `DirectorBoard.vue`'yu **15 satırlık bir taslak** olarak
okudu:

```
<template><TenderPage><h2>Director Board</h2>
  <EmptyState :title="t('Director board overview')" /></TenderPage></template>
```

Gerçek dosya **376 satır**. `seed_tender_demo.py` de `def execute(): pass`
görünüyordu; gerçeği **816 satır**. Ve o taslak içerik **git geçmişinde hiç yok**:

```bash
git log -S "Executive tender portfolio oversight" --oneline --all   # → boş
```

Makefile `PY ?= $(VENV)/python` kullanıyor. Teşhis:

```bash
~/frappe-bench-local/env/bin/python -c "import stabler; print(stabler.__file__)"
```

- [ ] Çıktı `…/apps/stabler/stabler/__init__.py` **değilse**, venv'de uygulamanın
      eski ve editable olmayan bir kopyası kurulu. Düzelt:
      ```bash
      ~/frappe-bench-local/env/bin/pip install -e ~/frappe-bench-local/apps/stabler
      ```
      Gerekirse site-packages'taki eski `stabler` dizinini kaldır. Sonra teşhisi
      tekrarla; artık apps altını göstermeli.
- [ ] Düzeltmenin kendisi commit gerektirmiyor (venv repoda değil), ama **ne
      bulduğunu ve nasıl düzelttiğini** çıktıda net yaz.

> Bunun anlamı: bu projedeki son turların bütün "OK — pre-push gate passed"
> çıktıları yanlış ağacı ölçmüş olabilir. Aşağıdaki 0.2 bu yüzden var.

## 0.2 Gerçek borcu yeniden ölç ve YAZ

Ölçüm aleti onarıldıktan sonra, "bilinen borç" listesi baştan çıkarılmalı —
elimizdeki liste güvenilir değil.

```bash
cd ~/frappe-bench-local/apps/stabler
for m in $(grep -v -e '^#' -e '^$' .github/frappe-free-tests.txt); do
  r=$(python3 -m unittest $m 2>&1 | tail -1)
  case "$r" in OK*) ;; *) echo "$m : $r";; esac
done
```

- [ ] Çıkan listeyi `docs/ops/known-test-debt.md` diye bir dosyaya yaz: modül adı,
      düşen testin adı, **tek cümlelik sebep** (ör. "eski `stbl-ds-root` sarmalını
      arıyor, katman `TenderPage`'e taşındı").
- [ ] Sebebi "iddia bayatlamış" olanları **düzelt** — testin niyetini koru,
      bugünkü kaynağa uyarla. Sebebi gerçek bir hata olanları listede bırak.
- [ ] Bu dosya bundan sonra tek referans: bir sonraki tur "yeni mi eski mi"
      sorusunu buna bakarak cevaplar.

**Bilinen bir tanesi zaten teşhisli:** `test_director_board_source` →
`test_the_embedded_funnel_is_still_rendered`, `'<TenderFunnel />'` tam yazımını
arıyor. Bileşen artık `<TenderFunnel pipeline-strip :selected="phase" …>` olarak
monte ediliyor. Test, bileşenin **monte edildiğini** kontrol etmeli, tam string'i
değil.

## 0.3 Huni: yamuk ve geçiş düğmesi kaldırılıyor

**Kullanıcı kararı: yalnız bar kalacak.**

Gerekçe (koda yorum olarak yaz): yamuğun son basamağının taban genişliği
`r.n * 0.82` ile çiziliyordu — hiçbir veriyi temsil etmeyen, sadece "huni gibi
görünsün" diye konmuş bir sayı.

- [ ] `TenderFunnel.vue`'den SVG yamuk çizimi ve görünüm geçiş düğmesi çıkar.
- [ ] Yalnız o iki şey için eklenmiş i18n anahtarlarını beş CSV'den de çıkar
      (`Trapezoid`, `Bars`, `Toggle funnel view` ve varsa kardeşleri).
- [ ] `test_tender_funnel_source` ve `test_tender_pipeline_strip` yeşil kalmalı.

## 0.4 Belge Merkezi K2 kalıcı

**Kullanıcı kararı: elle işaretleme kalkışı doğruydu, kalıyor.** Geri alma yok.

- [ ] Değişikliği `docs/` altında bir cümleyle not et (kullanıcıların bugünkü
      alışkanlığı değişti; ekip duyurusu kullanıcının işi, ama kaydı bizde dursun).

## 0.5 Kalan Özbekçe hatası

- [ ] `stabler/translations/uzc.csv:5408` → `"Missing file","Файл йетишмайди"`.
      Doğrusu **`"Файл етишмайди"`**. Önceki düzeltme yalnız `Йетказ*`
      varyantlarını kapsamış.
- [ ] `uzc.csv`'de kelime başındaki `Й`'leri bir kez daha tara. `Йўналиш`,
      `бўйича`, `рўйхат` **doğru** — onlara dokunma; yanlış olan yalnız
      `й + ünlü` ile başlayan Özbekçe kökler (`етказ`, `етиш`, `ёз`…).
      Emin olmadığını kullanıcıya sor, uydurma.

## 0.6 Kapı

- [ ] `make check` (artık gerçek ağacı ölçüyor olmalı) + `npm run test:js`
- [ ] `make fix`'i **tüm ağaçta koşturma** — yalnız elinle değiştirdiğin
      dosyalarda `ruff format <dosya>` / `npx eslint --fix <dosya>`.
      (Geçen tur bu 84 dosyayı yeniden biçimlendirip 7 test modülünü kırmıştı.)

---

# BÖLÜM 1 — Seviye 1: ihale panosu

## 1.1 Sorun

Bugün `/tender/crm` **lot** panosu: her kart bir `CRM Deal`. Beş lotlu bir ihale
panoda beş ayrı kart olarak duruyor; hiçbir ekran "bu ihalenin tamamı nerede"
sorusunu cevaplamıyor.

Spec `docs/superpowers/specs/2026-07-30-hierarchical-tender-crm-design.md` §3
iki seviye tanımlıyor: **Seviye 1** bir kart = bir ihale, **Seviye 2** o ihalenin
lotları.

## 1.2 Altyapı HAZIR — yeniden yazma

| Var olan | Nerede | Durum |
|---|---|---|
| `Tender Master` doctype | `stabler/stabler/doctype/tender_master/` | 12 alan, hazır |
| `list_tender_masters` / `get_tender_master` / `save_tender_master` | `api/tender_master.py` | Şirket kapılı, hazır |
| `orphan_tender_lots(company)` | `api/tender_master.py:436` | **Göç kuyruğu — hiç kullanılmıyor** |
| `_tender_master_state.py` | `api/` | Lane TÜRETİLİR, saklanmaz |
| `custom_parent_tender` | patch v61, CRM Deal | Hazır |
| `validate_deal_parent_tender` | `hooks.py` doc_events | Şirket tutarlılığını korur |
| `test_tender_master_api` (27) + `test_tender_master_schema` (7) | `tests/` | Yeşil |

**Eksik olan tek şey SPA.** `list_tender_masters` hiçbir yerden çağrılmıyor.

## 1.3 Tasarım kararları

**L1 — Lane sunucuda türetilir, SPA saymaz.** `_tender_master_state.py` zaten
çocuk lotlardan lane hesaplıyor ve `list_tender_masters` kartlara katıyor. SPA
render eder, toplamaz. Aynı sayının iki yerde hesaplanması bu projede tekrar eden
hata (bkz. huni ↔ pano, "cheapest" ↔ "cheapest landed").

**L2 — `/tender/crm` ebeveyn panosu olur; lotlara oradan inilir.**
Kırılma yaratıyor ama spec'in modeli bu ve breadcrumb'ı bu:
`Tender CRM → Tender → Lot`.
- `/tender/crm` → ihale kartları, lane'ler: `Hazırlık → Aktif → Sonuç bekleniyor → Kısmi sonuç → Tamamlandı`
- `/tender/crm?tender=TND-…` → bugünkü lot panosu, o ihalenin çocuklarına süzülmüş
- Geri dönüş breadcrumb'la; `Esc` üst seviyeye (`useEscapeBack` deseni zaten var)

**L3 — Bağlantısız lotlar GİZLENMEZ.** Bugün lotların çoğunun ebeveyni yok ve
`custom_parent_tender` bilerek zorunlu değil (`test_tender_master_api:569` bunu
açıkça yazıyor: altı kiracı CRM Deal'ı sıradan satış için kullanıyor).

> Ebeveyn panosunda kalıcı bir **"Bağlantısız lotlar"** paneli olacak,
> `orphan_tender_lots` ile beslenen. Spec §8: *"Missing parent links appear in a
> migration queue and are not silently grouped."* Ne sessizce gruplanır, ne de
> ayrı bir yönetici ekranına sürülür — göç kuyruğu, işin yapıldığı yerde durur.

Panelden bir lot seçilip mevcut bir ihaleye bağlanabilir ya da yeni ihale
açılabilir. Panel boşaldığında kaybolur.

**L4 — Ebeveyn zorlanmaz.** Ebeveyni olmayan lot geçerli bir kayıttır; kuyruk bir
dürtmedir, duvar değil. Hiçbir yere `reqd` ekleme.

**L5 — Bağlam drill-down'da korunur.** Şirket, dönem ve `?phase=` süzgeci
seviyeler arasında kaybolmaz. Bugünkü `tenderRouteFilters` / `filterTenderRows`
altyapısı korunur.

**L6 — Ebeveyn toplamları çocukları KOPYALAMAZ.** Kart üzerindeki değer, lot
sayısı, en yakın son tarih, politika açığı ve risk sayısı hep türetilir. Hiçbir
sayaç `Tender Master` üzerine yazılmaz. Spec §6.

## 1.4 Dosyalar

**Yeni**
- `stabler/public/js/pages/tender/TenderMasterBoard.vue` — Seviye 1 panosu
- `stabler/public/js/components/TenderMasterDrawer.vue` — ihale oluştur/düzenle + lot bağlama
- `stabler/tests/test_tender_master_board_spa.py` — kaynak sözleşmesi

**Değişecek**
- `stabler/public/js/router.js` — `/tender/crm` bileşeni; `?tender=` parametresi
- `stabler/public/js/pages/tender/TenderCrm.vue` — ebeveyne göre süzme + breadcrumb
- `stabler/public/js/pages/tender/TenderNav.vue` — etiket "Tender CRM" kalır
- 5 × CSV

## 1.5 Görev sırası

**M1 · Ebeveyn panosu (salt okunur).** Kartlar, lane'ler, sayaçlar; hepsi
`list_tender_masters`'tan. Kart tıklaması `?tender=` ile lot panosunu açar.
→ `feat(tender): one card per tender, not one per lot`

**M2 · Göç kuyruğu.** `orphan_tender_lots` paneli; lotu mevcut bir ihaleye bağla
ya da yeni ihale açıp bağla.
→ `feat(tender): the lots that belong to no tender, where you can see them`

**M3 · İhale oluştur/düzenle.** `save_tender_master` üzerinden çekmece; alanlar
`_TENDER_FIELDS`'la sınırlı, `company` sunucudan.
→ `feat(tender): create a tender without leaving Stabler`

**M4 · Breadcrumb + bağlam.** İki seviye arası gezinme, süzgeç ve dönem korunur.
→ `feat(tender): two levels, one context`

**M5 · i18n + kapılar.** 5 CSV, `make check`, migrate, ekranın açıldığının
doğrulanması.
→ `feat(tender): tender board release`

## 1.6 Kabul kriterleri

- [ ] Ebeveyn kartındaki lot sayısı ve toplam değer, o karta tıklayınca açılan
      lot listesiyle **birebir** uyuşur.
- [ ] Hiçbir sayaç `Tender Master` üzerine yazılmaz — hepsi türetilir.
- [ ] Ebeveyni olmayan lot **kaybolmaz**; "Bağlantısız lotlar" panelinde durur.
- [ ] Bir lot yalnız **kendi şirketindeki** bir ihaleye bağlanabilir
      (`validate_deal_parent_tender` zaten koruyor — testle kanıtla).
- [ ] Başka şirketin ihalesi hiçbir koşulda listelenmez veya açılmaz.
- [ ] Seviye 1 → Seviye 2 → lot çekmecesi geçişinde şirket, dönem ve `?phase=`
      korunur.
- [ ] `Tender Master` kaydı olmayan bir kiracıda ekran **boş değil**: bütün lotlar
      göç kuyruğunda görünür ve oradan ihale açılabilir.
- [ ] `Esc` bir seviye yukarı çıkarır, uygulamadan atmaz.

---

# Çalışma şekli

- Görev başına bir commit; TDD sırası: düşen test → RED → uygula → GREEN → commit.
- Her görev sonunda dur ve göster.
- Test silme; hedefi hâlâ yaşayan bir davranışsa uyarla.
- `make fix`'i tüm ağaçta koşturma.
- Yarısı çalışan düğme koyma; koymamayı seç ve sebebini kaynağa yaz.

# Sonraki iş (henüz başlama)

**Rol kuyrukları** (spec §4). Gümrük, lojistik ve finans bugün ekranlarını
belgeden besleyemiyordu; Belge Merkezi geldiğine göre artık besleyebilir.
Her rolün kendi türetilmiş kuyruğu: `belge eksik → hazır → beyan edildi →
muayene → serbest` (gümrük), `planlama → alım → transit → sınır → teslim →
kabul` (lojistik). Hepsi **türetilir**; hiçbir rol panosu ikinci bir aşama
durumu yazmaz.
