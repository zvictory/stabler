# PI Group Container Status raporu — spec denetimi ve parite planı

**Kaynak spec:** msaerp (Django) `pi_group_container_status_report_spec.md` —
`/reports/pi-group-container-status/` operasyon panosu: PI Group bazında
konteyner yaşam döngüsü (adet) + finans ($) rollup'ı.

**Stabler'daki durum:** Rapor **portlanmış** (`pages/reports/PiGroupContainerStatus.vue`,
route `/reports/pi-group-container-status`, uç `api/reports.py::get_pi_group_container_status_report`)
— ama hiç gerçek şemaya karşı çalıştırılmamış ve spec'ten sapıyor. Aşağıdaki
denetim satır satır koda karşı yapıldı.

---

## Denetim: var / bozuk / eksik

### ✅ Var ve spec'e uygun

| Spec öğesi | Durum |
|---|---|
| Route + sayfa + modül kapısı (`module: imports`) | ✓ |
| Filtre çubuğu UI'ı (grup / vendor / tarih / PI status) | ✓ (ama bkz. B4) |
| KPI şeridi | ✓ (büyük ölçüde) |
| Kova kolonlu tablo + genel toplam satırı | ✓ (tek satırlı — bkz. E1) |
| CSV export (istemci tarafı) | ✓ |
| Pending formülleri (grup düzeyi) | ✓ — `planned − toplam` ve `PI agreed − Σ CI agreed`, `cro_count=0` spec'le aynı |

### 🔴 Bozuk (hata — özellik değil)

**B1 · FATAL: SQL var olmayan kolonları seçiyor.** Uç `pg.group_title` ve
`pg.vendor` okuyor; `Import PI Group` doctype'ının gerçek alanları **`title`**
ve **`pi_vendor`**. Canlıda ilk çağrıda `Unknown column` → rapor 500 atar.
(`imports_flow`'da yaşadığımız sınıfın aynısı: kaynak denetimlerinden geçer,
prod'da ölür. Hiç gerçek veriyle koşulmadığının kanıtı.)

**B2 · Kova haritası spec'ten sapmış ve hatta imkânsız.** Spec:

| Kova | Spec statüleri | Koddaki hali |
|---|---|---|
| ORIGIN | BOOKED, STUFFED, GATE_IN | + **ON_BOARD** (yanlış: spec'te TRANSIT) + hayalet `DRAFT` |
| TRANSIT | ON_BOARD, IN_TRANSIT, DISCHARGED | **AVAILABLE, ARRIVED_AT_IRAN** buraya konmuş (spec: DESTINATION) |
| DESTINATION | AVAILABLE, ARRIVED_AT_IRAN | `CUSTOMS_CLEARANCE`, `RELEASED` — **Stabler hattında böyle statü yok → kova hep 0** |
| DELIVERED | DELIVERED_TO_UZBEKISTAN | + hayalet `DELIVERED`, `CLOSED` |

Sonuç: her şey ORIGIN/TRANSIT'e yığılır, DESTINATION daima 0 — pano yanlış
hikâye anlatır.

**B3 · Planned FCL veriden değil, tahminden.** Kod `boxes/1400 (boxes>500 ise,
değilse 1.0)` sezgiseliyle FCL uyduruyor ve grup boşsa `len(member_pis)` ile
**veri fabrikasyonu** yapıyor. Oysa `Proforma Invoice Item.fcl` alanı **var** —
spec de "PI satırlarındaki planned FCL toplamı" diyor. Ayrıca PI başına ayrı
item sorgusu (N+1).

**B4 · Tarih ve PI-status filtreleri ölü.** İmzada `date_from/date_to/status`
var, Vue gönderiyor — backend'de **hiçbir koşulda kullanılmıyor**. Filtre
çubuğu yalan söylüyor.

### 🟡 Eksik (spec'te var, portta yok)

**E1 · Çift satırlı ızgara — finans alt satırı.** Spec'in ayırt edici özelliği:
her grup için 2. satır (`bg-slate-50/60`) aynı kolonlarda **$ tutarları**
gösterir — kova başına CI agreed toplamları + pending amount. Portta yalnız
grup düzeyi tek "Agreed Amount" kolonu var; kova başına tutar **hesaplanmıyor
ve gösterilmiyor**.

**E2 · KPI şeridi spec'in 6'lısına hizalanmalı:** Groups · Planned FCL ·
Origin · In Transit · At Destination · Delivered (Destination KPI'ı B2 yüzünden
şu an hep 0 zaten).

---

## Plan (fazlı — her faz kendi başına deploy edilebilir)

### Faz 1 · Raporu çalışır yap (dakikalar)
- B1: `pg.group_title→pg.title`, `pg.vendor→pg.pi_vendor` (SELECT + vendor
  filtresi + supplier JOIN).
- msa konsolunda gerçek veriyle bir çağrı: satır sayısı + kova toplamı =
  konteyner sayısı sağlaması.

### Faz 2 · Doğruluk paritesi (~yarım gün)
- B2: kova haritasını spec'e sabitle. Harita **saf modüle** taşınır
  (`api/_pi_group_report.py`, frappe-siz) — testler 9 statülük hattın tamamını
  tarar: her statü tam bir kovada, bilinmeyen statü sessizce düşmez (görünür
  sayılır — `imports_flow`'daki "unknown gizlenmez" ilkesi).
- B3: `planned_fcl = Σ PI Item.fcl` (tek gruplu sorgu, N+1 yok). Sezgisel ve
  `len(member_pis)` fabrikasyonu silinir — veri yoksa 0 dürüsttür.
- B4: tarih (`pi_date BETWEEN`) ve PI-status filtreleri member_pis sorgusuna
  bağlanır; boş grup davranışı korunur.

### Faz 3 · Spec'in çift satırı (~yarım gün)
- Kova başına tutar: CI `agreed_total`'ları aynı kova haritasıyla topla
  (`amounts: {ORIGIN, TRANSIT, DESTINATION, DELIVERED}` + pending) — sayım ve
  tutar **aynı geçişte**, ayrışamazlar.
- Vue: grup başına ikinci satır (soluk zemin, `formatMoney`), KPI şeridi 6'lı,
  CSV'ye tutar satırı dahil.
- i18n: yeni başlıklar 5 dile.

### Faz 4 · Guard testleri + deploy (~çeyrek gün)
`test_pi_group_report_source.py`:
- **SQL kolonları doctype'a karşı** doğrulanır (`pg.<kolon>` regex'i ↔
  `import_pi_group.json` alan listesi) — B1 sınıfı bir daha yeşil geçemez.
- Kova haritası tam-kapsama testi (saf).
- **Ölü filtre guard'ı:** imzadaki her filtre parametresi sorgu koşullarında
  geçmek zorunda.
- Deep-link/i18n/read-only standart guard'ları.
Deploy: kod-only (şema yok, migrate yok) → msa konsol sağlaması → tarayıcıda
filtrelerin gerçekten daralttığının kontrolü.

**Toplam kestirim: ~1 gün.** Sıra önerisi: Faz 1 hemen (rapor şu an ölü),
2–4 tek pakette.

---

*Denetim: 2026-07-28 · spec: antigravity brain 7c00f3d9 · kod referansları:
`api/reports.py:2051-2191`, `pages/reports/PiGroupContainerStatus.vue`,
`doctype/import_pi_group/import_pi_group.json`.*
