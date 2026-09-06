# Mikas — ihale tam döngü gerçek deneme senaryosu (adım adım, ekran görüntülü)

Tarih: 2026-09-05. Hazırlayan: Claude (ölçerek), onay ve yürütme: Zafar.
Kapsam: ADR-609 P1–P5b `main`'de ve prod'da (Zafar 2026-09-04 deploy etti; deploy sonrası
doğrulama çıktıları henüz bu dosyaya işlenmedi — `.worktrees/p5b-evidence-2026-09-04/deploy-runbook-2026-09-04.md` §3).

**Kural:** her adımın bir ekran görüntüsü vardır. Ekranı OLAN adımlar yerel `stabler` sitesinde
(Mikas kopyası) yürünerek çekildi; ekranı OLMAYAN adımlar için tasarım mockup'ı vardır.
Görüntüler: `2026-09-05-mikas-deneme-ekranlar/` (64 dosya, 5,4 MB; `ls | wc -l`, `du -sh`). Retina yakalamalar
1600 px genişliğe indirildi ve 256 renk paletine indirgendi (`sips --resampleWidth`, Pillow `quantize`);
ham 24 MB'lık asıllar depoda değil.
Tasarım kanvası (düzenlenebilir): <https://claude.ai/code/artifact/1723b5a1-32b2-4c44-aa9d-41dd4bf37881>

Durum sütunu: **✓ çekildi** · **✓⚠ çekildi, kusurla** (adım tamamlandı ama bir hata ya da geçici çözüm
gerekti — §G) · **◆ tasarım** (ekran yok, mockup var) · **✗ ekran yok** (tasarım da yok, §E).

**Yürütme koşulları (ölçüldü):**
- Arayüz dili **Rusça** (Zafar: "testleri ruscha devam et"). Görüntülerdeki İngilizce metinler
  katalog boşluğudur, §H'de listelenmiştir.
- Şirket: **Mikas** (`Stabler Company Modules`: enable_tender 1, **enable_crm 0**, enable_modern_sales_order 0,
  enable_sales 1, enable_purchasing 1, enable_money 1). CRM modülü kapalı olduğu için `/crm/deals/...`
  rotaları Mikas'ta yoktur; A2 ve C2'nin CRM'e bağlı kısımları başka ekranlardan doğrulandı.
- Kullanıcı: Zafar'ın kendi hesabı (tüm roller). **Rol kapıları bu yürüyüşte sınanmadı**; §F'de prod
  yürüyüşü Mikas kullanıcılarıyla yapılmalı.
- Yalnız yerel `stabler` sitesine yazıldı (Zafar: "yerel kayıtlara onay veriyorum"). Prod'a hiçbir şey
  yazılmadı. Yaratılan kayıtlar §0.1'de.

## 0. Önkoşullar (ölçüldü 2026-09-05, yerel `stabler` sitesi, yürüyüş öncesi)

| Koşul | Ölçüm | Kaynak |
|---|---|---|
| Tender modülü Mikas'ta açık | evet (TenderNav görünür, `session.canAccessModule("tender")`) | `Stabler Company Modules` |
| Accounting Dimension `Tender` (CRM Deal) | var, `mandatory_for_pl = 1` | v103 yaması |
| GENEL GİDER anlaşması | `CRM-DEAL-2026-00014` · deal_type Overhead · UZS | `frappe.db.get_value` |
| GENEL GİDER'e düşmüş GL satırı | 5 satır, 2 Mal Kabul Fişi (MAT-PRE-2026-00003/00004), EIV alacağı 189 985 422,00 сўм | `tender_gl_pnl` |
| Aktif ihale anlaşması / RFQ / sourcing kararı | **0 / 0 / 0** — deneme bunları sıfırdan yarattı | `frappe.db.count` |
| Tedarikçi teklifi | 46, hiçbirinde landed charge yok | `Supplier Quotation` |
| Stokta mal (Stores - MIK) | UAT-IMP-BEEF-TRIM-01 20 000 Kg · UAT-IMP-BEEF-LIVER-01 5 000 Kg | `tabBin` |

Roller (`stabler/api/organization.py:137`): Stabler Tender Director / Sourcing / Logistics / Declarant /
Finance, ayrıca Sales User/Manager. Deneme için en az **Sourcing + Director + Finance** rolleri olan
bir kullanıcı gerekir (tek kullanıcıda üçü de olabilir).

### 0.1 Yürüyüşün yarattığı kayıtlar (yerel `stabler`, Mikas — hepsi `[DEMO]` etiketli)

| Adım | Kayıt | Durum (DB, yürüyüş sonu) |
|---|---|---|
| B1 | CRM Deal `CRM-DEAL-2026-00015` "UAT 2026-09-05 — Поставка запчастей для вагонов [DEMO]", UZEX-UAT-2026-0905, müşteri O'zbekiston temir yo'llari AJ [DEMO], 250 000 000 UZS, teminat 5 000 000 | `custom_tender_stage = won`, intake `result = won`, CRM `status = Qualification` (değişmedi) |
| B1 | Tender Master `TND-2026-00002` (otomatik) | başlık = alıcı adı, tarihler boş, toplam 0 |
| B3 | RFQ `PUR-RFQ-2026-00001` — 5 tedarikçi, yanıt 12.09.2026 | gönderildi (WhatsApp → Communication `m42civp7gm`), 5/5 yanıtlandı |
| B4 | Supplier Quotation `PUR-SQTN-2026-00047` Temiryo'l ta'minot 214 800 000 · `00048` Sanoat kompleks 223 200 000 · `00049` Hebei Rail Parts 194 400 000 · `00050` Shandong Heavy 201 600 000 · `00051` UralVagonSnab 208 800 000 | hepsi submitted |
| B5 | `custom_landed_charges`: 00047 +1 500 000 → 216 300 000 (en ucuz teslim) · 00048 +1 800 000 · 00049 +30 140 000 → 224 540 000 · 00050 +30 560 000 · 00051 +28 080 000 | `update_quotation_landed` |
| B7 | Tender Sourcing Decision `TSD-2026-00001` | Approved; selected = cheapest = 00047; 5 teklif / 3 ülke; istisna yok |
| C3 | Purchase Order `PUR-ORD-2026-00009` 214 800 000 | submitted; `tender` = `custom_crm_deal` = 00015 (başlık + satır) |
| C4 | Purchase Receipt `MAT-PRE-2026-00005` 120 × 1 790 000 | Completed, per_billed 100; GL 2 satır, ikisinde de tender 00015 |
| C5 | Purchase Invoice `ACC-PINV-2026-00883` 214 800 000 | Unpaid; update_stock 0; GL: Stock Received But Not Billed borç / Creditors alacak, ikisinde de tender 00015 |
| C6 | Journal Entry (Bank Entry) `ACC-JV-2026-07011` 1 500 000 Legal Expenses ← Cash | submitted; GL 2 satır, ikisinde de tender 00015 |
| C2 | Sales Order `SAL-ORD-2026-05895` 120 × 1 850 000 = 222 000 000 | Closed, per_delivered 100, per_billed 100; `tender` = `custom_crm_deal` = 00015; rezerv `MAT-SRE-2026-03623` Delivered 120 |
| C7 | Sales Invoice `ACC-SINV-2026-07435` 222 000 000, update_stock 1 | Unpaid; GL: Debtors 222 000 000 / Sales 222 000 000 / COGS 891 010 000 / Stock In Hand 891 010 000, dördünde de tender 00015; SLE −120 |

`tender_gl_pnl("CRM-DEAL-2026-00015")` yürüyüş sonu: gelir 222 000 000 · COGS 891 010 000 · gider
1 500 000 · sonuç −670 510 000. COGS'un neden 214 800 000 değil 891 010 000 olduğu §I.2'de (veri artığı,
kod hatası değil).

---

## A. Giriş ve modül kontrolü

### A0 — Giriş ✓
- Rota: `http://localhost:8000/stabler#/login`
- Görüntü: `00-giris.png`

