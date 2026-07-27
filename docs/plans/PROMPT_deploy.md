# Deploy prompt — Stabler (prod = anjan.erpstable.com)

Bu Mac'da ishlaydi (`ice-production` SSH alias + bench-local bor). CLAUDE.md deploy
qoidalariga QAT'IY amal qil. **Sandbox prodga ula olmaydi — deploy Mac'dan bo'ladi.**

## ENG MUHIM QOIDA (o'tgan safar shu tufayli ishlamadi)
rsync `dist/` ni chiqarib tashlaydi → prod **o'z bundle'ini o'zi qurishi shart**. Har
qanday JS o'zgarishi (drill, transfer detali, valyuta) prodда ko'rinishi uchun:
1. prodда **`bench build --app stabler`** ishlashi SHART, va
2. brauzerда **hard refresh** (`Cmd+Shift+R`) qilinishi SHART (eski bundle cache).
Build'dan keyin bundle **hash o'zgaradi** — o'zgarmasa build ishlamagan.

## Bu turkumdagi o'zgargan fayllar (faqat shularni stage qil — `git add -A` YO'Q)
Backend: `stabler/api/money.py`, `hr_finance.py`, `salary_payment.py`, `reports.py`, `export.py`
Frontend: `stabler/public/js/pages/hr/Employees.vue`,
`stabler/public/js/components/ReportTable.vue`,
`stabler/public/js/pages/reports/SalesByCustomer.vue`,
`stabler/public/js/pages/reports/CustomerBalanceSummary.vue`,
`stabler/public/js/pages/ReportsHub.vue`, `stabler/public/js/router.js`,
`stabler/public/js/pages/money/Transfers.vue`
i18n: `stabler/translations/en.csv ru.csv uz.csv uzc.csv tr.csv`

## Eng oson yo'l — tayyor skript
```bash
bash /Users/zafar/frappe-bench-local/apps/stabler/deploy_hr_employee_crud.sh
```
Skript: aniq fayllarni commit → lokal build → prod target tasdig'i → **backup tar** →
rsync (`--delete` YO'Q, exclusion'lar) → chown → **prod `bench build`** → `bench restart`.
(Agar "nothing to commit" desa — manba allaqachon commitda; to'g'ridan-to'g'ri build+restart bosqichига o't.)

## Yoki qo'lda (ishonchli, hash-tasdiq bilan)
```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
# backup
ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler'
# manbani yubor (dist chiqarilgan — prod o'zi quradi)
rsync -rltz --no-owner --no-group \
  --exclude='.git' --exclude='node_modules' --exclude='dist' --exclude='__pycache__' \
  --exclude='*.pyc' --exclude='.claude' --exclude='.tx_*.json' --exclude='graphify-out' \
  --exclude='.smoke' --exclude='tests' --exclude='*.tgz' --exclude='.DS_Store' \
  ./ ice-production:/home/frappe/frappe-bench/apps/stabler/
ssh ice-production 'chown -R frappe:frappe /home/frappe/frappe-bench/apps/stabler'
# prod build (majburan) + cache tozalash + restart + YANGI hash
ssh ice-production 'cd /home/frappe/frappe-bench && bench build --app stabler --force && bench --site anjan.erpstable.com clear-cache && bench restart && ls -t apps/stabler/stabler/public/dist/js/stabler.bundle.*.js | head -1'
```
So'ng brauzerда **`Cmd+Shift+R`**. Oxirgi qator chiqargan hash — oldingidан **boshqa** bo'lishi kerak.

## `migrate` shart emas (yangi doctype/patch yo'q). `bench restart` yangi `.py` endpoint'lar uchun kerak.
`bench restart` butun bench'ni (~22 tenant) qisqa blip qiladi — past trafikda.
Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Deploy'dan keyin smoke-check
1. **Transfers**: Money → Transfers → ro'yxatdan bir transferni och → detay **transfer tarzida** (From → To, tutar, kur) → **Amend** → forma to'ladi → saqla.
2. **Sales by Customer**: mijoz **qatorini bos** → pastda **Ledger** ochiladi (running balans = Balance); summalar **сўм**.
3. **Customer Balance Summary** (`/reports/customer-balance-summary`): ochiladi, qator bosilsa **Ledger** drill, **Excel/CSV** ishlaydi.
4. **Employees**: xodim → ledger qatorini bos (voucher) → **New transaction** / **Accrue salary**.
5. Direct-URL refresh: mavjud SINV/PINV/PO/Payment URL populated ochiladi.

## Rollback
Backup tar'ni tikla → `chown -R frappe:frappe` → `bench build --app stabler` → `bench restart`.
