# `uzc` seçenekten çıkarıldı — katalog korundu

**Tarih:** 2026-08-28 · **Karar veren:** Zafar

---

## Karar

> **`uzc` (Ўзбекча, Özbekçe Kiril) artık kullanıcıya sunulmuyor. Katalog kalıyor.**

Sunulan dört dil: **en, ru, uz, tr**. Beşinci katalog `uzc` deposunda duruyor,
çevrilmeye devam ediyor, ve `uzc` ayarı taşıyan bir hesap Kiril görmeye devam eder.

## Nasıl çıktı

Karar bir dil politikası tartışmasından değil, bir hata avından çıktı. `Line A Operator`
rolü silinirken `User.save()` şurada patladı:

```
LinkValidationError: Could not find Language: uzc
```

Ölçüldü: **`uzc` için `Language` kaydı sekiz kiracının hiçbirinde yok** (`uz`, `ru`,
`tr` hepsinde var). Sonuç, `language="uzc"` taşıyan altı hesabın `User` belgesinin
**hiçbir doğrulanmış yoldan kaydedilememesiydi** — Desk, API, `user.save()` çağıran
her kod. Etkilenenlerden biri `zafar@stable.uz`'du.

İki çıkış vardı: eksik `Language` kaydını sekiz kiracıda oluşturmak, ya da dili
çekmek. Zafar ikincisini seçti.

### Neden bugüne kadar fark edilmedi

`stabler/__init__.py` zaten bir monkey-patch taşıyor: `frappe.get_doc` ve
`get_cached_doc` için `Language "uzc"` isteklerini `"uz"`ye yönlendiriyor. O yama
**okumaları** kapsıyor ve `uzc` katalogu için hâlâ gerekli — ama **link
doğrulamasını** kapsamıyor. Ekran çalıştığı için hata görünmedi; yalnızca birisi bir
kullanıcıyı kaydetmeye çalıştığında ortaya çıkıyordu.

## Yapılanlar

| | |
|---|---|
| Üç seçiciden kaldırıldı | `Sidebar.vue`, `Profile.vue`, `api/onboarding.py` — her birine sebebi ve geri alma yolu yorum olarak yazıldı |
| Prod hesapları taşındı | 6 hesap `uzc` → `uz` (anjan 4, smartbox 1, zuma 1) |
| Doğrulandı | anjan'da `zafar@stable.uz` için `User.save()` yeniden denendi — **geçiyor** |
| Korundu | `translations/uzc.csv` (5 219 çeviri), `SUPPORTED_LANGUAGES`, `__init__.py` yaması |
| Pinlendi | `stabler/tests/test_uzc_retired_from_pickers.py`, `make check` kapsamında |

## Neden yarı emeklilik — ve neden bu sefer tehlikeli değil

Bu depo yarı emekli edilmiş şeylerden tekrar tekrar zarar gördü: hiçbir izin vermediği
hâlde veriyormuş gibi duran bir rol, bir dosyada geçersiz bir dosyada canlı bir ADR,
tarif ettiği koddan üstün tutulan bir UAT dokümanı. Üçü de sonradan kusur sanılıp
yeniden ölçüldü.

Bu karar aynı biçimde ama farklı kurulumda: **durum iki taraftan da pinlendi.** Test
hem `uzc`'nin hiçbir seçicide olmamasını hem de katalogun ve `SUPPORTED_LANGUAGES`
girdisinin **durmasını** kontrol ediyor. Yani "temizlik" niyetiyle `uzc.csv`'yi silmek
ya da `SUPPORTED_LANGUAGES`'ten çıkarmak `make check`'i kırar. Kararın iki yarısı da
aynı ağırlıkta korunuyor.

Test kaynak metni tarıyor, dosya listesi tutmuyor — dördüncü bir seçici eklenip `uzc`
sunarsa o da yakalanır.

## Geri alma

Üç liste girdisi:

```
Sidebar.vue        { code: "uzc", label: "Ўзбекча" },
Profile.vue        { code: "uzc", label: "Ўзбекча" },
onboarding.py      {"value": "uzc", "label": "Ўзбек"},
```

Artı `test_uzc_retired_from_pickers.py`'nin silinmesi ya da güncellenmesi. Çeviriler
zaten yerinde olduğu için geri dönüş aynı gün mümkün.

**Eksik kalan tek şey:** `Language` kaydı hâlâ hiçbir kiracıda yok. `uzc` yeniden
sunulacaksa **önce o oluşturulmalı**, yoksa aynı `LinkValidationError` geri gelir.

## Kapsam dışı

`uzc.csv` silinmedi, çeviri iş akışı değişmedi, `__init__.py` yamasına dokunulmadı.
`stabler/api/organization.py:506`'daki `_SUPPORTED_LANGUAGES` kümesi (`en, ru, uz,
uzc` — **`tr` yok**) bu turda ele alınmadı; ayrı bir tutarsızlık, ayrı bir iş.