### A1 — İhale modülü ve üst çubuk ✓
- Rota: `/tender/overview`. TenderNav rol kapılarıyla göründü.
- Görüntü: `01-tender-genel-bakis.png` (yürüyüş öncesi), `01b-tender-genel-bakis-yuruyus-sonrasi.png`
  (yürüyüş sonrası; huni "3 выиграно / 1 проиграно · 75%").
- Not: `#/dashboard`'da ihale görünmemesinin sebebi aktif şirketin ANJAN olmasıydı; Mikas'a geçildi.

### A2 — GENEL GİDER anlaşması var ✓ (Deal 360 yerine seçiciden)
- `/crm/deals/CRM-DEAL-2026-00014` Mikas'ta **yok** (enable_crm 0). GENEL GİDER'in varlığı ve sırası
  gider formunun ihale seçicisinden doğrulandı: `list_deals(active_tenders=1)` → ilk satır
  "GENEL GİDER · Общие расходы", ikinci satır UAT anlaşması (`bench execute` ile de ölçüldü: 2 kayıt,
  `is_overhead` 1/0).
- Görüntü: `19b-gider-ihale-secici-genel-gider-ilk-sirada.png` (C6 ile ortak).

---

## B. Kazanım öncesi (pre-win)

### B1 — İhale anlaşması oluştur ✓
- Rota: `/tender/crm` → yeni ihale (drawer). Kayıt `CRM-DEAL-2026-00015`; `TND-2026-00002` otomatik açıldı.
- Görüntü: `03-ihale-crm-kanban.png`, `03b-ihale-yeni-anlasma-drawer.png`, `03c-ihale-crm-yeni-kart.png`.
- Gözlem: kart ve tüm seçiciler anlaşmayı **kurum adıyla** gösterir (ihale adı / UZEX numarası hiçbir yerde
  etiket değil) — aynı kurumun 5 kartı ayırt edilemez (§H.1). Otomatik Tender Master başlık = alıcı, tarihler
  boş, toplam 0 (§G.12).

### B2 — Belge zinciri ✓
- Rota: `/tender/documents`. Lot için 7 belge gereksinimi girildi ve kaydedildi.
- Görüntü: `04-belge-merkezi.png`, `04b-belge-merkezi-lot-bos-cheklist.png`,
  `04c-belge-merkezi-cheklist-duzenle.png`, `04d-belge-merkezi-lot-cheklist-kayitli.png`.
- Gözlem: boş kontrol listesi **%100 hazır** okunur (`_tender_documents.py:182`,
  `required == 0 → 100`) (§G.9). PO kontrol panosunun "Документы" sekmesi aynı lot için "Пока нет требований"
  der, genel bakış şeridi "Документы 0/5" yazar, Belge merkezi 7 sayar — üç ekran, üç sayı (§G.8):
  `04e-po-kontrol-belgeler-sekmesi-bos.png`.

### B3 — RFQ oluştur ve yazdır ✓
- Rota: `/tender/rfq/new` → `/tender/rfq/PUR-RFQ-2026-00001` → `/print`. 5 tedarikçi, yanıt tarihi 12.09.2026,
  WhatsApp ile "gönderildi" işaretlendi (Communication yazıldı).
- Görüntü: `05-rfq-listesi-bos.png`, `06a-rfq-yeni-form-dolu.png`, `06b-rfq-detay-taslak.png`,
  `06c-rfq-yazdir.png`, `06d-rfq-detay-gonderildi.png`, `06e-rfq-detay-5-of-5-yanitlandi.png`.
- Gözlem: "gönderildi" işareti detay rozetinde görünmez — 5/5 yanıt alınmış RFQ hâlâ "Черновик" (§G.13).
  Yazdırma metni İngilizce cümle içerir, beş katalogda da yok (§H.2).

### B4 — Tedarikçi tekliflerini gir ✓⚠
- Rota: RFQ detayı → "Записать предложение" → `/tender/sourcing?rfq=…` çekmecesi. 5 teklif girildi ve gönderildi.
- Görüntü: `07a-sourcing-teklif-yok.png`, `07b-teklif-cekmecesi-dolu.png`, `07c-teklif-taslak-kaydedildi.png`,
  `07d-sourcing-ilk-teklif-gonderildi.png`, `07e-sourcing-bes-teklif-karsilastirma.png`.
- Kusur: Sourcing başlığındaki "Добавить предложение" butonu 404 verir — "RFQ not found: {isTrusted…}"
  (`SourcingWorkspace.vue:455` click olayını `rfq` parametresi olarak geçirir) (§G.4). Geçici çözüm: RFQ
  detayından girmek.

### B5 — Teklif başına landed (varış) maliyeti ✓
- Rota: `/tender/sourcing` → teklif satırı → nakliye maliyeti editörü. Kanonik kalem türleri
  (`_landed_charge_types.py`). Karşılaştırma teslim toplamına göre yeniden sıralandı: etiket lideri Hebei
  (194 400 000) teslimde 224 540 000'e düştü, Temiryo'l 216 300 000 ile en ucuz teslim oldu.
- Görüntü: `08a-nakliye-maliyet-editoru-dolu.png`, `08b-sourcing-nakliye-dahil-karsilastirma.png`.

### B6 — Teklif fiyatlaması ve başvuru paketi ✓ (yalnız görüntülendi, kaydedilmedi)
- Rota: `/tender/po-control?deal=CRM-DEAL-2026-00015` → Обзор. BidPricing "Взять из PO (с доставкой):
  214 800 000,00 сўм · 1 PO"; hedef marj %20 → teklif fiyatı 301 352 840,97; plan-gerçek tablosu.
  "Сохранить ценообразование" ve "Подготовить пакет заявки" **tıklanmadı** (kayıt yok).
