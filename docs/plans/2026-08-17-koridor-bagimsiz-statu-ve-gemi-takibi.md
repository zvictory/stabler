# Koridor-Bağımsız Statü Modeli ve Gemi Bazlı Takip — Tasarım Notu

**Tarih:** 2026-08-17
**Tetikleyici:** `ARRIVED_AT_IRAN` artık güncel bir statü değil. MSA malı Türkiye üzerinden de Özbekistan'a getiriyor.
**Durum:** Karar önerisi. **Hiçbir koda dokunulmadı.**
**Kanıt:** Bu notta geçen her `dosya:satır` referansı `apps/stabler` çalışma kopyasından okunarak doğrulandı.

---

## 0. Özet

Üç şey söylüyorum:

1. **Problem tek bir statü adı değil.** Coğrafya (İran) sistemin *statü makinesine çivilenmiş* durumda ve orada durmuyor: **bir para tetikleyicisi** (%70 avans Payment Entry), **bir fiziksel çıkış kapısı** (kamyon İran'dan çıkamaz), **13 landed-cost bileşeninin 5'i**, KPI kovaları ve 5 dilin çeviri katalogları buna bağlı. `ARRIVED_AT_IRAN` yazılmazsa **%70 avans ödeme belgesi hiç oluşmuyor** — sessizce.

2. **En derin kusur ise henüz konuşulmadı: kamyon boru hattı tek sınır varsayıyor.** `PENDING → DEPARTED_IRAN → AT_BORDER → CROSSED_BORDER → IN_TRANSIT → ARRIVED`. İran koridorunda 2 sınır vardı ve bu yaklaşık doğruydu. Orta Koridor'da (Türkiye → Gürcistan → Azerbaycan → Hazar feribotu → Kazakistan/Türkmenistan → Özbekistan) **4 sınır ve 1 deniz geçişi** var. Model bunları temsil edemez ve sınır-geçiş maliyet faturası (`CROSSED_BORDER` tetikleyicisi) **sadece bir kez** ateşlenir.

3. **Gemi bazlı takipte tamamen haklısın ve model bunu neredeyse hazır bekliyor.** CI zaten voyage'ın sahibi (`sea_lifecycle.py` bunu açıkça yazıyor), `vessel/voyage/bl_number/atd/ata` alanları CI üzerinde, container'lar CI'ya bağlı, senkron yolu (`syncable`, `summarise`) yazılmış — sadece **yazan taraf yok**. Tek gerçek eksik: `vessel` serbest metin. AIS API'leri **IMO** ile çalışır, isimle çalışmaz. `vessel_imo` alanı eklenirse bir sorgu → bir CI → o CI'nın bütün container'ları. Senin dediğin fan-out mimarisi zaten bu.

---

## 1. İş gerçeği ne değişti

Genel araştırma sonucu (kaynaklar en altta):

| | Eski koridor | Yeni koridor A | Yeni koridor B |
|---|---|---|---|
| **Ad** | Hormuz / Bandar Abbas | Türkiye → İran karayolu | Türkiye → Orta Koridor (TITR) |
| **Deniz ayağı** | Menşe → Bandar Abbas | Menşe → Mersin / İstanbul | Menşe → Mersin / İstanbul |
| **Kara ayağı** | İran → Sarahs/Gaudan → UZ | Tahran → Sarakhs → Gaudan → UZ | Kars (BTK) → Tiflis → Bakü → **Hazar feribotu** → Aktau/Türkmenbaşı → UZ |
| **Sınır sayısı** | ~2 | ~3 | **~4 + 1 feribot** |
| **Transit süre** | (MSA'nın kendi verisi) | 12–20 gün | 18–25 gün |
| **İran maruziyeti** | Tam | Karayolu transit | **Yok** |

Bağlam: Hormuz Boğazı 28 Şubat 2026'daki askerî harekâttan sonra fiilen kapandı; 14 Haziran 2026 itibarıyla çıkış yönlü ticarî trafik beş gün üst üste sıfıra yakın seyretti. Yani İran koridoru "artık güncel statü değil" demekten daha fazlası: **deniz ayağı çalışmıyor.**

**Modelleme açısından kritik nokta:** bu "İran koridoru" ve "Türkiye koridoru" diye iki değer değil. Türkiye bir **deniz-ayağı tahliye noktası**; Türkiye'den *sonra* en az iki farklı kara koridoru var ve bunların sınır sayısı, gün sayısı ve masraf kalemleri farklı. Statü modeline tek bir `TURKEY` değeri koymak bugünkü hatanın aynısını bir kez daha yapmak olur.

---

## 2. Sistemdeki hasar — kanıtlı

`ARRIVED_AT_IRAN` kaynak ağacında (dist bundle hariç) **25 dosyada**, `DEPARTED_IRAN` **13 dosyada** geçiyor. Ama dosya sayısı yanıltıcı; önemli olan hangilerinin *davranış* olduğu.

### 2.1 Bu bir etiket değil, para tetikleyicisi

```
stabler/imports_module/payment_math.py:46-47
    def wants_advance_pe(old_status, new_status) -> bool:
        """True on the transition INTO ARRIVED_AT_IRAN (not on a re-save that keeps it)."""
        return bool(new_status == "ARRIVED_AT_IRAN" and old_status != new_status)
```

`stabler/imports_module/hooks.py:135-201` — Import Container `ARRIVED_AT_IRAN`'a *geçtiği anda* DRAFT %70 avans Payment Entry kuyruğa alınıyor; iş içinde `hooks.py:160` statüyü bir kez daha doğruluyor.

**Sonuç:** Türkiye koridorundaki bir konteyner için operatör bu statüyü yazmayacak (mantıken yazamaz, çünkü mal İran'a gitmiyor). O zaman `AVAILABLE`'da kalır ve **%70 avans ödeme belgesi hiç oluşmaz.** Hata mesajı yok, uyarı yok — sadece olmayan bir belge. Bu bir görsel sorun değil, nakit akışı sorunu.

### 2.2 Geri dönülemezlik semantiği yanlış yere bağlı

```
stabler/doctype/commercial_invoice/commercial_invoice.py:25-26
    "AVAILABLE": {"ARRIVED_AT_IRAN", "Cancelled"},
    "ARRIVED_AT_IRAN": {"DELIVERED_TO_UZBEKISTAN"},
```
(aynısı `stabler/doctype/import_container/import_container.py:28-29`)

`ARRIVED_AT_IRAN`, boru hattında **`Cancelled` çıkışı olmayan tek statü** — dosyanın kendi yorumuyla: "once goods have physically arrived in-country the deal cannot be walked back". Bu kural doğru. Ama bağlandığı gerçek *"mal fiziksel olarak transit ülkeye vardı"*; **İran** değil. Kural doğru, adresi yanlış.

### 2.3 Kamyon çıkış kapısı

```
stabler/imports_module/departure_math.py:23
    GATED_TRANSITION = ("PENDING", "DEPARTED_IRAN")
```

`stabler/doctype/import_truck/import_truck.py:46-85` — bu geçiş gümrük beyanı (GTD) + veteriner sertifikası şartına bağlı; engellenince kullanıcıya birebir şu cümle gidiyor: *"Bu araç henüz İran'dan çıkamaz:"* (`translations/tr.csv:5212`).

Kural doğru (temizlik olmadan mal kımıldamasın), coğrafya yanlış. Mersin'den kalkan bir kamyona "İran'dan çıkamaz" demek operatörün sisteme güvenini bozar — ve tecrübe şu ki bu tür mesajlar `departure_override` ile aşılmaya başlanır, yani gerçek kontrol de erozyona uğrar.

### 2.4 En derin kusur: tek-sınır varsayımı

```
stabler/doctype/import_truck/import_truck.py:24-35
    "PENDING":        {"DEPARTED_IRAN", "Cancelled"},
    "DEPARTED_IRAN":  {"AT_BORDER", "Cancelled"},
    "AT_BORDER":      {"CROSSED_BORDER", "Cancelled"},
    "CROSSED_BORDER": {"IN_TRANSIT", "Cancelled"},
    "IN_TRANSIT":     {"ARRIVED", "Cancelled"},
```

`AT_BORDER` ve `CROSSED_BORDER` **tekil** durumlar. Boru hattı tek yönlü olduğu için ikinci bir sınıra geri dönmek *imkânsız* — `assert_transition` reddeder.

Ve bu sadece görünürlük değil, yine para:

```
stabler/imports_module/payment_math.py:50-52
    def wants_transport_pi(old_status, new_status) -> bool:
        """True on the transition INTO CROSSED_BORDER."""
```
`stabler/imports_module/hooks.py:251-259` + `:264` — `CROSSED_BORDER`'a geçişte **bir** DRAFT sınır-aşırı nakliye Purchase Invoice'ı üretiliyor (3 kademeli maliyet kaynağı: bağlı Import Expense → eşleşen Import Expense → kamyonun kendi `transport_cost`'u).

Orta Koridor'da bir sevkiyat Gürcistan, Azerbaycan, Hazar feribotu, Kazakistan/Türkmenistan ve Özbekistan ayaklarının her biri için ayrı ücret üretir. Model bir tanesini biliyor. Kalanlar ya tek bir `transport_cost` rakamına sıkıştırılır (kalem kaybı → landed cost'ta koridor karşılaştırması imkânsız) ya da elle Import Expense olarak girilir (3. kademe resolver bunu kısmen kurtarır, ama tetikleyici yine tek).

Bunu bir "gelecek özelliği" olarak işaretlemenin sakıncası şu: Türkiye koridoru **bugünkü** koridor.

### 2.5 Landed-cost bileşenlerinin 5'i "Iran" adlı

```
stabler/doctype/container_cost_line/container_cost_line.json:25  (aynı liste: import_expense.json:182)
    Freight
    Iran Customs Duty      ←
    Iran Port & THC        ←
    Iran Storage           ←
    Iran Demurrage         ←
    Iran Inspection        ←
    Cross-Border Transport
    Insurance
    Certificate
    Uzbekistan Customs Duty
    Uzbekistan Port Handling
    Customs Clearance Fee
    Other
```

13 seçenekten 5'i tek bir koridora ait. Mersin'deki THC'yi operatör ya **"Iran Port & THC"** olarak girecek (rapor yalan söyler) ya da **"Other"** kovasına atacak (kalem kimliğini kaybeder — ve `Other` bugün de en kalabalık kova olma yolunda).

Bunun landed-cost işiyle doğrudan bağı var: GTD öncelik kuralı

```
stabler/imports_module/lcv_math.py:58-65
    def is_uzbekistan_customs_duty(component) -> bool:
        """... Only the Uzbek duty is replaced by a cleared customs declaration — Iran-side
        duty stays a real landed cost, so it is deliberately not matched here."""
```

**Kuralın mantığı doğru ve korunmalı:** transit ülke gümrük vergisi gerçek bir landed cost'tur, Özbek GTD'si onun yerine geçmez. Ama kural bugün *"iran" kelimesinin yokluğu* üzerinden çalışıyor. Bileşen adı `Turkey Customs Duty` olsaydı da doğru çalışırdı — çünkü `"uzbek" in c` şartı sağlanmaz. Yani **bu kural şans eseri sağlam.** `Other`'a atılan bir transit vergisi de doğru davranır. Ama şansa bırakılmış bir doğruluk, doğruluk değil; adlandırmayı düzeltirken bu kuralı da niyetli hale getirmek gerekir.

### 2.6 KPI ve rapor kovaları

| Yer | Ne yapıyor |
|---|---|
| `api/imports.py:5830` | `SUM(CASE WHEN c.status IN ('IN_TRANSIT','GATE_IN','ON_BOARD','STUFFED','ARRIVED_AT_IRAN') …)` → container "yolda" sayacı |
| `api/imports.py:5873`, `:8248` | `('DEPARTED_IRAN','AT_BORDER','CROSSED_BORDER','IN_TRANSIT')` → kamyon "yolda" sayacı |
| `api/_pi_group_report.py:39` | `"ARRIVED_AT_IRAN": "DESTINATION"` → PI Group raporu faz eşlemesi |
| `api/_imports_rules.py:129,135` | `CI_STATUSES`, `TRUCK_IN_TRANSIT_STATUSES` — tüm KPI kovalarının kaynağı |
| `api/_imports_rules.py:859` | `_CI_SHIPPING_STATUSES` → Purchase Order'ı "SHIPPING" gösteren küme |
| `api/reports.py:1984` | rapor filtresi |
| `public/js/pages/imports/ImportContainers.vue:216-219` | SQL'i birebir taklit eden istemci tarafı sayaç (yorumu da "Mirrors container_list_stats' SQL exactly" diyor) |

Not: `ImportContainers.vue` sayacı sunucu SQL'ini **elle kopyalıyor**. Statü kümesi değişince iki yerde de değişmezse ekran ile KPI birbirini yalanlar. Bu, yeniden adlandırmanın en sessiz kırılma noktası.

### 2.7 Konumsal sıralama

```
stabler/imports_module/sea_lifecycle.py:30-40
    SEA_PIPELINE = [BOOKED, STUFFED, GATE_IN, ON_BOARD, IN_TRANSIT,
                    DISCHARGED, AVAILABLE, ARRIVED_AT_IRAN, DELIVERED_TO_UZBEKISTAN]
```

`rank()` listedeki **indeksi** döndürüyor; `drift()` container ile CI arasındaki "behind / ahead / aligned" kararını bu indekse göre veriyor. Listeye statü eklemek/çıkarmak bütün drift hesabını kaydırır. Yeniden adlandırma bu yüzden mekanik bir `sed` işi değil.

### 2.8 Kalan kırıntılar

- `stabler/doctype/freight_booking/freight_booking.json:106` — `pickup_location` default değeri **`"Bandar Abbas, Iran"`** (ayrıca `public/js/pages/imports/FreightBookings.vue:57`). Bu doctype zaten silinecekler listesinde; artık silmek için ikinci bir gerekçe var.
- `translations/{en,ru,uz,uzc,tr}.csv` — `Transit ETA (Iran)`, `70% balance due 7 days before Iran arrival`, `This truck cannot leave Iran yet:`, 5 masraf bileşeni adı. 5 katalog × ~8 satır.
- `integrations/msa_migrate/ci_backfill.py:48` ve `maintenance/migrate_msaerp_imports.py` — eski Django verisinin statü eşlemesi. **Bunlar geriye dönük veriyi okur; değiştirilmemeli.** Eski satırlar `ARRIVED_AT_IRAN` ile geldi ve öyle kalmalı.

---

## 3. Yanlış çözüm ve nedeni

**Yanlış:** `ARRIVED_AT_IRAN` → `ARRIVED_AT_TURKEY` yeniden adlandırması.

Nedeni: bugünkü hatayı bir kez daha yapar. İki koridor birlikte çalışıyor (Türkiye üzerinden gelen mal hâlâ İran karayolunu da kullanabiliyor — Koridor A). Bir sonraki değişiklikte (Rusya üzeri? doğrudan demiryolu?) aynı iş üçüncü kez yapılır. Ayrıca **geriye dönük veri** `ARRIVED_AT_IRAN` ile dolu; adı değiştirmek 243 fatura ve bağlı container'ların geçmişini yeniden yazmak demektir.

**Yanlış-2:** Statüyü olduğu gibi bırakıp operatöre "Türkiye'ye vardığında da `ARRIVED_AT_IRAN` yaz" demek.

Nedeni: %70 avans ödemesi doğru tetiklenir, evet — ama sistem artık yalan söyleyen bir veri tabanı olur. Denetimde, koridor maliyet karşılaştırmasında ve gümrük dosyasında karşılığı yok. Bu, kayıt sistemini raporlama uğruna bozmaktır.

---

## 4. Kararlar

### ADR-201 — Statü *işlevi* adlandırır, coğrafya *veri* olur

Boru hattı koridordan bağımsız hale gelir:

```
BOOKED → STUFFED → GATE_IN → ON_BOARD → IN_TRANSIT → DISCHARGED
       → AVAILABLE → ARRIVED_TRANSIT_COUNTRY → DELIVERED_TO_UZBEKISTAN
```

`ARRIVED_AT_IRAN` yerine **`ARRIVED_TRANSIT_COUNTRY`**. Bunun taşıdığı üç anlamın hepsi korunur: (a) mal fiziksel olarak transit ülkede, (b) geri dönüş yok — `Cancelled` çıkışı olmayan tek statü, (c) %70 avans tetikleyicisi.

Coğrafya **Commercial Invoice üzerinde yeni bir alan** olur — CI zaten deniz ayağının sahibi (`sea_lifecycle.py` modül başlığı bunu karar olarak yazıyor):

- `transit_corridor` — Select: `IRAN_HORMUZ`, `TURKEY_IRAN_ROAD`, `TURKEY_MIDDLE_CORRIDOR`, `OTHER`
- `transit_country` — Link → Country (fiilen hangi ülkede beklediği)

Boş bırakılan koridor eski davranışı sürdürür (aşağıda ADR-204).

### ADR-202 — Masraf bileşenleri koridordan arındırılır

`Iran X` → **`Transit X`**:

| Eski | Yeni |
|---|---|
| Iran Customs Duty | Transit Customs Duty |
| Iran Port & THC | Transit Port & THC |
| Iran Storage | Transit Storage |
| Iran Demurrage | Transit Demurrage |
| Iran Inspection | Transit Inspection |

Hangi ülkenin masrafı olduğu, satırın bağlı olduğu belgenin `transit_corridor` alanından okunur. Kazanç: **koridor başına $/kg karşılaştırması mümkün hale gelir** — MSA'nın şu anda vermek zorunda olduğu iş kararı tam olarak bu (Koridor A ucuz ama İran riski taşıyor, Koridor B temiz ama 6–7 gün uzun). Bugünkü bileşen adlarıyla bu karşılaştırma yapılamaz.

`lcv_math.is_uzbekistan_customs_duty` **davranışsal olarak değişmez** (`"uzbek" in c and "customs duty" in c`) ama testine yeni bir vaka eklenir: `Transit Customs Duty` netlenmez. Bugünkü doğruluk şansa dayanıyor; bu onu niyete çevirir.

### ADR-203 — Kamyon boru hattı çoklu sınırı temsil eder

`DEPARTED_IRAN` → **`DEPARTED_TRANSIT_COUNTRY`**, mesaj koridordan parametrik.

Tek-sınır varsayımı için iki seçenek var:

- **203a (küçük, önerilen ilk adım):** `AT_BORDER` / `CROSSED_BORDER` **tekrarlanabilir** hale getirilir — `CROSSED_BORDER → AT_BORDER` geçişine izin verilir, ve her `AT_BORDER → CROSSED_BORDER` turu bir alt tabloya (`border_crossings`: sınır adı, tarih, masraf) satır yazar. `wants_transport_pi` tekil geçiş yerine bu satırlara bağlanır. Boru hattının tek yönlülüğü bozulmaz çünkü sayaç ileri gider.
- **203b (büyük):** Kamyonu ayaklara böl (`Import Truck Leg` çocuk doctype'ı; her ayak kendi taşıyıcısı, sınırı, ücreti). Doğru model, ama Import Truck'ın tüm ekranlarını ve nakliye faturası akışını yeniden yazmayı gerektirir.

**Öneri: 203a.** Orta Koridor'un dört sınırını temsil eder, mevcut ekranları kırmaz, nakliye faturasını ayak başına doğru üretir.

### ADR-204 — Göç: `db_set`/SQL zorunlu, `doc.save()` yasak

Bu maddenin tek başına bir ADR olması gerekiyor çünkü **yanlış yapılırsa para hareketi üretir.**

`wants_advance_pe(old, new)` statüye *geçişte* ateşlenir. Statüyü `frappe.get_doc(...).save()` ile yazan bir patch, `doc_events → on_update → on_container_update` zincirini çalıştırır ve `old_status != new_status` koşulu **sağlanır** (`ARRIVED_AT_IRAN` → `ARRIVED_TRANSIT_COUNTRY`). Sonuç: geçmişteki her container için **ikinci bir %70 avans Payment Entry**. Idempotency koruması `advance_70_payment_entry` alanı ve `70PCT-<container>` referans numarası üzerinden var (`hooks.py:163-169`), yani muhtemelen yakalanır — ama "muhtemelen" ile para yazmak kabul edilemez. Kural:

- Statü göçü **yalnızca** `frappe.db.set_value` / doğrudan SQL ile yapılır (doc_events tetiklenmez).
- Patch, çalışmadan önce ve sonra `ARRIVED_TRANSIT_COUNTRY` sayısını loglar.
- Patch, `Payment Entry` sayısını önce/sonra karşılaştırır ve fark varsa `frappe.throw`.
- Patch numarası **v88 veya sonrası** — `v87` çakışması hâlâ açık (bkz. LCV handoff notu).

Eski değer okunabilir kalır: `sea_lifecycle.rank()` ve `getStatusBadgeClass` her iki adı da tanır (geçiş dönemi için alias tablosu), ama `_ALLOWED_TRANSITIONS` yalnızca yeni adı hedef olarak kabul eder.

### ADR-205 — 7 tenant'ta koridor alanı zorunlu değil

`transit_corridor` boş bırakılabilir ve boşsa sistem bugünkü gibi davranır. Nedeni: bu bench'te 7 tenant var ve hepsi et ithal etmiyor. Zorunlu alan, imports modülü kapalı tenant'larda kaydetmeyi kırar. `_should_run` / `_imports_enabled` deseni zaten bu ayrımı yapıyor; ona uyulur.

### ADR-206 — `vessel` alanına IMO eklenir

Bkz. bölüm 5. `Commercial Invoice`'a `vessel_imo` (Data, 7 hane, kontrol basamağı doğrulanır) ve opsiyonel `vessel_mmsi`. `vessel` serbest metin olarak kalır (operatör alışkanlığı) ama takibin anahtarı IMO olur.

### ADR-207 — `Freight Booking` silinir

Zaten ölü. `"Bandar Abbas, Iran"` default'u onu yeniden adlandırılacak yüzeylerden biri yapıyor; silmek hem işi küçültür hem bir kalem borç kapatır.

---

## 5. Gemi bazlı takip

### 5.1 Mimari zaten senin dediğin şey

`sea_lifecycle.py` modül başlığı bunu bir karar olarak yazmış:

> *"The design settles the ownership question: the CI is the source of truth for the sea leg, containers display it."*

Ve CI'da voyage verisi hazır: `vessel`, `voyage`, `bl_number`, `port_of_loading`, `port_of_discharge`, `eta_transit_port`, `etd`, `eta`, `atd`, `ata` (`commercial_invoice.json:122-171`). Container'lar `commercial_invoice` Link'i ile bağlı. `summarise()` bir CI'nın bütün container'larının drift'ini tek çağrıda veriyor, `syncable()` hangilerinin ileri itilebileceğini söylüyor.

Yani **"vessel'i bilirsek ona bağlı 3 container'ın durumu aynı"** cümlesi, sistemin zaten kurulmuş olan modeli. Eksik olan tek şey: bu senkronu tetikleyecek **bir yazan taraf**. Bugün `sea_lifecycle` sadece *ölçüyor* — modülün kendi ifadesiyle "WHY THIS MODULE ONLY MEASURES": sessiz otomatik senkron, sorunun ne kadar büyük olduğunun kanıtını yok edeceği için kasıtlı olarak yazılmadı.

**Sıralama sonucu:** AIS entegrasyonundan *önce* drift raporunun bir kez çalıştırılıp bakılması gerekiyor. Otomatik yazmaya başlarsan, önceki elle tutulan verinin ne kadar kaymış olduğunu bir daha ölçemezsin.

### 5.2 Tek gerçek eksik: IMO

`vessel` bir `Data` alanı — serbest metin. AIS API'leri gemiyi **IMO** (kalıcı, 7 hane) veya **MMSI** (bayrak değişince değişir) ile bulur. `"MSC ARIA"` / `"Msc Aria"` / `"MSC ARİA"` üçü aynı gemi ama üç farklı anahtar; üstelik benzer isimli gemiler gerçekten var. İsimle sorgulamak yanlış gemiyi izleme riski taşır ve bu risk **sessizdir** — ekranda bir konum görünür, sadece başka birinin konumudur.

Bu yüzden IMO'nun kontrol basamağı doğrulanmalı: 7. hane ilk 6 hanenin ağırlıklı toplamından türetilir, çevrimdışı hesaplanabilir. Bir harf hatası IMO'yu geçersiz kılar ve girişte yakalanır. Bu, "yanlış gemiyi izleme" hatasını tasarımla imkânsıza yakın hale getiren tek ucuz önlem.

### 5.3 Ne otomatikleşir, ne otomatikleşmez

| Statü | AIS ne söyler | Otomatik? |
|---|---|---|
| `BOOKED` | — | Hayır (ticarî) |
| `STUFFED` | — | Hayır (fiziksel, terminalde) |
| `GATE_IN` | — | Hayır (terminal kapı verisi, AIS'te yok) |
| `ON_BOARD` | gemi POL'den ayrıldı → `atd` | **Evet** |
| `IN_TRANSIT` | gemi seyir halinde | **Evet** |
| `DISCHARGED` | gemi POD'a demirledi/rıhtımda → `ata` | **Evet** (tahliye ≈ varış, birkaç saat sapma) |
| `AVAILABLE` | — | Hayır (terminal serbest bırakma) |
| `ARRIVED_TRANSIT_COUNTRY` | — | Hayır (gümrük/kara) |
| `DELIVERED_TO_UZBEKISTAN` | — | Hayır |

**Üç statü otomatikleşir, altısı elle kalır.** Bunu küçümsememek lazım: otomatikleşen üçü tam olarak *operatörün göremediği* ayak. Kalan altısı MSA'nın kendi elinde olan olaylar; onları yazmak zaten doğru.

Ve bir bonus: `atd`/`ata` alanları bugün elle giriliyor ve muhtemelen sık boş. AIS bunları doldurursa **transit süre istatistiği ilk kez gerçek olur** — koridor karşılaştırması (ADR-202) için gereken ikinci veri de bu.

### 5.4 Türkiye koridoru takibi *kolaylaştırıyor*

Bu, önceki araştırmanın sonucunu tersine çeviren nokta ve önemli:

Bandar Abbas için container-seviyesi API'ler işe yaramıyordu, çünkü DCSA standardını uygulayan 10 taşıyıcı (MSC, Maersk, CMA CGM, Hapag-Lloyd, Evergreen, ONE, HMM, Yang Ming, ZIM, PIL) 2018'de İran'dan çıkmış taşıyıcıların *aynısı*. Yani API vardı, o limana veri yoktu.

**Mersin ve İstanbul bu taşıyıcıların hepsinin uğradığı limanlar.** Yani Türkiye koridorunda:

- Taşıyıcının kendi DCSA Track & Trace API'si (v3.0) fiilen kullanılabilir hale gelir.
- Kpler/MarineTraffic Container Tracking API'sinin B/L + SCAC anahtarı gerçekten çözülür.
- Terminal49 / Shipsgo gibi toplayıcılar bu lane'i kapsar.

Buna karşılık **AIS hâlâ ilk adım olmalı**, üç nedenle: (1) ücretsiz/çok ucuz katman yeter (aisstream.io ücretsiz; VesselFinder €330/10k kredi kamuya açık fiyatı olan tek seçenek), (2) satış döngüsü gerektirmez, (3) MSA'nın aynı anda açık voyage sayısı azdır — **kaç olduğu ölçülmedi**, ama container sayısı değil voyage sayısı önemli olduğu için ölçek küçük.

Bir de Orta Koridor'un kendi ikramiyesi var: **Hazar feribotu ikinci bir deniz ayağı** ve AIS Hazar'ı kapsar. Bakü → Aktau/Türkmenbaşı geçişi bugün tamamen kör; aynı entegrasyon onu da görünür kılar. Ayrıca Türkiye koridorunda tahliye limanı artık tek bir bilinen yer değil (Mersin mi, İstanbul mu, Poti mi) — *"gemi fiilen nereye gitti"* sorusunun cevabı geminin kendi konumu.

### 5.5 Önerilen sıra

1. **Ölç:** drift raporunu bir kez çalıştır (CI ile container statüleri ne kadar kaymış), ve açık voyage sayısını say. İkisi de bir SQL sorgusu.
2. **Anahtarı ekle:** `vessel_imo` + kontrol basamağı doğrulaması. Kod yazmadan önce operasyonun IMO'ya erişebildiğini teyit et — B/L'de ve booking teyidinde yazar.
3. **Ücretsiz AIS ile bir voyage'ı elle izle.** Üç gerçek gemiyle bir hafta. Karar verilecek soru: konum verisi `ata`'yı MSA'nın kabul edeceği hassasiyette veriyor mu?
4. **Sonra** yazan tarafı bağla: `atd`/`ata` doldur, `ON_BOARD`/`IN_TRANSIT`/`DISCHARGED` öner — **otomatik yazma değil, öneri.** Kullanıcı onaylar. Nedeni: statü boru hattı tek yönlü; otomatik yanlış bir ileri adım geri alınamaz ve `status_correction_reason` gerektirir.
5. Container-seviyesi API'yi ancak AIS'in yetmediği kanıtlanırsa aç.

---

## 6. Ölçülmemiş olanlar

Bu notta rakam vermediğim, vermeden karar verilmemesi gereken şeyler:

- Kaç CI/container `ARRIVED_AT_IRAN` durumunda duruyor (tenant başına).
- CI ↔ container statü kayması ne kadar (`sea_lifecycle.drift` hiç çalıştırılmadı).
- Şu an kaç açık voyage var — AIS maliyetini bu belirler.
- `Other` masraf kovasının bugünkü payı — ADR-202'nin aciliyetini bu gösterir.
- Türkiye koridorunda fiilen kullanılan tahliye limanı ve kara koridoru (A mı B mi) — MSA'nın operasyon bilgisi.

---

## 7. Ne yapılmadı

- **Hiçbir kod değiştirilmedi.** Bu bir karar önerisi.
- Bead oluşturulmadı.
- `v87` patch çakışması hâlâ açık; `a2c584f` üzerindeki 4 inceleme bulgusu hâlâ düzeltilmedi (ayrı iş, bkz. LCV handoff notu).
- Hormuz/İran durumuyla ilgili yukarıdaki bilgi kamuya açık haber kaynaklarından; **hukukî veya yaptırım tavsiyesi değildir.** Koridor seçimi ve İran karayolu transiti (Koridor A) yaptırım maruziyeti taşır; herhangi bir sistem veya sözleşme değişikliğinden önce MSA'nın kendi hukuk müşavirine danışması gerekir.

---

## Kaynaklar

- [Strait of Hormuz Shipping 2026: Six Months Later — Routes, Costs and Alternatives](https://www.movargo.com/post/strait-of-hormuz-shipping-2026)
- [FCL Shipping Turkey to Uzbekistan | Delta Global](https://deltaglobal.ae/cargo-from-turkey-to-uzbekistan/)
- [Services via Mersin Port of Turkey to CIS | SLR Shipping](https://www.slrshipping.com/ctservice/services-via-mersin-port-of-turkey-to-cis/)
- [TITR — Trans-Caspian International Transport Route](https://middlecorridor.com/en/)
- [The Trans-Caspian International Transport Route (Middle Corridor) is emerging as an alternative | Oxford Business Group](https://oxfordbusinessgroup.com/articles-interviews/the-trans-caspian-international-transport-route-middle-corridor-is-emerging-as-an-alternative-to-global-trade-corridor-disruptions-news-report/)
- [Iran attacks prompt Red Sea rethink as box shipping exits Strait of Hormuz | Lloyd's List](https://www.lloydslist.com/LL1156478/Iran-attacks-prompt-Red-Sea-rethink-as-box-shipping-exits-Strait-of-Hormuz)
