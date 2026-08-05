# Stabler · Faz 2 kapanışı + Teklif düzeyinde landed cost

> **Devir belgesi.** Faz 2'nin üç görevi commit'lendi (`e116963`, `be9871e`, `6e36cb7`)
> ama kapanmadı: beş açık iş var. Onlar bitmeden Bölüm 2'ye geçme.
> Kod yazan ajan bu dosyayı tek başına okuyup çalışabilmeli.

**Repo:** `~/frappe-bench-local/apps/stabler` · **Dal:** `design/modernist-operations-desk`
**Devraldığın son commit:** `6e36cb7 feat(tender): phase 2 complete with i18n and clean navigation`
**Önceki devir belgesi:** `PROMPT_tender_sourcing_phase2_handoff.md` — §0'daki kurallar ve §2'deki tuzaklar hâlâ geçerli, tekrar okumadan başlama.

---

# BÖLÜM 0 — Faz 2 kapanışı (önce bu)

## 0.1 Silinen testleri gözden geçir

`6e36cb7`, `test_tender_dashboard_spa.py`'den **146 satır ve 10 test metodu** sildi,
yerine hiç yenisi eklemedi. Çoğu gerçekten silinen bileşenlere aitti
(`TenderControlTower`, `TenderPortfolioPreview`) — o kısım meşru. Üçü şüpheli:

- `test_tender_today_is_read_in_local_time`
- `test_dashboard_offers_no_period_control_it_cannot_honour`
- `test_portfolio_risk_has_distinct_good_warn_and_risk_semantics`

Birincisi `bc7de50 fix(tender): the desk's "today" came from UTC, not from the desk`
ile düzeltilmiş **gerçek bir hatanın** bekçisi.

```bash
git show 2442b9a:stabler/tests/test_tender_dashboard_spa.py > /tmp/before.py
```

- [ ] Üçünü tek tek aç. Silinen bir bileşene bağlı DEĞİLSE, hedefini bugünkü
      ekranlara uyarlayıp geri getir. Bağlıysa, neden silindiğini commit
      mesajına yaz — "kapı yeşil olsun diye" kabul edilebilir bir sebep değil.

## 0.2 `supplier_quotation_history` — iki kusur

`stabler/api/purchasing.py`. Ham SQL + `LEFT JOIN tabTender Sourcing Decision`.
Şirket izolasyonu doğru (`_assert_company_scope` + `sq.company = %(company)s`),
ama:

**a) Satır çoğaltma.** Controller, onaylı bir karardan sonra aynı lota YENİ karar
kaydına izin veriyor (hata mesajı zaten "Record a new one"). İki onaylı karar olan
bir lotta LEFT JOIN her teklif satırını **iki kez** döndürür.

**b) Kayıt düzeyinde izin filtresi yok.** Ham SQL, `get_list`'in rol + kullanıcı
izinlerini sorgunun içinde uygulamasını atlıyor. Sadece doctype düzeyinde
`has_permission("Supplier", "read")` var. Kısıtlı bir alıcı, göremeyeceği
Supplier Quotation'ları bu sekmede görür.

- [ ] JOIN'i kaldır. İki okuma: `get_list("Supplier Quotation", …)` (izin
      filtreli) + o anlaşmalar için `get_list("Tender Sourcing Decision",
      {"status": "Approved"})` → Python'da `deal → selected_quotation` sözlüğü.
      Sonuç kolonu sözlükten türetilir. "Tek sorgu" hedefi **anlaşma başına sorgu
      atmamak** demekti, tek `SELECT` yazmak değil.
- [ ] Çoklu onaylı karar senaryosu için test ekle: aynı lotta iki onaylı karar,
      teklif **bir kez** listelenir ve sonucu **en son** onaylanana göre okunur.
- [ ] Kısıtlı kullanıcı testi: göremeyeceği SQ satırı dönmez.

## 0.3 Huni kararı

`FunnelCompare.vue` ve `TenderFunnelLegacy.vue`, kullanıcı karşılaştırmayı hiç
görmeden silindi. Karar hâlâ kullanıcının.

