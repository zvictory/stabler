# Paket 3 · Operasyon Masası — rol bazlı günlük iş ekranı

Bu dosyanın tamamını yapıştır. **ONAY yazan yerde dur ve sor.**
`git add -A` YASAK; yol yol stage et. TDD: her adımda önce KIRMIZI gör.
Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`

Tasarım kaynağı: `docs/superpowers/specs/2026-07-30-hierarchical-tender-crm-design.md`
ve onaylanan "Virtual Operations Desk" sunumu.

---

## Neden bu paket, neden şimdi

Sunumu sunum yapan ekran bu: rol seçilir, üstte dört sayaç, solda **bugünkü iş
planı**, sağda **karar/onay kutusu**, altta 7 günlük takvim ve blokajlar.
Bugüne kadarki işler (Tender Master, migrasyon, bugfix'ler) bu ekranın VERİSİNİ
hazırladı; ekranın kendisi hiç yapılmadı. Bu paket onu açar.

## Bu paketin tek mimari kuralı

**Görev kaydı YOK.** Yeni doctype açmıyoruz, hiçbir görev durumu saklanmıyor.
Her satır mevcut belgelerden **deterministik olarak türetilir** — tıpkı
`_funnel.py` ve `_tender_master_state.py` gibi. Sebep: elle tutulan görev
listesi ilk haftada kayar ve pano yalan söyler; ayrıca spec'in kuralı zaten
"panolar kaynak belgelerin projeksiyonudur, iş durumunu kopyalamaz".

Saklanan görev (`Tender Work Item`, erteleme/kişisel not/manuel görev) ayrı bir
pakette, bu ekran gerçek kullanımda oturduktan sonra tartışılacak. **Bu pakette
açma.**

## Görünüm beklentisi (yanlış anlaşılmasın)

Sunum koyu temalıydı; **uygulama Stabler'ın mevcut açık Tabler temasında kalır.**
Eşleşmesi gereken şey renk değil *yerleşim ve içerik*: sayaç şeridi → iş planı +
karar kutusu → takvim/blokaj. CLAUDE.md kuralları aynen geçerli: bölge başına tek
`.btn-primary`, `table-striped` EKLEME, para `MoneyInput`/`font-monospace`,
tarih `formatDate`/`DateInput`, statü `getStatusBadgeClass`, `/app/...` linki YOK.

---

# İŞ 1 — Saf türetme motoru (Frappe'siz)

`stabler/api/_desk_rules.py` — tek işi: olgu listesinden görev satırları çıkarmak.
Frappe import ETME (tıpkı `_funnel.py`).

```python
SEVERITY = ["overdue", "today", "soon", "info"]   # sıralama önceliği

def build_plan(facts: dict, today: str) -> list[dict]
```

`facts` girdisi (API tarafı hazırlar, hepsi hazır veriden):

- `lots`: [{deal, label, parent_tender, lot_no, stage, bid_deadline,
  delivery_deadline, sq_count, assigned_to, result, risk}]
- `orphan_lots`: [{name, organization}]
- `won_without_po`: [deal]
- `po_late`: [{po, supplier, schedule_date, per_received}]
- `unpaid`: [{doctype, name, due_date, outstanding}]
- `approvals`: [{name, reference_doctype, reference_name, requested_by}]

Üretilecek görev tipleri (her biri ayrı `kind`, ayrı test):

| kind | koşul | severity |
|---|---|---|
| `bid_due` | açık lot, `bid_deadline` bugün/geçmiş | overdue/today |
| `bid_soon` | `bid_deadline` ≤ 3 gün | soon |
| `policy_gap` | stage=`sourcing` ve `sq_count` < 5 | today |
| `no_parent` | orphan lot | info |
| `won_no_po` | kazanılmış, PO yok | today |
| `po_late` | `schedule_date` geçmiş, `per_received` < 100 | overdue |
| `invoice_due` | vadesi gelmiş/geçmiş açık fatura | overdue/today |
| `approval_pending` | bana düşen onay | today |

Her satır **şu beş alanı taşımak zorunda** (sunumun kuralı): `title` (ne),
`why` (neden bugün — insan diliyle kanıt: "son tarih 2 gün geçti", "3/5 teklif"),
`owner`, `due`, `route` (ilgili kaydı açan SPA yolu).

Sıralama: severity → due → title. Bilinmeyen/bozuk veri **görev üretmez**
(asla uydurma iş çıkarma), ama sessizce yutulmaz: `skipped` sayacı döndür.

## Testler — `stabler/tests/test_desk_rules.py`

Tablodaki her satır için ayrı test; boş girdi → boş plan; bozuk tarih → skip
sayılır, çökmez; aynı lot iki kurala uyarsa **iki ayrı görev** çıkar (bilinçli:
"teklif topla" ile "son tarih yaklaştı" farklı işlerdir); sıralama determinist.

`.github/frappe-free-tests.txt`'e `stabler.tests.test_desk_rules` ekle.

```bash
python3 -m unittest stabler.tests.test_desk_rules -v   # önce KIRMIZI
```

# İŞ 2 — API: `stabler/api/tender_desk.py`

```python
@frappe.whitelist()
def operations_desk(company: str, view: str | None = None, days: int = 7) -> dict
```

Dönen şekil:

```
{ "counters": {"due_today", "overdue", "awaiting_me", "waiting_others"},
  "plan": [...],          # _desk_rules.build_plan çıktısı
  "decisions": [...],     # onayıma düşenler (approvals.list_pending kohortu)
  "calendar": [{date, items:[...]}],   # önümüzdeki `days` gün
  "team_load": [...],     # SADECE oversight rolü; aksi halde []
  "currency": "...", "view": "...", "generated_at": "..." }
