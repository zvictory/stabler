# Çalıştır — MSA uçtan uca gerçek test (genişletilmiş)

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Sıradan çıkma, her adımın çıktısını bana göster, onay istediğim yerde dur.

---

## Bu ne yapar

`TEST_msa_full_cycle_ext.py` — msa **canlı** sitesinde tüm zinciri gerçek belgelerle
yürütür: PI → PO → CI → konteyner → vet → **çıkış kapısı** → TIR → GRN → Truck Receipt
→ **Purchase Receipt (gerçek stok girişi)** → LCV → FEFO → SO → **Sales Invoice (gerçek
stok çıkışı)**. Ayrıca bu hafta deploy edilen iki kontrolü de kanıtlar:

- **Çıkış kapısı:** TIR `PENDING` oluşturulur, gümrük beyannamesi yokken
  `PENDING → DEPARTED_IRAN` **reddedilmeli**; temiz bir GTD eklenince **açılmalı**.
- **Deniz sapması:** ayrı bir CI konteynerinin önüne geçirilir; `sync_containers_to_ci`
  yalnız **geride** olanı, hattı istasyon istasyon yürüterek eşitlemeli.

## ⚠ Bu prod'a YAZAR — geri alınamaz, sonra temizlenir

ERPNext `submit()` içinde commit eder; script gerçek stok + GL kaydı oluşturur, her
belgeyi anında `/tmp/stabler_e2e_msa_registry.json`'a yazar ve sonunda `cleanup()`
hepsini ters bağımlılık sırasıyla siler. Miktar 240 kg (bariz sentetik), tüm kayıtlar
`ZZE2E` etiketli. Ayrı staging yok — bu msa canlı.

## Adım 1 — dosyayı prod'a kopyala (modül yolu olarak)

```bash
scp TEST_msa_full_cycle_ext.py \
  ice-production:/home/frappe/frappe-bench/apps/stabler/stabler/tmp_e2e.py
```

## Adım 2 — DRY RUN (hiçbir şey oluşturmaz)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute stabler.tmp_e2e.run'
```

Çıktıyı bana göster. Bağlam satırlarında (company / supplier / **batch-tracked item** /
warehouse / customer) hepsinin dolu olduğunu doğrula. Biri boşsa **DUR** — canlı veri
eksik demektir, LIVE koşma.

## Adım 3 — registry temiz mi

```bash
ssh ice-production 'cat /tmp/stabler_e2e_msa_registry.json 2>/dev/null || echo "yok (temiz)"'
```

`[]` ya da "yok" olmalı. Dolu ise önce eski koşumu temizle (Adım 6), sonra devam et.

## Adım 4 — ONAY İSTE

Bana sor: "**msa canlıya yazıp sonra temizleyeyim mi?**" Açık **evet** almadan Adım 5'e geçme.

## Adım 5 — LIVE

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute stabler.tmp_e2e.run --kwargs "{\"dry_run\": 0}"'
```

Tüm çıktıyı bana göster. Beklenen: sonda **`N/N checks passed`** (yaklaşık 30 kontrol,
hepsi PASS). Özellikle şunlar PASS olmalı:

- `2.6 controller REFUSES PENDING->DEPARTED_IRAN while uncleared`
- `2.7 gate OPENS once GTD cleared + vet valid`
- `2b.1 drift detected` · `2b.2 dry-run plans ONLY the lagging container` · `2b.4 container caught up`
- `3.3 truck receipt submitted -> Purchase Receipt` · `3.6 a Batch was created` · `3.7 stock ledger carries the batch`
- `6.2 sales invoice submitted with the received batch` · `6.4 remaining batch balance is correct` (240−100 = **140 kg**)

Herhangi biri FAIL ise: **temizliğe yine de geç** (Adım 6), FAIL satırının detayını bana getir.

## Adım 6 — TEMİZLE (her hâlükârda çalıştır)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute stabler.tmp_e2e.cleanup'
```

Her satır `removed` ya da `gone` olmalı. `FAILED` varsa o doctype+adı bana getir —
elle kapatırız. Sonra registry'nin boşaldığını doğrula:

```bash
ssh ice-production 'cat /tmp/stabler_e2e_msa_registry.json'
```

## Adım 7 — sıfır kalıntı doğrula + scripti sil

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com execute frappe.client.get_list \
  --kwargs "{\"doctype\":\"Commercial Invoice\",\"filters\":{\"ci_number\":[\"like\",\"ZZE2E%\"]},\"fields\":[\"name\"]}"'
ssh ice-production 'rm /home/frappe/frappe-bench/apps/stabler/stabler/tmp_e2e.py'
```

İlk komut boş liste dönmeli (hiç `ZZE2E` CI kalmamış). Aynısını istersen
`Purchase Receipt`/`Sales Invoice` için de bakabilirsin.

## Yapma

- Adım 4 onayını atlayıp doğrudan LIVE koşma.
- FAIL çıksa bile Adım 6 temizliğini atlama — registry'de kayıt kalır.
- Scripti prod'da bırakma (Adım 7'de sil) — `tmp_e2e.py` orada durmasın.
