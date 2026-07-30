# Deploy prompt — Stabler `8409dab` (funnel v2 + except onarımı + v56–58)

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
Sıradan çıkma, her adımın çıktısını göster, ilk hatada dur.

---

## Adım 0 — ağaç temiz mi

```bash
cd ~/frappe-bench-local/apps/stabler && git log --oneline -1 && git status --short | grep -v '^??' | head
```

Beklenen: HEAD `8409dab`, kirli izlenen dosya **yok**. Kirli dosya varsa bana
listeyi göster ve dur — bu prompt yazıldığında ağaç temizdi; arada başka oturum
çalışmış demektir.

## Ne gidiyor

Prod'un tam hangi commit'te olduğu bilinemez (git yok, rsync ile gidiyor) —
ekranda huni panelinin v1'i göründüğüne göre son deploy `2f1ebbf` civarı.
rsync idempotent: mevcut ağacın tamamı gider. Öne çıkanlar:

**1 · KRİTİK GÜVENLİK AĞI — except onarımı (`52360a6`)**
Bir "ruff format" commit'i 46 dosyada `except (A, B):` yapılarını Python 2
sözdizimine bozmuştu (tender, kassa, bordro, packing, FEFO dahil — modüller
import edilemiyordu). Onarıldı; 1681 test yeşil. Funnel'ı taşıyan önceki
deploy bu onarımı da içeriyorduysa sorun yok — ama Adım 6'da **import
doğrulaması zorunlu**, çünkü bu dosyalar olmadan yarım tenant çalışmaz.

**2 · Tender funnel v2 (`2f1ebbf` + `da41982` + `8409dab`, mikas)**
Director board'un tepesi onaylanan tam tasarım: 4 KPI kartı, faz bantlı ikonlu
akış (SONUÇ? elması + kazanıldı/kaybedildi dalı), veri-kaynağı altyazıları,
sunucudan sayılan sarı rozetler ("N politika altında", "N süre <48s"),
dönüşüm hunisi + lejant. 20 yeni string × 5 dil.

**3 · Imports düzeltmeleri (`8dd1cc2`, `e62647b`, msa)** — PI↔CI eşleme:
boş kategori eşleşme anahtarı değil, başlık PI'ı boş satırlara damgalanır.

## Şema etkisi — migrate GEREKLİ

`patches.txt`'de üç yeni patch var (başka oturumlardan):
`v56_crm_deal_company_scope` · `v57_agreement_management_fields` ·
`v58_ci_item_proforma_backfill`. Hepsi guard'lı/idempotent — yine de
**7 sitenin hepsinde migrate çalıştır** (atlanan site kolonsuz kalır).

## Adım 1 — yedek

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'
```

## Adım 2 — rsync DRY RUN

Bench **`apps/`** dizininden (cwd tuzağı: `apps/stabler/` içinden çalıştırma).
`-v` zorunlu — v'siz dry-run hiçbir şey basmaz ve "temiz" sanırsın.

```bash
cd ~/frappe-bench-local/apps
rsync -rltznv --no-owner --no-group \
  --exclude '.git' --exclude 'node_modules' --exclude 'dist' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.claude' \
  --exclude '.tx_*.json' --exclude 'graphify-out' --exclude '.smoke' \
  --exclude 'tests' --exclude '*.tgz' --exclude '.DS_Store' \
  --exclude '.worktrees' --exclude '.superpowers' --exclude '.obsidian' \
  --exclude 'scratch' \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

Kardeş dizin veya `stable-erp-website/` görürsen **dur**. Özeti bana göster.

## Adım 3 — rsync + chown

Aynı komut `n` ve `v` olmadan (`-rltz`), sonra:

```bash
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
```

## Adım 4 — build

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
```

## Adım 5 — migrate, 7 sitenin HEPSİ

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && for s in anjan dts horeca laminor mikas msa smartbox; do
  echo "=== $s ==="; bench --site "$s.erpstable.com" migrate 2>&1 | tail -4; done'
```

