# Stabler · Ağaç temizliği + duman testi + Belge merkezi

> **Devir belgesi.** Landed cost commit'leri sağlam (`24edf28`…`acc137a`), ama
> çalışma ağacı bozuk ve landed akışı hiç elle denenmedi. Bölüm 0 bitmeden
> Bölüm 1'e geçme.
>
> **Önceki belgeler hâlâ geçerli, okumadan başlama:**
> `PROMPT_tender_sourcing_phase2_handoff.md` (§0 kurallar, §2 tuzaklar) ve
> `PROMPT_landed_cost_at_quotation.md` (§1.7 tuzaklar).

**Repo:** `~/frappe-bench-local/apps/stabler` · **Dal:** `design/modernist-operations-desk`
**Son commit:** `acc137a fix(tender): add missing dashboard i18n translation keys`

---

# ⛔ ÖNCE — iki soru, cevap gelmeden kod yazma

Son iki turda bu kural iki kez çiğnendi: belgede "kullanıcıya sor" yazan yerde
ajan kendi kararını verip uyguladı. Bu yüzden sorular artık görev listesinin
**dışında**, en başta.

**S1 · Huni görünümü.** `TenderFunnel.vue`'ye kimse istemeden bir yamuk/bar geçiş
düğmesi eklendi. Kullanıcı bu kararı hiç vermedi. Sor: *"Huni yamuk mu bar mı
olsun, yoksa geçiş düğmesi kalsın mı?"* Cevap gelene kadar o dosyaya dokunma.

**S2 · Belge merkezi kapsamı.** Bölüm 1'e başlamadan önce §1.3'teki **K2 kararını**
(elle işaretleme kalkıyor, `done` türetiliyor) kullanıcıya onaylat. Bu, bugünkü
davranışı değiştiriyor: kullanıcılar alışkın oldukları kutuyu artık elle
işaretleyemeyecek. Onay gelmeden yazma.

Kod yazan ajan bu iki soruyu **tek mesajda** sorar, cevabı bekler, sonra başlar.

---

# BÖLÜM 0 — Ağacı temizle, sonra dene

## 0.1 Commit'lenmemiş tree-wide reformat'ı at

`git status` → **84 değişik izlenen dosya**, `+11060 / -3343`. Bu commit'lenmemiş
biçimlendirme, **7 test modülünü** kırıyor ve dördü satış/envanterde — tender'la
hiç ilgisi yok.

Kök neden: `.prettierrc.json` `printWidth: 100`, `trailingComma: "es5"` diyor;
ağaçtaki fark sondaki virgülleri **siliyor** ve ~80'de sarıyor. `router.js`'teki
tek satırlık rota nesneleri çok satıra patladı, kaynak sözleşme testleri tam o
satıra bakıyordu.

**Commit'lenmiş tarih temiz** — `acc137a` ayrı bir dizine çıkarılıp koşturuldu,
yalnız bilinen 5 borç düşüyor. Yani atılacak şey hiçbir işi kaybettirmiyor.

```bash
git stash push -- $(git diff --name-only | grep -v -e '^CLAUDE.md$' -e '^deploy_stabler.sh$')
make test
```

- [ ] `make test` sonrası **tam olarak** şu beş modül düşer, fazlası değil:
      `test_director_board_source`, `test_operations_desk_source`,
      `test_seed_tender_demo`, `test_tender_crm_source`, `test_tender_flow_source`.
- [ ] `CLAUDE.md` ve `deploy_stabler.sh` kullanıcının kendi değişiklikleri —
      **dokunma**, stash'e alma.
- [ ] Stash'i `git stash show -p` ile gözden geçir. İçinde biçimlendirme dışında
      gerçekten istenen bir şey varsa onu tek tek geri al; yoksa `git stash drop`.

> **Bir daha:** `make fix` bu dalda ayak kapanı. `CHANGED_JS`/`CHANGED_PY` main'e
> karşı hesaplanıyor, yani dalın dokunduğu HER dosyayı yeniden biçimlendiriyor.
> Yalnız o commit'te elinle değiştirdiğin dosyalarda çalıştır:
> `ruff format <dosya>` / `npx eslint --fix <dosya>`.