- Görüntü: `09a-po-kontrol-genel-bakis.png` (tam sayfa; C9'un defter tablosu da bu görüntüde).

### B7 — Tedarik kararı: kaydet ve onaylat ✓
- Rota: `/tender/sourcing` → karar paneli. `TSD-2026-00001` kaydedildi, onaylandı (selected = cheapest = 00047).
- Görüntü: `10a-karar-paneli-dolu.png`, `10b-karar-taslak-kaydedildi.png`, `11-karar-onaylandi.png` (tam sayfa).

---

## C. Kazanım sonrası (post-win)

### C1 — İhale kazanıldı ✓
- Rota: `/tender/crm` → kart "Закупки" sütunundan "Выиграно" sütununa sürüklendi
  (`move_deal_stage(name, "won")`, `tender.py:3331`). DB: `custom_tender_stage = won`, intake `result = won`,
  `custom_tender_stage_entered_at` yazıldı.
- Görüntü: `12a-kanban-tasima-oncesi.png`, `12b-kanban-kazanildi-suutununa-tasindi.png`.
- Gözlem: PO, mal kabul ve faturalar varken kart hâlâ "Закупки"deydi — kazanım sonrası sütunlar yalnız
  `result = won` sonrası türetilir (tasarım gereği; ama operasyon belgeleri olan bir lotun "sourcing"de durması
  yanıltıcı, §G.14). CRM `status` "Qualification" kaldı. Toast iki kez basıldı (§H.4). Sütun adları:
  "Поражений" (hal eki), "PO Created" (İngilizce) (§H.2).

### C2 — Satış siparişi (SO) anlaşmadan ✓
- Rota: `/sales/orders/new?crm_deal=CRM-DEAL-2026-00015&customer=…` — form (Classic; `enable_modern_sales_order 0`)
  "Из тендерной сделки: CRM-DEAL-2026-00015" bandını gösterdi, müşteri ön-dolu geldi.
  Kalem 120 × 1 850 000 = 222 000 000; "Провести и зарезервировать склад" → `SAL-ORD-2026-05895`, rezerv 120.
- Görüntü: `13a-satis-siparisi-yeni-ihale-anlasmasindan.png`, `13b-satis-siparisi-dolu-stok-121-mevcut.png`,
  `13c-satis-siparisi-gonderildi-rezerve-120.png`, `13d-sozlesme-panosu-yeni-so-gorunmuyor.png`.
- Gözlemler: (a) Mikas'ta bu forma **ulaştıran buton yok** — "Sözleşme oluştur" yalnız CRM modülünün
  `crm/Deals.vue:532` çekmecesinde, ihale kanbanında yok; rota elle yazıldı (§G.15). (b) Kalem seçilince
  fiyat listesi 2 270 000 000,00 getirdi (demo fiyat kaydı), elle düzeltildi. (c) Gönderilmiş SO'da
  "К ВЫПЛАТЕ ВСЕГО —", "ИТОГО —" (satır toplamı 222 000 000 iken) (§G.3b). (d) Toast: "Partially billed — 0%
  invoiced." — %0 faturalanmış belgeye "kısmen faturalandı" (§H.2). (e) `/tender/board` sözleşme panosu yeni
  SO'yu hiçbir sütunda göstermez ("Closed 0") (§G.16).

### C3 — Kazanan tekliften PO ✓⚠
- Rota: `/tender/sourcing` → onaylı karar → "Создать заказ на покупку" → **403 "Quotation does not belong to the
  selected company."** (§G.1, P0). Geçici çözüm: `/purchasing/orders/new` formundan elle PO; "Tender (Deal)"
  seçicisinden UAT anlaşması seçildi; DB'de `custom_crm_deal` ve `tender` başlık + satırda 00015.
- Görüntü: `14a-po-formu-ihale-alani-dolu.png`, `14b-po-taslak-kaydedildi.png`, `14c-po-onaylandi-to-receive.png`,
  `14d-po-kontrol-tedarikci-ve-po-sekmesi.png` (5 teklif / 2 ülke rozetleri yeşil; 1 PO, 214 800 000, %100 alındı).
- Gözlem: PO seçicisinde 5 aynı etiket (kurum adı), anlaşma adıyla arama yok, `?deal=` ön-doldurma çalışmaz
  (§G.7).

### C4 — Mal kabul ve landed cost ✓⚠
- PO detayında "Приёмка" / "Создать счёт" butonları **çıkmadı** (§G.3): fiş, butonun çağırdığı uç nokta
  `create_purchase_receipt_from_po` ile sayfa içinden oluşturuldu, sonra `/purchasing/receipts` çekmecesinden
  gönderildi → `MAT-PRE-2026-00005`. GL: Stock Received But Not Billed alacak / Stock In Hand borç 214 800 000,
  ikisi de tender 00015 (`stamp_tender`, `_ITEM_SOURCES`).
- `/purchasing/landed-cost-review/Purchase Receipt/MAT-PRE-2026-00005`: "No landed-cost lines have been found",
  "Нечего оформлять в ваучер" — bu fişe bağlı LCV/PI kalemi yok, ekran doğru boş. LCV **oluşturulmadı**.
- Görüntü: `16a-mal-kabul-listesi-taslak.png`, `16b-mal-kabul-detay-taslak.png`, `16c-mal-kabul-onaylandi.png`,
  `16d-mal-kabul-cekmecesi-fatura-olustur.png`, `16e-po-kontrol-teslimat-sekmesi.png`,
  `17a-landed-cost-review-mal-kabul.png` (tam sayfa).
- Gözlem: inceleme ekranı "Принято (кг) 120" yazar, kalemin birimi `litr` (demo kalem) — etiket birimi sabit
  "kg" (§H.3). Mal kabul çekmecesinde "СВЯЗАННЫЕ ДОКУМЕНТЫ —" (PO bağlı olduğu hâlde) (§G.17).
- B5 teklif landed tahmini ↔ gerçekleşen LCV karşılaştırması bu yürüyüşte **yapılamadı** (LCV yok) — §E.1 açık.

### C5 — Satın alma faturası ✓
- `/purchasing/invoices/new`: "Тендер" alanı **GENEL GİDER ön-dolu** ve değiştirilebilir
  (`18a`). Fişten fatura: mal kabul çekmecesi "Создать счёт" → `ACC-PINV-2026-00883` taslak; formda alan PO'nun
  ihalesiyle dolu ve **kilitli** ("Задано заказом на закупку", `tender_locked`) (`18d`); gönderildi → Unpaid;
  GL iki satırda da tender 00015; fişin `per_billed` 100.
- Görüntü: `18a-satinalma-faturasi-yeni-genel-gider-varsayilan.png`,
  `18b-yeni-fatura-dokunulmamis-form-kaydedilmemis-uyarisi.png`, `18c-fatura-listesi-fisten-taslak-olustu.png`,
  `18d-fatura-taslak-ihale-alani-siparisten-kilitli.png`, `18e-fatura-onay-modali-ingilizce.png`,
  `18f-fatura-gonderildi-odenmedi.png`.
- Gözlemler: (a) dokunulmamış yeni fatura formundan çıkarken "kaydedilmemiş değişiklik" uyarısı — GENEL GİDER
  varsayılanı formu kirli sayıyor (§G.10). (b) "Создать счёт" `/purchasing/invoices?open=<ad>` rotasına
  gider ama liste `open` parametresini okumaz; kullanıcı taslağı listede kendi bulur (§G.6). (c) Onay modali
  İngilizce "Submit document? …" (§H.2). (d) Kilitli ihale alanı kurum adını gösterir, anlaşma adını değil (§H.1).

### C6 — Gider kaydı (ihaleye) ✓
- `/money/expenses` → "Новые расходы": "Тендер (сделка)" **GENEL GİDER ön-dolu**; liste açılınca GENEL GİDER
  ilk sırada, UAT anlaşması ikinci (`19b`). UAT anlaşması seçildi; Cash → Legal Expenses 1 500 000
  "Тендерная документация УзЭкс — сбор за участие [DEMO]" → `ACC-JV-2026-07011` (Bank Entry, submitted).
  GL iki satırda da tender 00015; `tender_gl_pnl` expenses 1 500 000.
- Görüntü: `19a-gider-formu-genel-gider-varsayilan.png`, `19b-gider-ihale-secici-genel-gider-ilk-sirada.png`,
  `19c-gider-formu-ihaleye-bagli-dolu.png`, `19d-gider-kaydi-gonderildi-detay.png`.
- Gözlemler: kayıt detayı hangi ihaleye yazıldığını **göstermez** (alanlar: ad, tarih, KIND, alıcı, not, hesaplar)
  (§G.18); "KIND" İngilizce (§H.2). "Выплатить с" listesi Cash'in yanında öz sermaye hesaplarını da sunar
  (Capital Stock, Retained Earnings…) — `equity_accounts` bilinçli görünüyor, karar Zafar'ın (§E.6).

### C7 — Sevk irsaliyesi ve satış faturası ✓ (irsaliye ekranı yok — fatura stok düşer)
- SPA'da sevk irsaliyesi **oluşturma ekranı yok** (`DeliveryNotes.vue` yalnız `list_/get_delivery_note`);
  `create_sales_invoice` (`sales.py:2242`) faturayı **`update_stock = 1`** ile açar, gönderim stoku düşer ve
  rezervi kapatır. Akış: SO detayı "Создать счёт-фактуру" → `ACC-SINV-2026-07435` taslak → "Отправить" →
  Unpaid, vade 10.09.2026. SLE −120 (kalan 1), SO Closed 100/100, rezerv Delivered.
- GL (dördü de tender 00015): Debtors 222 000 000 borç · Sales 222 000 000 alacak · COGS **891 010 000** borç ·
  Stock In Hand 891 010 000 alacak. COGS'un kaynağı §I.2.
- Görüntü: `21a-satis-faturasi-taslak-siparisten.png`, `21b-satis-faturasi-gonderildi-odenmedi.png`.
- Gözlemler: fatura formunda ihale alanı **hiç görünmez** (`SalesInvoiceForm.vue` "tender" içermez) (§G.18);
  "СВЯЗАННЫЕ ДОКУМЕНТЫ —" (SO bağlı) (§G.17); PO kontrol "Доставка" sekmesi "ДОСТАВКА Нет связанных документов"
  — irsaliyesiz teslimi teslimat saymaz (§G.19); "Send to Didox" İngilizce, "Юк хати" Özbekçe (§H.2).

### C8 — Gümrük ve lojistik kuyrukları ✓
- `/tender/customs`: `PUR-ORD-2026-00009` "Выпущен" sütununda (ETA 05.09.2026 сегодня). `/tender/logistics`:
  aynı PO "Принят" sütununda. İkisi de fişten türetildi; gümrük/lojistik alanları elle doldurulmadı.
- Görüntü: `22-gumruk-kuyrugu.png`, `23-lojistik-panosu.png` (tam sayfa).

### C9 — İhale kâr/zarar: defter ve belgeler ✓
- `/tender/po-control?deal=…` → Обзор → "Главная книга и документы" (`09a`, tam sayfa) ve "Финансы" sekmesi
  (`24b-po-kontrol-finans-sekmesi.png`).
- Ölçülen defter tablosu (belgeler ↔ GL ↔ Δ): gelir 198 214 285,71 ↔ 222 000 000,00 ↔ 23 785 714,29 ·
  maliyet 214 800 000,00 ↔ 891 010 000,00 ↔ 676 210 000,00 · gider 1 500 000,00 ↔ 1 500 000,00 ↔ 0 ·
  sonuç −18 085 714,29 ↔ −670 510 000,00.
- Gözlemler: (a) belge tarafı gelir = 222 000 000 / 1,12 — fatura **KDV'siz** iken belge tarafı %12 KDV
  düşmüş görünüyor (aritmetik ölçüldü, kod okunmadı) (§G.11). (b) "Счёт продажи · КОЛИЧЕСТВО 2": tek fatura
  iki GL satırı sayıldı — sütun belge adedi gibi okunuyor (§G.11). (c) Finans sekmesi: AP 214 800 000
  "Невыплаченная: 0,00", AR 222 000 000 "Невыплаченная: 0,00" — **iki fatura da ödenmemiş** (§G.2, P1).

### C10 — Direktör paneli ✓
- `/tender/portfolio` yürüyüş öncesi (`25-direktor-paneli.png`) ve sonrası (`25b-direktor-paneli-yuruyus-sonrasi.png`,
  tam sayfa).
- Gözlem: direktör paneli "66.7% · 2 выиграно / 1 проиграно", genel bakış aynı anda "75% · 3 выиграно /
  1 проиграно" — iki ekran kazanılan sayısında anlaşmıyor (§G.20).

---

## D. Ekranı olmayan adımlar — tasarım ◆

### D1 — GENEL GİDER kâr/zarar ekranı ◆
- Bugün: `tender_gl_pnl("CRM-DEAL-2026-00014")` çalışır (rakamlar §0), ama yalnız PO kontrol panosunda
  bir anlaşma seçildiğinde görünür; GENEL GİDER'in kendi sayfası yok, dönem filtresi yok.
- Tasarım: yeni rota `/tender/overhead`, TenderNav'da "Genel gider" (director/finance). KPI şeridi, uyarı bandı,
  BidPricing ile aynı "Defter ve belgeler" tablosu, sağda kaynak belgeler + "İhaleye taşı…".
- Backend boşlukları: dönem filtresi; damga kaynağı (varsayılan/seçildi) GL'de tutulmuyor; yeniden etiketleme
  uç noktası yok.
- Görüntü: `tasarim-00-canvas.png`, `tasarim-01-genel-gider-kz.png` · kanvas: Main artboard.

### D2 — Stok çıkışında ihale seçimi ◆
- Bugün: Custom Field `tender` Stock Entry ve Stock Entry Detail'de var (v103), ama Stabler'ın
  "Yeni stok kaydı" modalı alanı göstermez, `create_stock_entry` geçirmez ve `stamp_tender` Stock Entry'yi
  kapsamaz. Mikas'ta `mandatory_for_pl = 1` olduğu için ihalesiz Malzeme çıkışı ERPNext'in ham hatasıyla düşer.
- Tasarım: "İhale (Anlaşma)" Typeahead (Expenses ile aynı bileşen/sorgu), yalnız Çıkış ve Transfer'de;
  hata durumu için eylemi adlandıran mesaj + "GENEL GİDER'i seç" hızlı eylemi.
- Görüntü: `tasarim-02-stok-cikisi-ihale-secici.png` · kanvas: StockEntryTender ve StockEntryTenderRequired.

---

## E. Açık kararlar ve bilinen boşluklar

1. **Landed KDV farkı uyarısı** — teklif landed tahmini (B5) ile gerçekleşen LCV (C4) arasındaki fark için
   eşik/uyarı kararı verilmedi (kurul kaydı §7). Bu yürüyüşte LCV oluşmadı, fark ölçülemedi. Karar Zafar'ın.
2. **Dönem filtresi** — `tender_gl_pnl` tarih almıyor (P5b §12). İhale için sorun değil, GENEL GİDER için şart.
3. **Prompt 03–12 tasarım göçü** — ADR §2.1 envanterindeki ekranlar `ds-*` katmanına taşınmadı.
4. **Katalog:** `tr.csv` "Issues" → "Sorunlar" (stok çıkışı yerine "problemler"); mockup "Çıkışlar" yazıyor.
5. **Deploy doğrulaması** — 2026-09-04 deploy'unun §3 kontrolleri (DDL, Patch Log, çeviri önbelleği, P5b uç
   noktası, ekran smoke, ikinci tenant, drift, loglar) bu dosyaya henüz işlenmedi.
