# Stabler · Rol kuyrukları — gümrük ve lojistik

> **Devir belgesi.** Seviye 1 panosu ve Belge Merkezi indi, kapı temiz:
> `docs/ops/known-test-debt.md` → **0 aktif borç, 148 modül yeşil.** Bu taban
> çizgisini bozmadan devam et.
>
> **Önceki belgeler geçerli, okumadan başlama:**
> `PROMPT_tender_sourcing_phase2_handoff.md` (§0 kurallar, §2 tuzaklar),
> `PROMPT_landed_cost_at_quotation.md` (§1.7),
> `PROMPT_belge_merkezi.md` (§1.3),
> `PROMPT_seviye1_ihale_panosu.md` (§1.3).

**Repo:** `~/frappe-bench-local/apps/stabler` · **Dal:** `design/modernist-operations-desk`
**Son commit:** `1121cca feat(tender): one card per tender, not one per lot`

**Bu turda karar sorulmayacak** — planlanmış karar noktası yok. Tereddüt edersen
dur ve sor.

**Tarayıcı duman testleri SENDE DEĞİL.** Kullanıcı kendisi yapıyor. Sen
`bench migrate` + `bench build` ile ekranın açılabilir olduğundan emin ol,
orada bırak.

---

# BÖLÜM 0 — İki kural

## 0.1 `git add` yolu yolu stage'ler, dizin değil

Son commit'te `git add stabler/tests/ docs/` kullanıldı ve oturum başından beri
takip edilmeyen **~7.500 satır** belge (`docs/uat/tender/*`, prototip HTML, iki
ilgisiz test dosyası) "fix(test): repair test gate" başlıklı commit'e karıştı.
Veri kaybı yok, ama commit okunamaz hâle geldi.

- [ ] Bundan sonra **her yol tek tek** stage'lenir. `git add <dizin>` yok,
      `git add -A` zaten yasak. Commit öncesi `git status --short` ile ne
      stage'lendiğini gör.

## 0.2 Taban çizgisini koru

- [ ] Her görev sonunda: `make test` **0 düşen modül** vermeli.
      Bir şey kırılırsa `docs/ops/known-test-debt.md`'ye ekleme — **düzelt**.
      O dosya artık "sıfır borç" diyor; bu turda da öyle kalmalı.
- [ ] `make fix`'i tüm ağaçta koşturma. Yalnız elinle değiştirdiğin dosyalarda
      `ruff format <dosya>` / `npx eslint --fix <dosya>`.

---

# BÖLÜM 1 — Sorun

Spec `docs/superpowers/specs/2026-07-30-hierarchical-tender-crm-design.md` §4
altı rol için türetilmiş çalışma kuyruğu tanımlıyor. Bugün gümrük ve lojistik
ekranları var ama **kuyruk değil, düz liste**:

| Ekran | Uç nokta | Bugün ne yapıyor |
|---|---|---|
| `/tender/customs` | `tender.declarant_queue` (`api/tender.py:1980`) | PO listesi: ТН ВЭД, gümrük masrafı, ETA, `per_received` |
| `/tender/logistics` | `tender.logist_board` (`api/tender.py:2023`) | PO listesi: nakliye masrafı, ETA, teslim gecikme riski |

İkisi de **satın alma siparişi merkezli**. Gümrükçünün asıl sorusu — *"hangi
lotta hangi belge eksik, hangisi beyana hazır, hangisi muayenede"* — hiçbir
ekranda cevaplanmıyor. Belge Merkezi geldiğine göre artık cevaplanabilir:
ilk halka gerçek bir dosyaya bakabiliyor.

Spec'in istediği kulvarlar:

```
Gümrük:   belge eksik → hazır → beyan edildi → muayene → serbest
Lojistik: planlama → alım → transit → sınır → teslim → kabul
```

---

# BÖLÜM 2 — Tasarım kararları

**R1 — İKİNCİ BİR AŞAMA ALANI YOK.** Spec'in sert kuralı (§4):
*"Moving a card in one role board must not create a second, conflicting tender
stage."* Kulvarlar **zaten var olan belgelerden türetilir**, hiçbir yere yeni bir
durum kolonu yazılmaz.

Gümrük kulvarları neye bakar:

| Kulvar | Kaynak |
|---|---|
| belge eksik | `_tender_documents.docs_summary` → gümrük kapsamlı gereksinimlerde `missing` dolu |
| hazır | gümrük belgeleri tam, `Customs Declaration` henüz yok |
| beyan edildi | lota bağlı `Customs Declaration` mevcut (taslak/gönderilmiş) |
| muayene | beyannamenin kendi durumu |
| serbest | beyanname serbest bırakılmış / mal teslim alınmış |

Lojistik kulvarları: `Import Container`, `Import Truck`, `Freight Booking` ve
`Delivery Note` zaten kendi durumlarını taşıyor (`hooks.py`'de
`on_container_update`, `on_truck_update`, `CROSSED_BORDER` kancaları var).
Kulvar bunlardan türetilir.

**R2 — Belge gereksinimi hangi role ait olduğunu SÖYLER.** Bugün
`intake.documents[]` satırı rolü bilmiyor, dolayısıyla "gümrük belgesi eksik mi"
sorusu cevaplanamıyor. `_tender_documents.parse_doc_requirements`'a `role` alanı
eklenir: `customs` / `logistics` / `finance` / `general`.

Geriye dönük uyumlu: alanı olmayan eski satır `general` sayılır — **sıfırlanmaz,
uydurulmaz.** Standart belge seti (ГТД, sertifika, kabul aktı…) tohumlanırken
rolünü de yazar.

> Etiketten **çıkarım yapma.** "ГТД geçiyorsa gümrüktür" kuralı, serbest metin
> bir alanda çalışan bir tahmindir; kullanıcı "GTD" yazdığı gün sessizce bozulur.

