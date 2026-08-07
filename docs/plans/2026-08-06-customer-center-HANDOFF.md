# HANDOFF — Customer Center · tipografi · AR toplam hatası

**Devir tarihi:** 2026-08-06
**Devreden:** Cowork oturumu (Claude, bulut konteyner + device bridge)
**Devralan:** Claude Code, `~/frappe-bench-local/apps/stabler`
**Durum:** Değişiklikler diskte, **commit edilmedi**, **`bench build` çalıştırılmadı**

> Bu dosyayı okuyan Claude Code'a: aşağıdaki her iddia ya doğrudan kod okunarak
> ya da çalıştırılarak doğrulandı; doğrulanamayanlar açıkça "doğrulanmadı" diye
> işaretli. Varsayım yapılan hiçbir yer yok.

---

## 0. İlk yapılacak

```bash
cd ~/frappe-bench-local && bench build --app stabler
```

Henüz hiç derlenmedi. Bench kökü Cowork oturumuna mount edilmemişti (yalnızca
`apps/stabler` bağlıydı), o yüzden `bench build`, `make guards` ve `make check`
**hiç çalıştırılmadı**. İlk iş bu.

Site: `http://localhost:8000/stabler/#/sales/customers` (Frappe varsayılan portu;
`sites/common_site_config.json` → `webserver_port` ile doğrula).

---

## 1. Diskteki durum

```
 M stabler/api/sales.py                        +39 -1
 M stabler/public/css/stabler.css              +4
 M stabler/public/js/pages/sales/Customers.vue +168 -19
 M stabler/translations/{en,ru,tr,uz,uzc}.csv  ← DİKKAT: aşağıya bak
?? stabler/public/css/stbl-typography.css
?? stabler/public/fonts/                       8 woff2, 248 KB
?? stabler/translations/*.csv.bak-i18n         ← yedek, STAGE ETME
?? stabler/public/js/pages/sales/Customers.vue.bak-skeleton  ← yedek, STAGE ETME
```

**Çeviri CSV'leri uyarısı:** `git diff --stat` her dilde **+74 satır** gösteriyor
ama bu oturumda eklenen yalnızca **5 satır/dil**. Kalan ~69 satır bu oturum
başlamadan önce zaten commit'lenmemiş durumdaydı — başka bir işten. Commit
ederken bunu ayır ya da bilerek birlikte al.

Ayrıca repoda bu oturumla ilgisi olmayan 10+ commit'lenmemiş dosya var
(`_imports_rules.py`, `imports.py`, `tender.py`, `patches.txt`,
`CommercialInvoiceForm.vue`, `ProformaForm.vue`, `PoControlBoard.vue`,
`TenderIntake.vue`, `TenderWorkspaceTabs.vue`). **Hiçbirine dokunulmadı.**

---

## 2. Asıl bulgu — AR toplam çelişkisi gerçek bir üretim hatası

Bu iş bir tasarım işi olarak başladı; kod okunduğunda 7 tenant'ın hepsini
etkileyen bir muhasebe hatası çıktı. `Customers.vue`'daki tek satır:

```js
const totalReceivable = computed(() =>
	customers.value.reduce((sum, c) => sum + Number(c.balance_base || 0), 0)
);
```

**Üç bağımsız hata taşıyordu:**

1. **Filtreyi yok sayıyordu.** Tablo `visibleRows`'u render ediyor (grup ve bölge
   filtreli), footer ham `customers`'ı topluyordu. Kullanıcı "Bayi" grubunu seçince
   liste daralıyor, toplam olduğu yerde kalıyordu. Koşulsuz — her tenant, her gün.
2. **Kolon `balance_acc`, footer `balance_base`.** Çok para birimli tenant'ta ikisi
   asla uyuşamaz. Üstelik CLAUDE.md açıkça yasaklıyor: *"Amounts must render in
   their original transaction/account currency only. Do not convert totals."*
3. **Ağaç modunda çift sayım riski.** Parent satırı kümülatif gösteriyor,
   çocukları ayrı satır olarak da render ediliyor.

Buna ek olarak `limit: 500` sessizce kesiyordu — footer 501. müşteriden sonrasını
hiç görmüyor, kullanıcıya da söylemiyordu.

