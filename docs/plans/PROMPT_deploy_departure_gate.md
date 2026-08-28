# Deploy prompt — Stabler `36c36b6`

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Sıradan çıkma, ilk hatada dur.

---

## ⚠ Adım 0 — ÖNCE BUNU OKU: rsync commit'i değil, çalışma ağacını gönderir

Bu deploy git tabanlı değil. `rsync` diskteki dosyaları kopyalar — commit edilmiş
olup olmadıklarına bakmaz. Şu anda ağaçta **commit edilmemiş 8 dosya** var ve
rsync onları da prod'a taşır:

| Dosya | Boyut |
|---|---|
| `stabler/public/js/pages/inventory/Items.vue` | +399 / −11 |
| `stabler/www/kassa.html` | +384 / −220 |
| `stabler/maintenance/migrate_msaerp_imports.py` | +59 / −29 |
| `stabler/integrations/kassa/_smart.py` | +43 / −39 |
| `stabler/integrations/kassa/shadow_flow.py` | +13 / −9 |
| `stabler/integrations/kassa/bot.py` | +6 / −11 |
| `stabler/api/_accounts.py` | +3 / −2 |
| `stabler/public/js/router.js` | +2 |

Bunlar bu deploy'un konusu değil — başka bir oturumun yarım işi. `Items.vue` ve
`kassa.html` küçük değil; ikisi de canlı ekran.

**Önce şunu çalıştır ve çıktıyı bana göster:**

```bash
cd ~/frappe-bench-local/apps/stabler && git status --short | grep '^ M'
```

Sonra bir karar ver ve söyle:

- **(a) Hazırlarsa commit et** — sahibine sor, bitmiş iş ise commit'le, sonra deploy et.
- **(b) Bekletecekse ayır** — `git stash push -- <yollar>` ile ağaçtan çek, deploy et,
  sonra `git stash pop`. Temiz yol budur.
- **(c) Bilerek gönder** — sadece o dosyaların çalıştığını biliyorsan.

**Karar verilmeden Adım 2'ye geçme.** Sessizce (c)'yi seçme.

---

## Ne gidiyor

Prod `f291556`'da. Aradaki **18 commit**, dört öbek:

**1 · TIR çıkış kapısı (yeni, msa) — `9d17932`, `2f160e4`**
Bugüne kadar herhangi bir TIR `PENDING → DEPARTED_IRAN`'a geçebiliyordu; gümrük
beyannamesi ve veteriner sertifikası kontrol edilmiyordu. Artık CI genelinde
ya hep ya hiç kapı var, Imports Manager gerekçeli override yapabiliyor, ve TIR
formu engelleri önceden listeliyor.

**2 · Ortak deniz yaşam döngüsü (yeni, msa) — `36c36b6`**
`Commercial Invoice` ile `Import Container` **aynı** durum hattını
(`BOOKED → … → DELIVERED_TO_UZBEKISTAN`) ayrı ayrı elle taşıyor. Tek sefer, iki
kopya — ve ayrıştıklarında kimse fark etmiyor. Bu commit sahipliği belirliyor
(CI seferin sahibi, konteynerler onu izler) ama **henüz zorlamıyor**:

- CI ekranında sapma paneli: kaç konteyner geride, hangisi ileride.
- "Konteynerleri ilerlet" butonu — önce dry-run, sonra onay, sonra uygula.
- Sadece **geride** olanı iter; **ileride** olanı asla geri almaz (o bir çelişki,
  insan çözer). İptal edilmiş konteynere dokunmaz.
- Hattı istasyon istasyon `doc.save()` ile yürür, böylece konteyner
  controller'ının kendi geçiş kuralları çalışmaya devam eder.
- **Hiçbir hook'a bağlı değil** — otomatik sync, sapmanın ne kadar kötü olduğunu
  kimse bakamadan silerdi. Önce ölçelim.

Şema değişikliği yok; var olan alanları okuyor.

**3 · FEFO / raf ömrü okuma uçları — `3049dd3`**
`batch_availability`, `suggest_fefo`, `expiring_batches`. Salt okunur, henüz
UI'a bağlı değil.

**4 · Tender panosu (mikas) — 13 commit**, Codex'ten merge edilmiş: yaşam
döngüsü toplamları, adaptif operasyon panosu, drilldown izinleri, yürütme
toplamları hizalaması.