6. **Gider "Выплатить с" listesinde öz sermaye hesapları** (`money.equity_accounts`) — ortak cebinden ödeme
   senaryosu için bilinçli mi, Zafar karar verir.
7. **Sevk irsaliyesi** — SPA irsaliye açmaz; teslim satış faturasının `update_stock=1`'i ile olur. Mikas'ın
   ihale teslimatında ayrı irsaliye belgesi gerekiyorsa ekran yok (tasarım da yok — ✗).
8. **Kazanım sonrası sütunların türetimi** — `result = won` olmadan PO/fiş/fatura kartı taşımaz (C1). Kural
   böyle kalacak mı, yoksa operasyon belgesi olan lot otomatik "won" sayılacak mı?

## F. Prod'a geçiş

Yerel döngü ✓ (kusurlarıyla) — §G.1 (P0) düzeltilmeden prod'da C3 "tekliften PO" adımı **çalışmaz**; elle PO
geçici çözümü prod'da da geçerlidir. Aynı adımlar `mikas` prod sitesinde **Mikas kullanıcılarıyla** (rol
kapıları!) yürünür; ajan prod'a yazmaz. Her adımın ekran görüntüsü bu klasöre `prod-NN-*.png` adıyla eklenir.

---

## G. Bulgular — kod (dosya:satır, yeniden üretim, sunucu mesajı)

Öncelik: P0 doğruluk/para · P1 akış kırık · P2 yanıltıcı ya da eksik. Hiçbiri bu oturumda düzeltilmedi;
her biri ayrı, test-önce bir iş.

1. **P0 — `create_po_from_quotation` her zaman 403.** `stabler/api/purchasing.py:3557`
   `selected_company = _assert_company_scope(company)`; `stabler/api/approvals.py:124-135` fonksiyonu yalnız
   doğrular ve **`None` döndürür** → `:3563 sq.company != None` → `frappe.throw(_("Quotation does not belong to the
   selected company."), PermissionError)`. Yeniden üretim: onaylı karar + "Создать заказ на покупку" (C3).
   `stabler/tests/test_po_from_quotation.py:323` `approvals._assert_company_scope = lambda company: company`
   monkeypatch'i hatayı testten gizler. `sourcing.py:69-76`'nın kullandığı `tender_master.require_selected_company`
   şirketi döndürür — düzeltme ve testin monkeypatch'ini kaldırma birlikte.
   **Düzeltildi 2026-09-05** (dal `fix/po-from-quotation-company-scope`): şirket `_require_company`'den alınır,
   `_assert_company_scope` yalnız doğrular; stub gerçek sözleşmeyi (None) yansıtır; yeni test
   `test_company_comes_from_require_company_not_from_the_scope_assertion` eski kodda aynı mesajla düşer, yenide geçer.
   Canlı doğrulama: yerel sitede `create_po_from_quotation("PUR-SQTN-2026-00047", "Mikas")` artık 403 yerine mevcut
   PO'yu (`PUR-ORD-2026-00009`, `existing: True`) döndürür; yeni kayıt yazılmadı.