Her site sonucunu göster. Sonra restart:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

(7 tenant'ta kısa kesinti — düşük trafik anı seç.)

## Adım 6 — IMPORT DOĞRULAMASI (bu deploy'un sigortası)

Onarılan 46 modülün canlıda import olduğunu kanıtla — curl HTTP 200 bunu
KANITLAMAZ, gerçek import gerekir:

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com console' <<'PY'
import importlib
mods = [
    "stabler.api.tender", "stabler.api.approvals", "stabler.api.compliance",
    "stabler.api.hr_payroll", "stabler.api.sfa", "stabler.api._fefo",
    "stabler.api._funnel", "stabler.integrations.kassa.bot",
    "stabler.stabler.imports_module.packing_service",
    "stabler.integrations.uzex._parse", "stabler.integrations.bank_statement.match",
]
bad = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:
        bad.append((m, str(e)[:80]))
print("IMPORT FAIL:", bad) if bad else print(f"{len(mods)}/{len(mods)} modul import OK")
PY
```

`11/11 modul import OK` görmeden devam etme.

## Adım 7 — funnel ucunu canlıda doğrula (mikas, salt okuma)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com console' <<'PY'
import frappe, json
frappe.set_user("Administrator")
company = frappe.get_all("Company", pluck="name", limit=1)[0]
from stabler.api.tender import tender_funnel
r = tender_funnel(company)
print("stages :", r["stages"])
print("funnel :", [(f["key"], f["n"]) for f in r["funnel"]])
print("kpi    :", r["kpi"])
print("meta   :", r["meta"])
print("so     :", r["so"])
# durusluk kurali: bir deal tam bir asamada -> acik + won + lost = benzersiz deal sayisi olmali
tot = sum(v for k, v in r["stages"].items())
print("toplam sayim:", tot)
PY
```

Beklenen: `meta` anahtarı var (v2'nin kanıtı), funnel'ın son basamağı = stages
`won` değeri (kaybedilenler son basamağa sayılmaz — tasarım kuralı).

## Adım 8 — tarayıcı (mikas)

`https://mikas.erpstable.com/stabler#/tender/director` — **Sales Manager rollü
kullanıcıyla** (admin değil):

1. En üstte **4 KPI kartı** (açık hat / win-rate K-M / aktif sözleşme / süre riski).
2. **Faz bantları** (Karar · Sourcing — önce maliyet · İhale · Sözleşme & yürütme)
   ve altında ikonlu aşama kartları; kartların altında gri mono veri-kaynağı
   satırları (`go_no_go=go · SQ=0` gibi).
3. **SONUÇ? elması** ve altında soluk "Kaybedildi" kartı.
4. Bir aşama kartına tıkla → ilgili listeye gitmeli (ör. Sourcing → sourcing ekranı).
5. **Dönüşüm hunisi** ayrı kartta: solda trapez huni, sağda lejant (geçiş % + −düşüş),
   en altta Win-rate satırı.
6. Dili ru/uz yap → tüm yeni metinler çevrili görünmeli.

Ayrıca CLAUDE.md standart smoke'u: var olan bir kaydın URL'sini doğrudan aç +
yenile (ör. `…#/purchasing/invoices/<PINV>`) → dolu form gelmeli, boş "New" değil.

## Geri alma

Adım 1 tar'ını geri yükle → `chown` → `bench build --app stabler` →
`bench restart`. v56–58 kolonları kalır, zararsız (kod olmadan okunmaz).

## Yapma

- Adım 2 dry-run çıktısını göstermeden Adım 3'e geçme.
- Adım 5'te site atlama.
- **Adım 6 import doğrulamasını atlama** — 46 dosyalık onarımın canlıda
  çalıştığının tek kanıtı o.
- Tender panelini admin kullanıcıyla "doğruladım" deme — admin her şeyi görür.
