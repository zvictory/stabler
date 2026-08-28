# Manufacturing — İş Emirleri yeniden tasarımı: bugünkü durum

**Tarih:** 2026-08-28 · **Ölçen:** Claude, Zafar'ın talebiyle
**Kaynak paket:** `Manufacturing interface and work orders.zip` (2026-08-24), Zafar'ın
Downloads klasöründe. **Bu depoda kopyası yok.**

Bu doküman bir karar değil, bir **envanter**. Yazılma sebebi: paketin repoda hiçbir
plan dokümanı yoktu, dolayısıyla "ne yapıldı" sorusu her seferinde arşivi açmayı
gerektiriyordu. Buradaki her satır 27–28 Ağustos'ta ya kodda ya prod'da ölçüldü.

---

## Beş yön, bugünkü hâli

| Yön | Durum | Kanıt |
|---|---|---|
| **1a** Yoğun vardiya defteri | KISMEN | `WorkOrders.vue:361` — tek filtre: durum. Tarih / hat / operatör filtresi yok, yoğunlaştırma uygulanmadı. |
| **1b** Kanban panosu | YOK | `pages/manufacturing/` altında kanban dosyası yok. |
| **1c** Hat × zaman planlama | KISMEN | Backend canlı: `hooks.py:429` → `manufacturing.create_material_request_for_tomorrow_wo`; anjan'da **488 malzeme talebi** üretmiş. **Planlama ekranı yok.** |
| **1d** Tam sayfa sipariş detayı | KISMEN | `WorkOrderDetail.vue` var (`4bc87d6`). Soyağacı tek blok: `:462-484` parti no + tüketilen malzeme listesi — **ağaç görünümü yok**. `suggest_wo_batch` bu sayfada değil, yalnız kioskta (`ManufacturingOperatorBoard.vue:644`). |
| **1e** Operatör kiosk 2.0 | VAR | `ManufacturingOperatorBoard.vue` (1 652 satır), numpad `292574a`. |
| — **Operasyon kartları** | **ÖLÜ** | Ölçümle iptal, aşağıya bakınız. |

## Operasyon kartları neden ölü

Bariz tasarım, detay sayfasında ERPNext rota operasyonu başına bir kart göstermekti.
İş emri koşturan tek kiracıda ölçüldü (anjan): **0 Work Order Operation, 0 BOM
Operation, 0 Workstation, 0 Job Card.** Operasyon kartları sistemdeki *her* siparişte
boş ızgara olurdu.

Bunun yerine kartlar, bu atölyenin gerçekten sahip olduğu ayrıştırmayı gösteriyor:
iki farklı iş yapan iki kişi (döküm ve paketleme), BOM rolle bölünmüş, rol başına bir
sapma kovası. Gerekçe kodda da duruyor: `composables/workOrderStages.js:1-12`.

## Prod ölçümleri (anjan, salt-okunur, 27–28.08)

| Ölçüm | Değer | Ne söylüyor |
|---|---|---|
| Manufacture girişi | 3 725 | üretim kaydediliyor |
| …`process_loss_qty > 0` | **0** | fire hiç kaydedilmiyor |
| Downtime Entry | **0** | duruş hiç kaydedilmiyor |
| Workstation / WO Op / BOM Op / Job Card | **0 / 0 / 0 / 0** | rota katmanı hiç kullanılmıyor |
| Gönderilmiş iş emri | 3 787 | |
| …`operator` atanmış | 13 | |
| …`packaging_operator` atanmış | **0** | rol ataması pratikte kullanılmıyor |
| Girişleri yapan ilk iki hesap | 3 688 / 3 725 | iş, operatör ekranından değil **Desk'ten yönetici eliyle** giriliyor |

## Bu turda kapanan iş

- **Rol kapsamı.** `work_order_detail` bir operatöre yalnız kendi rolünün satırlarını
  veriyordu ama iki operatör adını da filtresiz gönderiyordu — diğer rol, "üzerinde iş
  olmayan bir aşamaya atanmış kişi" gibi, yani yanlış kurulmuş BOM şeklinde görünüyordu.
  `manufacturing.py` artık `items_scoped_to_role` yolluyor; `workOrderStages.js:48,63`
  bunu `itemsHidden`'a çeviriyor.
- **Kanıt:** `test_wo_role_scoping_integration` 43 test, `test_wo_operator_roles` 22
  test — bench'te, canlı DB ile, hepsi yeşil (28.08).
- **Malzeme hazırlığı float düzeltmesi:** `composables/materialReadiness.js`, epsilon +
  `settle()`.

## Engel — ve bu bir kod engeli değil

Ekranların hepsi çalışıyor; kullanan yok. 3 725 üretim girişinin 3 688'i iki yönetici
hesabından, fire ve duruş sıfır, paketleme operatörü hiç atanmamış.

**Karar gereken:** operatörler kiosk'a alınacak mı, yoksa yöneticinin Desk akışı kabul
edilip o mu iyileştirilecek? Fire/duruş kataloğu, 1b kanban ve 1c planlama ekranı — üçü
de bu cevaptan sonra anlam kazanıyor. Cevap "yönetici" ise 1b ve 1c yazılmamalı.

Bu soru, `operator-dashboard` paketinin sorusuyla (bkz.
`2026-08-28-operator-dashboard-durum.md`) **aynı sorudur** ve birlikte cevaplanmalıdır.
