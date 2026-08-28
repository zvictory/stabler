# UZEX entegrasyonu — go-live doğrulama + prod checklist (WP-309)

**Tarih:** 08.07.2026 · **Kapsam:** WP-300..308 canlıya alma. **Deploy YAPILMADI** (sert sınır).

> **Not:** Aşağıdaki `bench` adımları bu ortamda (app-only mount, DB/bench yok) **koşulmadı**; bunlar **sizin lokal/prod bench'inizde** çalıştıracağınız adımlardır. Beklenen çıktılar + kabul ölçütleri verildi. Dedupe invariant'ı ayrıca kodda statik olarak kanıtlı (aşağıda §A.2).

---

## A. LOKAL DOĞRULAMA (Mac bench — sizin çalıştırmanız)

Site: lokal stabler-bearing site (ör. `stabler.localhost`). Komutları bench kökünden çalıştırın.

### A.1 Migrate + idempotency (v39)
```bash
bench --site <lokal-site> migrate
# Beklenen: hatasız; v39_deal_uzex_fields uygulanır (CRM Deal'e 7 custom_uzex_* alan).
bench --site <lokal-site> migrate
# Beklenen: v39 ATLANIR (tekrar uygulanmaz) → 0 yeni alan. patches.txt [post_model_sync] altında.
```
Kabul: ikinci koşuda yeni alan yok; `bench --site <site> console` →
`frappe.db.get_value("Custom Field", {"dt":"CRM Deal","fieldname":"custom_uzex_lot_no"}, "unique")` → `1`.

### A.2 Poller — canlı dedupe invariant (2 koşu = 0 duplicate Deal)
`site_config.json`'a test değerleri:
```json
{ "uzex_endpoint": "https://apietender.uzex.uz/api", "uzex_keywords": ["kabel", "kompyuter"], "uzex_poll_cap": 20 }
```
```bash
bench --site <lokal-site> execute stabler.tasks.uzex_poll.fetch_and_store
# 1. koşu → {"status":"ok"|"partial","seen":N,"created":X,"updated":0,"notified":..,"errors":[]}
bench --site <lokal-site> execute stabler.tasks.uzex_poll.fetch_and_store
# 2. koşu → created=0 (aynı lotlar zaten var), updated=X. DUPLICATE YOK.
```
Kabul: **ikinci koşu `created=0`**. Doğrula:
```bash
bench --site <lokal-site> execute frappe.db.count --args '["CRM Deal", {"custom_uzex_portal":"etender"}]'
# İki koşu arasında aynı sayı.
```
> **Statik kanıt:** `tasks/uzex_poll.py::_upsert_deal` önce `frappe.db.get_value("CRM Deal", {"custom_uzex_lot_no": lot_no})` ile arar; varsa `update`, yoksa `insert`. `custom_uzex_lot_no` UNIQUE (v39). Yani dedupe DB seviyesinde de garanti. Saf birim testleri: `stabler.tests.test_uzex_parse` (44 uzex testi yeşil).
> **UA/Referer filtresi:** ilk koşuda `errors:[]` değil de `UZEX HTTP 403` görürseniz, portal anonim ajanı filtreliyor → `site_config`'e `"uzex_user_agent": "<tarayıcı UA>"` ekleyin (client zaten `Referer: https://etender.uzex.uz/` gönderiyor).

### A.3 fetch_lot — gerçek lot
```bash
bench --site <lokal-site> execute stabler.api.uzex.fetch_lot --kwargs '{"lot":"https://etender.uzex.uz/lot/500606"}'
# Beklenen: {lot_id, url, lot_no, buyer, bid_deadline, start_price, status, type_name} dolu.
```
(Güncel bir lot deneyin; 500606 kapanmış olabilir — liste ucundan taze bir id alın.)

### A.4 Bid paketi (WP-306)
```bash
# python-docx kurulu mu:
./env/bin/python -c "import docx; print(docx.__version__)"   # yoksa: ./env/bin/pip install python-docx
```
SPA'da bir tender Deal'inde **Bid Pricing → "Başvuru paketini hazırla"**: eksikse `missing[]` uyarısı; tamsa docx Deal'e File olarak eklenir + indirilebilir. docx dd.mm.yyyy tarih + Остаток içermeli.

### A.5 Auto-refresh (WP-305)
Tender board'u (MyTenders/DirectorBoard) aç → tarayıcı Network sekmesi: ~60 sn'de bir `load` XHR tekrarlanır; **sekmeyi arka plana al** → istek durur (document.hidden); geri dön → hemen bir yenileme. Bellek: sayfadan ayrılınca timer temizlenir (kod: `onUnmounted`).

---

## B. PROD CHECKLIST (İNSAN — uygulama YOK)

Deploy prosedürü: **CLAUDE.md → "Deploy procedure (rsync + on-server build)"** ve `deploy_full.sh`. Aşağıdakiler UZEX'e özgü eklemeler.