- [ ] **Kullanıcıya sor**, kendi başına karar verme. "Bar kalsın" derse bir şey
      yapma. "Yamuğu geri istiyorum" derse `git show 7087ec8:` ile geri getir ve
      bu kez SVG yamuğu **mevcut `stbl-ds` katmanına** taşı (eski dosya Tabler
      sınıfları ve sabit hex renkler taşıyordu — aynı sayfada iki tasarım dili).

## 0.4 Kalite kapıları

- [ ] `make check` — bu turda **hiç çalışmadı**. ruff (0.16.0 pinli) + eslint.
      `bench build`'in geçmesi lint'in temiz olduğu anlamına gelmez.
- [ ] `make test` + `npm run test:js` tam koşu. Bilinen borç, dokunma:
      `test_director_board_source`, `test_operations_desk_source`,
      `test_seed_tender_demo`, `test_tender_crm_source`, `test_tender_flow_source`.

## 0.5 Migrate + tarayıcı dumanı

`bench build` yapıldı, **`bench migrate` yapılmadı** — `Tender Sourcing Decision`
doctype'ı ve v68 patch'i hiçbir sitede yok, yani yeni ekranlar canlıda boş gelir.

- [ ] `bench --site <site> migrate`
- [ ] Duman senaryosu (mikas): RFQ oluştur → 2 teklif gir → politika rozetlerini
      gör → istisna gerekçesiyle karar kaydet → direktör onaylasın → PO panosunda
      kazanan işaretli → tedarikçi panelinde ikisi de listeli.
      `msa`: `/tender/sourcing` engelli. `anjan`: tender arayüzü yok.

---

# BÖLÜM 1 — Teklif düzeyinde landed cost

## 1.1 Sorun

Bugün "en ucuz" iki ekranda **iki farklı şey** demek:

| Ekran | Uç nokta | "Cheapest" neye göre |
|---|---|---|
| `/tender/sourcing` | `purchasing.tender_quotations` | çıplak `base_grand_total` |
| `/tender/po-control` | `tender.po_control_board` | landed (`base_po_total + charges_total`) |

Aynı anlaşmada iki farklı tedarikçi yeşil işaretlenebilir. Daha kötüsü: landed
hesabı **yalnız Purchase Order açıldıktan sonra** çalışıyor, yani "hangi teklif
teslimli olarak en ucuz" sorusu **kararı verirken** cevaplanamıyor.

Ve `Tender Sourcing Decision.cheapest_quotation` çıplak fiyata göre doluyor:
denetlenebilir bir kaydın içinde yanlış bir referans sayı.

Somut örnek — bugünkü demo verisiyle: Hebei Rail Parts (Çin, 874 000 000 сўм)
kâğıt üzerinde Temiryo'l ta'minot'tan (Özbekistan, 846 400 000 сўм) pahalı
görünüyor. Navlun + gümrük + iç nakliye eklendiğinde sıra değişebilir ve ekran
bunu söylemiyor.

## 1.2 Kullanılacak mevcut altyapı — yeniden yazma

| Var olan | Nerede | Ne yapar |
|---|---|---|
| `_parse_landed(raw)` | `api/tender.py:256` | PO'daki `custom_landed_charges` JSON'unu temizler. **KDV'nin geri alınabilir kısmını landed'a sermayeleştirmez** (WP-T1, IAS 2 §11). Aynen kullan. |
| `hs_rate_lookup(hs_code, company)` | `api/tender.py:364` | Gerçek oran motoru (WP-T2). Otomatik doldurma buradan. |
| `po_landed_charges` / `save_po_landed_charges` | `api/tender.py:401,435` | PO düzeyindeki editörün uç noktaları. Şema ikizi olacak. |
| `HS Duty Rate`, `Stabler Customs Fee Tier` | doctype'lar | Oran tabloları. |
| `_funnel.py` | `api/_funnel.py` | **Deseni taklit et:** saf, frappe-free, site olmadan kapsamlı test edilebilir modül. |

## 1.3 Tasarım kararları (bunlar tartışmaya açık değil, sebepleriyle yazıldı)