2. **P1 — PO kontrol "Финансы": ödenmemiş her zaman 0.** `stabler/api/tender.py:911`
   `fields.extend(["outstanding_amount", "base_outstanding_amount"])` — `base_outstanding_amount` sütunu
   Purchase Invoice ve Sales Invoice'ta **yok** (ölçüm: `select base_outstanding_amount …` → 1054 Unknown column;
   DocField ve Custom Field'da yok). `:1108-1118` `flt(None) = 0` toplar; `ap_paid = ap_total − 0`.
   `tender_workspace("CRM-DEAL-2026-00015")` ölçümü: ap_total 214 800 000, ap_outstanding 0, ap_paid 214 800 000;
   ar aynı — iki fatura da Unpaid. Ekran: `24b`.
   **Düzeltildi 2026-09-05** (dal `fix/tender-finance-outstanding`): sorgu var olmayan sütunu değil
   `outstanding_amount`, `conversion_rate` ve `party_account_currency`'yi ister; `_base_outstanding_amount`
   ERPNext kuralıyla şirket para birimine çevirir — taraf hesabı fatura para birimindeyse faturanın kuruyla
   çarpar, değilse tutar zaten şirket para birimindedir (`calculate_outstanding_amount`,
   erpnext/controllers/taxes_and_totals.py). Hata hiç görünmüyordu çünkü `frappe.get_list` bilinmeyen alanı
   sessizce düşürür (ölçüm: dönen satırda anahtar yok, istisna yok). Yeni testler
   `test_workspace_finance_outstanding_survives_frappe_dropping_the_column_it_never_had` ve
   `test_document_row_states_outstanding_in_company_currency_the_way_erpnext_keeps_it` eski kodda
   `(0.0, 100.0) != (100, 0)` ve `0.0 != 260000` ile düşer, yenide geçer. Canlı doğrulama:
   `tender_workspace("CRM-DEAL-2026-00015")` → ap_outstanding 214 800 000 / ap_paid 0, ar_outstanding
   222 000 000 / ar_paid 0; gerçek USD fatura `ACC-PINV-2026-00882`: 3 800 × 11 960,18 → 45 448 684 =
   `base_grand_total`. `make test-bench` çalıştırılmadı: iki test modülü de frappe-free, bench'e özel test yok.
3. **P1 — PO detayı `fromDetail` docstatus/per_received/grand_total'ı düşürür.**
   `PurchaseOrderForm.vue:159-190` yalnız supplier/currency/…/items döndürür; `:374-380 canReceive`,
   `:429-435 canCreateInvoice` ve `:583-595` KPI'ları bu alanları okur → gönderilmiş PO'da "Приёмка" /
   "Создать счёт" yok, KPI "—" (`14c`). **3b (gözlem):** Classic SO detayında da "К ВЫПЛАТЕ ВСЕГО —", "ИТОГО —"
   (`13c`); aynı sınıf, kaynağı okunmadı.
   **Düzeltildi 2026-09-05** (dal `fix/po-form-server-facts`): `fromDetail` artık sunucunun salt-okunur
   gerçeklerini modele taşır — `docstatus`, `status`, `net_total`, `grand_total`, `per_received`, `per_billed`,
   `purchase_invoices`, `purchase_receipts` ve satırlarda `name` (mal kabul diyaloğunun gönderdiği `po_detail`;
   sunucu bunu zorunlu tutar: `create_purchase_receipt_from_po` "po_detail is required") ile `received_qty`.
   `toPayload` bunları geri göndermez; kirlilik koruması yükleme sonrası `reset(model)` ile sıfırlandığı için
   sahte "kaydedilmemiş değişiklik" doğmaz. Yeni spec `purchaseOrderFormServerFacts.spec.js` `fromDetail`'i
   gerçek `grossRate` ile çalıştırır; dört iddiası da eski kodda `undefined` ile düşer, yenide geçer. Canlı
   doğrulama (yerel site, yeni bundle): `PUR-ORD-2026-00008` → KPI 96 500,00 $ / 100 % / 0 %,
   "Создать счёт-фактуру" düğmesi görünür, mal kabul şeridi MAT-PRE-2026-00003/00004; `PUR-ORD-2026-00009` →
   214 800 000,00 сўм / 100 % / 100 %, bağlı fatura şeridi; iki kapı da doğru şekilde kapalı.
   **3b kaynağı okundu:** `SalesOrderFormClassic.vue:156-197 fromDetail` de `net_total`/`grand_total`/
   `per_delivered`/`per_billed` döndürmez; şablon `:1068-1084`, `:1230-1252` ve `:832` bunları okur → aynı sınıf,
   düzeltilmedi (oradaki kapılar motorun `docstatus.value`'sunu okuduğu için yalnız KPI'lar boş kalır).
   **3b düzeltildi 2026-09-05** (dallar `fix/so-classic-server-facts`, `fix/so-modern-server-facts`): iki SO
   formunun `fromDetail`'i de artık `status`, `net_total`, `grand_total`, `advance_paid`, `per_delivered`,
   `per_billed`, `billing_status`, `has_reservations`, `sales_invoices` ve satırlarda `name`, `billed_amt`
   taşır; Modern form aynı sınıftı, yürüyüşte açılmamıştı. Spec'ler `salesOrderClassicServerFacts.spec.js` ve
   `salesOrderModernServerFacts.spec.js` eski kodda `undefined` ile düşer, yenide geçer. Canlı doğrulama (yerel
   site, bundle `7XN3WRNQ`): `SAL-ORD-2026-05895` detayında teslim/faturalama yüzdeleri 100 %, toplam
   222 000 000,00 сўм, bağlı fatura şeridinde `ACC-SINV-2026-07435`.
4. **P1 — Sourcing başlığı "Добавить предложение" MouseEvent'i RFQ sanır.** `SourcingWorkspace.vue:455`
   `@click="openAddQuotation"` → `:257 openAddQuotation(rfq = "")` → `get_rfq` 404 "RFQ not found: {isTrusted…}"
   (`sourcing.py:346/607`). Geçici çözüm B4'te.
   **Düzeltildi 2026-09-05** (dal `fix/sourcing-add-quotation-event`): `openAddQuotation` artık yalnız string bir
   RFQ adını ön seçim sayar (`typeof rfq === "string" ? rfq : ""`); başlık düğmesinin çıplak `@click`'iyle gelen
   MouseEvent boş giriş açar, `?rfq=` derin bağlantısı (`:405`) adı geçirmeye devam eder. Yeni spec
   `sourcingAddQuotationEvent.spec.js` işlevi kaynaktan çıkarıp çalıştırır; MouseEvent iddiası eski kodda düşer
   (`entryRfq` nesne oluyordu), derin bağlantı iddiası düzeltmenin fazla ileri gitmediğini korur. Canlı doğrulama
   (yerel site, yeni bundle, CRM-DEAL-2026-00015): "Добавить предложение" → çekmece "Новое предложение
   поставщика" açıldı, `get_quotation_defaults` gövdesi `deal` + `company` (rfq yok) ile 200, kalem ön dolu, hata
   ve toast yok. Çekmece "Закрыть" ile kapatıldı, kayıt yazılmadı.
