# Faz 0 — msa.erpstable.com Canlı Site Envanteri

**Tarih:** 2026-07-09 · **Kaynak:** `https://msa.erpstable.com` REST API, read-only GET (`/api/resource/...`, `/api/method/...`)
**Bağlam:** `2026-07-09-msaerp-to-stabler-migration-plan.md` §K1/K2 için ön koşul envanteri. Bu doküman canlı sitenin **gerçek** durumunu raporlar; plandaki bazı varsayımlarla **çelişen** bulgular aşağıda açıkça işaretlendi.

---

## 0. Yönetici Özeti — en kritik 4 bulgu

1. **Sürüm uyumu TAM** — Frappe 16.18.2 / ERPNext 16.18.3, ikisi de `version-16` branch'inde. Stabler'ın v16 gereksinimiyle **birebir uyumlu**, site upgrade gerekmiyor (K1(a) kapandı).
2. **Custom field isimleri planla ÇELİŞİYOR** — plan `custom_docs_rate/amount/total`, `custom_docs_diff_total`, `custom_ikpu_code` varsayıyordu. Canlıda bunlar **yok**; onun yerine `custom_agreed_rate/amount/total`, `custom_cash_difference`, `custom_allocated_advance_bank/cash` var ve `custom_ikpu_code` Item'da **hiç mevcut değil** (sorgu "Field not permitted" hatası veriyor — alan şemada yok). K3/§3.1 patch tasarımı bu gerçek isimlere göre **yeniden yazılmalı**.
3. **Satın alma tarafı ERPNext'te tamamen BOŞ** — Purchase Order, Purchase Invoice, Purchase Receipt, Landed Cost Voucher, Stock Entry, Batch: **hepsi 0 kayıt**. §3.1'deki "PO'lar zaten site'ta, yenisi üretilmez / backfill" varsayımı geçersiz — import/tedarik zinciri şu an %100 Django'da yaşıyor, ERPNext tarafı bu konuda **yeşil alan** (mevcut veriye backfill değil, sıfırdan üretim).
4. **K2 legacy köprüsü SI'da SIFIR, PE'de küçük ama gerçek** — `custom_child_reference` alanı **hiçbir** Sales Invoice'ta dolu değil (0/4149) ve hiçbir SI parent müşteriye kesilmemiş. Ama **Payment Entry'de 14 aktif kayıt** (toplam ~4,57 milyar UZS, 2026-06-02/03 tarihli) doğrudan parent müşteri "Ravshan aka"ya işlenmiş — ve PE'de child'a atıf için **hiçbir alan yok** (SI'daki gibi bir `custom_child_reference` benzeri mekanizma PE'de tanımlanmamış). Ayrıntı §5.

---

## 1. Sürüm / Yüklü Uygulamalar

```
frappe:  16.18.2  (branch: version-16)
erpnext: 16.18.3  (branch: version-16)
msaerp:  0.0.1    (branch: version-16)  — mevcut Django-entegrasyon köprü app'i mi, ayrı incelenmeli
```