```

Kurallar — mevcut kalıplara **birebir uy**:

- `_require_tender(company)` + `_assert_company_scope(company)` (modül + kiracı kapısı).
- Rol penceresi: `_tender_views()`; `view` verilmişse `_require_tender_view(view, company)`.
  Sourcing kullanıcısı yalnızca **kendine atanmış** lotları görür
  (`sourcing_my_tenders`'daki `oversight` mantığının aynısı); director tümünü.
- `team_load` yalnızca `_is_tender_oversight()` true iken doldurulur.
- **DÖNGÜ İÇİNDE SORGU YOK.** SQ sayıları için `tender_funnel`'daki gruplu
  `sq_counts` kalıbını (`api/tender.py:2174`) kopyala; PO/fatura tarafını da tek
  gruplu geçişle çek. Bunu bir kaynak-tarama testiyle koru
  (`test_tender_funnel_source.py` kalıbı).
- **Frappe v16 tuzağı:** string SELECT içinde `count(x) as n` gibi SQL fonksiyonu
  YOK — düz alan çek, Python'da say. (Canlıda 500 attırır.)
- `has_permission` filtresi her kohortta; izinsiz kayıt hiç görünmez.
- `route` alanları gerçek SPA yollarına çıkmalı: lot → `/tender/crm?deal=...`,
  PO → `/purchasing/orders/<name>`, fatura → `/purchasing/invoices/<name>`.
  **`/app/...` YASAK.**

## Testler — `stabler/tests/test_tender_desk_api.py`

Modül kapalı şirkette `PermissionError`; başka şirketin company argümanı reddedilir;
sourcing kullanıcısı başkasına atanmış lotu görmez; oversight `team_load` alır,
düz kullanıcı almaz (boş liste); sayaçlar `plan` içeriğiyle **birebir tutarlı**
(sayaç ile liste asla çelişmez — spec §9 kabul kriteri); döngü içinde sorgu yok
(kaynak taraması); dönen her `route` `/app/` içermez.

# İŞ 3 — SPA: `pages/tender/OperationsDesk.vue`

Yerleşim (yukarıdan aşağı):

1. **Başlık şeridi**: tarih, şirket, aktif rol rozeti, dönem/`Yenile`.
   Rol seçici yalnızca birden fazla view'ı olan kullanıcıda görünür.
2. **Dört sayaç kartı**: Bugün bitmeli · Geciken · Onayımda · Cevap bekliyor.
   Her biri tıklanabilir → planı o filtreye daraltır (URL query'ye yazılır).
3. **İki kolon**: solda **Bugünkü iş planı** (görev satırları: başlık, `why`
   kanıt metni, sorumlu, son tarih rozeti, satır tıklanınca `route`'a gider),
   sağda **Karar / onay kutusu** (onayıma düşenler; satır ilgili belgeye açar —
   bu pakette onay butonu YOK, sadece görünürlük ve yönlendirme).
4. **Alt şerit**: 7 günlük takvim (gün başına sayı + en kritik iki satır) ve
   oversight rolünde **ekip yükü** tablosu.

Uygulama kuralları:

- Yükleme sırasında `SkeletonRows` — boşlukta spinner YOK.
- Boş durumlar ayrı ve anlamlı: "Bugün için planlanmış iş yok" ≠ "Yetkiniz yok"
  ≠ "Şirket seçilmedi".
- Şirket/rol değişiminde **request-token** kalıbını kullan (Tender CRM'de
  yaptığımız yarış düzeltmesinin aynısı) — eski cevap yeni ekrana yazmasın.
- Filtreler URL query'de tutulur; geri/ileri ve F5 durumu korur.

## Testler

- Vitest kaynak-sözleşmesi (`stabler/tests/operations_desk.test.mjs`):
  request-token var; `/app/` yok; `SkeletonRows` kullanılıyor; sayaç tıklaması
  query yazıyor.
- `test_tender_desk_spa.py`: MoneyInput/`font-monospace`, `formatDate`,
  `getStatusBadgeClass`, bölge başına tek `btn-primary`, `table-striped` eklenmemiş.

# İŞ 4 — Navigasyon, rol görünürlüğü, i18n

- `router.js`: `{ path: "/tender/desk", name: "tender-desk", component: OperationsDesk,
  meta: { title: t("Operations desk"), module: "tender" } }`.
- `Sidebar.vue` `tenderChildren`: **en üste** "Operasyon masası" (`/tender/desk`),
  her tender view'ı için. Paket 2'deki path-tekilleştirme çalışıyor olmalı —
  bozma.
- `TenderNav.vue`: aynı bağlantı, ilk sırada.
- Yeni stringler **5 dilde** (`en,ru,uz,uzc,tr`), **CRLF** ile satır ekle, dosyaları
  yeniden yazma; `test_tender_dashboard_i18n.py` kalıbında anahtar testi ekle.
- Dashboard'a küçük bir giriş: tender açıkken üstte "Operasyon masası" butonu.
  Dashboard'ın kendisini bu pakette YENİDEN YAZMA.

# İŞ 5 — Doğrulama

```bash
python3 -m unittest $(grep -v '^#' .github/frappe-free-tests.txt | grep -v '^$' | tr '\n' ' ') 2>&1 | tail -5
npm run test:js
bench build --app stabler
make check 2>&1 | tail -30
git diff --stat main..HEAD
```

`make check` çıktısını **ikiye ayır**: (a) bu paketin ürettiği → düzelt,
(b) dalda önceden var olan borç → dokunma, raporla.

Sonra dal bütününü `pr-review-toolkit:code-reviewer` ile incelet. Odak: döngü
içinde sorgu yok; sayaç–liste tutarlılığı; rol/şirket sızıntısı yok; `/app` linki
yok; para/tarih/statü kuralları. **Bulguları bana getir.**

---

# Deploy — ONAY sonrası

Yeni doctype ve patch **YOK** → `migrate` gerekmez. `.py` değişti → `bench restart`
var (tüm bench'i kısa etkiler, düşük trafikte koş).

```bash
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'