5. **P2 — `?rfq=` aynı rotada çekmeceyi açmaz.** `SourcingWorkspace.vue:401-407` yalnız `onMounted`'ta okur;
   hash değişimi bileşeni yeniden kurmaz. RFQ detayından gelince çalışır (rota değişir).
   **Düzeltildi 2026-09-05** (dal `fix/sourcing-rfq-query-kicker-toast`): `onMounted` okuması yerine
   `watch(() => route.query?.rfq, …, { immediate: true })` — aynı rotada hash değişince de çekmeceyi açar ve
   `router.replace` ile `rfq`'yu adresten siler (`deal` kalır). Spec `sourcingRfqQueryWatch.spec.js`. Canlı
   doğrulama (yerel site): sayfa içinden `/tender/sourcing?deal=CRM-DEAL-2026-00015&rfq=PUR-RFQ-2026-00001`
   → çekmece 0,6 s'de açık, adres `#/tender/sourcing?deal=CRM-DEAL-2026-00015`. Yalnız `?rfq=` (deal'siz)
   çekmeceyi açmaz — çekmece `entryOpen && deal` ister; RFQ detayındaki düğme iki parametreyi de gönderir.
6. **P2 — Fişten fatura sonrası liste taslağı açmaz.** `PurchaseReceipts.vue:220`
   `router.push({ path: "/purchasing/invoices", query: { open: res.name } })`; `PurchaseInvoices.vue:26-28` yalnız
   `from_date/to_date/tender_only` okur (`18c`).
   **Düzeltildi 2026-09-05** (dal `fix/pi-form-defaults-and-receipt-flow`): fişten fatura oluşturulunca
   `PurchaseReceipts.vue` liste + `?open=` yerine `purchaseInvoiceFormPath(name)` = `/purchasing/invoices/<ad>`
   ile doğrudan taslak forma gider. Spec `purchaseReceiptsCreateBillNav.spec.js`. Tarayıcıda yeniden
   üretilmedi (yeni fatura yazmak gerekir); spec kaynaktan çıkarılan işlevi çalıştırır.