**Çözüm** (`Customers.vue:172-194`): `filteredCustomers` + `visibleTotals` +
`listTruncated`. Toplam artık filtreye uyuyor, para birimi başına kırılıyor
(baz'a çevirme yok), yalnızca **kendi** bakiyelerini topluyor (çift sayım yok) ve
düz filtrelenmiş kümeden hesaplanıyor (parent açıp kapatınca toplam oynamıyor).
Backend `total_count` döndürüyor, footer `500 / 1240` rozetiyle kesmeyi itiraf
ediyor.

**Doğrulanmadı:** anjan'da gerçek veriyle `receivables_cockpit.total_receivable`
ile yeni footer toplamının farkı ölçülmedi (DB erişimi yoktu). İlk fırsatta bak —
fark büyükse cockpit sorgusunun da `disabled = 0` ve party filtresi eksik olabilir.

---

## 3. Yapılan değişiklikler

### `stabler/api/sales.py`

| Satır | Değişiklik |
|---|---|
| 360 | `only_overdue: int = 0` parametresi (default 0 → `reports.py:331` kırılmıyor) |
| 387-390 | `total_count` — ana sorgunun `WHERE`'ini (`where` değişkeni) birebir yeniden kullanan `COUNT(*)`, `LIMIT`siz |
| 423, 537 | `"total_count"` **iki return noktasına da** eklendi (erken return, `customer_rows` boşken) |
| 492-512 | Vadesi geçmiş tutarlar — **tek toplu sorgu**, `GROUP BY customer`. N+1 yok. GL toplamının kullandığı aynı `parties` tuple'ı |
| 525 | `r["overdue_base"]` satır sözlüğüne |
| 530-531 | `only_overdue` filtresi |
| ~1233 | `customer_detail` üzerindeki çift `@frappe.whitelist()` temizlendi |

Yeni doctype / alan / patch **yok**. `due_date`, `outstanding_amount`,
`conversion_rate` ERPNext standardı. `python3 -m py_compile` geçti.

### `stabler/public/js/pages/sales/Customers.vue`

| Satır | Değişiklik |
|---|---|
| 42-44 | `onlyOverdue` → `useListViewState` (URL + localStorage senkronu) |
| 172-194 | `filteredCustomers`, `visibleTotals`, `totalCount`, `listTruncated` — §2 |
| 354 | `paymentButtonTitle` — parti adı + kod + bakiye |
| 469, 473 | `only_overdue` gönderiliyor, `total_count` okunuyor |
| 880 | "Overdue only" filtresi |
| 896, 1066, 1403, 1508 | 4 × "spinner in a void" → iskelet |
| 998-1016 | Footer: "Görünen · N" + para birimi başına satır + kesme rozeti |
| 1153 | Ödeme butonu `:title="paymentButtonTitle"` + tutar inline |
| — | Cockpit KPI'ına `All customers` alt etiketi |
| — | "Statement" (XLSX ekstre) header'a çıktı |

### Tipografi (paylaşılan katman — 17 modülün hepsini etkiler)

`stbl-typography.css` (yeni) + `stabler.css`'e 4 satır `@import` + `public/fonts/`.

**Neden:** Bugüne kadar **hiçbir web font yüklenmiyordu.** `stabler.html` sadece
Tabler CDN'i çekiyor; Tabler `Inter var` ilan ediyor ama Inter dosyası hiç
indirilmiyordu → kullanıcılar Mac'te San Francisco, Windows'ta Segoe UI
görüyordu. `stabler.css`'teki `font-feature-settings: "cv02","cv03","cv04","cv11"`
Inter'e özel karakter varyantları — Inter olmadan **ölüydüler**, şimdi çalışıyorlar.

**Neden Archivo değil:** Tasarım sistemi (Modernist Tabler) Archivo kullanıyor ama
`google/fonts` `METADATA.pb`'den doğrulandı: Archivo yalnızca `latin`,
`latin-ext`, `vietnamese` taşıyor — **Kiril yok**. Stabler 5 dil konuşuyor.
Özbekçe-Kiril'in `қ ғ ҳ` harfleri `U+0460–052F` aralığında, yani `cyrillic-ext`
şart. Inter ve JetBrains Mono ikisi de taşıyor.

Self-hosted, Google CDN yok (prod Özbekistan'da; CDN düşerse tüm ERP sistem
fontuna iner). Tüm rakamlar JetBrains Mono + `tabular-nums` — CLAUDE.md'nin şart
koştuğu `font-monospace` şimdiye kadar her makinede başka fonta çözülüyordu
(Mac SF Mono, Windows Consolas), yani ekstre kolon hizası makineye göre değişiyordu.

**Doğrulama:** dili `uzc` yap, `Муддати ўтган қарз` satırında `қ` ve `ғ` komşu
harflerle aynı ağırlık/x-yüksekliğindeyse `cyrillic-ext` yüklenmiş demektir.

---

## 4. Bilinçli kararlar — tekrar tartışmadan değiştirme

**`ListToolbar.vue`'ye geçilmedi.** CLAUDE.md *"Every list page must use
ListToolbar.vue"* diyor. Customers 400px'lik bir master panel (`col-lg-4`);
`ListToolbar` tam genişlikli liste sayfaları için tasarlanmış — Select'ler +
sayaç + primary buton o darlıkta sarar ve UI kötüleşir. **Açık kalan karar:**
kurala Customers/Suppliers istisnası yazmak mı, `ListToolbar`'a dar-pane varyantı
eklemek mi. Kullanıcıya soruldu, cevap gelmedi.

**Parent'ta "Payment" butonu KAPATILMADI.** İlk plan kapatmaktı; bir inceleme
ajanı bunun mevcut bir özelliği öldüreceğini yakaladı: `Customers.vue:1048`
parent'ta `ParentBulkPaymentDialog`'u açıyor ("Split one payment across child
locations"). msa/anjan'da parent ödeme akışı buna bağlı. Yalnızca "New Invoice /
New SO" parent'ta disabled — o zaten öyleydi.

**`bench execute stabler.translations.harvest.run` ÇALIŞTIRMA.** `harvest.py:114`
`for source in sorted(rows)` ile yazıyor ama repodaki 5 CSV **sıralı değil**
(en.csv'de sıralı önek uzunluğu 1/5101). Harvest çalışırsa 5 dosyanın tamamı
yeniden sıralanır → ~5100 satırlık sahte diff. Git geçmişinde izi var:
`09cb9d4 fix(i18n): stop the merge from rewriting main's translation rows`.
Bu oturumda 5 anahtar **elle append** edildi (CRLF korunarak, `csv` modülüyle).

**`customer_detail`'e alan eklenmedi** — zaten `email_id`, `mobile_no`, `tax_id`,
`customer_group`, `territory`, `default_currency` döndürüyormuş. Açık UI
tarafındaydı, backend'de değil.

**`side-tab` dedektör bulguları yanlış pozitif.** DC dosyasındaki 3px sol/üst
şerit dekor değil, vade aşımı şiddetini kodluyor. `Tender CRM` ve
`Stabler Dashboard` da aynı deseni kullanıyor → sistem konvansiyonu.

---

## 5. Kalanlar (öncelik sırasıyla)

1. **`bench build --app stabler` + `make guards` + `make check`.** Hiç
   çalıştırılmadı. `make guards` CLAUDE.md'nin 7 kuralını grep'le zorluyor
   (`Makefile:216-254`).
2. **Gerçek veriyle doğrulama** — anjan'da footer toplamı ile
   `receivables_cockpit.total_receivable` farkını ölç (§2 sonu).
3. **`sales.py:2895` civarı ikinci çift `@frappe.whitelist()`** — `list_sales_orders`
   üzerinde. Kapsam dışıydı, tek satır.
4. **`Suppliers.vue`** — aynı üç toplam hatası orada da var (`payables_cockpit`
   karşılığı, ~1748 satır, `Customers.vue`'nun %80 kopyası). Customers canlıda
   doğrulandıktan sonra aynı yamalar.
5. **Ortak `PartyCenter` bileşeni** — Customers + Suppliers ≈ 3400 satır kopya kod,
   aynı `cust-merged-*` CSS sınıflarını bile paylaşıyorlar. Ayrı ve büyük iş.
   Plan: `docs/plans/2026-08-05-party-center-2pane-redesign.md`
6. **Tahsilat durumu + temas günlüğü** (`Aranmadı / Arandı / Söz verdi / İtirazlı`).
   Kritiğin en büyük bulgusu: *ekran parayı okuyabiliyor ama işi hatırlayamıyor.*
   Yeni doctype gerekiyor. **Şimdi yapma** — önce 1-4 canlıya çıksın, muhasebeci
   iki hafta kullansın, gerçek durum listesini ondan öğren.
7. **Kredi limiti + ödeme koşulu ihlali bayrağı** — aynı gerekçe.

---

## 6. Commit (CLAUDE.md: `git add -A` yasak)

İki ayrı commit — blast radius farklı:

```bash
# 1) Tipografi: paylaşılan katman, 17 modül
git add stabler/public/fonts stabler/public/css/stbl-typography.css \
        stabler/public/css/stabler.css

# 2) Customer Center: tek sayfa + endpoint + çeviriler
git add stabler/public/js/pages/sales/Customers.vue stabler/api/sales.py \
        stabler/translations/en.csv stabler/translations/ru.csv \
        stabler/translations/uz.csv stabler/translations/uzc.csv \
        stabler/translations/tr.csv
```

Trailer: `Co-Authored-By: Claude <noreply@anthropic.com>` — model adı/versiyonu yazma.

**Stage etme:** `*.bak-skeleton`, `*.csv.bak-i18n`, `graphify-out/`, `.smoke/`,
`scratch/`, `_to_delete/`, `PROMPT_*.md`, `stabler/translations/__pycache__/`.

---

## 7. Geri alma

```bash
# tipografi
git checkout stabler/public/css/stabler.css
rm -rf stabler/public/fonts stabler/public/css/stbl-typography.css

# Customer Center
git checkout stabler/public/js/pages/sales/Customers.vue stabler/api/sales.py
# ya da nokta atışı yedekler:
#   stabler/public/js/pages/sales/Customers.vue.bak-skeleton  (iskelet öncesi)
#   stabler/translations/*.csv.bak-i18n                       (i18n öncesi)
#   /tmp/sales.py.bak                                         (backend öncesi, silinmiş olabilir)
```

---

## 8. İlgili dokümanlar

| Dosya | İçerik |
|---|---|
| `docs/plans/2026-08-05-customer-center-critique-ve-oneri.md` | Impeccable kritiği: 19/40 Nielsen skoru, ölçülmüş kontrast/dokunma hedefi/kesilme kanıtı, 7 hamlelik öneri. **Yöntem notu: Assessment A izole ajan olarak koşmadı, banner'ı oku.** |
| `docs/plans/2026-08-05-party-center-2pane-redesign.md` | Vue uygulama planı, ortak `PartyCenter` bileşeni tasarımı |
| `Customer Center - Modernist Tabler.dc.html` (Tender tasarım paketi, repoda değil) | Görsel spec. Tek başına açılmaz — `support.js` + `_ds/` yanında olmalı |

---

## 9. Bu oturumda ölçülen sayılar (DC dosyası üzerinde, referans)

Tasarım tarafında yapılan düzeltmelerin etkisi — Vue'ya henüz tamamı taşınmadı:

| Ölçüm | Önce | Sonra |
|---|---|---|
| WCAG AA kontrast hatası | 35+ benzersiz kombinasyon (en kötüsü 2,43:1) | 0 |
| 44px altı kontrol | 26 | 0 |
| Kesilen metin (1320px) | 9 | 0 |
| 1280px yatay taşma | 40px | 0 |

`#9099a6` hiçbir zeminde AA geçmiyordu ve muhasebe ekranının **tüm etiket
katmanını** taşıyordu. `#667382`'ye çevrildi (4,84:1) — görünüm neredeyse aynı.
Vue tarafında karşılığı `.stbl-subtext` / `text-secondary`; oraya henüz
uygulanmadı, `stabler.css`'te tek yerden yapılabilir.