Ayrıca karar kaydı belgesi (`docs/plans/2026-07-23-msa-open-decisions.md`) ve
çeviri tamamlamaları (5 dil).

## Şema etkisi — bu sefer VAR

`patches.txt`'ye **`v55_departure_gate`** eklendi. Üç yeni custom field:

- `Customs Declaration.required_for_departure` (Check, **varsayılan 1**)
- `Import Truck.departure_override` (Check)
- `Import Truck.departure_override_reason` (Small Text)

→ **`bench migrate` GEREKLİ ve her stabler sitesinde çalıştırılmalı.** Patch
idempotent; kolon eklemekten başka bir şey yapmıyor, veri yazmıyor.

**Varsayılanın 1 olması bilinçli:** var olan bir beyanname önemli sayılır.
Birini isteğe bağlı işaretlemek bilinçli bir eylemdir; işaretlemeyi unutmak
kapıyı sessizce açmamalı.

## Adım 1 — yedek

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'
```

## Adım 2 — rsync DRY RUN

Bench **`apps/`** dizininden. `apps/stabler/` içinden çalıştırırsan `stabler/`
iç Python modülüne çözülür ve sahte toplu silme listesi üretir.

```bash
cd ~/frappe-bench-local/apps
rsync -rltzn --no-owner --no-group \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.claude' \
  --exclude '.tx_*.json' --exclude 'graphify-out' --exclude '.smoke' \
  --exclude 'tests' --exclude '*.tgz' --exclude '.DS_Store' \
  --exclude '.worktrees' --exclude '.superpowers' --exclude '.obsidian' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

Kardeş dizin veya `stable-erp-website/` görürsen **dur**. Özeti göster.

Listede Adım 0'da karar verdiğin dosyaların **beklediğin gibi** olduğunu doğrula:
stash'ladıysan `Items.vue` ve `kassa.html` listede olmamalı.

## Adım 3 — rsync + chown

Aynı komut `n` olmadan (`-rltz`), sonra:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## Adım 4 — build

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## Adım 5 — migrate, stabler sitelerinin HEPSİ

`migrate` site bazlıdır; rsync ve restart bench genelinde. Atlanan sitede
`required_for_departure` kolonu olmaz. Kod bunu tolere ediyor (o durumda **her**
beyannameyi zorunlu sayar, yani kapı daha sıkı çalışır, açılmaz) — ama yine de
hepsini migrate et.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  echo "=== $s ==="; bench --site "$s" migrate 2>&1 | tail -4; done'
```

Her site için sonucu göster.

## Adım 6 — restart

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

Her kiracıda kısa kesinti — düşük trafikli bir an seç.

## Adım 7 — alanlar yerinde mi

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in $(ls sites | grep "\."); do
  bench --site "$s" list-apps 2>/dev/null | grep -q "^stabler" || continue
  printf "%-28s " "$s"; bench --site "$s" execute frappe.db.has_column \
    --kwargs "{\"doctype\":\"Customs Declaration\",\"column\":\"required_for_departure\"}" 2>&1 | tail -1; done'
```

Listelenen her site `True` dönmeli.

## Adım 8 — kapıyı canlıda doğrula (msa)

Yazma yok, sadece okuma:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
import frappe
from stabler.stabler.imports_module import departure_math as dm
from stabler.api import imports as api

# saf kural
print("bos beyanname engel mi:", [b["code"] for b in dm.departure_blockers([], vet_valid=True)])
print("onayli+tarihsiz temiz mi:", dm.is_cleared({"status":"Approved","cleared_date":None}))
print("gerekcesiz override:", dm.may_depart([], vet_valid=True, override=True, override_reason="")["allowed"])

# canli bir TIR uzerinde onizleme
t = frappe.db.get_value("Import Truck", {"status": "PENDING"}, "name")
print("\nPENDING TIR:", t)
if t:
    r = api.truck_departure_status(t)
    print("  gated:", r["gated"], "| allowed:", r["allowed"])
    print("  blockers:", [b["code"] for b in r["blockers"]])
    print("  vet_valid:", r["vet_valid"], "| beyanname sayisi:", len(r["declarations"]))