7. **P2 — PO ihale seçicisi.** `PurchaseOrderForm.vue:54-61` etiket `d.organization || d.lead_name || d.name`
   (anlaşma adı yok, `active_tenders` yok); `crm.list_deals` `search_fields` organization/email/lead_name — anlaşma
   adıyla arama yok; `:89-92, :329` `?deal=` ön-doldurma çalışmadı (ölçüldü). Aynı kurumun 5 kartı ayırt edilemez.
   **Kısmen düzeltildi 2026-09-05** (dal `fix/po-deal-picker`): etiket `dealOptionLabel(d)` =
   `<kurum|lead> · <anlaşma adı>` (liste ve kilitli alan tek kural); `list_active_tenders`
   (`tender_dimension.py`) `name`/`organization`/`lead_name` üzerinden `or_filters` ile anlaşma adıyla da arar;
   `?deal=` ön-doldurması `tenderOn` geç gelse de bir kez uygulanır (`createFormReady` kapısı: izleyici
   `blankForm()`'dan önce yazamaz). Spec `purchaseOrderTenderDeal.spec.js`, test
   `stabler/tests/test_tender_dimension.py`. Canlı doğrulama (yerel site):
   `/purchasing/orders/new?deal=CRM-DEAL-2026-00015` → seçici doldu ama **ham id gösterdi**: `loadDealLabel`
   `crm.get_deal`'i `company` göndermeden çağırır, sunucu "Требуется компания." fırlatır, `catch` id'ye düşer
   (`PurchaseOrderForm.vue:90`; aynı hata `Expenses.vue:562`). Ayrıca `searchDeals` hâlâ `crm.list_deals`'i
   `active_tenders: 1` olmadan çağırır, yani ad araması bu ekrana ulaşmaz (inceleme bulgusu A). İkisi takip
   dallarında (`fix/review-followups-2026-09-05`, `fix/deal-label-company-arg`); birleşince bu not güncellenir.
   **Tamamlandı 2026-09-06** (`fix/deal-label-company-arg` → main `cf450b6`; `fix/review-followups-2026-09-05` →
   main `ac81631`): `loadDealLabel` iki formda da `company: activeCompany.value` gönderir (spec
   `dealLabelCompanyArg.spec.js`; stub sunucu kapısını taklit eder, eski kodda dört iddia "Received:
   CRM-DEAL-2026-00015" ile düşer). `searchDeals` `active_tenders: 1` ister — id araması bu seçiciye ulaşır ve
   seçici PI/gider seçicileriyle aynı kurala bağlanır: `is_active_tender` kaybedilmiş ihaleyi ve bütün gönderilmiş
   SO'ları Closed/Cancelled olan kazanılmış ihaleyi sunmaz. Yerel veride 00015'in tek SO'su Closed, bu yüzden
   seçici artık yalnız GENEL GİDER'i listeler (`list_deals(active_tenders=1)` → total 1). Aynı bileşen örneğinde
   ikinci bir `?deal=` bağlantısı için `route.query.deal` izleyicisi mandalı yeniden açar. Canlı doğrulama (yerel
   site, bundle `ET37PR7B`): `/purchasing/orders/new?deal=CRM-DEAL-2026-00015` seçicisi "O'zbekiston temir
   yo'llari AJ [DEMO] · CRM-DEAL-2026-00015" gösterir. Karar gerekir: ön dolumla açılan formdan çıkışta
   "kaydedilmemiş değişiklik" uyarısı çıkar; bitmiş ihaleye `?deal=` ile gelinebilir ama seçici onu sunmaz.
8. **P2 — Belge sayısı üç ekranda üç değer.** Belge merkezi 7 gereksinim (`custom_tender_intake.documents`);
   PO kontrol Обзор "Документы 0/5"; PO kontrol "Документы" sekmesi "Пока нет требований" (`04e`). Kaynak
   alanlar farklı (Tender Master ↔ lot intake); hangisi doğru — karar gerekir.
9. **P2 — Boş kontrol listesi %100.** `stabler/api/_tender_documents.py:182`
   `readiness_pct = … if required > 0 else 100`.
10. **P2 — Dokunulmamış yeni fatura "kaydedilmemiş değişiklik" uyarısı verir.** `PurchaseInvoiceForm.vue:423`
    GENEL GİDER varsayılanı forma yazılır → dirty (`18b`). Uyarı metni de İngilizce.
    **Düzeltildi 2026-09-05** (dallar `fix/pi-form-defaults-and-receipt-flow`, `fix/dirty-guard-create-baseline`):
    (a) `PurchaseInvoiceForm.vue` `applyCreateDefaults()` GENEL GİDER varsayılanını yazdıktan sonra, başka şey
    değişmediyse `reset(form)` ile temiz taban alır (`useDocumentForm` artık `reset`'i dışa verir). (b) Kök
    neden daha genişti: `useDirtyGuard.js:19` tabanı `""` ile başlatıyordu, her yeni form ilk karede kirliydi —
    artık `JSON.stringify(model)`. Spec'ler `purchaseInvoiceFormCreateDefaults.spec.js`,
    `useDirtyGuardBaseline.spec.js`. Canlı doğrulama (yerel site, bundle `7XN3WRNQ`): dokunulmamış yeni PO ve
    yeni PI sayfalarından çıkışta modal yok.
11. **P2 — K/Z defter tablosu.** (a) Belge tarafı gelir 198 214 285,71 = 222 000 000 / 1,12, fatura vergisiz
    (`tender_gl.py:145 tender_gl_pnl` reconciliation; sabit KDV varsayımı — kod okunmadı). (b) `by_voucher.count`
    GL satırı sayar ("Счёт продажи 2"), sütun başlığı "КОЛИЧЕСТВО" belge adedi gibi okunur.
12. **P2 — Otomatik Tender Master boş.** `_apply_tender_parent_link` `TND-2026-00002`'yi başlık = alıcı adı,
    tarihler null, toplam 0 ile açtı; PO kontrol "Детали тендера" bu boş kaydı okur.
13. **P2 — RFQ "gönderildi" rozeti.** `mark_rfq_sent` Communication yazar (`sourcing.py:958`), detay rozeti
    "Черновик" kalır (`06d`, `06e`).
    **Düzeltildi 2026-09-05** (dal `fix/rfq-sent-badge`): `get_rfq` gönderilmiş Communication sayısını ve son
    gönderimi döndürür (`_rfq_sent_summary`: `reference_doctype/name`, `sent_or_received = Sent`);
    `RfqDetail.vue` taslak + `sent_count > 0` ise "Sent" rozeti ve `sent_on` tarihini basar, gönderim sonrası
    `load()` ile yeniler. Test `stabler/tests/test_sourcing_api.py`, spec `rfqSentBadge.spec.js`. Canlı
    doğrulama (yerel site): `PUR-RFQ-2026-00001` → `sent_count 1`, detay rozeti "Отправлен". Liste rozeti ve
    `STATUS_MAP` girişi takip dalında (inceleme bulguları C, D).
    **Tamamlandı 2026-09-06** (`fix/review-followups-2026-09-05` → main `ac81631`): rozet
    `composables/rfqStatus.js`'e taşındı, sınıfını `STATUS_MAP["Request for Quotation"].Sent` üzerinden
    `getStatusBadgeClass` verir (sabit `text-green` kalktı); `list_rfqs`/`list_all_rfqs` satırlara toplu
    `_rfq_sent_counts` ile `sent_count` yazar, `RfqList.vue` aynı rozeti basar. Testler `test_sourcing_api.py`
    (eski kodda `KeyError: 'sent_count'`, `_rfq_sent_counts` yok), spec `rfqSentBadge.spec.js` gerçek
    `getStatusBadgeClass` ile. Canlı doğrulama (yerel site, bundle `V4VWOKYM`, Mikas): liste satırı
    `PUR-RFQ-2026-00001 … Отправлен [badge bg-green-lt]`, detay rozeti aynı sınıfla. Bench kanıtı: `make
    test-bench` main `ac81631` üzerinde (başında ve sonunda aynı sha) 79 modül, çıkış 0, FAIL/ERROR yok —
    D, F ve G böylece bench'te de ölçüldü.
14. **P2 — Kanban kazanım sonrası türetimi** (E.8'e bağlı): PO/fiş/fatura varken kart "Закупки"de (`12a`).
15. **P2 — Mikas'ta SO'ya giden buton yok.** `prepare_so_from_deal` çağrısı yalnız `crm/Deals.vue:537`;
    ihale kanbanı çekmecesinde "Sözleşme oluştur" yok; `enable_crm 0` olan Mikas rotayı elle yazmak zorunda.
16. **P2 — Sözleşme panosu (`/tender/board`) yeni SO'yu göstermez.** `SAL-ORD-2026-05895` Closed/100/100, pano
    "Closed 0" (`13d`). Kaynağı okunmadı.
17. **P2 — "СВЯЗАННЫЕ ДОКУМЕНТЫ —"** PR çekmecesi (PO bağlı), PI detayı (PR+PO bağlı), SI detayı (SO bağlı) —
    hepsinde boş (`16d`, `18f`, `21b`).
    **Düzeltildi 2026-09-05** (dal `fix/linked-docs-and-tender-stamp`): `get_linked_documents` yalnız belgeye
    bağlanan aşağı akışı biliyordu; `_add_upstream_item_links` satır bağlarını (`PR.items.purchase_order`,
    `PI.items.purchase_order/purchase_receipt`, `SI.items.sales_order`) okuma izniyle ekler. Test
    `stabler/tests/test_related_documents_upstream_links.py`. Canlı doğrulama (yerel site):
    `ACC-SINV-2026-07435` → "Sales Orders · SAL-ORD-2026-05895"; `ACC-PINV-2026-00883` → PO
    `PUR-ORD-2026-00009` + PR `MAT-PRE-2026-00005`. Grup başlıkları ("Sales Orders", "Purchase Orders")
    `RelatedDocuments.vue:28` `t()`'siz — Rusça ekranda İngilizce kalır (§H.2 sınıfı, düzeltilmedi). PR
    çekmecesine tarayıcıda yeniden bakılmadı.
18. **P2 — İhale damgası görünmez.** Gider detayı (`19d`) ve satış faturası formu (`SalesInvoiceForm.vue`
    "tender" içermez) hangi ihaleye yazıldığını göstermez; satın alma faturası gösterir ama kurum adıyla.
    **Düzeltildi 2026-09-05** (dal `fix/linked-docs-and-tender-stamp`): `sales_invoice_detail` ve
    `journal_entry_detail` `tender` + `tender_label` döndürür (`_deal_display_label`; JE'de `custom_crm_deal`
    sütunu `has_column` korumalı); `SalesInvoiceForm.vue` ve `Expenses.vue` detayı salt-okunur "Tender" satırı
    gösterir (`v-if` — damgasız belgede satır yok). Test `stabler/tests/test_expense_tender_stamp.py`, spec
    `tenderStampReadOnly.spec.js`. Canlı doğrulama (yerel site): SI `ACC-SINV-2026-07435` "Тендер ·
    O'zbekiston temir yo'llari AJ [DEMO] · CRM-DEAL-2026-00015"; `journal_entry_detail("ACC-JV-2026-07011")`
    aynı etiketle döner. Etiket kuralı §H.1 kararına bağlı.
    **Ek 2026-09-06** (`fix/review-followups-2026-09-05`): `_deal_display_label` kurum ve lead yoksa id'yi iki kez
    yazmaz (`sales.py`, `money.py`; testler `test_related_documents_upstream_links.py`,
    `test_expense_tender_stamp.py`); `get_linked_documents`, `sales_invoice_detail` ve `journal_entry_detail`
    bağlama satırları kaynak düzeyinde testlendi (inceleme bulgusu E).
19. **P2 — Teslimat sekmesi irsaliyesiz teslimi saymaz.** `update_stock=1` fatura stoku düşürdü, sekme
    "ДОСТАВКА Нет связанных документов" (`16e`).
20. **P2 — Direktör paneli ↔ genel bakış kazanılan sayısı.** 2 / %66,7 ↔ 3 / %75 aynı anda (`25b`, `01b`).
    Kaynağı okunmadı (pencere ya da Tender Master filtresi olabilir — doğrulanmadı).
21. **P2 — Toast tekrarı.** "Перемещено в Выиграно" ×2 (C1); daha önce ×3 İngilizce toast (C4/C5).
    **Düzeltildi 2026-09-05** (dal `fix/sourcing-rfq-query-kicker-toast`): `TenderCrm.vue` `onDrop` kart başına
    `movingCards` kilidi tutar — aynı kart için ikinci `drop` olayı iyimser güncellemeye ve toast'a ulaşmaz;
    kilit `finally`'de kalkar. Spec `tenderCrmMoveToast.spec.js`. Tarayıcıda sürükle-bırakla yeniden
    üretilmedi. C4/C5'teki üçlü İngilizce toast ayrı kaynak; bakılmadı.
22. **P1 — PI detayı: aynı `fromDetail` sınıfı, "Make payment" ve iade düğmeleri hiç görünmez.**
    `PurchaseInvoiceForm.vue:209-274 fromDetail` `docstatus` ve `status` döndürmez; `:672-679 canPay`
    (`form.value.docstatus === 1 && PAYABLE_STATUSES.has(form.value.status)`) ve `:697-703 canReturn` bunları
    okur. Canlı ölçüm 2026-09-05: gönderilmiş, "Не оплачено" `ACC-PINV-2026-00883` detayında yalnız "Назад" ve
    "Отмена"; ödeme bu ekrandan kaydedilemez. PO düzeltmesi (§G.3) yapılırken bulundu; aynı iki satırlık
    düzeltme sınıfı, düzeltilmedi.
    **Düzeltildi 2026-09-05** (dal `fix/pi-form-server-facts`): `fromDetail` artık `docstatus`, `status`, `name` ve
    `modified`'ı modele taşır. Kapılar ilk ikisini okur; `PaymentModal` (`invoice-name`, `modified`), iade gönderimi
    (`purchase_invoice: form.value.name`) ve yazdır bağlantısı `name`'i okur — dördü de düşüyordu, yani düğme
    görünse bile ödeme boş bir ada yazılacaktı. Yeni spec `purchaseInvoiceFormServerFacts.spec.js` `fromDetail`'i
    gerçek `grossRate` ile çalıştırır; üç iddiası da eski kodda düşer, yenide geçer. Canlı doğrulama (yerel site,
    yeni bundle): `ACC-PINV-2026-00883` detayında "Make payment" ve "Issue debit note" göründü; düğme modalı
    "Выплатить поставщику · ACC-PINV-2026-00883", tedarikçi ve ödenmemiş 214 800 000,00 сўм ile açtı (ödeme
    gönderilmedi, Отмена ile kapatıldı); yazdır bağlantısı `#/purchasing/invoices/ACC-PINV-2026-00883/print`.
    İki etiketin ru/uz/uzc/tr çevirileri kataloglarda anahtar olarak vardı ama boştu — düğmeler hiç görünmediği
    için fark edilmemişti; dolduruldu (ru: Оплатить / Выпустить дебет-ноту, mevcut "Issue credit note"
    kalıbıyla).

## H. Bulgular — arayüz metni ve katalog

1. **Etiket = kurum adı.** Kanban kartı, PO/PI/gider/SO ihale seçicileri ve kilitli alanlar anlaşmayı
   `organization` ile gösterir; ihale adı ve UZEX numarası hiçbir yerde. Bu, §G.7'nin kullanıcı yüzü.
2. **Rusça arayüzde İngilizce (katalogda yok ya da çevrilmemiş):** "New Purchase Invoice", "New Sales Order",
   "New purchase invoice" (liste butonu), "Bill No.", "Bill Date", "Update stock",
   "Commercial Invoice (Import Attribution)", "TAX AMOUNT", "Add Row", "Add Item", "New Item", "Search…",
   "Submit document? Are you sure you want to submit this document? This will finalize transactions.",
   "You have unsaved changes. Leaving this page will discard them.", "Partially billed — 0% invoiced.",
   "Fulfilment & Billing", "LINE DETAILS", "ORDERED", "BILLED AMT", "KIND", "Send to Didox", "PO Created" (sütun),
   "No expenses in this range", "Record an outgoing payment to start tracking spend.",
   "No landed-cost lines have been found.", "Exchange rate preview", "Spread the charges over", "By line value",
   "The voucher is created as a draft. Review it under Existing vouchers…", "ESTIMATED TOTAL", "PRICE",
   "LOT / DEAL", "PARENT TENDER", "SCOPE", "EVIDENCE", "TOTAL DELIVERED COST", "CHARGE TYPE",
   "Document saved successfully.", "Purchase Receipt submitted.", "Submitted"/"Draft" durum rozetleri,
   RFQ yazdırma cümlesi "We kindly ask you to quote your prices and delivery terms for the following items."
   (`RfqPrint.vue:86`), `create_purchase_receipt_from_po` ham `frappe.throw` metinleri (`purchasing.py:2476`).
   Ayrıca "Поражений" (hal eki; "Проиграно" beklenir). "Юк хати" (`Yuk xati`) Özbekçe belge adı — bilinçli
   anahtar, Rusça ekranda yabancı duruyor.
   **Kısmen düzeltildi 2026-09-05** (dal `fix/i18n-ru-walk`): ele alınan anahtarlar beş katalogda
   eklendi/dolduruldu (satır silinmedi; kapsam `i18nRuWalk.spec.js`'te sayılır); `purchasing.py:2491-2507` ham
   `frappe.throw` metinleri `_()`'ya alındı; `LineItemsEditor.vue` "Search…" `t()`'ye; landed cost incelemesinde
   dağıtım etiketi `landedCostLabels.js`'ten. Canlı doğrulama (yerel site, önbellek temizlendi): yeni satın alma
   faturasında "Номер счета", "Дата выставления счета", "Обновить запасы". Doğrulanmayanlar: modal ve toast
   metinleri; "Поражений" stabler'ın CSV'siyle düzelmez — kaynak crm/erpnext'in `_()` kataloğu, uygulama yükleme
   sırası `frappe, stabler, crm, hrms, erpnext` ve sonraki uygulama anahtarı ezer; RelatedDocuments grup
   başlıkları (§G.17).
   **Ek 2026-09-06** (`fix/review-followups-2026-09-05`): `Typeahead.vue` varsayılan yer tutucusu `t("Search…")`
   oldu (spec `typeaheadPlaceholder.spec.js`); yeni PO'da üç seçici de "Поиск…" ailesinde okunur. Aynı bileşende
   `noResultsText` varsayılanı hâlâ İngilizce (ajanın bulgusu, ayrı görev). Sekme başlığı "New Purchase Order ·
   Stabler" RU ekranda İngilizce (yeni gözlem, aynı sınıf). purchasing.py'deki kalan ham `frappe.throw` metinlerini
   başka bir oturum `_()`'ya aldı (`fix/i18n-purchasing-receipt-throws`, main `da73ae8`).
3. **Sabit birim:** landed cost incelemesi "Принято (кг)" — kalem birimi ne olsa "kg".
   **Düzeltildi 2026-09-05** (dal `fix/i18n-ru-walk`): `LandedCostReview.vue` başlığı `receivedLabel(uom)` =
   `t("Received ({0})", [uom])` ile fişin gerçek birimini yazar; `api/imports.py` ve `api/lcv.py` satırlara
   `received_uom` ekler (lcv: ilk kalemin birimi). Boş/karışık birim dalları takip dalında (inceleme bulgusu G).
   **Tamamlandı 2026-09-06** (`fix/review-followups-2026-09-05` → main `ac81631`): boş birim "Received", "kg"
   (büyük/küçük harf fark etmez) çevrili "Received (kg)" anahtarı, diğerleri `Received ({0})`; `lcv.py` bütün
   satırlar aynı birimdeyse onu, değilse boş döndürür. Spec `i18nRuWalk.spec.js`, test `test_lcv_math.py`
   (kaynak düzeyi). Tarayıcıda yeniden bakılmadı.
4. Toast tekrarı (§G.21).
5. Katalog: `tr.csv` "Issues" → "Sorunlar" (§E.4).

## I. Yerel site veri artıkları (kod hatası değil; prod'u etkilemez)

1. **SO adı yeniden kullanıldı.** `SAL-ORD-2026-05895` için `tabDeleted Document`'ta 2 satır (2026-09-04 12:49 ve
   16:35 — dünkü prob temizliği); silinen SO'ların rezerv kayıtları (`MAT-SRE-2026-03621` Cancelled,
   `MAT-SRE-2026-03622` Delivered, kalem UAT-IMP-BEEF-TRIM-01) silinmedi ve şimdi bugünkü SO'nun adına
   bağlı görünüyor. Prob temizliği SO'yu sildi, Stock Reservation Entry'yi bırakmış; Frappe adı yeniden verdi.
2. **COGS 891 010 000.** `Rels birikmasi [DEMO]` için 2026-08-03 tarihli `MAT-PRE-2026-00002` (UralVagonSnab,
   1 × 590 000 000, stok değeri 678 000 000) stokta duruyordu. Değerleme FIFO (`Stock Settings.valuation_method`
   = FIFO, kalemde boş): 120 adet çıkış = 1 × 678 000 000 + 119 × 1 790 000 = 891 010 000. Bu yüzden yerel K/Z
   −670 510 000 gösterir. Bu kalemin prod'da olup olmadığı ölçülmedi.
3. **Fiyat listesi:** aynı demo kalemin "Price (UZS)" satırı 2 270 000 000,00 — SO'da elle düzeltildi.
4. Bin'de 1 adet artık (121 − 120).