**K1 — Aynı alan adı, aynı şekil.** Patch **v69**: `custom_landed_charges`
(Long Text) Supplier Quotation üzerinde, PO'dakiyle **birebir aynı JSON şekli**.
Sebep: `_parse_landed` olduğu gibi yeniden kullanılır, ve ihale kazanıldığında
PO'nun masraf satırları teklifinkinden **tohumlanabilir** — planlanan→gerçekleşen
zinciri kopmaz. Farklı bir şekil, iki ayrı ayrıştırıcı ve iki ayrı hata demekti.

**K2 — Sıralama tek yerden.** Yeni saf modül `api/_landed.py`: teklif/PO fark
etmeksizin "satırlar + masraflar → teslimli toplam, en ucuz, en ucuza göre prim"
hesabı. `tender_quotations` ve `po_control_board` **ikisi de** onu çağırır.
Sebep: bugünkü hatanın kökü iki ekranın kendi sıralamasını yazması.

**K3 — Eksik tahmin, sıfır tahmin DEĞİLDİR.** Bir teklifin landed satırı yoksa,
landed = fiyat varsayma. Beş teklifin üçünde navlun tahmini varsa ve ikisinde
yoksa, hepsini "teslimli" diye sıralamak yalandır.

> **Kural:** `cheapest` bayrağı landed'a göre YALNIZCA karşılaştırılan teklişerin
> **hepsinde** tahmin varsa hesaplanır. Aksi hâlde ekran "karşılaştırma eksik"
> der, hangi tekliflerde tahmin olmadığını **isimle** sayar, ve o ana kadar
> fiyata göre sıralamaya devam eder — ama "en ucuz" rozetini **takmaz**.

Bu, projenin kendi ilkesinin aynısı: "en ucuz" ile "seçilen" ayrı gerçeklerse,
"en ucuz fiyat" ile "en ucuz teslimli" de ayrı gerçektir.

**K4 — İki bayrak, iki isim.** `cheapest_price` ve `cheapest_landed` ayrı
alanlar olarak döner. Tek bir `cheapest` alanı, hangi soruya cevap verdiğini
gizler — bu ekranın var olma sebebi ikisinin **farklı** olabilmesi.

**K5 — Her şey şirket para biriminde.** Karşılaştırma `base_*` alanlarından.
Bir USD teklifin masrafını UZS bir teklifin masrafıyla toplamak anlamsız.

## 1.4 Dosyalar

**Yeni**
- `stabler/patches/v69_sq_landed_charges.py` — v68'in ikizi, Supplier Quotation üzerinde
- `stabler/api/_landed.py` — saf sıralama/toplama modülü
- `stabler/tests/test_landed_ranking.py` — saf matematik, kapsamlı
- `stabler/tests/test_quotation_landed_api.py` — uç nokta sözleşmeleri
- `stabler/public/js/components/LandedChargesEditor.vue` — teklif satırındaki masraf editörü

**Değişecek**
- `stabler/api/sourcing.py` — `quotation_landed_charges(quotation, company)`, `save_quotation_landed_charges(quotation, charges, company)`, HS koddan otomatik doldurma
- `stabler/api/purchasing.py` — `tender_quotations` landed kolonlarını ve iki bayrağı döner
- `stabler/api/tender.py` — `po_control_board` sıralamasını `_landed`'a devreder; `_parse_landed` ortaklaşır
- `stabler/stabler/doctype/tender_sourcing_decision/` — snapshot landed taşır; `cheapest_quotation` **landed'a göre** dolar
- `stabler/public/js/pages/tender/SourcingWorkspace.vue` — landed kolonu, eksik-tahmin uyarısı, masraf editörü
- `stabler/patches.txt`, `.github/frappe-free-tests.txt`, 5 × CSV

## 1.5 Görev sırası

**G1 · v69 + saf modül.** Patch (çift çalıştırma güvenli, doctype yoksa erken
dön), `_landed.py` ve saf testleri. Sıralama, prim yüzdesi, eksik-tahmin
tespiti, KDV'nin dışarıda kalması — hepsi site olmadan test edilir.
→ `feat(tender): one place that decides which bid is cheapest delivered`

**G2 · Teklif masraf uç noktaları.** `sourcing.py`'ye iki uç nokta, üç kapı
deseni aynen. HS koddan otomatik doldurma `hs_rate_lookup` ile; kullanıcı
üzerine yazabilir, yazdığı korunur.
→ `feat(tender): estimate the delivered cost before the PO exists`