PY
```

Beklenen: `['no_required_declaration']`, `False`, `False`. Canlı bir TIR varsa
`gated: True` ve engeller listelenmiş olmalı.

## Adım 9 — deniz sapmasını ÖLÇ (msa) — bu deploy'un asıl kazancı

Hâlâ yazma yok. Bu, "CI ile konteynerler ne kadar ayrışmış" sorusunun ilk kez
sayıyla cevaplandığı yer. **Çıktıyı bana ham haliyle göster** — sonraki adım
(konteyner durumunu tamamen kaldırmak) bu sayıya bakarak kararlaştırılacak.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
import frappe
from stabler.stabler.imports_module import sea_lifecycle as sl

cis = frappe.get_all("Commercial Invoice", fields=["name","status"], limit_page_length=0)
tot = {"aligned":0,"behind":0,"ahead":0,"cancelled":0,"unknown":0}
drifted, worst = 0, []
for ci in cis:
    cnts = frappe.get_all("Import Container",
        filters={"commercial_invoice": ci.name},
        fields=["name","container_number","status"], limit_page_length=0)
    if not cnts:
        continue
    s = sl.summarise(ci.status, cnts)
    for k in tot: tot[k] += s[k]
    if not s["in_sync"]:
        drifted += 1
        worst.append((s["behind"] + s["ahead"], ci.name, ci.status, s["behind"], s["ahead"]))

print("CI sayisi           :", len(cis))
print("Sapmali CI          :", drifted)
print("Konteyner durumlari :", tot)
print("\nEn kotu 10 CI (sapan konteyner sayisina gore):")
for n, name, st, b, a in sorted(worst, reverse=True)[:10]:
    print(f"  {name:24} CI={st:24} geride={b} ileride={a}")
PY
```

Okuma notu:

- **`ahead` > 0 ise dikkat.** Konteyner, faturasından ileride olamaz — bu bir
  çelişki, eskimişlik değil. Sayı büyükse durum alanlarından biri yanlış
  yönetiliyor demektir ve bunu elle düzeltmeden otomatikleştirme.
- `behind` yüksekse bu beklenen durum: kimse konteynerleri güncellemiyor.
- `unknown` > 0 ise hattın dışında bir durum değeri var — hangisi olduğuna bak.

## Adım 10 — tarayıcı

`https://msa.erpstable.com/stabler#/imports/trucks` → `PENDING` durumda bir TIR aç.

1. Üstte sarı uyarı paneli: **"Bu araç henüz İran'dan çıkamaz:"** ve altında
   engel maddeleri.
2. **DEPARTED_IRAN butonu devre dışı.** Cancel ve Roll back butonları normal.
3. Gümrük sayfasında o CI'ın beyannamesini `Approved` + `cleared_date` yap,
   veteriner sertifikasını `Approved` + ileri tarihli yap, TIR sayfasını
   yenile → panel kaybolur, buton aktifleşir.
4. Dil değiştir (ru/uz) → uyarı metinleri çevrilmiş görünmeli.

Sonra bir CI aç (`#/imports/commercial-invoices/<Adım 9'daki en kötü CI>`) →
Lojistik hazırlık kartında **gemi ikonlu sarı panel** görünmeli: "Konteynerler
fatura sefer durumuyla uyuşmuyor", altında geride/ileride konteyner listesi.

**"Konteynerleri ilerlet"e Adım 9 çıktısını bana göstermeden basma.** Buton
gerçekten yazıyor — önce dry-run onay ekranı çıkar, orada kaç konteynerin hangi
duruma geçeceğini gösterir; onaylarsan uygular.

Ayrıca mikas'ta tender panosunu aç (`#/tender/...`) — 13 commit oradan geliyor,
en azından sayfanın açıldığını ve sayıların geldiğini gör.

## Geri alma

Adım 1'deki tar'ı geri yükle, `chown`, `bench build --app stabler`,
`bench restart`. Custom field'lar kalır ama zararsızdır — kod olmadan kimse
okumaz. Tamamen temizlemek istersen üç `Custom Field` kaydını sil.

Deniz yaşam döngüsü tarafında geri alınacak veri yok — hiçbir şey yazmıyor
(sen Adım 10'da butona basmadıysan).

## Yapma

- **Adım 0'ı atlama.** Commit edilmemiş 8 dosya hakkında karar vermeden rsync yapma.
- Adım 2 çıktısını göstermeden Adım 3'e geçme.
- Adım 5'te bir siteyi atlama.
- Adım 8'deki üç saf kural kontrolünü atlama — kapının gerçekten kapalı
  olduğunu kanıtlayan tek şey o.
- Adım 9'un çıktısını göstermeden "Konteynerleri ilerlet"e basma.
