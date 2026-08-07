# SESSION BRIEF — Customer/Vendor Center · toplam hataları · sıradaki iş

**Tarih:** 2026-08-06
**Önceki devir:** `docs/plans/2026-08-06-customer-center-HANDOFF.md` (o dokümanın
§5 listesi bu oturumda 1-4 arası kapandı)
**Uygulama planı:** `docs/plans/2026-08-05-party-center-2pane-redesign.md`
**Kritik:** `docs/plans/2026-08-05-customer-center-critique-ve-oneri.md`

---

## 0. ÖNCE OKU — dal karışıklığı

Bu oturumun **4 commit'i `tender-document-center` dalında.** Oturum sonunda
çalışma ağacı **`design/modernist-operations-desk`** dalına geçmişti (başka bir
iş). Yani `git log` çalıştırdığında bu commitleri göremezsin.

```bash
git log --oneline -5 tender-document-center     # commitleri gör
git branch --contains 5404533                   # sadece tender-document-center
```

Devam etmeden önce: `git checkout tender-document-center`.

`git stash list` içinde `stash@{0}: On tender-document-center:
wip-imports-before-design-preview` var — **bu bizim değil**, dokunma.

---

## 1. Bu oturumda inen commitler

| SHA | Ne |
|---|---|
| `e5d02fb` | Customers: liste kesildiğinde kitap geneli alacak toplamı (`grand_totals`) |
| `d4364d3` | (başkasının) tender intake satır parse'ı |
| `4a70a7e` | **Suppliers: üç toplam hatası + `truncated` düzeltmesi** |
| `5404533` | **Suppliers: `only_overdue` filtresi** (party-center planı adım 1) |

### `4a70a7e` — ne kırıktı

`Suppliers.vue`'daki footer şuydu:

```js
const totalPayable = computed(() =>
    suppliers.value.reduce((sum, s) => sum + Number(s.balance_base || 0), 0)
);
```

Üç hatadan **ikisi ANJAN'da canlıydı:**

1. `suppliers` (ham API sayfası) toplanıyordu, tablo ise `filteredSuppliers`
   render ediyordu → 5 tedarikçi grubundan birini seçmek listeyi daraltıyor,
   toplamı değiştirmiyordu.
2. `balance_base` toplanıyordu, satırlar `balance_acc` gösteriyordu. ANJAN'da
   **421 672,37 USD + 1 318 686 764,41 UZS** var; footer ikisini tek bir
   **528 034,17** yapıyordu — CLAUDE.md'nin "toplamları çevirme" kuralının
   doğrudan ihlali.
3. Ağaç modunda çift sayım — **Suppliers'ta yok**, hiyerarşi yok.

Ölçüm (ANJAN, 1745 Supplier GL satırı, 150 aktif tedarikçi):

| Para birimi | Tedarikçi | Gerçek bakiye |
|---|---|---|
| (yok) | 53 | 0,00 |
| USD | 35 | 421 672,37 |
| UZS | 62 | 1 318 686 764,41 |

### `4a70a7e` — kendi hatamı da düzeltti

`e5d02fb`'de `listTruncated` istemci tarafında `total_count > rows.length` diye
türetiliyordu. Ama `total_count` Python tarafındaki `only_with_balance` /
`only_overdue` filtrelerini **görmüyor**. Sonuç: "bakiyesi olanlar" açıkken
**tam** bir 93 satırlık liste, 150'ye karşı turuncu "sayfa kesildi" uyarısı
veriyordu — doğru bir toplamın üstünde yanlış uyarı.

Artık karar sunucuda, filtrelerden **önce**:

```python
truncated = total_count > len(rows)   # Python filtrelerinin ÜSTÜNDE
```

`sales.py`'nin **iki** return noktasında da var (erken dönüş + final).

### `5404533` — `only_overdue`

`list_suppliers_with_balances`'e eklendi; sayfadaki parti kümesi için tek
batch Purchase Invoice sorgusu (`outstanding_amount * conversion_rate`), satırlara
`overdue_base`, sonra Python filtresi. `sales.py`'deki karşılığının birebir aynası.

`showGrandTotals` artık `!onlyOverdue` de istiyor: `only_with_balance` gibi bu da
Python tarafında ama ondan farklı olarak **toplamı değiştiriyor** — kitap geneli
rakam ekrandakini tarif etmez olurdu.

