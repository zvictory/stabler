# Dönem kapanışı — FX yeniden değerleme ve elle girilen USDT kuru

> **Neden bu dosya var:** USDT'nin **otomatik kur kaynağı yok**. `cbu.uz` USDT
> yayınlamıyor, dolayısıyla `stabler.tasks.cbu_rate_refresh` onu yazmıyor
> (`_TRACKED` = USD, EUR, RUB, CNY). ADR-006 gereği USDT masası sıradan bir Cash
> yaprağı olduğundan, bir kiracı **arkasında hiçbir kur olmayan gerçek bir USDT
> bakiyesi** taşıyabilir.
>
> Bu unutulduğunda eskiden ne olurdu: ERPNext eksik kuru hata saymaz.
> `erpnext/setup/utils.py:145-154` Currency Exchange satırı yoksa **0.0** döner,
> `exchange_rate_revaluation.py:264-266` bakiyeyi onunla çarpar
> (`bakiye × 0 = 0`) ve satırın **tamamı** kur zararı olarak yazılır. Yol boyunca
> tek bir exception yok. ADR-009 uyarınca havale FX marjı **yalnızca** yeniden
> değerlemede tanındığı için, uydurma zarar doğrudan kâra iniyordu.
>
> **Artık sessiz değil:** `stabler.api.fx_revaluation.assert_positions_priced`
> (`hooks.py` → `doc_events["Exchange Rate Revaluation"]["validate"]`) böyle bir
> belgeyi **kaydettirmez**. Adımı unutmak kapanışı durdurur; çekmeceyi sıfırlamaz.
> Bu runbook o durdurmanın nasıl açılacağını anlatır.

## Aylık adımlar (dönem sonu)

1. **Günlük kurların boşluğu var mı bak.** CBU kurları otomatik yazılır; hafta
   sonu/tatil ya da bir ağ kesintisi boşluk bırakmış olabilir.

   ```bash
   bench --site <site> execute stabler.tasks.cbu_rate_refresh.fill_gap \
     --kwargs "{'end_date':'<dönem-sonu>'}"
   ```

   `fill_gap` cbu.uz'a **vurmaz** — en son bilinen kuru eksik günlere taşır.
   Arşivden gerçek kur çekmek için `backfill` kullan.

2. **USDT kurunu elle gir.** Dönem sonu tarihli bir **Currency Exchange** kaydı:

   | Alan | Değer |
   |---|---|
   | Date | dönem sonu (ör. `2026-08-31`) |
   | From Currency | `USDT` |
   | To Currency | şirketin ana para birimi (UZS) |
   | Exchange Rate | **o gün masada gerçekten işlem gören USDT/UZS kuru** |
   | For Buying / For Selling | ikisi de işaretli |

   Kur, **USD ile 1:1 varsayılarak türetilmez.** Peg varsaymak bir iş kararıdır
   ve kâra doğrudan yazar; kullanılan kurun kaynağını (hangi masa, hangi kotasyon)
   kapanış dosyasına yaz.

   Bench'ten yazmak istersen — iki yönü de (`USDT→UZS` ve `UZS→USDT`) tek seferde
   yazar, aynı gün için tekrar çalıştırmak no-op'tur:

   ```bash
   bench --site <site> execute stabler.tasks.cbu_rate_refresh._upsert_rate \
     --kwargs "{'from_currency':'USDT','rate':<kur>,'on_date':'<dönem-sonu>'}"
   ```

3. **Yeniden değerlemeyi çalıştır.** Stabler → Money → FX Revaluation, ya da
   `stabler.api.fx_revaluation.create_fx_revaluation`. Önizleme (`list_fx_accounts`)
   kuru olmayan bir bakiyeyi `new_rate = 0` ve devasa bir "loss" olarak gösterir —
   bu, 2. adımın atlandığının işaretidir.

4. **Dönemi kapat.** Kapanış tarihi Stabler Settings'te; kural
   `stabler/api/_period_close.py`, uygulaması `period_close.enforce_on_validate`.

## "Missing exchange rate" hatası aldıysan

Belge kaydedilmedi — **doğru davranış bu.** Mesaj hangi hesabın, hangi para
biriminde, ne kadar bakiyeyle kursuz kaldığını yazar. Yapılacak:

1. Mesajdaki para birimi ve tarih için Currency Exchange kaydını oluştur (2. adım).
   USDT değilse, CBU'nun yayınladığı bir para birimi eksik kalmış demektir —
   `fill_gap` / `backfill` çalıştır.
2. Exchange Rate Revaluation belgesini **yeniden yükle** (kurlar satırlara
   doldurulurken okunur; açık duran belge eski sıfırları taşımaya devam eder).
3. Kaydet.

**Yapılmayacak olan:** guard'ı kapatmak ya da `Exchange Rate Revaluation`
satırını silip kapanışı geçmek. Guard kiracı bazında opsiyonel değildir
(`valuation_guard`'ın aksine) — yakaladığı durumun meşru bir hali yok: içinde
para olan ve kuru olmayan bir satır, bakiyenin tamamını kur zararı yazar.

## Doğrulama

```bash
# Dönem sonunda hangi para birimlerinin kuru var?
bench --site <site> execute frappe.client.get_list \
  --kwargs "{'doctype':'Currency Exchange','filters':{'date':'<dönem-sonu>'},'fields':['from_currency','to_currency','exchange_rate'],'limit_page_length':0}"
```

Beklenen: USD, EUR, RUB, CNY (otomatik) **+ USDT** (elle) — her biri iki yönlü.

## İlgili

- `stabler/tasks/cbu_rate_refresh.py` — günlük CBU kurları, `_TRACKED` listesi,
  `backfill`, `fill_gap`.
- `stabler/api/_fx_revaluation.py::find_unpriced_positions` — kuralın kendisi.
- `stabler/api/fx_revaluation.py::assert_positions_priced` — guard.
- `stabler/tests/test_fx_unpriced_guard.py` — kuralın, kaydın ve davranışın testi.
- `docs/runbooks/install-stabler-on-msa.md` §Scheduled Job Type — zamanlanmış
  işlerin kiracı bazında açık/kapalı listesi.