## 0.2 Alakasız dosyayı ayır

`b9a2e10` (tender landed commit'i) içinde `stabler/public/js/pages/money/Expenses.vue`
var — lint hatasını susturmak için düzenlenmiş. Para modülündeki bir değişiklik
tender commit'inin içinde kaybolmamalı.

- [ ] Değişiklik gerçekten gerekliyse kendi commit'ine ayır:
      `fix(money): <ne düzeltildiği>`. Gereksizse geri al.

## 0.3 Özbekçe çeviriler bozuk

- [ ] `uz.csv`: `"Toggle funnel view","Gidronoma koʻrinishini oʻzgartirish"` —
      **"Gidronoma" diye bir kelime yok**, uydurma. Doğrusu "voronka".
- [ ] `uzc.csv`: **13 satırda** `"Йетказ…"` yazılmış. Özbek Kirilcesinde doğrusu
      `"Етказ…"` — baştaki `Й` yanlış.
- [ ] Tutarsızlık: aynı kavram bir yerde "Etkazib beruvchi", başka yerde
      "Yetkazib berish". Birini seç, hepsini ona çevir.
- [ ] Beş dilin **dolu** olması yetmiyor, **doğru** olması gerekiyor. Emin
      olmadığın terimi uydurma — kullanıcıya sor.

## 0.4 Landed akışının duman testi — hiç yapılmadı

K3 kuralının (eksik tahmin → landed sıralaması durur) tek gerçek sınavı bu.

- [ ] `bench --site mikas.localhost migrate` (v69) + `bench build --app stabler`
- [ ] `#/tender/sourcing?deal=<tender lot>` aç. En az 3 teklif olsun.
- [ ] **İkisine** masraf tahmini gir, **birine girme**.
- [ ] Doğrula: uyarı şeridi çıkıyor, eksik teklifi **isimle** sayıyor,
      **"En ucuz teslimli" rozeti çıkmıyor**, sıralama fiyata düşüyor.
- [ ] Üçüncüye de gir → rozet çıkıyor, ve `cheapest_price` ≠ `cheapest_landed`
      olan bir veri kur (Çin tedarikçisi kâğıtta pahalı, navlunla ucuz).
      Ekran farkı **öne çıkarıyor mu?** Çıkarmıyorsa bu işin bütün amacı kaçmış.
- [ ] Geri alınabilir KDV'li bir satır ekle → teslimli toplama **girmemeli**.
- [ ] Award kaydet → snapshot'ta landed kolonları var mı, `cheapest_quotation`
      teslimli en ucuzu mu gösteriyor?

Bulduğun her kusuru düzelt ve ayrı commit'le. **Duman testi geçmeden Bölüm 1 yok.**

---

# BÖLÜM 1 — Belge merkezi

## 1.1 Sorun

Bugün `intake.documents[]` sadece bir **checklist**: `{label, required, done, date}`.
"ГТД ✓" demek *"birisi kutuyu işaretledi"* demek, *"dosya burada"* demek değil.
Tek gerçek ek, `bid_package`'ın ürettiği docx (`api/tender.py:1281`).

Bu, gümrük ve lojistik rollerinin ekranda yaşayamamasının sebebi: teslim aktı,
sertifika, ГТД — hepsi WhatsApp'ta ve masaüstünde duruyor, ERP'de yalnız
işaretleri var. Denetim, devir ve arama imkânsız.

Spec `docs/superpowers/specs/2026-07-30-hierarchical-tender-crm-design.md`
§2 "Document scope" ve Seviye 3'ün 9. sekmesi bunu tanımlıyor.

## 1.2 Mevcut altyapı — yeniden yazma

| Var olan | Nerede | Ne yapar |
|---|---|---|
| `intake.documents[]` | `CRM Deal.custom_tender_intake` JSON | Gereksinim listesi. Omurga bu, değiştirme — genişlet. |
| `_docs_summary(intake)` | `api/tender.py:1478` | total / required / done_required / missing |
| `_read_intake_for_update` | `api/tender.py:1504` | `FOR UPDATE` satır kilidi. Eşzamanlı yazma için zaten düşünülmüş. |
| `_clean_intake(data, prior, audit_actor)` | `api/tender.py:1371` | Temizleme + denetim aktörü. Yeni alanlar buraya. |
| `save_file(...)` | Frappe | `bid_package` zaten kullanıyor (`tender.py:1281`). Dosya deposu bu. |
| `TenderIntake.vue` | `pages/tender/` | Bugünkü checklist editörü. |
| `TenderWorkspaceTabs.vue` | `pages/tender/` | Sekme şeridi — "Documents" buraya. |

## 1.3 Tasarım kararları

**K1 — Yeni doctype YOK.** Dosyalar Frappe'nin `File`'ında yaşar
(`attached_to_doctype` / `attached_to_name`), gereksinim listesi bugünkü JSON'da
kalır. Sebep: iki yazma yolu iki tutarsızlık demek, ve `_read_intake_for_update`
kilidi zaten var. *Bilinen bedel:* "hangi lotlarda ГТД eksik" sorgusu JSON
üzerinde ucuz değil; toplu rapor gerektiğinde ayrı fazda doctype'a terfi edilir.
Bu bedeli commit mesajına yaz.

**K2 — `done` elle işaretlenmez, TÜRETİLİR.** ⚠️ *Uygulamadan önce S2'yi onaylat.*
```
done  =  en az bir dosya eklenmiş   VEYA   gerekçesiyle muaf tutulmuş
```
Sebep: bu ekranın var olma sebebi. Elle işaretlenen bir kutu, dosyanın orada
olduğunu söylemiyor — sadece birinin öyle sandığını söylüyor.

**Muafiyet sessiz olamaz.** Bazı gereksinimler bizde dosya olmadan da sağlanır
(alıcı tarafında kalan onay gibi). O yüzden açık bir "muaf" durumu var ve
**yazılı gerekçe** ister — award'daki politika istisnasının aynısı.

**K3 — Eski veri sessizce sıfırlanmaz.** Bugün elle işaretlenmiş satırlar var.
Onları "yapılmadı"ya çevirmek, insanların gözünde tamamlanmış işi geri alır;
"yapıldı" saymak ise yalanı sürdürür. Üçüncü yol: **`unverified` rozeti** —
projenin kendi hâlihazırdaki deseni (`lifecycle.unverified_history`,
DirectorBoard'daki "Unverified" çipi). Sayı orada, arkasındaki kayıt eksik.

**K4 — Kapsam: tender ↔ lot.** Her gereksinim satırı `scope` taşır.
Tender kapsamlı olanlar `Tender Master`'da yaşar ve **her çocuk lottan görünür**,
lot kapsamlı olanlar CRM Deal'de. Tender kapsamlı bir dosya **bir kez** saklanır,
lot başına kopyalanmaz. Patch **v70**: `custom_tender_documents` (Long Text)
Tender Master üzerinde, lot JSON'uyla aynı şekil.

**K5 — İndirme kapıdan geçer.** SPA'da ham `/files/...` bağlantısı **yok**.
İndirme, lot/tender kapsamını yeniden doğrulayan bir uç noktadan geçer. Sebep:
Frappe'nin özel dosya koruması eklenti iznine bakar, bu projenin şirket
kapsamlaması ise ayrı bir katman — ikisi aynı şeyi söylemiyor.

**K6 — Dosya silinmez, ÜSTÜNE YAZILIR.** Yanlış yüklenen dosya yenisiyle
geçersizleşir, eskisi geçmişte kalır. Award'ın değişmezliğiyle aynı gerekçe:
denetim kaydından sessizce satır kaybolmaz.

## 1.4 Dosyalar

**Yeni**
- `stabler/patches/v70_tender_master_documents.py`
- `stabler/api/tender_documents.py` — liste / yükle / muaf tut / indir
- `stabler/public/js/pages/tender/TenderDocuments.vue` — Documents sekmesi
- `stabler/tests/test_tender_documents_api.py` (frappe-free, `_FakeFrappe` deseni)
- `stabler/tests/test_tender_documents_spa.py` (kaynak sözleşmesi)

**Değişecek**
- `api/tender.py` — `_clean_intake` yeni alanları tolere eder (eski 4 anahtarlı satırlar bozulmadan geçer), `_docs_summary` türetilmiş `done`'a göre sayar
- `pages/tender/TenderIntake.vue` — elle `done` kutusu kalkar, satır Documents sekmesine bağlanır
- `pages/tender/TenderWorkspaceTabs.vue` — dokuzuncu sekme
- `patches.txt`, `.github/frappe-free-tests.txt`, 5 × CSV

## 1.5 Görev sırası

**B1 · Şema + saf kurallar.** v70 patch'i, `_clean_intake` genişlemesi, türetilmiş
`done`/`unverified` mantığı saf bir yardımcıda + kapsamlı testleri.
→ `feat(tender): a document requirement that knows whether the file is actually there`

**B2 · Uç noktalar.** `list_tender_documents`, `upload_tender_document`,
`waive_tender_document`, `download_tender_document`. Üç kapı deseni aynen.
→ `feat(tender): upload, waive and download, each through the same gate`

**B3 · Documents sekmesi.** Gereksinim satırları, kapsam rozeti (tender/lot),
yükleme, muafiyet gerekçesi, geçmiş, `unverified` çipi.
→ `feat(tender): the documents tab, where the file lives next to the requirement`

**B4 · Sayaçlar türetilmişe bağlanır.** Masa, CRM kartları ve pano rozetleri
(`%25/%50/%75 готовность`) artık gerçek dosyaya göre okur.
→ `fix(tender): the readiness badge counts files, not ticks`

**B5 · i18n, kapılar, duman.** 5 CSV, `make check` (yalnız değişen dosyalarda
`ruff format`/`eslint --fix`), migrate, tarayıcı senaryosu.
→ `feat(tender): document centre release`

## 1.6 Kabul kriterleri

- [ ] Bir gereksinim satırı **elle** "yapıldı" işaretlenemez.
- [ ] Muafiyet gerekçesiz kaydedilemez.
- [ ] Eski elle işaretlenmiş satırlar `unverified` rozetiyle görünür; ne sıfırlanır
      ne de tamamlanmış sayılır.
- [ ] Tender kapsamlı dosya her çocuk lotta görünür ve **bir kez** saklanır.
- [ ] SPA'da hiçbir ham dosya URL'i yok; indirme kapılı uç noktadan geçer.
- [ ] Başka şirketin lotuna ait dosya hiçbir koşulda indirilemez — testle kanıtla.
- [ ] Yanlış dosya yenisiyle geçersizleşir; eskisi geçmişte kalır, silinmez.
- [ ] Migrate edilmemiş sitede okuma çalışır, yazma açıkça "Run migrate" der.
- [ ] Masa/CRM/pano rozetleri türetilmiş sayıyı gösterir; iki ekran farklı sayı
      söylemez.

---

# Çalışma şekli

- Görev başına bir commit, TDD sırası: düşen test → RED → uygula → GREEN → commit.
- Her görev sonunda **dur ve göster**.
- `make fix`'i tüm ağaçta koşturma (Bölüm 0.1'deki not).
- Test silme; hedefi hâlâ yaşayan bir davranışsa uyarla. "Kapı yeşil olsun diye"
  bir sebep değil.
- Yarısı çalışan düğme koyma; koymamayı seç ve sebebini kaynağa yorum olarak yaz.
- Belgede "kullanıcıya sor" yazan yerde **dur ve sor**.

# Sonraki iş (henüz başlama)

**Seviye 1 ihale panosu** (Faz 1 · Task 3). `Tender Master` doctype'ı, API'si
(`api/tender_master.py`, 4 uç nokta) ve 27 testi hazır; SPA yok —
`list_tender_masters` hiçbir yerden çağrılmıyor. Bugün 5 lotlu bir ihale panoda
5 ayrı kart. Lane'ler çocuk lotlardan türetilir:
`Hazırlık → Aktif → Sonuç bekleniyor → Kısmi sonuç → Tamamlandı`.
Belge merkezi bittiğinde kapsam alanı (`scope`) zaten hazır olacağı için bu iş
doğal olarak sıradaki adım.