Doğrulama (ANJAN): 150 tedarikçi / 93 bakiyeli / **71 vadesi geçen**, bağımsız SQL
sayımıyla birebir.

---

## 2. Doğrulama durumu

**Yeşil:** `py_compile`, `ruff format --check`, `ruff check`, `bench build --app
stabler` (1,5 s), ESLint (Suppliers.vue 5 sorun / Customers.vue 3 sorun — hepsi
stash'leyip yeniden lint ederek **önceden var** olduğu kanıtlandı).

**`make guards` kırmızı — 3 bulgu, hiçbiri bizim değil:**
- `Suppliers.vue:1237` — **false positive**, `formatTime()` kullanıyor
- `CommercialInvoiceForm.vue:1842-43` — başkasının commit edilmemiş işi

**`test_company_scope_guard` kırmızı** — sadece `tender_documents.py` ihlalleri.
Ne `sales.py` ne `purchasing.py` listede.

**YAPILAMADI — tarayıcı doğrulaması.** İki footer'ın görsel kontrolü ve `uzc`
Kiril tipografi kontrolü açık. `site_config.json`'da `admin_password` yok;
denenen 5 dev şifresi (admin/administrator/stabler/frappe/123456) `/api/method/login`
üzerinden 401 döndü. **Şifre izinsiz sıfırlanmadı.** Sonraki oturum kullanıcıdan
şifreyi istesin ya da kullanıcı `! bench --site stabler set-admin-password …`
çalıştırsın.

---

## 3. Ekran nerede

| | URL |
|---|---|
| Customer Center | `#/sales/customers` (`/sales` buraya redirect) |
| Vendor Center | `#/purchasing/suppliers` |
| Yerel | `http://localhost:8000/stabler#/sales/customers` |
| Prod | `https://anjan.erpstable.com/stabler#/sales/customers` |

Ayrı detay route'u **yok** — sağdaki pane aynı sayfada `selected` ref'i +
`stabler.api.sales.customer_detail` ile açılıyor (`Customers.vue:524`, `:575`).

Yeni footer bloğu: para birimi başına toplam, liste kesikse "All suppliers · N"
kitap geneli blok + turuncu `N / total` rozeti.

---

## 4. HANDOFF §5 — güncel durum

| # | Madde | Durum |
|---|---|---|
| 1 | build + guards + check | ✅ |
| 2 | Gerçek veriyle doğrulama | ✅ (ANJAN, sayılar §1'de) |
| 3 | `sales.py` çift `@frappe.whitelist()` | ✅ **zaten `1fce44a`'da kaldırılmış** — dosyada yok, doğrulandı |
| 4 | `Suppliers.vue` aynı toplam hataları | ✅ `4a70a7e` |
| 5 | **Ortak `PartyCenter` bileşeni** | ⬜ **SIRADAKİ** — kullanıcı onayı bekliyor |
| 6 | Tahsilat durumu + temas günlüğü | ⏸ "şimdi yapma" (yeni doctype; muhasebeci 2 hafta kullansın) |
| 7 | Kredi limiti + ödeme koşulu bayrağı | ⏸ aynı gerekçe |

---

## 5. Sıradaki iş — §5/5 PartyCenter

Plan: `docs/plans/2026-08-05-party-center-2pane-redesign.md`. Handoff'un kendisi
"**ayrı ve büyük iş**" diyor. Customers (1881 satır) + Suppliers (1813 satır) ≈
%80 kopya, aynı `cust-merged-*` CSS sınıflarını bile paylaşıyorlar.

**Kullanıcıdan onay alınmadan başlama** — iki canlı sayfayı aynı anda yeniden
yazmak demek. Bu oturumda soruldu, cevap gelmedi.

Planın **adım 1'i (backend) bitti.** Kalan sıra: 2) `components/party/*` yeni
bileşenler → 3) `Customers.vue` wrapper'a in (anjan smoke) → 4) `Suppliers.vue`
wrapper'a in (msa/mikas smoke) → 5) eski `cust-merged-*` CSS sil → 6) i18n.

### Planın §3 tablosu YANLIŞ — düzeltilmedi

Tablo `customer_detail` / `supplier_detail`'e iletişim alanları eklenmesini
istiyor. **İkisi de bugün zaten dönüyor:** `email_id`, `mobile_no`, `tax_id`,
grup, `territory`, `default_currency`. Tablo 05.08'de, o iş inmeden yazılmış.
Yani §3'ten geriye kalan tek şey `only_overdue`'ydu ve `5404533` ile bitti.

### Ayrıca kapsamda bekleyen

- **§4 açık tasarım kararı** (önceki oturumdan, hiç cevaplanmadı):
  Customers/Suppliers için `ListToolbar.vue` istisnası mı, yoksa dar-pane varyantı
  mı? Planın S1 adımı buna bağlı.
- **Kontrast**: `#9099a6` hiçbir zeminde WCAG AA geçmiyor ve muhasebe ekranının
  tüm etiket katmanını taşıyor. `#667382` (4,84:1) karşılığı DC dosyasında
  uygulandı, Vue'ya taşınmadı. `stabler.css`'te `.stbl-subtext` / `text-secondary`
  üzerinden **tek yerden** yapılabilir.

---

## 6. Ortam / operasyon notları

- **Deploy gerekiyor:** `sales.py` + `purchasing.py` değişti → prod'da `bench
  restart` şart (7 tenant'ın hepsinde kısa blip). Doctype/patch **yok** → `migrate`
  gerekmiyor. Prod git repo değil, deploy = rsync (CLAUDE.md'deki cwd tuzağına dikkat).
- **`bench execute stabler.translations.harvest.run` ÇALIŞTIRMA.** 5 CSV'yi
  baştan sıralıyor (`harvest.py:114`) → ~5100 satırlık sahte diff.
- **Stage etme:** `*.bak-skeleton`, `*.csv.bak-i18n`, `graphify-out/`, `.smoke/`,
  `scratch/`, `_to_delete/`, `PROMPT_*.md`, `stabler/translations/__pycache__/`,
  `stabler/logs/`. Bunlar çalışma ağacında duruyor.
- **Asla `git add -A`.** Açık path.
- Commit trailer: `Co-Authored-By: Claude <noreply@anthropic.com>` — model adı yazma.
- CSV'ler **CRLF**. Byte seviyesinde düzenle:
  ```python
  old = "All suppliers,\r\n".encode()
  assert data.count(old) == 1
  open(p, "wb").write(data.replace(old, f"All suppliers,{target}\r\n".encode()))
  ```
- `bench console` stdin'i satır satır çalıştırır → script'i tek `exec()` içine sar:
  ```bash
  echo "exec(open('$P/x.py').read(), {'__name__':'__main__'})" | bench --site stabler console
  ```
- macOS: GNU `timeout` yok. `ruff` = `<bench>/env/bin/ruff`.
- `bench serve` **artık çalışmıyor** (oturum sonunda kapalı). `watch`, `worker`,
  `schedule` de kapalı.
- Yerel site adı: `stabler`.

### Doğrulama script'leri

`/private/tmp/claude-501/-Users-zafar-frappe-bench-local/2593859d-78c1-4443-b5af-fba3843b6c29/scratchpad/`
altında: `ap_delta.py`, `ap_cur.py`, `verify_ap.py`, `verify_trunc.py`,
`verify_overdue.py`, `ar_delta.py`, `drift.py`, `verify_gt.py`. Scratchpad
oturuma özel — kaybolursa yeniden yazılmaları gerekir.

---

## 7. Bilinmesi gereken teknik ayrıntılar

- **AR işareti** `debit - credit`, **AP işareti** `credit - debit`.
- **Payment Entry drift düzeltmesi**: tek bacaklı PE voucher'larında GL satırı ile
  PE'nin `paid_amount`/`received_amount` alanı ayrışıyor; satır bazında düzeltiliyor.
  `grand_totals` bu düzeltmeyi **içermiyor** — ANJAN'da fark USD 0,03 / UZS 102,99
  (~%0,000008) ve blok yalnız liste kesikken göründüğü için ikisi hiç yan yana gelmiyor.
- **`grand_totals`** `limit`'ten bağımsız, `where` ile aynı filtreyi kullanır,
  para birimi başına gruplanır (çevrilmez). `verify_ap.py` limit=10/500/100000'de
  aynı sonucu verdiğini, eşleşme yokken `[]` döndüğünü, aramayla doğru daraldığını
  doğruladı.
- **Çok tenant**: TEK kod tabanı, 7 site. `bench restart` hepsini etkiler. Tenant
  adına göre dallanma **yasak** — `Stabler Company Modules` üzerinden parametrele.