**R3 — KUYRUKTA SÜRÜKLEME YOK.** Kartlar salt okunur izdüşümdür; ilerleme,
altındaki gerçek belge oluşturulup gönderilerek kaydedilir. Kartın üzerindeki
eylem düğmeleri o belgeyi **açar**, durumu değiştirmez.

Sebep: sürüklenebilir bir kart, er ya da geç "sürükleyince ne oluyor" sorusunu
doğurur ve cevabı ya "hiçbir şey" (yalan bir arayüz) ya da "ikinci bir durum
yazılıyor" (R1'in ihlali) olur. Yapısal olarak kapatmak, kurala uymayı
hatırlamaktan güvenli.

**R4 — Sayı ve liste TEK geçişte.** `tender_funnel`'ın deseni: kulvar sayacı ile
o kulvarın satırları aynı sunucu geçişinden çıkar. İki sorgu, iki farklı cevap
demektir — bu projede tekrar eden hata (huni ↔ pano, "cheapest" ↔ "cheapest
landed").

**R5 — Boş kuyruk SEBEBİNİ söyler.** Sonucu belli lot yoksa gümrük kuyruğu boş
gelir; ekran "kazanılmış lot yok, gümrük işi henüz başlamadı" der. Boş bir ızgara
hata gibi okunur.

**R6 — Kapı rolün kendisinde.** `_require_tender_view("declarant", …)` ve
`("logist", …)` zaten var, korunur. Menüde gizlemek güvenlik değildir.

---

# BÖLÜM 3 — Görev sırası

## C1 · Belge gereksinimine rol alanı
`_tender_documents.parse_doc_requirements` + standart set tohumlayıcısı +
`docs_summary`'nin role göre süzülebilmesi. Saf, frappe-free, kapsamlı test.
→ `feat(tender): a document requirement that knows whose job it is`

## C2 · Gümrük kuyruğu — sunucu
`declarant_queue`'yu kulvar döndürecek şekilde yeniden yaz. Mevcut PO bilgisi
(ТН ВЭД, gümrük masrafı, ETA) kart üzerinde **kalır** — kaybolmasın, sadece
kulvara yerleşsin. Tek geçiş, sayaç + satır.
→ `feat(tender): the customs queue, derived from the documents it waits on`

## C3 · Gümrük kuyruğu — ekran
`DeclarantQueue.vue` kulvarlı hâle gelir. Kart: lot, alıcı, eksik belge sayısı,
ТН ВЭД, ETA, risk. Eylemler ilgili belgeyi açar (Belge Merkezi sekmesi,
`Customs Declaration` formu). Sürükleme yok.
→ `feat(tender): the declarant sees a queue, not a list`

## C4 · Lojistik kuyruğu — sunucu + ekran
Aynı desen, `logist_board` + `LogistBoard.vue`. Kulvarlar konteyner/tır/teslimat
durumlarından türer. C2–C3'te kurulan yardımcıları yeniden kullan, kopyalama.
→ `feat(tender): the logistics queue, derived from where the goods actually are`

## C5 · i18n, kapılar, derleme
5 CSV, `make check`, `make test` (0 düşen), `npm run test:js`, `bench build`.
→ `feat(tender): role queues release`

---

# BÖLÜM 4 — Kabul kriterleri

- [ ] Hiçbir kulvar bir alandan **okunmaz**; hepsi türetilir. Yeni durum kolonu
      eklenmediğini test kaynak düzeyinde kilitler.
- [ ] Kulvar sayacı ile o kulvarın satır sayısı **birebir** uyuşur (tek geçiş).
- [ ] Gümrük kuyruğunda "belge eksik" kulvarı, Belge Merkezi'ndeki gerçek eksik
      dosyaları sayar — elle işaretlenmiş eski satırlar (`unverified`) **tam
      sayılmaz.**
- [ ] Rolü olmayan eski belge satırı `general` görünür; hiçbir kuyruğu kirletmez
      ve hiçbir yerde kaybolmaz.
- [ ] `declarant` görünümü olmayan kullanıcı uç noktadan 403 alır — ekranı
      gizlemek yeterli sayılmaz, testle kanıtla.
- [ ] Başka şirketin lotu hiçbir kuyrukta görünmez.
- [ ] Kazanılmış lot yokken ekran boş ızgara değil, sebebini yazan bir panel.
- [ ] Bugün `declarant_queue`/`logist_board` kartında görünen hiçbir bilgi
      (ТН ВЭД, gümrük/nakliye masrafı, ETA, gecikme riski) **kaybolmaz.**
- [ ] Migrate edilmemiş sitede okuma çalışır, kulvarlar boş gelir, hata vermez.

---

# Çalışma şekli

- Görev başına bir commit; TDD: düşen test → RED → uygula → GREEN → commit.
- Her görev sonunda dur ve göster.
- Test silme; hedefi hâlâ yaşayan bir davranışsa uyarla.
- Yarısı çalışan düğme koyma; koymamayı seç ve sebebini kaynağa yaz.
- `git add` ile **yol** ver, dizin verme.

---

# Sonraki iş (henüz başlama)

**Finans kuyruğu** (spec §4, altıncı satır): `belge bekliyor → kaydedildi →
vadesi geldi → tahsil edildi → marj sapması`. Bilerek ayrı bırakıldı, çünkü
diğer ikisinden farklı: finans verisi ayrıca **yetki kapılı**
(`_tender_finance_chain`, workspace'in `has_finance` kapısı) ve son kulvarı
(marj sapması) planlanan ile gerçekleşeni karşılaştıran ayrı bir hesap.
Gümrük–lojistik deseni oturduktan sonra kendi turunda ele alınacak.
