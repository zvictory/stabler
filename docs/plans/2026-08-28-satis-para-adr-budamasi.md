# Satış ve Para ADR'leri — sekizi geçersiz, ikisi kalıyor

**Tarih:** 2026-08-28 · **Karar veren:** Zafar
**Yerine geçtiği belge:** `docs/plans/2026-08-18-satis-ve-para-formlari-tasarim-kurulu-karari.md`,
**§4'ün on ADR'sinden sekizi**

---

## Karar

> **ADR-405 ve ADR-406 kalır. Kalan sekizi geçersizdir.**

Geçersiz: **ADR-401, 402, 403, 404, 407, 409, 410** — artı **ADR-408**, ki o zaten
2026-08-21 kapsam kararıyla geçersizdi (`2026-08-21-so-si-modern-kapsam-karari.md`).

---

## Dayanak — on gün, 51 düzeltme, sıfır ADR

Karar 2026-08-28'de ölçüldü, belgeden okunmadı. On ADR'nin **hiçbiri** kodda
uygulanmamıştı; ADR-403 ve ADR-407 alt kural düzeyinde kısmen karşılanıyordu ve
karşılanan kısımlar da ADR yüzünden değil, başka işlerin yan ürünü olarak oradaydı.

| Eksen | Ölçüm |
|---|---|
| 10 ADR | **0 tam** (403 ve 407 kısmi) |
| 21 zorunlu P0 | 9 kapalı · 2 yarım · 10 açık |
| 48 zorunlu D maddesi | **5 kapalı · 2 yarım · 41 açık** |
| Aynı dönemde atılan commit | 67 — 51'i `fix`, 3'ü `refactor` |

Satış Siparişi Modern'de **15 D maddesinin biri bile** kapanmadı.

Bir mimari kararın on gün aktif çalışma boyunca hiç uygulanmaması onun *bloke*
olduğunu göstermez — *istenmediğini* gösterir. Kâğıtta tutulması, durum panosunun her
sürümünde bir "yapılmadı" satırı üretmekten başka bir işe yaramıyordu.

## Neden bu ikisi kaldı

Ölçülmüş bir bedeli olan tek iki madde bunlar.

**ADR-405 — yükleme sırasında watcher'lar susar.** Üç P0'ın (`P0-SO-1`, `P0-SO-4`,
`P0-SI-5`) ortak cevabı; tek işle üçünü birden kapatıyor. Bugün üç ayrı çözüm var:
Klasik `loadingDoc`, Transfer `hydrating`, SO/SI Modern **hiçbiri**;
`composables/useDocumentForm.js` (341 satır) `hydrating` dizesini hiç içermiyor.

**ADR-406 — para biçimlemesi tek yoldan.** Bir görünüm tercihi değil, **yanlış rakam**:
`formatMoney` `tr` yerelinde nokta-binlik üretiyor, yerel `fmtAmt` boşluk-binlik —
Türkçe'de `.` binlik ayırıcı olduğu için aynı değer yan yana bir buçuk milyon ve bir
buçuk milyar okunabiliyor. Yerel kopyalar duruyor: `Expenses.vue:126,137`,
`Transfers.vue:229,238`, 15+ çağrı. (Hedef `formatRate` `composables/fx.js:123`'te —
ADR metni onu `money.js`'de gösteriyordu, 2026-08-28'de düzeltildi.)

## Geçersiz ≠ kusur kabul edildi

**Bu karar hiçbir hatayı onaylamıyor.** Geçersiz kılınan şey ADR'lerin dayattığı
**mimari zorunluluk** — "şu altı sözleşme tek yere iner" mandası. Aynı belgenin
§2'sindeki 21 P0 ve §5'indeki 48 D maddesi **aynen geçerlidir** ve ölçülmüş hâlleri
yukarıdaki tabloda duruyor.

Somut olarak: ADR-410 geçersiz oldu diye `Waybill.vue:29`'daki koli regex'i doğru hâle
gelmedi; hâlâ orada ve hâlâ yanlış. Sadece "bu, tek bir mimari kararın parçası olarak
çözülecek" iddiası kalktı.

## Bu kararın bedeli

Sekiz ADR gidince, dört ekranın form sözleşmesini tek yere indirme fikri de gidiyor.
Kur bloğu, aksiyon çubuğu, kaydetme sözlüğü ve liste araç çubuğu **dört ekranda ayrı
ayrı yaşamaya devam edecek**. 2026-08-18 belgesinin "ortak kök" teşhisi doğruydu ve
geçerliliğini koruyor — kabul edilen şey teşhisin yanlışlığı değil, **bu turda
tedavinin yapılmayacağı**.

Bu bedel bilinçli. Alternatifi, on gün boyunca kimsenin dokunmadığı bir mandayı on
birinci güne taşımaktı.

## Yeniden açılma koşulu

Bu sekiz ADR'den biri, **onu isteyen somut bir iş** ortaya çıktığında yeniden açılır —
tarihi yenilenmiş yeni bir kararla, bu belgeye atıfla. En olası aday ADR-401: SO
Modern'in altı P0'ı kapatılmaya karar verilirse kur bloğu zaten yeniden yazılacak, ve
o an dört kopyayı tek bileşene indirmenin maliyeti sıfıra yakın olur.
