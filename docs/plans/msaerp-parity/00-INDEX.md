# MSAERP → Stabler Özellik Parite Denetimi — İNDEKS

**Tarih:** 2026-07-10 · **Yöntem:** 4 paralel denetim ajanı, her ikisi kod tabanını da satır seviyesinde okudu (şablonlar, view'lar, modeller, doctype'lar, WP1-3 working tree). Tahmin yok — her madde dosya referanslı.

| Doküman | Kapsam |
|---|---|
| `01-master-data.md` | Dashboard, Vendor + Kategoriler, Products, Warehouses & Stock Transfer |
| `02-pi-ci.md` | PI (liste/form/gruplar/dual pricing/avanslar), CI (liste/form/giderler/BRV/VAT/7-gün kuralı) |
| `03-lojistik-grn-landed-cost.md` | Container, Truck + Truck Receipt, GRN, Landed Cost, ГТД + Vet + Freight |
| `04-satis-musteri-finans.md` | Customers (hiyerarşi), Sales (SO/SI/DN/iade/POS/import), Giderler/Banka/Fon, Raporlar, CoA |

---

## En Önemli Çapraz Bulgu: "MSAERP'de var" ≠ "MSAERP'de çalışıyor"

10 aylık MSAERP birikiminin envanteri iki kategoriye ayrıştı:

**Gerçekten canlı ve taşınacak değer:** PI/CI/Container operasyon ekranları ve dashboard'lar, dual pricing + avans akışı, БРВ gümrük hesabı, varyans motoru, FIFO satış/fatura akışı, Excel toplu satış/ödeme importu, müşteri merkezi.

**Modelde var ama üretimde ölü/kopuk (parite hedefi DEĞİL):** GRN→PR→LCV zinciri (PR hiç oluşmuyor, LCV hiç ateşlenmiyor), TruckReceipt QC şablonu (hiçbir URL render etmiyor — sıcaklık/mühür/foto hiç toplanmamış), vet-sertifika kapısı (gündelik buton bypass ediyor), SalesOrder/DeliveryNote/VendorBill detay/Banka mutabakat UI/Cash Management (erişilemez ya da hata veriyor), Freight Booking (UI'sız), lokal Batch-ATP (kendi "ERPNext system of record" kuralını ihlal ediyor).

**Sonuç:** Stabler'ın hedefi MSAERP'nin ekran kopyası değil — *çalışan* yüzeyin paritesi + tasarlanıp çalışmayan zincirin ilk kez gerçekten çalışan hali. WP1-3 tam bunu yaptı (PR-per-truck, gerçek LCV, zorunlu QC kapısı, tam clearance fee, VAT hariç).

## Durum Özeti (2026-07-10)

| Katman | Durum |
|---|---|
| Backend doctype + otomasyon (PI/CI/Container/Truck/GRN/LCV) | ✅ WP1-3 ile yazıldı (working tree'de, commit bekliyor) — MSAERP'nin kopuk zinciri düzeltilmiş halde |
| WP4 (ГТД, Import Expense, Freight Booking, БРВ hesaplayıcı) | 🔜 Sıradaki paket |
| SPA (18 sayfa: listeler, formlar, board'lar, tablet kabul) | ❌ 1 placeholder — Faz 2 (≈ Ağu ortası–Eyl ortası 2026) |
| api/imports.py + maske katmanı | ❌ Yok — Faz 2 |
| Müşteri hiyerarşi UI (QB modeli) + kredi limiti + parent toplu tahsilat | ❌ Yok — Faz 2 (temiz başlangıç: 4.149 SI'ın 0'ı hiyerarşi kullanmış) |
| ETL (masters, açık zincir, batch açılışı, dosyalar) | ❌ Yok — Faz 3 (≈ Eyl ortası–Eki başı) |
| Kurulum (msa.erpstable.com) | Runbook hazır, kurulum bekliyor (desk_gate kararı) |
| Cutover + hypercare | Faz 5 (≈ Eki sonu–Kas/Ara başı 2026) |

## Sahip Kararı Bekleyen Maddeler (dokümanlardan derlendi)

1. **Vendor Categories** (tedarikçiye özel ürün/koli şablonları, PO otomatik doldurma) — planda hiç yok; taşınacak mı? (01)
2. **Excel toplu satış/ödeme importu** — kalıcı özellik mi, yalnız ETL aracı mı? (04)
3. **Delivery Note/WMS** (imza/foto/batch picking) — stabler "SI=stok hareketi" modeli yeterli mi? (04)
4. **MSAERP-format banka ekstresi parser'ı** — planda var, önceliği belirlenmeli. (04)
5. **Kredi limiti düzenleme UI'ı** — MSAERP'de bile UI yok; K2 parent-modeliyle sıfırdan. (04)
6. **7-gün ödeme kuralı** — MSAERP'de 3 tutarsız implementasyon var; Stabler'da tek doğru tanım seçilmeli. (02)
7. **Fiscal Year bootstrap sahipliği** — geçmişte prod kazası yaşanmış; net kural gerek. (04)
8. **SPA kural ihlalleri temizliği** (mevcut stabler sayfalarında ListToolbar/SkeletonRows eksikleri) — ayrı bakım paketi. (01)

## Önerilen Sıra

1. WP1-3 commit + staging `bench migrate` + msa kurulumu (runbook)
2. WP4: ГТД + Import Expense + Freight Booking + БРВ
3. Faz 2 SPA: TruckReceiptForm (tablet) önce → ImportOrder/CI/Container listeleri → hiyerarşi modu Customer Center
4. Faz 3 ETL + taze dump doğrulaması
5. Karar listesi (yukarıdaki 8 madde) Faz 2 başlamadan kapatılmalı
