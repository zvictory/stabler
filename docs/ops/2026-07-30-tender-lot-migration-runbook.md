# Mikas tender lotlarını Tender Master'a bağlama — runbook

Tarih: 2026-07-30
Script: `stabler/maintenance/link_tender_lots.py`
Hedef site: **yalnızca mikas.erpstable.com** (tender modülü açık tek tenant)

## Neden

v61 ile gelen Tender CRM (`#/tender/crm`) lotu `deal_type = "Tender"` +
`custom_parent_tender` ile tanır. v61 ÖNCESİ açılmış tüm lotlar v60
varsayılanıyla `deal_type = "Standard"` ve parent'sız kaldı. Sonuç: funnel
dashboard 35 tender sayarken yeni pano ve orphan kuyruğu boş görünüyor.
Bu migrasyon iki tanımı eşitler.

## Ne yapar

1. Funnel'ın tender saydığı her lotu (`_tender_deal_names`) + Tender tipli ama
   parent'sız lotları toplar.
2. `tender_no` doluysa aynı numaralı lotları TEK parent altında gruplar;
   boşsa her lot kendi parent'ını alır (intake `lot_no` anahtarıyla).
   *Sonradan parent birleştirmek UI işi; yanlış birleştirilmişi ayırmak
   değildir — bu yüzden varsayılan güvenli taraf per-lot'tur.*
3. Eksik `Tender Master` kayıtlarını açar, lotları bağlar
   (`db.set_value`, `update_modified=False` — hook tetiklemez, modified
   damgası oynamaz).

## Güvence

- **Dry-run varsayılan** — `apply=1` verilmeden hiçbir yazma olmaz.
- **Idempotent** — bağlı lot atlanır; parent `(company, tender_number)` ile
  önce aranır, yarım kalmış koşu güvenle tekrarlanır.
- **Tenant-safe** — `company` parametreli; tender modülü kapalı şirkette
  çalışmayı reddeder. Kod hiçbir yerde tenant adına dallanmaz.
- Demo kayıtları dışarıda bırakmak istersen: `skip_org_prefix='ZDEMO'`.
  (Not: mikas'taki mevcut portföyün büyük kısmı ZDEMO seed'i — demoyu da
  panoda görmek istiyorsan prefix VERME.)

## Prosedür

```bash
# 0) Script'i prod'a taşı (normal deploy akışının parçası olarak rsync eder;
#    tek dosya için hızlı yol):
cd ~/frappe-bench-local/apps
rsync -rltz --no-owner --no-group \
  stabler/stabler/maintenance/link_tender_lots.py \
  ice-production:/home/frappe/frappe-bench/apps/stabler/stabler/maintenance/
ssh ice-production 'chown frappe:frappe /home/frappe/frappe-bench/apps/stabler/stabler/maintenance/link_tender_lots.py'
# .py değişti → bench restart GEREKMEZ (bench execute taze process açar).

# 1) DRY-RUN — çıktıyı OKU: grup sayısı, parent adları, lot listesi mantıklı mı?
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute \
  stabler.maintenance.link_tender_lots.run --kwargs "{\"company\": \"Mikas\"}"'

# 2) Yedek (tablo bazlı, hızlı):
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com backup'

# 3) APPLY:
ssh ice-production 'cd /home/frappe/frappe-bench && bench --site mikas.erpstable.com execute \
  stabler.maintenance.link_tender_lots.run --kwargs "{\"company\": \"Mikas\", \"apply\": 1}"'
```

`company` değeri şirket doctype adıdır (`Mikas` — dry-run bilinmeyen şirkette
zaten durur, doğru adı `bench --site ... console` yerine dry-run hatasından
teyit edebilirsin).

## Fiilî koşu — mikas, 2026-07-30

İlk dry-run `Unknown column 'tender_no'` ile düştü: `v27_tender_deal_fields`
Patch Log'da işaretli ama `CRM Deal` doctype'ı o sırada yokken erken dönmüş,
yani `tender_no` / `tender_source` Custom Field'ları mikas'ta hiç oluşmamış.
Script bu iki alanı artık `frappe.db.has_column` ile opsiyonel seçiyor
(`sales.py`'nin aynı guard'ı). Sonucu değiştirmez — alanlar var olsaydı bile
pre-v61 lotlarda boş olurdu → gruplama zaten per-lot'a düşerdi.

Sonuç: 35 aday → 35 parent (hepsi per-lot), 35 lot bağlandı, orphan 0.
Kohort tamamen seed verisi: 28 `ZDEMO UTY`, 4 `[TEST]`, 3 `[TEST-E2E]`;
v61 öncesi **gerçek** tender lotu yok. `skip_org_prefix` verilmedi.
Yedek: `20260730_204339-mikas_erpstable_com-database.sql.gz`.

Not (kapsam dışı, ayrı iş): `tender_no` / `tender_deadline` / `bid_value` /
`tender_source` mikas'ta hâlâ yok, ama `Deals.vue` bu alanların formunu
render ediyor ve `crm.py` yazılabilir alan listesinde tutuyor.

## Duman testi (apply sonrası, tarayıcı)

1. `https://mikas.erpstable.com/stabler#/tender/crm` — şeritler doldu mu?
   Şerit toplamı ≈ dashboard'daki tender sayısı olmalı (funnel pencere
   filtresi yüzünden ufak fark normal).
2. Bir parent karta tıkla → lot listesi yalnızca o ihalenin lotları;
   parent sayıları görünen lotlarla birebir.
3. Orphan uyarı şeridi artık ya hiç yok ya da bilinçli dışarıda bırakılan
   (prefix'li) lot sayısını gösteriyor.
4. `#/dashboard` → bir KPI'ya tıkla → `/tender/crm` aynı kohortu açıyor.
5. msa'da `#/tender/crm` hâlâ erişilemez (modül kapısı regresyonu yok).

## Geri alma

Yedekten tam dönüş yerine hedefli geri alma yeterli:

```sql
-- yalnızca bu migrasyonun yazdığı alanlar:
UPDATE `tabCRM Deal` SET custom_parent_tender = NULL
 WHERE company = 'Mikas' AND custom_parent_tender LIKE 'TND-%';
DELETE FROM `tabTender Master` WHERE company = 'Mikas';
```

(`deal_type`'ı Standard'a döndürmek istersen dry-run çıktısındaki
`(+deal_type)` işaretli listeyi kullan — hepsini toptan döndürme; migrasyon
öncesi zaten Tender tipli olanlar vardı olabilir.)