### B.1 site_config.json anahtarları (**mikas**.erpstable.com)

> Düzeltildi 2026-08-28. Burası 08.07'den beri `anjan.erpstable.com` yazıyordu ve
> yanlıştı — büyük olasılıkla başka bir checklist'ten kopyalanmış varsayılan.
> Ölçüldü, prod, salt-okunur: `module_map_for(c).get("tender")` sekiz kiracının
> yalnız **mikas**'ında `True` (`Mikas`); anjan dahil diğer yedisinde `False`.
> `2026-07-11-master-roadmap.md:43` de mikas diyor ve bu dosyadan 19 gün daha yeni.
> Anahtarlar anjan'a yazılsaydı poller doğru kiracıda hiç açılmazdı ve yanlış
> kiracıda ihale aramaya başlardı — iki hata birden, ikisi de sessiz.
| Anahtar | Zorunlu | Değer |
|---|---|---|
| `uzex_endpoint` | hayır (varsayılan var) | `https://apietender.uzex.uz/api` |
| `uzex_keywords` | **evet** (yoksa yeni lot ingest edilmez) | ör. `["kabel","transformator","kompyuter"]` |
| `uzex_type_ids` | hayır | varsayılan `[1,2,3,5,6]` |
| `uzex_poll_cap` | hayır | varsayılan `50` |
| `uzex_user_agent` | koşullu (403 alınırsa) | tarayıcı UA string |
| `uzex_telegram_token` | Telegram için | bot token |
| `uzex_telegram_chat_id` | Telegram için | kanal/chat id |
| `uzex_telegram_secret` | **evet (webhook açıksa)** | rastgele güçlü secret (WP-308 fail-closed: yoksa webhook TÜM POST'ları reddeder) |

> Token/secret yalnız `site_config.json`'a elle konur; koda/loga girmez. Anonim read API'si için token GEREKMEZ.

### B.2 python-docx (WP-306)
`pyproject.toml`'a `python-docx>=1.1` eklendi. Prod'da:
```bash
cd /home/frappe/frappe-bench && ./env/bin/pip install python-docx
```
Kurulmazsa `bid_package` veriyi + `missing[]` yine döner, sadece docx üretilmez (warning).

### B.3 Telegram webhook (WP-307/308) — opsiyonel
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://anjan.erpstable.com/api/method/stabler.integrations.uzex.webhook.telegram_webhook" \
  -d "secret_token=<uzex_telegram_secret>"
# Telegram bu secret'ı X-Telegram-Bot-Api-Secret-Token başlığında gönderir; webhook fail-closed doğrular.
```

### B.4 Deploy (CLAUDE.md prosedürü)
1. Lokal `bench build --app stabler` (derleme kanıtı).
2. Prod yedeği (tar).
3. rsync (excludes; NO `--delete`) → `chown frappe:frappe`.
4. Prod `bench build --app stabler`.
5. `bench --site anjan.erpstable.com migrate` → **v39 uygular** (yeni patch var → migrate ZORUNLU).
6. `.py` değişti → `bench restart` (tüm tenant'larda kısa blip — düşük trafikte).

### B.5 İlk 48 saat izleme
- **Error Log**: `title` içinde "UZEX poll" arayın (list_trades/upsert/telegram hataları). Sürekli 403 → UA filtresi (`uzex_user_agent` ekleyin).
- **Tazelik**: birkaç Deal'de `custom_uzex_last_synced` son 1-2 saatte olmalı. Eskiyorsa poller portala ulaşamıyor (hook çalışıyor mu? endpoint erişilebilir mi?).
- **Dedupe**: `CRM Deal` içinde aynı `custom_uzex_lot_no` iki kez OLMAMALI (UNIQUE zaten engeller; log'da IntegrityError görülmemeli).
- **Telegram**: yeni lot geldi mi kanala 1 kart; tekrar gelmemeli.

### B.6 Geri alma (rollback)
En hızlısı — `stabler/hooks.py` `scheduler_events["hourly"]` içinde şu satırı yorumlayıp `bench restart`:
```python
# "stabler.tasks.uzex_poll.fetch_and_store",
```
Poller durur; mevcut Deal'ler ve alanlar kalır (veri kaybı yok). Telegram webhook'unu kapatmak için `deleteWebhook` çağırın. Tam geri dönüş = deploy öncesi tar'ı geri yükle (CLAUDE.md).

---

## C. Açık kalan (STATE.md §6)
- **UZEX resmi API başvurusu** — belgelenmemiş uçların sözleşmeyle sabitlenmesi + yazma/gönderim ucu (WP-306 oto-gönderimin ön koşulu).
- **xarid/dxarid** (devlet alımları) — ayrı keşif, muhtemelen auth.
- **WP-304 board chip/countdown** — tender.py board endpoint'lerinin `custom_uzex_*` emit etmesi (takip).