cd ~/frappe-bench-local/apps
rsync -rltzvn --no-owner --no-group --exclude-from=stabler/.rsync-exclude \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

**Dry-run çıktısını göster, ONAY bekle.** `-v` zorunlu (`-n` tek başına hiçbir şey
basmaz; boş çıktı "temiz" sanılır). Silme listesinde kardeş dizin veya
`stable-erp-website/` görürsen DUR. Ana worktree'daki başka oturuma ait kirli
dosyalar rsync'e girer — listede `sales.py`, `Customers.vue`, `MoneyInput.vue`
görürsen DUR ve bana sor.

# Duman testi (tarayıcı)

**mikas** — director rolüyle:
1. `#/tender/desk` açılıyor; dört sayaç dolu; iş planı satırlarında `why` kanıt
   metni görünüyor ("son tarih 2 gün geçti" gibi).
2. Bir plan satırına tıkla → doğru kayda gidiyor (lot/PO/fatura).
3. Sayaç kartına tıkla → plan daralıyor, URL query'ye yazılıyor, F5 sonrası
   filtre korunuyor.
4. Sayaçtaki sayı, daralan listenin satır sayısıyla **birebir aynı**.
5. Ekip yükü tablosu görünüyor (oversight).
6. Sidebar ve TenderNav'da "Operasyon masası" **tek** satır.

**msa**: `#/tender/desk` erişilemez (modül kapısı).
**anjan**: menüde yok, doğrudan URL engelli.

Sonuçları ekran görüntüleriyle getir.

# Yapma

- `Tender Work Item` / görev doctype'ı AÇMA — bu pakette türetme var, saklama yok.
- Dashboard'ı yeniden yazma; onay butonu ekleme (sadece görünürlük).
- Döngü içinde sorgu, string SELECT'te SQL fonksiyonu.
- Çeviri CSV'lerini toptan yeniden yazma (CRLF!); `translations/` dizinini toptan
  stage etme — beş CSV'yi adıyla ekle.
- Onaysız gerçek rsync; kirli dosyaları stage etme.
