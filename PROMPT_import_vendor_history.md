# msa — Vendor ödeme tarihçesi importu (gerçek tarihli PE + CI faturaları + FIFO mahsup)

Bu dosyanın tamamını Claude Code'a yapıştır, `~/frappe-bench-local/apps/stabler` içinden.
**ONAY yazan yerde bana sor, cevapsız geçme.** Her faz önce dry-run.

Kaynak: `IMPORT_msa_vendor_payments.csv` (394 ödeme, 2025-01-05 → 2026-07-23,
Bank+Cash) + `IMPORT_msa_vendor_history.py` (fazlı script). Onaylı kararlar:
tek şirket (MSA), ayrım CoA hesaplarında; vendor odaklı (PI etiketi sadece
remark); her ödeme GERÇEK tarihiyle; konteyner statüsü önemsiz; FY2025 yoksa aç.

## 0 · Dosyaları sunucuya taşı

```bash
cd ~/frappe-bench-local/apps/stabler
scp IMPORT_msa_vendor_payments.csv IMPORT_msa_vendor_history.py ice-production:/tmp/
```

## 1 · AUDIT (salt okuma)

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
audit()
PY
```

Çıktıyı bana GÖSTER. Birlikte dolduracağız:
- `SUPPLIER_MAP` — audit'in bulduğu adaylardan; eşleşmeyen vendor varsa DUR,
  Supplier'ı ben onaylayınca oluştur (Stabler SPA verisiyle uyumlu şekilde).
- "Other PEs already on these suppliers" listesi boş değilse bana göster —
  mükerrer riskini birlikte değerlendirelim.

Doldurmayı `/tmp/IMPORT_msa_vendor_history.py` içinde yap (sed/edit), CONFIG
bloğunu bana göster. **ONAY almadan devam etme.**

Hesaplar elle doldurulmaz — `ensure_accounts()` mevcut CoA'yı tarayıp çözer
(onaylı karar: mevcut hesaba göre ayarla, yoksa oluştur):

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
ensure_accounts(dry_run=1)
PY
```

Çözümleme tablosunu bana göster: hangi slot hangi mevcut hesaba bağlandı,
ne CREATE edilecek (NBU USD / Aloqa USD / Bank USD / Kassa USD, USD para
birimli, kendi tipinin grubu altında). `!! currency` uyarısı ya da
`no group in CoA — STOP` görürsen dur, bana getir. **ONAY** →
`ensure_accounts(dry_run=0)` koş (eksik hesaplar yaratılır).

## 2 · Mali yıl

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
ensure_fiscal_years()
PY
```

## 3 · Ödemeler (394 PE, gerçek tarihli)

Dry-run → planı bana göster (vendor başına adet + toplam; beklenen:
HMA 221 / 82,0M; FAIR 46 / 9,4M; MIRHA 77 / 15,1M; IFF 20 / 2,4M;
ALS 29 / 8,5M; AL-DUA 1 / 242K). **ONAY** → `dry_run=0`.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
ensure_accounts(dry_run=0)  # her yeni oturumda şart: ACCOUNTS'u yeniden çözer (idempotent)
import_payments(dry_run=1)
PY
```

`FAIL` satırı çıkarsa dur, bana getir (muhtemel neden: kur kaydı olmayan gün —
CBU rate fetch; ya da hesap para birimi uyumsuzluğu).

## 4 · CI → Purchase Invoice (CI tarihiyle)

Dry-run → convertible sayısı + EXCEPTIONS listesini bana göster.
Exceptions (lines≠agreed_total, ci_date yok) ZORLANMAZ — listeyi birlikte
değerlendiririz. **ONAY** → `dry_run=0`.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
convert_cis(dry_run=1)
PY
```

## 5 · FIFO mahsup

Dry-run → vendor başına eşleşme planını bana göster (en eski PE → en eski
fatura). **ONAY** → `dry_run=0`. FAIL çıkarsa o supplier'da dur, getir.

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
reconcile(dry_run=1)
PY
```

## 6 · Karşılaştırma + tarayıcı doğrulaması

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site msa.erpstable.com console' <<'PY'
exec(open("/tmp/IMPORT_msa_vendor_history.py").read())
compare()
PY
```

Tabloyu bana göster. Delta ≠ 0 hata değil bilgidir: sevk edilmemiş PI kalanı
(CI yok → ledger'da yok), Excel'in kendi iç tutarsızlıkları (IFF +217;
ALS −63 988 banka / +32 612 toplam), ya da adım 4 exceptions.

Tarayıcı: msa → Purchasing → Suppliers → HMA → ledger: debit/credit/running
balance 2025'ten bugüne akıyor olmalı; kapanış compare() ile aynı.

## Yapma

- CONFIG onayı olmadan hiçbir write fazı koşma.
- Exceptions'ı zorla fatura etme; negatif/`freight` işaretli satırları sorgusuz
  "goods" sayma (remark'ta tür var).
- `git add -A` yok; bu üç dosya zaten repo'da, sunucu tarafında sadece /tmp kullan.
