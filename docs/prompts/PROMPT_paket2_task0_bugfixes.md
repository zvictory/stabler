# Paket 2 · İki canlı bugfix: sidebar çift "Tender CRM" + PO-teklif farkı para birimi

Bu dosyanın tamamını yapıştır. **ONAY yazan yerde dur ve bana sor.**
`git add -A` YASAK; yol yol stage et. Test-önce (TDD): önce KIRMIZI gör, sonra düzelt.
Kaynak plan: `docs/superpowers/plans/2026-07-30-tender-sourcing-rfq-award.md` → Task 0.

Ana worktree'da başka oturuma ait kirli dosyalar var (`sales.py`,
`composables/date.js`, `MoneyInput.vue`, `Customers.vue`, `purchasing.py`,
`CommercialInvoiceForm.vue`, `ProformaForm.vue`, `Suppliers.vue` vb.) —
**bunlara dokunma, stage etme.** İstersen ayrı worktree aç
(`.worktrees/` kalıbı), ama değişiklik iki dosyayla sınırlı olduğu için
ana worktree'da dikkatli çalışmak da kabul.

---

## BUG 1 — Sidebar'da "Tender CRM" iki kez

`stabler/public/js/components/Sidebar.vue` (~44-50): `tenderChildren` listesinde
`/tender/crm` hem `director` hem `sourcing` view'ı için ayrı satır. İki role birden
sahip kullanıcıda (Zafar dahil) menüde çift girdi çiziliyor — canlıda görüldü.

### 1.1 Önce test (KIRMIZI)

`stabler/tests/test_tender_sidebar_navigation.py` mevcut kalıbı source-contract:
dosyayı okuyup string assert ediyor. Şunu ekle:

- `tenderChildren` hesabının role filtresinden SONRA **path bazlı tekilleştirme**
  içerdiğini assert et (ör. `dedupeByPath` / `seen.has(item.path)` gibi bir iz).
- Mevcut testlerin hiçbirini değiştirme/silme.

```bash
python3 -m unittest stabler.tests.test_tender_sidebar_navigation -v   # KIRMIZI gör
```

### 1.2 Düzeltme

Filtreden sonra path'e göre tekilleştir; sıra korunmalı (ilk görülen kazanır):

```js
const seen = new Set();
... .filter((item) => session.tenderViews.includes(item.view))
    .filter((item) => (seen.has(item.path) ? false : (seen.add(item.path), true))
```