**G3 · İki ekran tek sıralamaya bağlanır.** `tender_quotations` ve
`po_control_board` `_landed`'ı çağırır. `test_po_control_currency_source`'un
koruduğu her şey korunur — o testi **zayıflatma**, gerekirse genişlet.
→ `fix(tender): "cheapest" means one thing on both screens`

**G4 · Award landed'a bağlanır.** `cheapest_quotation` artık teslimli en ucuz.
Snapshot'a `landed_total` ve `estimate_complete` kolonları. Karar ekranında fark
hem fiyat hem landed olarak gösterilir.
→ `feat(tender): the award compares delivered cost, not sticker price`

**G5 · Arayüz + i18n + kapılar + duman.** Editör, uyarı şeridi, 5 CSV,
`make check`, migrate, tarayıcı senaryosu.
→ `feat(tender): the landed estimate, where the buyer already is`

## 1.6 Kabul kriterleri

- [ ] Bir teklifte masraf satırı yoksa, o teklif landed sıralamasına **girmez** ve
      ekran onu **isimle** "tahmin eksik" diye sayar.
- [ ] Hiçbir teklifte tahmin yoksa ekran eskisi gibi fiyata göre sıralar ama
      "en ucuz" rozeti çıkmaz; sebebi yazılıdır.
- [ ] `cheapest_price` ile `cheapest_landed` farklı tedarikçiyi işaret ettiğinde
      ekran bunu **öne çıkarır** — bu ekranın var olma sebebi.
- [ ] Geri alınabilir ithalat KDV'si landed'a girmez; saf testte bir vaka bunu
      kanıtlar (WP-T1 regresyonu).
- [ ] Karışık para birimli teklif seti doğru sıralanır; `base_*` dışında hiçbir
      toplam kullanılmaz.
- [ ] `po_control_board`'un vendor karşılaştırması davranışını **değiştirmez** —
      yalnız hesabın nereden geldiği değişir. Mevcut testleri yeşil kalır.
- [ ] Migrate edilmemiş sitede okuma çalışır (landed kolonları boş), **yazma**
      açıkça "Run migrate" der.
- [ ] Onaylı bir award'ın snapshot'ı sonradan değişen masraflardan etkilenmez.

## 1.7 Bu turda düşülen tuzaklar

1. **Kapıyı yeşile boyamak için test silme.** Bir test silinen bir bileşene
   bağlıysa silinir; hedefi hâlâ yaşayan bir davranışsa uyarlanır.
2. **"Tek sorgu" ≠ tek `SELECT`.** Hedef N+1'den kaçınmak. Ham SQL, `get_list`'in
   izin filtresini atlar; bu projenin güvenlik modeli o ayrımın üstüne kurulu.
3. **`make check` atlanamaz.** `bench build` lint çalıştırmaz.
4. **Ürün kararını ajan vermez.** Belgede "kullanıcı karar verdikten sonra"
   yazıyorsa, dur ve sor.
5. Önceki belgedeki `_` gölgeleme, patch numarası ve `stage`/`phase` tuzakları
   hâlâ geçerli.

---

# Sonraki iki iş (bunlara henüz başlama)

1. **Belge merkezi.** `intake.documents[]` bugün sadece bir checklist:
   `{label, required, done, date}`. "ГТД ✓" = birisi kutuyu işaretledi, dosya
   burada değil. Spec §2 "Document scope" + Seviye 3'ün 9. sekmesi: satır başına
   ek yükleme, tender-scoped ↔ lot-scoped ayrımı, izinli indirme/paylaşım.
2. **Seviye 1 ihale panosu** (Faz 1 · Task 3). `Tender Master` doctype'ı, API'si
   (`api/tender_master.py`, 4 uç nokta) ve 27 testi **hazır**; SPA yok —
   `list_tender_masters` hiçbir yerden çağrılmıyor. Bugün 5 lotlu bir ihale
   panoda 5 ayrı kart. Lane'ler çocuk lotlardan türetilir:
   `Hazırlık → Aktif → Sonuç bekleniyor → Kısmi sonuç → Tamamlandı`.
