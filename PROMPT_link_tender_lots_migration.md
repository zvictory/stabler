# Paket 1 · Mikas tender lotlarını Tender Master'a bağla (veri migrasyonu)

Bu dosyanın tamamını yapıştır. **ONAY yazan yerde dur ve bana sor.**
Kod değişikliği YOK — tek dosya kopyalanır, sonra yalnızca mikas'ta VERİ yazılır.
Runbook: `docs/ops/2026-07-30-tender-lot-migration-runbook.md` (çelişki olursa runbook kazanır).

---

## Bağlam (bir paragraf)

v61 Tender CRM'i (`#/tender/crm`) lotu `deal_type="Tender"` + `custom_parent_tender`
ile tanıyor. v61 öncesi açılan ~35 lot v60 varsayılanıyla `Standard` ve parent'sız —
bu yüzden funnel dashboard dolu, yeni pano boş. `stabler/maintenance/link_tender_lots.py`
bu boşluğu kapatır: funnel'ın tender saydığı lotları toplar, `tender_no` doluysa aynı
numaraları tek parent altında gruplar, boşları per-lot parent'a bağlar. Dry-run
varsayılan, idempotent, `company` parametreli; yazma `db.set_value(update_modified=False)`.

---

# İŞ 1 — Script'i prod'a taşı

```bash
cd ~/frappe-bench-local/apps
python3 -m py_compile stabler/stabler/maintenance/link_tender_lots.py && echo OK

rsync -rltz --no-owner --no-group \
  stabler/stabler/maintenance/link_tender_lots.py \
  ice-production:/home/frappe/frappe-bench/apps/stabler/stabler/maintenance/
ssh ice-production 'chown frappe:frappe /home/frappe/frappe-bench/apps/stabler/stabler/maintenance/link_tender_lots.py'
```

- Tek dosya, hedef yol sabit — genel deploy rsync'i ve `--delete` KULLANMA.
- `bench build` / `bench restart` GEREKMEZ (`bench execute` taze process açar,
  frontend değişmedi). Diğer 21 tenant hiçbir şey hissetmez.

# İŞ 2 — DRY-RUN ve ONAY

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute \
  stabler.maintenance.link_tender_lots.run --kwargs "{\"company\": \"Mikas\"}"'
```

- "Unknown company" hatası gelirse şirket doctype adını bul
  (`bench --site mikas.erpstable.com execute frappe.client.get_list --kwargs "{\"doctype\":\"Company\",\"fields\":[\"name\"]}"`)
  ve doğru adla tekrarla.
- Çıktıyı OLDUĞU GİBİ bana göster ve şu üç soruyu cevapla:
  1. Kaç parent / kaç lot planlandı? (beklenti: ~30-40 lot, çoğu per-lot parent)
  2. `skipped foreign-company` > 0 mı? (0 olmalı)
  3. ZDEMO kayıtları listede mi? (Zafar demo portföyün panoda GÖRÜNMESİNİ istiyor —
     `skip_org_prefix` verme; ama listede beklenmeyen gerçek-dışı bir grup varsa işaretle)
- **ONAY bekle. Onaysız İŞ 3'e geçme.**

# İŞ 3 — Yedek + APPLY

```bash
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com backup'
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute \
  stabler.maintenance.link_tender_lots.run --kwargs "{\"company\": \"Mikas\", \"apply\": 1}"'
```

- Apply çıktısındaki `created/reused/linked` sayıları dry-run planıyla eşleşmeli;
  eşleşmiyorsa DUR ve bana getir (script idempotent — panik yok, tekrar koşmadan önce sor).

# İŞ 4 — Duman testi (tarayıcı, mikas)

1. `https://mikas.erpstable.com/stabler#/tender/crm` → şeritler doldu; toplam ≈
   dashboard tender sayısı (funnel'ın tarih penceresi yüzünden küçük fark normal).
2. Bir parent karta tıkla → yalnızca o ihalenin lotları; kart sayıları görünen
   lot listesiyle birebir.
3. Orphan uyarı şeridi kayboldu (veya bilinçli atlananlar kadar).
4. `#/dashboard` → bir KPI'ya tıkla → `/tender/crm` aynı kohortu açıyor.
5. `https://msa.erpstable.com/stabler#/tender/crm` hâlâ engelli (modül kapısı).

Ekran görüntüleriyle sonucu bana raporla.

# İŞ 5 — Yerel commit

```bash
cd ~/frappe-bench-local/apps/stabler
git add stabler/maintenance/link_tender_lots.py \
        docs/ops/2026-07-30-tender-lot-migration-runbook.md
git commit -m "ops(tender): one-time migration linking legacy lots to Tender Master

Dry-run by default, idempotent, company-parametrized; groups lots by tender_no,
falls back to one parent per lot. Applied on mikas 2026-07-30.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- **`git add -A` YASAK.** Ana worktree'daki diğer kirli dosyalara (sales.py,
  MoneyInput.vue, Customers.vue vb.) DOKUNMA — başka oturumun işi.

---

# Geri alma (gerekirse — önce bana sor)

```sql
UPDATE `tabCRM Deal` SET custom_parent_tender = NULL
 WHERE company = 'Mikas' AND custom_parent_tender LIKE 'TND-%';
DELETE FROM `tabTender Master` WHERE company = 'Mikas';
```

`deal_type`'ı toptan Standard'a DÖNDÜRME — migrasyon öncesi zaten Tender tipli
kayıtlar olabilir; dry-run çıktısındaki `(+deal_type)` işaretli listeyi kullan.

# Yapma

- `--delete`'li rsync yok; genel app rsync'i yok (tek dosya).
- `bench migrate` / `bench restart` yok — bu pakette gerek yok.
- mikas dışında hiçbir sitede execute etme.
- Onay almadan apply yok; duman testinde veri silme/düzenleme yok.