(İstersen computed içinde ayrı küçük helper — ama Vue reaktivite tuzağına dikkat:
`seen` computed'ın İÇİNDE tanımlanmalı, her yeniden hesaplamada sıfırlanmalı.)

Görsel davranış: director+sourcing kullanıcı tek "Tender CRM" görür; yalnızca
sourcing kullanıcı yine görür (satırı silme, tekilleştir).

## BUG 2 — PO-teklif farkı karışık para biriminde

`stabler/api/tender.py` `po_control_board` (~601-627):

- `q_by_supplier` SQ **`grand_total`** topluyor (teklifin KENDİ para birimi — USD
  teklif + UZS teklif toplanıyor);
- `delta = (s["po_total"] - qt) / qt` → `po_total` da PO para birimi;
- frontend (`PoControlBoard.vue` ~440) bu sayıyı **şirket para birimiyle** basıyor.

Sonuç: farklı para birimli tekliflerde hem tutar hem `delta_pct` anlamsız.

### 2.1 Önce test (KIRMIZI)

`stabler/tests/` içinde uygun dosyaya (mevcut kalıba göre
`test_tender_dashboard_behavior.py` ya da `test_tender_funnel_source.py` tarzı
yeni `test_po_control_currency_source.py`) source-contract ekle:

- SQ sorgusunun `fields` listesinde `base_grand_total` bulunduğunu;
- `q_by_supplier` toplamının `base_grand_total` (fallback `grand_total`) üzerinden
  yapıldığını;
- `delta` hesabının PO tarafında `base_po_total` kullandığını assert et.

Yeni test modülü açtıysan `.github/frappe-free-tests.txt`'e ekle.

### 2.2 Düzeltme

```python
fields=["supplier", "grand_total", "base_grand_total"],
...
q_by_supplier[q.supplier] = q_by_supplier.get(q.supplier, 0.0) + (
    flt(q.base_grand_total) or flt(q.grand_total)
)
...
delta = ((s["base_po_total"] - qt) / qt * 100) if qt else None
```

- `quotation_total` alan adı ve API şekli DEĞİŞMEZ (frontend zaten `ccy` ile
  formatlıyor — artık doğru para birimini basacak).
- `sales/SourcingCompare.vue` ve `purchasing.tender_quotations`'a DOKUNMA —
  orası zaten `base_grand_total` kullanıyor.
- v16 tuzağı: string SELECT'te SQL fonksiyonu yok — düz alan çek, Python'da topla.

## Doğrulama (yerel)

```bash
python3 -m unittest $(grep -v '^#' .github/frappe-free-tests.txt | grep -v '^$' | tr '\n' ' ') 2>&1 | tail -5
npm run test:js
bench build --app stabler        # derleniyor mu
git diff --stat                  # SADECE 2 kaynak + test dosyaları görünmeli
```

Sonuçları bana göster. **ONAY sonrası** commit:

```bash
git add stabler/public/js/components/Sidebar.vue \
        stabler/api/tender.py \
        stabler/tests/test_tender_sidebar_navigation.py \
        <yeni/degisen test dosyasi> \
        .github/frappe-free-tests.txt   # sadece değiştiysen
git commit -m "fix(tender): dedupe sidebar children by path; compare vendor deltas in company currency

A director+sourcing user saw 'Tender CRM' twice — the role filter kept one row
per view for the same path. And po_control_board summed mixed-currency SQ
grand_totals against PO totals while the UI formatted the result as company
currency; both sides now use base amounts.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

# Deploy (CLAUDE.md prosedürü — .py değişti → restart VAR)

Şema/patch değişikliği YOK → **migrate GEREKMEZ**. Restart tüm bench'i kısa
etkiler → **düşük trafik saatinde koş ya da bana saat sor.**

```bash
# 1) yedek
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler && ls -lht /root/stabler-app-*.tgz | head -1'

# 2) dry-run — apps/ DİZİNİNDEN, -v ZORUNLU; silme listesinde kardeş dizin /
#    stable-erp-website görürsen DUR
cd ~/frappe-bench-local/apps
rsync -rltzvn --no-owner --no-group --exclude-from=stabler/.rsync-exclude \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
```

**Dry-run çıktısını bana göster — ONAY bekle.** DİKKAT: ana worktree'daki
başka oturuma ait kirli dosyalar rsync'e GİRER (rsync working tree kopyalar,
commit değil). Dry-run listesinde `sales.py`, `Customers.vue` vb. görürsen DUR
ve bana sor — gerekirse temiz bir worktree'dan/stash sonrası rsync planlarız.

```bash
# 3) ONAY sonrası gerçek rsync + build + restart
rsync -rltz --no-owner --no-group --exclude-from=stabler/.rsync-exclude \
  stabler/ ice-production:/home/frappe/frappe-bench/apps/stabler/
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler'
ssh ice-production 'cd /home/frappe/frappe-bench && bench restart'
```

# Duman testi (tarayıcı)

1. mikas `#/tender/crm` → sidebar Tender grubunda "Tender CRM" **tek** satır;
   Control Tower / My tenders / Vendor & PO / Customs / Logistics yerli yerinde.
2. mikas `#/tender/po-control?deal=<SQ'lu bir deal>` → vendor karşılaştırmada
   Quotation kolonu şirket para biriminde mantıklı tutar; `delta_pct` uçuk değil.
3. mikas `#/tender/sourcing?deal=<aynı deal>` → regresyon yok (bu ekrana dokunmadık).
4. Bir kayıt formunu doğrudan URL + F5 ile aç → dolu geliyor (standart kontrol).
5. msa `#/purchasing/suppliers` → defter açılıyor (restart sonrası genel sağlık).

Sonuçları ekran görüntüleriyle raporla. Hata varsa DUR; rollback = adım 1 tar'ı
geri yükle → chown → bench build → bench restart.

# Yapma

- İki bugfix dışında refactor yok; Suppliers.vue / SourcingCompare.vue'ya dokunma.
- Yeni i18n string yok (UI metni değişmiyor) — çeviri CSV'lerine dokunma.
- `--delete`'li rsync yok; migrate yok; onaysız gerçek rsync yok.
- Kirli dosyaları stage etme, stash'leyeceksen önce bana sor.
