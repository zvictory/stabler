# Prod deploy hazırlığı — 2026-09-06 (f3dd3c8 → main)

Hazırlayan: Claude, 2026-09-06 gece. **Deploy'u Zafar çalıştırır** (`deploy_stabler.sh`
ajana kapalıdır; tek `bench restart` sekiz stabler tenant'ını aynı anda blipler). Bu belge
ölçülen ön koşulları, aralığın deploy sonuçlarını ve sürüme özgü duman testlerini toplar.
Betiğin kendi adımları (yedek, dry-run, rsync, build, migrate kararı, restart, clear-cache,
probe) burada tekrarlanmaz — `deploy_stabler.sh` ve `stabler-deploy` becerisi yetkilidir.

## 1. Aralık

| | |
|---|---|
| Prod damgası (`apps/stabler/.stabler-migrated-sha`, ölçüm 2026-09-06) | `f3dd3c8` |
| Hedef | `main` — hazırlık anında `99d413d`; **çalıştırmadan önce `git rev-parse HEAD origin/main` ile yeniden okuyun**, başka bir oturum aynı checkout'ta `main`'e birleştirip push ediyor |
| Aralık | 25 commit (merge'siz), 127 dosya, +5115 / −183 |
| İçerik | 2026-09-05 Mikas yürüyüşünün 11 kod bulgusu + inceleme takibi A–H + `get_deal` şirket düzeltmesi + iki formun dirty-guard tabanı + purchasing.py'de kalan ham `throw`'lar + Typeahead varsayılanları + UAT/plan belgeleri |

Kapılar: her birleşmede `make check` yeşil; `make test-bench` main `ac81631` üzerinde 79 modül,
çıkış 0, FAIL/ERROR yok. `ac81631` sonrası üç commit yalnız Vue/spec/docs (Typeahead
`noResultsText`, SO create-form tabanı, UAT notları) — bench testi gerektiren kod değil.

## 2. Deploy sonuçları (dosya türünden türetildi, `git diff --name-only f3dd3c8 99d413d`)

| Değişen | Sonuç | Betikte |
|---|---|---|
| `stabler/api/{imports,lcv,money,purchasing,sales,sourcing,tender,tender_dimension}.py` | **`bench restart` şart** (bench geneli, tüm tenant'lar) | adım 6, sorar — **evet** |
| `stabler/translations/{en,ru,uz,uzc,tr}.csv` | **`clear-cache` her stabler sitesinde** (Redis 1 saat tutar, restart silmez) | adım 6b, otomatik, siteleri keşfeder |
| doctype JSON / `patches.txt` / `patches/` / `fixtures/` / `hooks.py` | **yok** → migrate gerekmez | adım 5 "Skipping migrate" der ve damgayı HEAD'e yazar |
| `package.json` / `package-lock.json` | değişmedi; prod `.stabler-deps-md5` = yerel md5 `c6b24e3f…` | adım 4 "nothing to install" der |
| 20 Vue/JS (test dışı) | `bench build` prod'da, .map'ler silinir | adım 4 |
| `docs/`, `.github/`, `tests/` | rsync dışı (`.rsync-exclude`) | — |

## 3. Ölçülen ön koşullar (2026-09-06, salt okunur)

- Stabler taşıyan siteler, `list-apps` ile: `anjan, dts, horeca, laminor, mikas, msa, smartbox, zuma`
  (8). Sayı hâlâ 8; yine de betik keşfeder, liste hardcode değildir.
- Prod `node_modules` mevcut, damga yerel manifestlerle aynı. Prod bundle `IEYKAVCU`, `.map` yok.
- `/root` 118G boş; en yeni yedek `/root/stabler-app-2026-09-04-2029.tgz`.
- `supervisorctl status`: redis-cache, redis-queue, web, socketio, iki long-worker, schedule, iki
  short-worker → hepsi RUNNING.
- Yerel canary: `bench build --app stabler` main `99d413d` üzerinde çıkış 0 (`UQ3HINCC`).
- Yerel ağaç temiz, `main == origin/main == github/main`.
- `make prod-drift` (deploy öncesi taban): prod'da git'te olmayan **4 dosya** —
  `stabler/public/js/pages/tender/{TenderCrmWrapper,TenderExecutionFlow,TenderExecutiveKpis,TenderTrendChart}.vue`.
  Önceki deploy'lardan kalan artıklar (rsync `--delete` kullanmaz); bu sürümle ilgisi yok, bundle'a
  girmezler (esbuild yalnız giriş noktasından içe alınanları derler). Silmek ayrı bir karar: önce yedek,
  sonra `ls`, sonra kaldır — hedefin kendi uyarısı. Deploy sonrası `make prod-drift` yine bu dördü
  listelemeli, fazlası çıkarsa rsync beklenmedik bir şey göndermiştir.

## 4. Çalıştırma (Zafar)

```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
git status --porcelain            # boş olmalı
git rev-parse HEAD origin/main    # aynı olmalı; sha'yı not edin — bu sürümün kimliği
bash deploy_stabler.sh
```

Betiğin soracakları:
1. **"Ship exactly the file list above?"** — dry-run listesini okuyun. `deleting`, `stable-erp-website/`,
   `professional-excel-export/`, `recon/` görünürse betik zaten durur; görünmezse evet.
2. **"Proceed with bench restart now?"** — `.py` değişti, restart şart; düşük trafikte **evet**.
   Hayır derseniz Python tarafı eski kodla çalışır ve CSV temizliği yapılmış olur; en kısa sürede
   `ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench restart'`.

Eşzamanlılık notu: bu checkout'ta başka bir oturum `main`'e birleştiriyor. Betik `git archive HEAD`
gönderir; komutu çalıştırdığınız andaki HEAD gider. Deploy sırasında yeni birleşme olmasın diye
sha'yı önce sabitleyin (yukarıdaki `rev-parse`) ve deploy bitene kadar birleşmeyi bekletin.

## 5. Deploy sonrası — sürüme özgü duman testleri

Betiğin genel testleri (kayıt formuna doğrudan URL + yenileme, ödeme günlüğü, `make prod-drift`)
aynen geçerli. Bu sürüme özgü olanlar:

**Çeviri önbelleği gerçekten yenilendi mi** (her sitede bir anahtar okuyun; boş dönerse
`clear-cache` o siteye uğramamıştır):
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  sudo -u frappe bench --site "$s" list-apps 2>/dev/null | grep -qw stabler || continue
  printf "%s: " "$s"
  sudo -u frappe bench --site "$s" execute stabler.www.stabler._load_translations --args "[\"ru\"]" 2>/dev/null \
    | env/bin/python -c "import sys,json; print(json.load(sys.stdin).get(\"Bill No.\") or \"MISSING\")"
done'
```
Beklenen: stabler taşıyan her site için bir satır, değeri `Номер счета` (siteler betikteki gibi
`list-apps` ile keşfedilir, sabit liste `make guards`'a takılır; yerel sitede aynı okuma bu değeri verdi; `bench execute` çıktısı
`\uXXXX` kaçışlı JSON'dur, o yüzden `grep` değil `json.load`).

**Mikas (ihale modülü, RU arayüz)** — hepsi salt okunur gezinti:
- `#/purchasing/invoices/new` açıp dokunmadan çıkın: "kaydedilmemiş değişiklik" uyarısı **yok**;
  "Номер счета", "Дата выставления счета", "Обновить запасы" Rusça.
- `#/purchasing/orders/new` aynı: uyarı yok; seçici yer tutucuları "Поиск…" ailesinde.
- Gönderilmiş bir RFQ varsa liste ve detay rozeti "Отправлен" (yoksa "Черновик" kalır — bu doğru).
- Bir satış faturası detayı: "Связанные документы" altında bağlı SO; ihaleye damgalıysa "Тендер"
  satırı `kurum · anlaşma` etiketiyle.
- Bir satın alma faturası detayı: bağlı PO ve PR; "Make payment" gönderilmiş ve ödenmemişse görünür.
- Gider detayı (ihale damgalı bir JE): "Тендер" satırı.

**anjan (ikincil doğrulama, ihale kapalı)**: PO/PI/SO/SI detayları eski gibi açılıyor, KPI'lar dolu,
"Тендер" satırı damgasız belgede **görünmüyor** (`v-if`). Sourcing/RFQ rotaları modül kapalıysa zaten
menüde yok.

**Sunucu tarafı, salt okunur** (mikas):
```bash
ssh ice-production 'cd /home/frappe/frappe-bench && sudo -u frappe bench --site mikas.erpstable.com execute stabler.api.sourcing.list_all_rfqs --kwargs "{\"company\":\"Mikas\"}"' | head -c 600
```
Satırlarda `sent_count` anahtarı olmalı (0 da olur; anahtarın varlığı yeni kodun çalıştığını gösterir).

## 6. Geri alma

Adım 2'nin tar'ı + `chown` + `bench build` + `bench restart` (beceride yazılı). Bu sürümde **migrate
çalışmadı**, şema ve veri değişmedi; kod geri alımı bu kez gerçekten "önceki durum"dur. CSV'ler de
tar ile geri gelir → geri alımdan sonra her sitede yeniden `clear-cache`, yoksa Redis yeni
çevirileri bir saat daha gösterir.

## 7. Bilinen açık noktalar (deploy'u engellemez)

- PO seçicisi artık PI/gider seçicileriyle aynı "bitmiş ihale" kuralında: bütün SO'ları Closed olan
  kazanılmış ihale sunulmaz, `?deal=` ile gelen ön dolum yine çalışır (UAT G.7 notu).
- `?deal=` ön dolumuyla açılan PO'dan çıkışta "kaydedilmemiş değişiklik" uyarısı çıkar.
- RU ekranda kalan İngilizceler: "New Purchase Order · Stabler" sekme başlığı, RelatedDocuments grup
  başlıkları ("Sales Orders"), "Поражений" (crm/erpnext kataloğundan gelir, stabler CSV'si ezmez).