**Yüklü modüller (app_name bazında, Module Def listesinden):**
- `frappe` — Automation, Contacts, Core, Custom, Desk, Email, Geo, Integrations, Printing, Website, Workflow
- `erpnext` — Accounts, Assets, Bulk Transaction, Buying, Communication, CRM, EDI, ERPNext Integrations, Maintenance, Manufacturing, Portal, Projects, Quality Management, Regional, Selling, Setup, Stock, Subcontracting, Support, Telephony, Utilities
- `hrms` — HR, Payroll
- `payments` — Payment Gateways, Payments
- `mint` — Mint (plan §3.2'de bahsedilen `integrations/mint/` hedefiyle tutarlı — zaten kurulu)
- `msaerp` — MSAERP (Sales management interface) — **stabler DEĞİL**, ayrı bir uygulama olarak zaten kurulu; ne yaptığı ayrıca incelenmeli (custom field'ların bir kısmını bu app kurmuş olabilir)

**`stabler` yüklü değil** (beklenen — K1'in "kurulacak" öngörüsüyle tutarlı).

---

## 2. Şirketler

| name | abbr | default_currency | country |
|---|---|---|---|
| MSA | M | UZS | Uzbekistan |

Tek şirket. Multi-company senaryosu yok — ETL ve modül-toggle mantığı basit kalabilir.

---

## 3. Custom Field Envanteri

### Customer (1 alan)
| fieldname | fieldtype | label | permlevel | options |
|---|---|---|---|---|
| `custom_parent_customer` | Link | Parent Customer | 0 | Customer |

### Sales Invoice (1 alan)
| fieldname | fieldtype | label | permlevel |
|---|---|---|---|
| `custom_child_reference` | Data | Child Customer Reference | 0 |

### Purchase Order (5 alan)
| fieldname | fieldtype | label | permlevel |
|---|---|---|---|
| `custom_pi_number` | Data | PI Number | 0 |
| `custom_msaerp_pi_id` | Int | MSAERP PI ID | 0 |
| `custom_agreed_total` | Currency | Agreed Total | 0 |
| `custom_cash_difference` | Currency | Cash Difference | 0 |
| `custom_advance_percentage` | Percent | Advance % | 0 |

### Purchase Order Item (4 alan)
| fieldname | fieldtype | label | permlevel |
|---|---|---|---|
| `custom_boxes` | Float | Boxes | 0 |
| `custom_box_weight_kg` | Float | Box Weight (kg) | 0 |
| `custom_agreed_rate` | Currency | Agreed Rate | 0 |
| `custom_agreed_amount` | Currency | Agreed Amount | 0 |

### Purchase Invoice (6 alan)
| fieldname | fieldtype | label | permlevel |
|---|---|---|---|
| `custom_ci_number` | Data | CI Number | 0 |
| `custom_msaerp_ci_id` | Int | MSAERP CI ID | 0 |
| `custom_agreed_total` | Currency | Agreed Total | 0 |
| `custom_cash_difference` | Currency | Cash Difference | 0 |
| `custom_allocated_advance_bank` | Currency | Allocated Advance (Bank) | 0 |
| `custom_allocated_advance_cash` | Currency | Allocated Advance (Cash) | 0 |

### Purchase Invoice Item (4 alan)
| fieldname | fieldtype | label | permlevel |
|---|---|---|---|
| `custom_boxes` | Float | Boxes | 0 |
| `custom_box_weight_kg` | Float | Box Weight (kg) | 0 |
| `custom_agreed_rate` | Currency | Agreed Rate | 0 |
| `custom_agreed_amount` | Currency | Agreed Amount | 0 |

### Payment Entry (3 alan)
| fieldname | fieldtype | label | permlevel | options |
|---|---|---|---|---|
| `custom_payment_stream` | Select | Payment Stream | 0 | Bank / Cash |
| `custom_msaerp_advance_id` | Int | MSAERP Advance ID | 0 | |
| `custom_pi_number` | Data | PI Number | 0 | |

### Item (1 alan)
| fieldname | fieldtype | label | permlevel |
|---|---|---|---|
| `custom_name_uzbek` | Data | Name (Uzbek) | 0 |

**Not:** Tüm alanlarda `permlevel = 0` — K3'ün öngördüğü "perm_level 1" maskeleme **henüz uygulanmamış**. Dual-pricing verisi (`custom_agreed_*`, `custom_cash_difference`) şu an herkese açık görünürlükte.

**Plan uyumsuzlukları (§3.1, §1.2 ile karşılaştırma):**
- Plan: `custom_docs_rate/amount/total`, `custom_docs_diff_total` (PO/PI/Item) → Gerçek: `custom_agreed_rate/amount/total`, `custom_cash_difference`. **İsimlendirme tersine dönmüş olabilir** — "docs" (belge/gösterim fiyatı) değil "agreed" (mutabık kalınan fiyat) olarak adlandırılmış. K3'ün "native rate = agreed" kararıyla birlikte okunduğunda, bu alan muhtemelen **native `rate`'in kendisi zaten agreed**, ve `custom_agreed_total` ayrı bir çapraz-kontrol/toplam alanı — anlamı PO/PI sahibiyle teyit edilmeli.
- Plan: `custom_ikpu_code` Item'da "mevcut, sadece backfill" → Gerçek: **alan yok**. IKPU backfill görevi "alan ekle + backfill" olarak yeniden kapsanmalı.
- Plan: `custom_docs_total` PO'da → Gerçek: yok; `custom_agreed_total` var.

---

## 4. Müşteri Hiyerarşisi (K2 için kritik)

- **Toplam Customer:** 170
- **`custom_parent_customer` dolu:** 165
- **Parent (root, alan boş):** 5 — `MSA`, `Ravshan aka`, `Saidma'ruf`, `Nodirxon`, `Abdulaziz`
- **Child dağılımı (parent başına):**

| Parent | Child sayısı |
|---|---|
| Ravshan aka | 97 |
| MSA | 65 |
| Saidma'ruf | 1 |
| Nodirxon | 1 |
| Abdulaziz | 1 |

- Hiyerarşi **tam 2 seviyeli** (parent → child; child'ın kendi child'ı yok) — QB modeliyle uyumlu, ekstra derinlik yönetmeye gerek yok.
- Tüm 165 parent-değeri, gerçek bir Customer kaydına işaret ediyor (referans bütünlüğü sağlam, yetim referans yok).
- **Not:** "MSA" ve "Ravshan aka" parent olarak muhtemelen gerçek iş ortağı değil, **toplayıcı/varsayılan kova** (bkz. §5) — gerçek anlamını sahiple teyit et.

---

## 5. Sales Invoice Analizi (K2/B1 için kritik)

- **Submitted (docstatus=1) SI sayısı:** 4.149
- **`custom_child_reference` dolu SI sayısı:** **0** (hem `is set` hem `!= ''` filtresiyle doğrulandı)
- **Parent müşteriye doğrudan kesilmiş SI sayısı:** **0** (5 parent'ın hepsi için tek tek kontrol edildi — `MSA`, `Ravshan aka`, `Saidma'ruf`, `Nodirxon`, `Abdulaziz` → hepsi 0)
- **posting_date aralığı:** 2025-05-09 → 2026-06-09 (~13 ay)
- **Distinct SI customer sayısı:** 165 — customer master'daki 165 child ile **birebir örtüşüyor**, customer master dışında yetim müşteri yok.

**Sonuç:** SI tarafında plan'ın endişe ettiği "tarihsel SI'lar parent üzerinde etiketli" (§K2, critique B1) senaryosu **gerçekleşmemiş** — `custom_child_reference` alanı tanımlı ama hiç kullanılmamış, ve hiçbir SI parent'a kesilmemiş. Tüm satış faturaları zaten doğrudan child (leaf) müşteriye kesiliyor. **K2 UNION formülünün SI bacağı bugün itibariyle gereksiz** — ama tarihsel garanti değil, ileride kullanılmaya başlanabilir; alan şemada durduğu için ETL'in yine de kontrol etmesi gerekir.

### Payment Entry — asıl legacy köprüsü burada

SI'da sıfır olan "parent'a doğrudan işlem" deseni, **Payment Entry'de gerçek**:

| Parent (party) | PE toplam | docstatus=1 (aktif) | docstatus=2 (iptal) |
|---|---|---|---|
| Ravshan aka | 46 | **14** | 32 |
| Saidma'ruf | 26 | 0 | 26 |
| Abdulaziz | 12 | 0 | 12 |
| MSA | 0 | 0 | 0 |
| Nodirxon | 0 | 0 | 0 |

- **Saidma'ruf ve Abdulaziz'deki tüm kayıtlar iptal edilmiş (docstatus=2)** — canlı bakiye etkisi yok, ETL'de yok sayılabilir.
- **Ravshan aka'da 14 kayıt hâlâ aktif (docstatus=1, `Receive`)**, toplam **4.571.804.371 UZS** (~360K USD @ ~12.700 kur), tamamı **2026-06-02 / 2026-06-03** tarihli (2 günlük pencere, muhtemelen tek bir toplu tahsilat operasyonu — remarks alanında `MSA-IMP-*` referanslarıyla bireysel işlem izleri var, muhtemelen mobil/banka entegrasyonundan otomatik gelmiş).
- **Payment Entry'de child'a atıf için hiçbir custom field yok** (SI'daki `custom_child_reference` benzeri bir mekanizma PE şemasında tanımlı değil) — bu 14 kayıt hangi child müşteriye ait olduğu bilgisini **kaybetmiş durumda**, sadece parent seviyesinde kümülatif bakiyeye katkıda bulunuyor.

**K2 için pratik sonuç:** Legacy köprü, plan'ın tahmin ettiğinden çok daha küçük ama **PE tarafında gerçek ve nitelik olarak farklı bir problem**: SI'da "hangi child" bilgisi var ama kullanılmamış; PE'de "hangi child" bilgisi **hiç yakalanmamış**. UNION formülü (`customer=child OR (customer=parent AND custom_child_reference=child_code)`) SI için bugün no-op ama PE için **çalışmıyor** — PE şemasında karşılık gelen alan yok. Ya (a) muhasebeci bu 14 kaydı elle child'lara yeniden dağıtır (K2 §61'deki "isteğe bağlı temizlik" seçeneği, go-live kapsamı dışı tutulmuş ama burada hacim küçük olduğu için go-live'a alınabilir), ya da (b) UNION helper PE için de "customer=parent" durumunu ayrı bir dal olarak ele alır (attribute edilemeyen tutar parent'ın kendi kümülatif bakiyesinde kalır, hiçbir child'a düşmez).

---

## 6. Satın Alma Tarafı (B1/K1 için kritik)

| Doctype | Toplam | Not |
|---|---|---|
| Purchase Order | **0** | Tüm docstatus (0/1/2) için 0 |
| Purchase Order Item | — | (PO'ya bağlı, PO 0 olduğundan mevcut değil) |
| Purchase Invoice | **0** | Tüm docstatus için 0 |
| Purchase Invoice Item | — | |
| Purchase Receipt | **0** | |
| Landed Cost Voucher | **0** | |
| Stock Entry | **0** | (dolayısıyla stock_entry_type kırılımı da yok) |
| Batch | **0** | |
| Payment Entry | **5.311** toplam — docstatus=1: 5.241, docstatus=2 (iptal): 70, docstatus=0 (taslak): 0 |
| PE `custom_payment_stream` | **Bank: 5.311**, Cash: 0, boş: 0 — alan dolu ama **hep "Bank"**, "Cash" akışı hiç kullanılmamış |

**Sonuç:** ERPNext'te satın alma/tedarik zinciri belgesi (PO/PI/PR/LCV/SE/Batch) **sıfır**. Custom field'lar PO/PO Item/PI/PI Item üzerinde tanımlı olsa da hiç kullanılmamış — muhtemelen ileride kullanılacak şekilde önceden hazırlanmış (§3'teki msaerp app'i tarafından mı kuruldu, incelenmeli). Bu, planın §3.1/§7'deki "ERPNext'te zaten var olan PO/PI/PE/SI'lar regenerate edilmez, Ref ile bağlanır" varsayımını **PO/PI için geçersiz kılar** — bağlanacak mevcut kayıt yok, ETL bu doctype'lar için **baştan üretim** yapacak (backfill değil, create). Bu aslında migration'ı **basitleştirir** (çakışma/idempotency riski PO/PI tarafında yok) ama Faz 3 ETL sırası ve hacim tahminleri buna göre güncellenmeli.

Ayrıca `custom_payment_stream`'in hep "Bank" olması: MSAERP'in nakit (Cash) akışı bu alanı hiç kullanmamış — ya nakit ödemeler ayrı işleniyor (henüz ERPNext'e senkron değil) ya da gerçek nakit hacmi bu şirkette düşük. Sahiple teyit gerekir.

---

## 7. Master Veriler

- **Supplier:** 23
- **Item:** 27 — tamamı `Meat Products` grubunda, kod-numaralı (örn. `005 Liver`, `41 TOPSIDE`, `172 WHOLE LEG`). `custom_ikpu_code` alanı **mevcut değil** (§3'te not edildi) → backfill görevi "alan yarat + doldur" olarak genişletilmeli.
- **Warehouse (9):** `All Warehouses - M` (group), `Andijon - M`, `Bektemir - M`, `Finished Goods - M`, `Goods In Transit - M`, `Main - M`, `MSA - M` (group), `Stores - M`, `Work In Progress - M`
- **Batch:** 0
- **Price List (5):** `11.03.2026` (selling), `fevral` (selling), `Spring 2026` (selling), `Standard Buying` (buying), `Standard Selling` (selling) — hepsi UZS. Tarihli/dönemsel fiyat listesi isimlendirme deseni var (`fevral`, `11.03.2026`, `Spring 2026`) — bu muhtemelen periyodik fiyat güncellemesi disiplinini yansıtıyor, ETL/Price List + Item Price taşımasında bu isimlendirme deseni korunmalı mı yoksa normalize mi edilmeli, sahiple netleştirilmeli.

---

## 8. Naming Series (örnekleme)

| Doctype | En yeni 3 isim | Desen |
|---|---|---|
| Sales Invoice | `ACC-SINV-2026-30508`, `...30507`, `...30506` | `ACC-SINV-{YYYY}-{5 haneli sayaç}` |
| Payment Entry | `ACC-PAY-2026-05322`, `...05321`, `...05320` | `ACC-PAY-{YYYY}-{5 haneli sayaç}` |
| Purchase Order | — (0 kayıt) | Henüz kurulmamış / kullanılmamış |
| Purchase Invoice | — (0 kayıt) | Henüz kurulmamış / kullanılmamış |

`ACC-` öneki, muhasebe modülünün naming series'i özelleştirildiğini gösteriyor (ERPNext varsayılanı `SINV-`/`ACC-PAY-` değil `PAY-` şeklindedir çoğu kurulumda — burada `ACC-` öneki eklenmiş). Stabler kurulumunda mevcut naming series ayarlarına dokunulmamalı (idempotent patch kuralı zaten bunu söylüyor).

---

## Stabler kurulum uyumluluğu — VERDİKT

| Kriter | Durum |
|---|---|
| Frappe sürümü | 16.18.2 (`version-16`) — **stabler'ın v16 gereksinimiyle uyumlu** |
| ERPNext sürümü | 16.18.3 (`version-16`) — **uyumlu** |
| Aynı bench'te mi? | Şema/versiyon API'sinden doğrulanamaz (bu sadece site-level bilgi) — **SSH ile `bench --site msa.erpstable.com list-apps` ve bench python sürümü (`py≥3.14` gereksinimi, plan §Hedef) ayrıca teyit edilmeli.** Bu API taramasıyla kapatılamayan tek açık madde. |
| Şirket sayısı | 1 (MSA) — multi-company karmaşıklığı yok |
| Çakışan custom field riski | **Orta-Yüksek** — 25 custom field zaten var (Customer/SI/PO/POI/PI/PII/PE/Item), plandaki varsayılan isimlerle **örtüşmüyor** (bkz. §3). Stabler patch'leri bu alanları **yeniden yaratmaya kalkarsa çakışma/veri kaybı riski var** — idempotent patch'ler mevcut alan adlarını (`custom_agreed_*`, `custom_cash_difference`, `custom_payment_stream`, vb.) **tanımalı**, üzerine yazmamalı. |
| PO/PI kurulum riski | **Düşük** — ERPNext'te sıfır PO/PI kaydı olduğundan, stabler'ın import modülü bu doctype'lara "temiz sayfa" olarak inşa edilebilir; backfill/reconcile riski yok. |
| **Genel verdikt** | **Kurulum için teknik engel yok** (versiyon uyumu tam). Ama patch tasarımı §3'teki gerçek alan envanterine göre **yeniden yazılmalı** — plan taslağındaki varsayılan alan isimleri canlı ile eşleşmiyor. Bench/Python sürümü SSH ile ayrıca doğrulanmalı. |

---

## K2 legacy köprüsü boyutu — özet

| Boyut | SI (Sales Invoice) | PE (Payment Entry) |
|---|---|---|
| Toplam aktif belge | 4.149 | 5.241 |
| Parent'a doğrudan işlenmiş (aktif) | **0** | **14** (yalnız "Ravshan aka") |
| Child'a atıf mekanizması | `custom_child_reference` (var ama **hiç dolu değil**) | **yok** (şemada karşılığı yok) |
| Parent'a işlenmiş tutar | 0 | **4.571.804.371 UZS** (~360K USD) |
| Tarih penceresi | n/a | 2026-06-02 → 2026-06-03 (2 gün) |
| İptal edilmiş parent-kayıtları (yok sayılabilir) | n/a | 70 (Saidma'ruf 26 + Abdulaziz 12 + Ravshan aka 32) |

**Genel değerlendirme:** K2'nin varsaydığı "büyük tarihsel parent-etiketli SI hacmi" **yok** — SI tarafı temiz, UNION formülünün SI bacağı bugün itibariyle no-op. Gerçek legacy köprü **çok küçük ve tek noktada**: 14 aktif Payment Entry, tek parent (`Ravshan aka`), 2 günlük pencere, ~4,57 milyar UZS. Bu hacim **go-live kapsamına küçük bir el-ile-yeniden-dağıtım veya PE-seviyesinde "attributed to parent, no child breakdown" özel-durum olarak dahil edilebilir** — plan §61'in "kapsam dışı" bıraktığı temizlik operasyonu, bu ölçekte artık kapsam dışı tutmanın maliyeti düşük olduğundan **go-live'a alınması önerilir** (R2 riski bu bulguyla birlikte **düşürülebilir**, ama PE şemasına child-attribution alanı eksikliği ayrı bir küçük görev olarak eklenmeli — SI'daki `custom_child_reference` benzeri bir alan Payment Entry'ye de patch'lenmeli, gelecekte aynı durum tekrarlanmasın diye).

---

## Açık maddeler / sonraki adımlar

1. **SSH ile bench/Python sürümü teyidi** (bu API taramasıyla ulaşılamadı) — `py≥3.14` gereksinimi karşılanıyor mu?
2. **`msaerp` app'inin (v0.0.1, "Sales management interface") kapsamı** — mevcut 25 custom field'ın kaynağı bu app mi, yoksa elle mi eklenmiş? Stabler kurulduğunda bu app'le çakışma olur mu?
3. **Custom field isim eşlemesi** — K3/§3.1 patch tasarımı `custom_agreed_*`/`custom_cash_difference`/`custom_allocated_advance_*` gerçek isimleriyle güncellenmeli; `custom_docs_*` adlandırması terk edilmeli veya "yeni alan" olarak `custom_agreed_*`'nin yanına ek olarak mı ekleneceği netleştirilmeli.
4. **`custom_ikpu_code` alanı Item'da yok** — "backfill" görevi "alan oluştur + backfill" olarak yeniden kapsanmalı (küçük ek iş, 27 kalem için düşük hacim).
5. **PE'ye child-attribution alanı ekleme ihtiyacı** — K2 UNION helper'ının PE bacağını çalıştırabilmesi için önerilir (bkz. yukarı).
6. **14 aktif "Ravshan aka" PE'sinin go-live kapsamına alınıp alınmayacağı** — sahiple karar (küçük hacim, tek pencere, muhasebeci onayıyla child'lara elle dağıtılabilir).
7. **`custom_payment_stream` hep "Bank"** — Cash akışının ERPNext'e hiç yansımaması nedeni sahiple teyit edilmeli (ayrı süreç mi, düşük hacim mi).
