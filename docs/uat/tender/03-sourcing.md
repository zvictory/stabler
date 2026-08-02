# UAT · 03 — TEDARİK (Sourcing) rolü

**Kapsam:** Stabler ERP tender modülünde `sourcing` rol penceresi. Bir tedarik uzmanının
bir günü: sabah masası → CRM hattı → tedarikçiden fiyat isteme → teklif karşılaştırma →
fiyatlama → sipariş takibi → kendi lotları.

**Test edilen sürüm:** `/mnt/user-data/uploads/stabler/` altındaki kaynak.
**Şirket:** Mikas · **Demo veri:** `seed_tender_demo.seed(company="Mikas")` (UTY-2026-4301…4316).

---

## 0. Test kullanıcısı ve rol haritası

Sourcing penceresi `_TENDER_VIEW_ROLES` sözlüğünden geliyor:

```
"sourcing": ("System Manager", "Stabler Admin", "Sales Manager", "Sales User")
```
— `stabler/api/tender.py:1725-1731`

Gözetim (oversight) rolleri ayrı bir listede:

```
_OVERSIGHT_ROLES = ("System Manager", "Stabler Admin", "Sales Manager", "Stabler Tender Director")
```
— `stabler/api/tender.py:1752`

**Kritik ayrım:** `Sales Manager` HEM sourcing HEM oversight. `Sales User` yalnız sourcing,
oversight DEĞİL. Bu dokümandaki "saf sourcing kullanıcısı" = **yalnız `Sales User` rolü olan,
`Sales Manager` / `System Manager` / `Stabler Admin` / `Stabler Tender Director` OLMAYAN** kullanıcı.

> **UAT-000 · Test hesabı kurulumu (ön koşul, tüm senaryolar için)**
>
> **Ön koşul:** Administrator olarak giriş.
> **Adımlar:**
> 1. `/app/user/new` → `sourcing@mikas.uz` kullanıcısı oluştur.
> 2. Roller: YALNIZ `Sales User`. `Sales Manager`, `System Manager`, `Stabler Admin`,
>    `Stabler Tender Director` işaretli OLMAMALI.
> 3. `User Permission` ile şirketi Mikas'a bağla.
> 4. Mikas'ta `tender` modülünün açık olduğunu doğrula (Stabler Settings → module map).
> 5. `bench --site mikas.erpstable.com execute stabler.maintenance.seed_tender_demo.seed`
>
> **Beklenen:** `stabler.api.tender.tender_views` çağrısı `{"views": ["sourcing"]}` döner —
> tek elemanlı liste.
> **Kırık belirtisi:** Listede `director` de varsa test hesabına fazladan rol verilmiştir;
> bu dokümandaki yetki testlerinin HİÇBİRİ geçerli olmaz. Baştan kur.
> **Kanıt:** `stabler/api/tender.py:1733-1735` (`_tender_views`), `1746-1749` (`tender_views`).

---

## 1. Sabah · `/tender/desk?view=sourcing` — Operasyon Masası

### UAT-101 · Masa açılıyor ve tek rol penceresi görünüyor

**Ön koşul:** `sourcing@mikas.uz` girişli, aktif şirket = Mikas.
**URL:** `https://mikas.erpstable.com/stabler/#/tender/desk`

**Adımlar:**
1. Adres çubuğuna `/tender/desk` yaz, Enter.
2. Sayfa başlığına bak: "Bugün ne yapmalıyım?" (`What should I do today?`).
3. Sağ üstteki rol seçici açılır kutusunu ara.

**Beklenen:**
- Sayfa açılır (yetki hatası YOK): `operations_desk` yalnız `_tender_views(user)` boş olmasın
  ister, boşsa "Access denied to Operations Desk." atar — sourcing kullanıcısında liste
  `["sourcing"]` olduğu için geçer.
- **Rol seçici açılır kutu GÖRÜNMEZ.** Şablon `v-if="deskData?.views && deskData.views.length > 1"`
  diyor; sourcing kullanıcısında `views` tek elemanlı.
- Üst satırda görünüm adı olarak `sourcing` yazar.

**Kırık belirtisi:** Açılır kutu görünüyor ve içinde `director` seçeneği varsa → test hesabına
fazla rol verilmiş (UAT-000'e dön) ya da `_tender_views` sızdırıyor.
**Kanıt:** `stabler/api/tender_desk.py:34-44`, `OperationsDesk.vue:21-32`, `OperationsDesk.vue:17`.

---

### UAT-102 · Masa KENDİ lotlarını mı gösteriyor, herkesinkini mi

Kod, sourcing için açık bir kısıt taşıyor:

```python
oversight = _is_tender_oversight(user)
...
# Permission filter: sourcing role sees only assigned or owned deals
if not oversight and view == "sourcing":
    deals = [d for d in deals if (d.get("assigned_to") == user or d.get("owner") == user)]
```
— `stabler/api/tender_desk.py:46`, `89-91`

**Ön koşul:** UAT-101 tamam, demo veri yüklü (13 lot).
**Adımlar:**
1. `/tender/desk` sayfasında "Günlük iş planı" (Daily work plan) panelini oku.
2. Üstteki dört sayaca bak: Bugün / Geciken / Onayımı bekleyen / Başkasını bekleyen.

**Beklenen (demo veriyle, saf sourcing kullanıcısı):**
- Dört sayacın **dördü de `0`**.
- İş planı paneli boş durum metnini gösterir:
  "Bugün için planlanmış iş yok" + "Bu görünümdeki tüm kalemler güncel."
- **Hiçbir UTY-2026-43xx lotu listelenmez.**

**Neden:** `seed()` anlaşmaları `frappe.new_doc(...).insert(ignore_permissions=True)` ile,
bench oturumunun kullanıcısıyla (Administrator) yaratıyor → `owner = "Administrator"`.
`assigned_to` sütunu da hiç yazılmıyor. İki koşulun ikisi de tutmuyor.
**Kanıt:** `stabler/maintenance/seed_tender_demo.py:179-187` (anlaşma insert'i; `assigned_to`
hiç set edilmiyor), `tender_desk.py:89-91`.

**Kırık belirtisi (ve bu bir HATA):** Masa boş olduğu hâlde `/tender/crm`'de aynı kullanıcı
13 kartın hepsini görüyor. Yani "sabah masam" ile "hattım" aynı veriyi anlatmıyor. Bu bir
kabul kriteri ihlalidir; aşağıda **BULGU-S1** olarak kayıtlı.

**Ek doğrulama (atama ne işe yarıyor):**
3. Administrator ile `/tender/portfolio` → bir lotu `sourcing@mikas.uz`'a ata
   (`assign_tender`).
4. Sourcing kullanıcısıyla `/tender/desk`'i yenile.

**Beklenen:** Lot masada **yine görünmez**. Çünkü `assign_tender` atamayı
`custom_tender_intake` JSON'unun içine (`intake["assigned_to"]`) yazıyor; masa ise
CRM Deal'in `assigned_to` **sütununu** okuyor. İki farklı yer.
**Kanıt:** `stabler/api/tender.py:1786-1189` özellikle `1171` civarı
(`clean["assigned_to"] = user`, intake JSON'una yazılıyor) vs `tender_desk.py:79`
(`d.get("assigned_to") or d.get("owner")` — doctype sütunu).
Karşılaştır: `sourcing_my_tenders` intake'ten okuyor → `tender.py:2136`
(`if not oversight and (intake.get("assigned_to") or "") != me`).

---

### UAT-103 · Masanın filtrelenMEyen bölümleri (veri sızıntısı testi)

Yukarıdaki atama filtresi **yalnız `deals` listesine** uygulanıyor. Geç siparişler,
ödenmemiş alış faturaları ve onaylar filtreye hiç girmiyor ve `frappe.get_all` ile
(izin denetimi olmadan) çekiliyor.

**Ön koşul:** Mikas'ta en az 1 gecikmiş Purchase Order ve 1 vadesi geçmiş Purchase Invoice
olsun (demo seed bunları üretmiyor — elle yarat: teslim tarihi dün olan onaylı bir PO ve
vadesi dün olan, ödenmemiş bir alış faturası, ikisi de BAŞKA bir kullanıcının üzerinde).
**Adımlar:**
1. Sourcing kullanıcısıyla `/tender/desk` aç.
2. İş planında `po_late` ve `invoice_due` türü satırları ara.

**Beklenen (tasarım niyeti):** Sourcing kullanıcısı kendisiyle ilgisi olmayan finansal
kalemleri görmemeli.
**Gerçek davranış (kırık):** Satırlar görünür ve alt satırda **kalan borç tutarı açıkça
yazar**: "Overdue by 3 days (Outstanding: 45.000.000,00)".
**Kırık belirtisi:** Yukarıdaki satırın görünmesi = **BULGU-S2**.
**Kanıt:** `tender_desk.py:146-181` (`frappe.get_all("Purchase Order"...)`,
`frappe.get_all("Purchase Invoice"...)` — `get_list` değil, yani izin süzgeci yok; ayrıca
`89-91`'deki filtre bu listelere uygulanmıyor), `_desk_rules.py:155-211` (tutar metne
gömülüyor).

---

### UAT-104 · Karar kutusuna başkasının onayı düşüyor mu

```python
decisions = [
    a for a in all_pending_approvals
    if isinstance(a, dict) and (a.get("assigned_to") == user or a.get("requested_by") != user or oversight)
]
```
— `tender_desk.py:225-228`

Ortadaki koşul `or a.get("requested_by") != user` — "bana atanmışsa" DEĞİL,
"**benim talep etmediğim her onay**" demek.

**Ön koşul:** Mikas'ta başka bir kullanıcının açtığı, bir üçüncü kişiye atanmış 1 bekleyen onay.
**Adımlar:**
1. Sourcing kullanıcısıyla `/tender/desk` aç.
2. Sağdaki "Karar kutusu" panelini oku ve "Onayımı bekleyen" sayacına bak.

**Beklenen (tasarım niyeti):** Karar kutusu boş, sayaç `0`.
**Gerçek davranış (kırık):** Onay listelenir, sayaç `1` olur, hatta üstte
"İmzanızı bekliyor / Bunlar cevaplanmadan hiçbir şey ilerlemez" vurgu bloğu çizilir.
**Kırık belirtisi:** Kendisine atanmamış bir onayın karar kutusunda görünmesi = **BULGU-S3**.
**Kanıt:** `tender_desk.py:225-228`, `OperationsDesk.vue:156-161` (vurgu bloğu),
`OperationsDesk.vue:342-349` ("Awaiting my approval" sayacı).

---

### UAT-105 · Yetki sınırı: masayı director gözüyle açmak

**Ön koşul:** Sourcing kullanıcısı girişli.
**URL:** `/tender/desk?view=director`

**Adımlar:**
1. Adres çubuğuna `#/tender/desk?view=director` yaz, Enter.

**Beklenen:** Sayfa çizilir ama veri gelmez; iş planı panelinde kırmızı hata satırı:
**"Not permitted"** (`role="alert"` olan `error` bloğu). Sayaçlar `0` kalır.
Backend `_require_tender_view("director", company)` → `frappe.PermissionError`.
**Kırık belirtisi:** Director verisi (takım yükü paneli, tüm şirketin lotları) gelirse
ciddi yetki açığı.
**Kanıt:** `tender_desk.py:41-44`, `tender.py:1738-1743`, `OperationsDesk.vue:79`
(`v-else-if="error"`), `OperationsDesk.vue:292-294`.

**Not:** "Takım yükü" (Team load) paneli sourcing kullanıcısında hiç çizilmez —
`team_load` yalnız `if oversight:` doldurulur ve şablonda `v-if="teamLoad.length"` var.
**Kanıt:** `tender_desk.py:258-277`, `OperationsDesk.vue:197`.

---

### UAT-106 · Masada gezinme çubuğu var mı

**Adımlar:**
1. `/tender/desk` sayfasının en üstünü incele.
2. "Tender CRM", "Kendi ihalelerim", "Tender PO kontrol" bağlantılarını ara.

**Beklenen (tasarım niyeti):** Modül gezinme çubuğu (`TenderNav`) her tender ekranında.
**Gerçek davranış:** `OperationsDesk.vue` **TenderNav'ı import etmiyor ve çizmiyor**.
Sourcing kullanıcısının sabah açtığı ilk ekrandan diğer tender ekranlarına tek tık yol yok;
kenar çubuğundaki tek "Tender" maddesi `/tender/board`'a (sözleşme panosu) gidiyor.
**Kırık belirtisi:** Bu bir gezinme kopukluğu (**BULGU-S9**, düşük öncelik).
**Kanıt:** `OperationsDesk.vue:246-252` (import listesinde `TenderNav` yok),
`Sidebar.vue:79` (`{ name: "tender", path: "/tender/board", ... }`),
karşılaştır `TenderCrm.vue:14,249` / `MyTenders.vue:18,99` (onlarda var).

---

## 2. `/tender/crm` — Tender CRM kanban

### UAT-201 · Hangi kulvarlar, kaç kart

**Ön koşul:** Sourcing kullanıcısı, Mikas, demo veri yüklü.
**URL:** `/tender/crm`

**Adımlar:**
1. Menüden "Tender CRM"e tıkla (sourcing için görünür: `v-if="can('director') || can('sourcing')"`).
2. Kulvar başlıklarını ve kart sayılarını say.

**Beklenen — 7 kulvar, isim ve renk sırasıyla:**

| Kulvar | Etiket | Renk | Demo kart sayısı | Kulvar toplamı (UZS) |
|---|---|---|---|---|
| `seen` | Intake | `#6c757d` | 2 | 0 |
| `go` | GO Decision | `#206bc4` | 2 | 2.480.000.000 |
| `sourcing` | Sourcing | `#f59f00` | 2 | 1.330.000.000 |
| `priced` | Bid Pricing | `#4299e1` | 2 | 3.930.000.000 |
| `submitted` | Submitted | `#ae3ec9` | 2 | 1.600.000.000 |
| `won` | Won | `#2fb344` | 2 | 3.920.000.000 |
| `lost` | Lost | `#d63939` | 1 | 890.000.000 |

Toplam **13 kart**. Kulvar ataması `custom_tender_stage` sütunundan (seed yazıyor);
`eff_stage = custom_stage or classified`.

**Kritik:** Sourcing kullanıcısı **herkesin kartını görüyor** — `crm_board`'da atama filtresi
YOK, yalnız `_require_tender(company)` var. Yani masa (UAT-102) boşken CRM hattı doludur.
**Kanıt:** `tender.py:2305-2307` (kapılar), `2309-2317` (kulvarlar), `2357-2360` (döngü;
tek süzgeç `frappe.has_permission("CRM Deal", "read")`), `2373` (`eff_stage`),
`seed_tender_demo.py:190-191`.

---

### UAT-202 · Kart üzerindeki teklif ölçeri — demo veriyle 0/5

**Adımlar:**
1. `sourcing` kulvarındaki iki karta bak.
2. Kartın alt kısmındaki beş kutucuklu ölçere ve yanındaki metne bak.

**Beklenen (kod ne diyor):** `{sq_count}/5 quotes`, dolu kutucuk sayısı = `sq_count`.
**Gerçek (demo veriyle):** **Her kartta `0/5 quotes`, beş kutucuk da boş**, hiçbir kart
"politika tamam" (`data-full="1"`) değil.

**Neden:** `DEMO_LOTS` tablosunda `sq_sayısı` ve `ülke_sayısı` sütunları var
(4308 için 5 ve 3, 4309 için 3 ve 1) ama `seed()` **hiç Supplier Quotation kaydı üretmiyor**;
`_intake()` fonksiyonu `sq_count` parametresini alıp gövdesinde hiç kullanmıyor.
**Kırık belirtisi:** Bu bir demo veri kusuru (**BULGU-S4**) — sourcing rolünün ANA ekranı
(teklif toplama) demo veride hiç test edilemez hâlde.
**Kanıt:** `seed_tender_demo.py:51-71` (tabloda sayılar var), `122-151` (`_intake`,
`sq_count` kullanılmıyor), `178-202` (döngüde Supplier Quotation yaratılmıyor),
`tender.py:2327-2342` (sq sayımı Supplier Quotation'dan geliyor),
`TenderCrm.vue:154` (`quoteMarks`), `TenderCrm.vue:367-372`.

---

### UAT-203 · KPI şeridi

**Adımlar:** Üstteki dört KPI kutusunu oku.

**Beklenen (demo veriyle):**

| KPI | Değer | Alt metin |
|---|---|---|
| Pipeline | `13` | "open deals" · 14.150.000.000 |
| Sourcing policy | `0/13` | sarı/dikkat (`data-sev="today"`) |
| Deadline | `1` | "at risk or expired" |
| Readiness | `5` | "document set complete" |

- **Sourcing policy 0/13:** UAT-202'nin sonucu — hiçbir kartta 5 teklif + 2 ülke yok.
- **Deadline 1:** yalnız UTY-2026-4305 (teklif son tarihi dün, `DEADLINE_OFFSETS = -1`).
- **Readiness 5:** doc_progress %100 olanlar = submitted(2) + won(2) + lost(1). Sourcing
  kulvarındaki iki lot %50'de (4 belgeden 2'si `ready`).

**Kırık belirtisi (gerçek kusur):** "Pipeline" kutusunun alt yazısı **"open deals"** ama
sayı `cards.value.length` — yani **won ve lost dahil 13**. Açık hat aslında 10.
Aynı şekilde "Sourcing policy 0/13" paydası da kapanmış işleri sayıyor. **BULGU-S8.**
**Kanıt:** `TenderCrm.vue:105-114` (`const all = cards.value`, `cap: t("open deals")`),
`TenderCrm.vue:120-125`, karşılaştır `_funnel.py:106`
(`open_pipeline` won/lost'u hariç tutuyor).

---

### UAT-204 · Kartlar birbirinden ayırt edilebiliyor mu

**Adımlar:**
1. `go`, `sourcing`, `priced`, `won` kulvarlarındaki kart başlıklarını oku.
2. UTY-2026-4308 lotunu bulmaya çalış.

**Beklenen (kullanıcı beklentisi):** Kart başlığında lot numarası.
**Gerçek:** Başlık `_deal_label(deal)` → CRM Deal'in **organization** alanı. Demo veride
dört ayrı lot aynı başlığı taşır:
- "O'zbekiston temir yo'llari AJ [DEMO]" → 4301, 4305, 4310, 4315 (**4 kart, aynı başlık**)
- "Signal va aloqa boshqarmasi [DEMO]" → 4306, 4308, 4316 (3 kart)
- kalan alıcılar 2'şer kart

Lot numarası (`intake.lot_no = "UTY-2026-4308 [DEMO]"`) **kartta hiç yazmıyor**; kartın
altındaki küçük gri satır CRM Deal id'si (`CRM-DEAL-2026-000xx`). Arama kutusu da lot
numarasında arama yapmıyor — `filteredCards` yalnız `name`, `label`, `organization`,
`lead_name` alanlarına bakıyor.

**Kırık belirtisi:** Tedarik uzmanı "4308'e teklif girmeliyim" dediğinde kartı bulamıyor.
**BULGU-S7.**
**Kanıt:** `tender.py:1850-1856` (`_deal_label`), `tender.py:2390-2408` (kart yükü —
`lot_no` alanı yok), `TenderCrm.vue:350-351`, `TenderCrm.vue:70-79` (arama alanları),
`seed_tender_demo.py:129` (lot_no yalnız intake'te), `seed_tender_demo.py:53-70`
(alıcı tekrarı). Karşılaştır: `tender_funnel` kartlarında `lot_no` VAR
(`tender.py:2119-2122` civarı, `stage_rows` yükü) — yani veri var, CRM kartına konmamış.

---

### UAT-205 · Kart sürükleme — hangi kartı, nereye

**Ön koşul:** Sourcing kullanıcısı, `/tender/crm`, Kanban görünümü.

**Adımlar:**
1. `sourcing` kulvarındaki UTY-2026-4308 kartını `priced` kulvarına sürükle bırak.
2. Yeşil bildirimi oku.
3. Sayfayı yenile.

**Beklenen:**
- Kart anında yeni kulvara geçer (iyimser güncelleme), sonra sunucu yanıtı gelir.
- Bildirim: **"Moved to Bid Pricing"** — kulvar ETİKETİ (kimlik `priced` değil).
- Sunucu `move_deal_stage` çağrılır ve şunları yazar:
  - `CRM Deal.custom_tender_stage = "priced"`
  - aşama gerçekten değiştiyse `custom_tender_stage_entered_at = <şimdi>`
  - değişmez bir `CRM Stage Event` kaydı (`axis="tender_stage"`, `from_tender_stage="sourcing"`,
    `to_tender_stage="priced"`, `changed_by=<kullanıcı>`)
- Yenilemeden sonra kart `priced`'te kalır.

**Beklenen (aynı kulvara bırakma):** `onDrop` `card.stage === targetLaneId` ise hiçbir çağrı
yapmaz; ayrıca sunucu tarafında da `previous != stage` kontrolü var — "kaç gündür bu
aşamada" sayacı sıfırlanmaz.

**Kırık belirtisi:** Bildirimde "Moved to priced" (İngilizce kimlik) yazması; ya da yenileme
sonrası kartın eski kulvarına dönmesi (yazma başarısız ama rollback çalışmamış).

**Kanıt:** `TenderCrm.vue:162-182` (`onDrop`, iyimser güncelleme + rollback),
`TenderCrm.vue:148-151` (`stageLabel`), `tender.py:2451-2507` (`move_deal_stage`),
`2467-2468` (aşama adı doğrulaması: `_funnel.STAGES` dışıysa "Unknown stage"),
`2474` (tek `moved_at`), `2484-2493` (damga + olay kaydı),
`2413-2447` (`_record_tender_stage_event`), `_funnel.py:31` (`STAGES`).

---

### UAT-206 · Sürükleme yetkisi: sourcing kullanıcısı kartı `won`/`lost`'a taşıyabiliyor mu

`move_deal_stage`'in kapıları: `_assert_company_scope` + `_require_tender` +
`frappe.has_permission("CRM Deal", "write")`. **Rol penceresi kontrolü YOK**, aşamalar arası
geçiş kuralı YOK.

**Adımlar:**
1. `submitted` kulvarındaki UTY-2026-4313 kartını **`won`** kulvarına sürükle.
2. Yenile, karta tıkla, çekmecedeki "Stage progress" şeridine bak.
3. Administrator ile `/tender/portfolio` aç, kazanma oranını kontrol et.

**Beklenen (kod ne yapıyor):** İşlem **başarılı olur**. Sunucu ek olarak intake'e de yazar:

```python
if stage in ("won", "lost"):
    intake["result"] = stage
```
— `tender.py:2498-2499`

Yani sourcing kullanıcısı **ihale sonucunu (kazandık/kaybettik) tek başına ilan edebiliyor**
ve bu, direktör panosundaki kazanma oranını (`win_rate`) doğrudan değiştiriyor.

Aynı şekilde `go` kulvarına bırakmak `intake["go_no_go"] = "go"` yazıyor (Go/No-Go kararını
verir), `submitted` kulvarına bırakmak `intake["submitted_at"]` damgalıyor — oysa
`mark_tender_submitted` bu damgayı özel olarak korumaya alıyor
(`_clean_intake` "Submission can only be created by mark_tender_submitted()" diyor).

**Kırık belirtisi:** Bu davranışın gerçekleşmesi **BULGU-S5**'tir (yetki/iş kuralı açığı).
Kabul kriteri olarak beklenmesi gereken: sonuç kulvarlarına geçiş oversight rolü ister,
ya da en azından bir onay ister.
**Kanıt:** `tender.py:2451-2460` (kapılar), `2495-2504` (intake yazımı),
`1373-1403` (`_clean_intake`'in audit anahtarlarını istemciden almama sözü),
`1649-1653` (`mark_tender_submitted`'ın kendi kapısı — `move_deal_stage` bunu atlıyor).

---

### UAT-207 · Şirket sınırı (tenant isolation)

**Ön koşul:** Sistemde ikinci bir şirket olsun (ör. `MSA`), tender modülü açık, en az 1 lotu olsun.
Sourcing kullanıcısının User Permission'ı YALNIZ Mikas.

**Adımlar (üç ayrı deneme):**
1. **Şirket seçici:** Üst çubuktan MSA'ya geçmeyi dene.
2. **Doğrudan API:** Tarayıcı konsolunda
   `await frappe.call("stabler.api.tender.crm_board", {company: "MSA"})`
   (ya da `/api/method/stabler.api.tender.crm_board?company=MSA`).
3. **Yabancı lot:** MSA'ya ait bir deal id'siyle
   `/tender/po-control?deal=<MSA_DEAL>` aç.

**Beklenen:**
1. Şirket seçicide MSA hiç listelenmez (izin listesi dışı).
2. `_assert_company_scope("MSA")` → **PermissionError**, HTTP 403, gövdede "Not permitted".
   Bu kapı `crm_board` (`tender.py:2306`), `tender_funnel` (`2184`), `tender_flow` (`3016`),
   `sourcing_my_tenders` (`_require_tender_view` içinde, `1741`), `move_deal_stage` (`2457`),
   `po_control_board` (`476`) ve `_deal_scope` (`985`) çağrılarının hepsinde var.
3. `po_control_board` şirketi deal'den okuyup `_assert_company_scope` uyguluyor → **403**.
   Ekranda kırmızı bildirim: "Could not load the PO board." / "Not permitted".

**Kırık belirtisi:** Herhangi birinde MSA verisi dönmesi = kritik kiracı sızıntısı.

**Kanıt:** `tender.py:2306`, `2184`, `3016`, `1741`, `2457`, `476`, `985`.
**⚠️ Doğrulanamayan kısım:** `_assert_company_scope`'un gövdesi `stabler/api/approvals.py`
içinde ve bu dosya incelenen pakette YOK (`tender.py:22`'deki import ile geliyor). Kapının
ÇAĞRILDIĞI kanıtlandı, ne yaptığı kanıtlanmadı — bu test canlı sitede fiilen koşulmalıdır.

**Ek risk (kod okumasından):** `tender_desk.operations_desk` verisini `frappe.get_all` ile
çekiyor (`tender_desk.py:66`, `98`, `125`, `146`, `165`) — bu API satır seviyesi izinleri
atlar. Şirket kapısı (`_assert_company_scope`, `tender_desk.py:31`) tuttuğu sürece kiracı
sınırı korunur, ama **şirket içi** satır izinleri masada uygulanmıyor. Karşılaştır:
`tender.py` her yerde `frappe.get_list` + `frappe.has_permission` kullanıyor
(ör. `2358-2360`, `2131-2133`).

---

## 3. Bir lot için tedarikçilerden fiyat isteme

### UAT-301 · Supplier Quotation üretme ekranı aranıyor

**Ön koşul:** Sourcing kullanıcısı, UTY-2026-4308 lotu seçili.
**Adımlar:**
1. `/tender/crm`'de karta tıkla → sağdan çekmece açılır. "Sourcing Summary" bloğuna bak.
2. Çekmecenin alt şeridindeki düğmeleri oku.
3. `/tender/po-control?deal=<id>` → "Vendor PO" sekmesi → "Supplier quotations" kartına bak.
4. `/tender/sourcing?deal=<id>` ekranını aç.
5. Kenar çubuğu ve tender gezinme çubuğunda "Teklif iste / RFQ / Tedarikçi teklifi" ara.

**Beklenen (kabul kriteri):** Bir lottan tedarikçiye fiyat isteme (RFQ) ya da gelen fiyatı
Supplier Quotation olarak kaydetme akışı olmalı.

**Gerçek durum — YOK:**
- Çekmecenin alt şeridinde yalnız üç şey var: "Sourcing comparison" bağlantısı,
  "Contract board" bağlantısı, "Close" düğmesi. (`TenderCrm.vue:575-586`)
- `/tender/sourcing` ekranı tamamen **salt okunur** bir tablo; hiçbir düğmesi yok.
  Boş durum metni bunu itiraf ediyor: *"Tag Supplier Quotations to this deal to compare them
  here."* — yani "başka bir yerde yarat, sonra bu deal'e etiketle". (`SourcingCompare.vue:143-148`)
- SPA'nın **tamamında** Supplier Quotation yaratan/düzenleyen tek bir rota, bileşen ya da
  API çağrısı yok. `router.js` içinde Purchasing altındaki rotalar: suppliers, orders,
  receipts, invoices, aging, landed-cost-review — **quotation yok**.
  `/sales/quotations` ise MÜŞTERİ teklifi (Quotation), tedarikçi teklifi değil.
- `custom_crm_deal` alanını (teklifi lota bağlayan alan) hiçbir SPA ekranı yazmıyor.

**Sonuç:** Sourcing kullanıcısının **asıl işi** — tedarikçiden fiyat toplamak — Stabler SPA'da
**yapılamıyor**. Tek yol Frappe desk arayüzü: `/app/supplier-quotation/new`, tedarikçiyi ve
kalemleri gir, `custom_crm_deal` alanına lot deal id'sini elle yaz, kaydet/onayla.

**Kırık belirtisi:** Yukarıdaki adımların hiçbirinde bir "yeni teklif" düğmesi bulunamaması —
bu **BULGU-S6** ve bu rolün en büyük fonksiyonel boşluğu.
**Kanıt:** `SourcingCompare.vue:143-148`, `TenderCrm.vue:575-586`,
`PoControlBoard.vue:322-335` (yalnız rozet + tedarikçi adı listesi, düğme yok),
`router.js:326-343` (Purchasing rotaları), `router.js:306-308` (Sales Quotation),
SPA genelinde `Supplier Quotation` geçen tek yer `SourcingCompare.vue:147`
(metin, kod değil).

---

### UAT-302 · Teklif geldikten sonra sayıların güncellenmesi (regresyon)

**Ön koşul:** Frappe desk'ten UTY-2026-4308'in deal'ine 5 adet Supplier Quotation
(en az 2 farklı ülkeden tedarikçi, `docstatus < 2`, `company = Mikas`,
`custom_crm_deal = <deal id>`) bağlanmış olsun.

**Adımlar:**
1. `/tender/crm` → 4308 kartına bak.
2. Karta tıkla → çekmecedeki "Quote set" satırı.
3. `/tender/sourcing?deal=<id>` aç.
4. `/tender/po-control?deal=<id>` → "Vendor PO" sekmesi.

**Beklenen:**
1. Kart ölçeri **`5/5 quotes`**, beş kutucuk dolu, ölçer `data-full="1"`.
2. Çekmecede "5/5 · policy met".
3. `/tender/sourcing`'de iki yeşil rozet: "Quotations: 5 / 5" ve "Countries: 2 / 2";
   tabloda 5 satır, en ucuz satır yeşil arka planlı ve "Cheapest" rozetli.
4. PO kontrol ekranında iki yeşil rozet: "5 quotes met", "2 countries met" ve
   tedarikçi adları rozet olarak listelenir.
5. KPI şeridinde "Sourcing policy" `1/13` olur.
6. `/tender/desk`'te bu lotun `policy_gap` satırı ("Missing supplier quotes") KAYBOLUR —
   kural `stage == "sourcing" and sq_count < 5`. *(Ancak UAT-102 gereği bu satır zaten
   görünmüyordu; bu adım oversight kullanıcısıyla doğrulanmalı.)*

**Kırık belirtisi:** Sayıların ekranlar arasında uyuşmaması (ör. kartta 5/5, çekmecede 0/5).
Kart sayısı `crm_board`'un kendi sayımından, çekmece `purchasing.tender_quotations`'tan
geliyor — iki ayrı kaynak.
**Kanıt:** `tender.py:2327-2351` (kart sayımı + ülke sayımı),
`TenderCrm.vue:193-208` (çekmece ikinci çağrı), `TenderCrm.vue:480-488`,
`SourcingCompare.vue:100-113`, `PoControlBoard.vue:326-329`,
`_desk_rules.py:102-114` (`policy_gap`).

---

## 4. `/tender/sourcing` — Teklif karşılaştırma (SourcingCompare)

### UAT-401 · Ekrana nasıl gidiliyor

**Adımlar:**
1. Tender gezinme çubuğunda (`TenderNav`) "Sourcing comparison" bağlantısını ara.
2. Kenar çubuğunda ara.

**Beklenen (tasarım niyeti):** Bu, sourcing rolünün adını taşıyan ekran; menüde olmalı.
**Gerçek:** `TenderNav.vue`'da `/tender/sourcing` bağlantısı **YOK**. Ekrana yalnız üç
dolaylı yoldan gidiliyor:
- `/tender/crm` → karta tıkla → çekmece → "Sourcing comparison" düğmesi (deal parametresiyle)
- `/tender/po-control` → sağ üstteki "Sourcing comparison" düğmesi (**deal parametresi YOK**)
- `/tender/board` → sağ üstteki düğme (deal parametresi YOK)
- ya da URL'yi elle yazarak

**Kırık belirtisi:** Menüde bulunamaması (**BULGU-S9**'un parçası).
**Kanıt:** `TenderNav.vue:37-61` (tam liste), `TenderCrm.vue:576-580` (tek parametreli giriş),
`PoControlBoard.vue:288-290`, `SalesOrderBoard.vue:118`, `router.js:270`.

---

### UAT-402 · Deal seçici gerçekten çalışıyor mu (kritik)

**Ön koşul:** Sourcing kullanıcısı. **URL:** `/tender/sourcing` (parametresiz).

**Adımlar:**
1. Ekran açılınca boş durum görünür: "Pick a tender deal to compare quotations."
2. "Tender / deal" yazan Typeahead kutusuna tıkla ve `4308` yaz.
3. Tarayıcı ağ sekmesinde `stabler.api.crm.list_deals` isteğine bak.

**Beklenen (kod okumasından — muhtemel KIRIK):**
- İstek gövdesi: `{search: "4308", page_length: 20}` — **`company` parametresi yok.**
- `list_deals` önce `_require_crm()` çağırıyor: kullanıcının **`crm` modülüne** erişimi
  olmalı. Tender erişimi yetmez — ayrı bir modül kapısı.
- Sonra `_require_crm_company(company)` → `_require_company("")`. Bu fonksiyonun
  dokümantasyonu net: *"CRM must never infer a company from user defaults... The selected
  company is therefore both mandatory"*.

**İki olası sonuç — ikisi de test edilmeli:**
- **(a)** Şirket zorunluysa: istek **hata döner**, açılır listede sonuç çıkmaz, kırmızı
  bildirim. Bu durumda `/tender/sourcing`'e **doğrudan** giren kullanıcı hiçbir lot
  seçemez; ekran yalnız `?deal=` parametresiyle (CRM çekmecesinden gelerek) kullanılabilir.
- **(b)** `_require_company` oturumun varsayılan şirketine düşüyorsa: liste gelir, ama
  arama yalnız `organization`, `email`, `lead_name` alanlarında yapılıyor — **`4308` yazmak
  hiçbir şey bulmaz**, çünkü lot numarası intake JSON'unda ve aranan alanlarda değil.
  Kullanıcı alıcı kurum adını yazmak zorunda ("Signal va aloqa…") ve 3 aynı isimli sonuçtan
  hangisi olduğunu ayırt edemez.

**Her iki hâlde de ekran pratikte kullanılamaz.** **BULGU-S10.**
**Kanıt:** `SourcingCompare.vue:26-29` (`call(... {search: q, page_length: 20})` — company yok),
`crm.py:281-285` (`_require_crm`, `_require_crm_company`), `crm.py:19-21`, `crm.py:24-37`
(zorunluluk dokümantasyonu), `crm.py:322` (`search_fields=["organization","email","lead_name"]`).
Aynı kusur `PoControlBoard.vue:66-69`'da da var (aynı çağrı, aynı eksik parametre).

---

### UAT-403 · Karşılaştırma tablosu (deal parametresiyle)

**Ön koşul:** UAT-302'deki 5 teklif bağlanmış. **URL:** `/tender/sourcing?deal=<4308 deal id>`
(bu URL'ye `/tender/crm` çekmecesindeki düğmeyle gitmek en güvenilir yol).

**Adımlar:**
1. Sayfa açılır, `stabler.api.purchasing.tender_quotations` çağrılır.
2. İki politika rozetini oku.
3. Tabloyu oku: Supplier / Country / Total / Base total / Valid till / Status.

**Beklenen:**
- Rozet 1: "Quotations: 5 / 5" — yeşil (`bg-green-lt text-green`) + tik ikonu,
  `data.has_min_5 === true` ise.
- Rozet 2: "Countries: 2 / 2" — yeşil, `data.has_2_countries === true` ise.
- 4 teklifle: rozet 1 **sarı** (`bg-yellow-lt text-yellow`) + üçgen uyarı ikonu,
  metin "Quotations: 4 / 5".
- Tabloda 5 satır. **En ucuz satırın tüm arka planı yeşil** (`table-success`) ve tedarikçi
  adının yanında yeşil **"Cheapest"** rozeti.
- "Base total" sütunu şirket para birimine (UZS) çevrilmiş, kalın punto; "Total" ise
  teklifin kendi para biriminde.
- Teklif yoksa: `EmptyState` — "No supplier quotations for this tender." +
  "Tag Supplier Quotations to this deal to compare them here."

**Kırık belirtisi:** `cheapest` bayrağı hiçbir satırda yoksa ya da birden fazla satırdaysa;
`base_total` boş geliyorsa (kur tanımlı değil); yükleme sırasında `SkeletonRows` yerine
boş tablo çıkıyorsa.
**Kanıt:** `SourcingCompare.vue:37-51` (yükleme), `100-113` (rozetler), `117-141` (tablo),
`130` (`:class="{ 'table-success': r.cheapest }"`), `133` ("Cheapest"), `143-148` (boş durum).

**⚠️ Doğrulanamayan:** `stabler.api.purchasing.tender_quotations` fonksiyonunun gövdesi
incelenen pakette YOK (`stabler/api/purchasing.py` dosyası yüklenmemiş). Dolayısıyla
`cheapest` / `has_min_5` / `has_2_countries` / `base_total` alanlarının nasıl hesaplandığı
ve endpoint'in hangi yetki kapılarını taşıdığı **kod düzeyinde doğrulanamadı**. Bu ekranın
yetki testi (başka şirketin deal'i ile çağırma) canlı sitede ayrıca koşulmalıdır.

---

### UAT-404 · Bu ekranda gezinme çubuğu

**Beklenen:** `SourcingCompare.vue` `TenderNav`'ı **import etmiyor** — sayfada tender
modül çubuğu yok. Yalnız sağ üstte iki düğme: "Contract board" ve "Tender PO control".
Yani buradan `/tender/crm`'e ya da `/tender/my-tenders`'a doğrudan dönüş yok.
**Kanıt:** `SourcingCompare.vue:1-13` (import listesi), `70-75` (düğmeler).

---

## 5. Fiyat belirleme (`BidPricing.vue`) ve lotu `priced`'a taşıma

### UAT-501 · Fiyatlama ekranına ulaşma

**Ön koşul:** Sourcing kullanıcısı, UTY-2026-4308'in deal id'si elde.
**URL:** `/tender/po-control?deal=<id>` (BidPricing'in TEK barındığı yer)

**Adımlar:**
1. `/tender/crm` → karta tıkla → çekmecede "Bid pricing" / "Fiyatlama" düğmesi ara.
2. Bulamayınca `/tender/po-control?deal=<id>`'yi elle aç.
3. "Overview" sekmesinde aşağı kaydır.

**Beklenen:**
- Adım 1'de **düğme yoktur** — CRM çekmecesinden fiyatlama ekranına yol yok
  (`TenderCrm.vue:575-586`'da yalnız Sourcing comparison / Contract board / Close).
- Adım 3'te "Overview" sekmesi altında iki kart alt alta: önce **TenderIntake**,
  sonra **"Tender bid pricing"** kartı.
- Sekme şeridinde sourcing kullanıcısı için **3 sekme**: Overview · Vendor PO · Delivery.
  **"Finance" sekmesi YOKTUR** — `tender_workspace` `finance` bloğunu yalnız
  `_can_view_tender_finance()` doğruysa ekliyor; bu da oversight VEYA
  `Accounts User`/`Accounts Manager` demek. Saf `Sales User` ikisine de girmiyor.

**Kırık belirtisi:** Finance sekmesinin görünmesi = yetki açığı (kâr/zarar zinciri sızıntısı).
**Kanıt:** `PoControlBoard.vue:20-23`, `314-320` (montaj), `108-112` (`allowedTabs`),
`tender.py:955-963` (`tender_workspace` finance bloğu), `tender.py:2574-2576`
(`_can_view_tender_finance`), `TenderCrm.vue:575-586`, `router.js:271`.

---

### UAT-502 · Fiyatı belirleme (marj → fiyat)

**Ön koşul:** UAT-501 ekranı açık, "Tender bid pricing" kartı görünür.

**Adımlar:**
1. Mod düğmelerinden **"Margin → price"** seçili olduğunu doğrula (varsayılan).
2. "Landed cost (goods + import)" alanının altındaki
   *"Use POs' landed: <tutar> · <n> PO"* bağlantısına tıkla.
3. "Target margin" alanına `20` yaz.
4. Sağdaki şelale tablosunu oku.
5. "Save bid pricing" düğmesine bas.

**Beklenen:**
- Adım 2, demo veride **`0` ve `0 PO`** getirir — seed hiç Purchase Order üretmiyor.
  Yani landed maliyet elle girilmek zorunda.
- Landed = `1.000.000.000`, marj `%20`, VAT `%12`, borsa komisyonu `%0,15`,
  kâr vergisi `%15`, temettü vergisi `%5` varsayılanlarıyla şelale şu sırayı gösterir:
  Bid price (Договор) → − VAT → **Net revenue** → − Landed cost → − Exchange fee →
  **Profit** (yeşil satır) → − Profit tax → Net profit → − Dividend tax → Dividends →
  **Остаток (net remaining)** (kalın, üst çizgili).
- Altta iki rozet: yeşil "Margin on revenue: 20.0%" ve mavi "Markup on cost: 25.0%".
- Kaydet sonrası yeşil bildirim: **"Bid pricing saved."**
- Sunucu `CRM Deal.custom_bid_pricing` alanına temizlenmiş JSON yazar
  (`update_modified=False` — belge "modified" damgası değişmez).
- Bilinmeyen anahtarlar atılır; tutarsız satırlar (`amount` 0/boş) elenir; etiketler
  140 karaktere kırpılır.

**Kırık belirtisi:** "Margin → price" modunda paydanın sıfır/negatif olması
(`denom = (1 - m) - (1 + vat) * exch`) — ör. marj `%100` girilirse `net = 0` ve tüm şelale
sıfırlanır, **hata mesajı verilmez**. Marj `%99,8` gibi değerlerde de fiyat astronomik olur.
Sunucu tarafında marj için üst sınır doğrulaması yok.
**Kanıt:** `BidPricing.vue:85-108` (yerel şelale), `91-95` (payda),
`BidPricing.vue:113` (`useLandedFromPOs`), `116-133` (kaydetme),
`tender.py:1301-1341` (`save_deal_bid_pricing`, temizleme + yazma),
`tender.py:967-975` (`_BID_DEFAULTS`), `tender.py:1088-1157` (`_compute_bid_pnl`),
`seed_tender_demo.py:178-202` (PO üretilmiyor).

---

### UAT-503 · Başvuru paketi hazırlama

**Adımlar:**
1. "Prepare application package" düğmesine bas.

**Beklenen:**
- Eksik alan varsa: sarı uyarı kutusu **"Missing fields: <liste>"** ve kırmızı bildirim
  "Package incomplete — fill the missing fields".
- Tamsa: yeşil bildirim "Bid package ready" ve `bid_<lot_no>.docx` bağlantısı
  (deal'e özel/private File olarak eklenir).
- Sunucuda `python-docx` yoksa: dosya üretilmez ama veri döner, altta gri uyarı
  "python-docx is not installed on the server; document not generated."
- **Portala otomatik gönderim YOK** — imza (E-IMZO) ve yükleme insana ait.

**Kırık belirtisi:** Düğmenin sessiz kalması; ya da paket "ready" dendiği hâlde
`files` listesinin boş gelmesi (docx üretimi patlamış, uyarı da yok).
**Kanıt:** `BidPricing.vue:26-41`, `264-282`, `tender.py:1227-1298` (`bid_package`),
`1289-1292` (ImportError → warning).

---

### UAT-504 · Lotu `priced` aşamasına taşıma — kaç yol var, hangisi gerçekten taşıyor

Bu, senaryonun en kritik ve en kafa karıştırıcı adımı. **İki farklı mekanizma var ve
demo veride bunlardan biri ETKİSİZ.**

**Adımlar:**
1. UAT-502'yi yap (fiyatlama kaydedildi → `custom_bid_pricing` dolu).
2. `/tender/crm`'e dön, yenile. 4308 kartı hangi kulvarda?
3. Şimdi kartı elle `sourcing` → `priced` kulvarına sürükle.
4. Tekrar yenile.

**Beklenen:**
- **Adım 2'de kart HÂLÂ `sourcing` kulvarındadır.** Çünkü `crm_board`
  `eff_stage = custom_stage or classified` diyor: `custom_tender_stage` sütunu doluysa
  (seed onu `"sourcing"` yazmış) türetilmiş aşama (`classify` → `priced`) **hiç
  kullanılmaz**. Fiyatlamayı kaydetmek kartı tek başına taşımaz.
- **Adım 3'ten sonra kart `priced`'tedir** ve `custom_tender_stage_entered_at` bugüne
  sıfırlanmıştır (bu aşamada 0 gündür).

**Kırık belirtisi:** Kullanıcı "fiyatı kaydettim, iş bitti" sanır; kart sourcing'de kalır ve
SLA sayacı (14 gün) işlemeye devam eder. Bu, ekranlar arası bir tutarsızlık değil, **iki
kaynaklı aşama** tasarımının yan etkisi — UAT'ta açıkça yazılmalı ki tester "kart taşınmadı,
hata" demesin. Aynı ikilik `tender_flow` içinde de var (`stored or classify(...)`).
**Kanıt:** `tender.py:2365-2373` (`eff_stage`), `_funnel.py:34-52` (`classify`,
`has_pricing` → `"priced"`), `tender.py:3038-3051` (`tender_flow`'da aynı `stored or ...`),
`tender.py:2476-2493` (elle taşımada damga sıfırlama).

---

### UAT-505 · Intake ekranında BELGE LİSTESİ — veri kaybı testi (kritik)

**Ön koşul:** Demo lot (ör. 4308), `/tender/po-control?deal=<id>` → Overview sekmesi →
"Tender intake" kartı.

**Adımlar:**
1. Belge kontrol listesi tablosuna bak. Kaç satır var, etiketleri ne yazıyor?
2. `/tender/crm`'de aynı lotun "Readiness" yüzdesini not et (demo: **%50**).
3. Intake kartında "Düzenle"ye bas, herhangi bir alanı değiştirme, doğrudan **Kaydet**'e bas.
4. `/tender/crm`'e dön, yenile, aynı lotun Readiness değerini tekrar oku.

**Beklenen (kod okumasından — KIRIK):**
- Adım 1: **4 satır görünür ama etiketleri BOŞtur.** Seed belgeleri
  `{"name": ..., "status": "ready"|"pending"}` şemasıyla yazıyor; ön yüz
  `{label, required, done, date}` bekliyor → `label` boş, `required`/`done` 0.
- Adım 3'ten sonra: `_clean_intake` etiketi boş olan her belgeyi **eler**
  (`if isinstance(d, dict) and str(d.get("label") or "").strip()`). Demo lotun 4 belgesi
  **kalıcı olarak silinir**.
- Adım 4: Readiness **%50 → %50** değil, `doc_progress` formülü belge listesi boşken
  `50` sabitini döndürdüğü için tesadüfen aynı kalır. Sourcing/priced dışındaki lotlarda
  fark görünür: `%100` olan bir submitted lot kaydedildikten sonra **`%50`'ye düşer**;
  `%25` olan bir seen lot **`%50`'ye çıkar**.

**Bu yüzden test 4314 (won, %100) üzerinde koşulmalı:** kaydetmeden önce %100,
kaydettikten sonra **%50**.

**Kırık belirtisi:** Herhangi bir lotun Readiness değerinin, hiçbir alan değiştirilmeden
yapılan bir kaydetmeden sonra değişmesi = veri kaybı. **BULGU-S11.**
**Kanıt:** `seed_tender_demo.py:134-139` (`{"name","status"}` şeması),
`tender.py:1415-1425` (`_clean_intake` belge normalizasyonu ve boş etiket süzgeci),
`tender.py:1478-1487` (`_docs_summary` — `required`/`done` bekliyor),
`tender.py:2387-2388` (`crm_board` doc_progress — `status == "ready"` bekliyor,
belge yoksa `50` sabiti), `TenderIntake.vue:65-69` (`label` eşlemesi).

---

### UAT-506 · "Teklif gönderildi" damgasını atma

**Adımlar:**
1. SPA'da `mark_tender_submitted`'ı tetikleyen bir düğme ara (intake ekranı, fiyatlama
   ekranı, CRM çekmecesi, PO kontrol).

**Beklenen (kabul kriteri):** Fiyat verildikten sonra "teklifi gönderdim" diyebilecek,
denetim izi bırakan bir eylem olmalı.
**Gerçek:** `mark_tender_submitted` **hiçbir SPA ekranından çağrılmıyor** (tüm
`public/js/` altında tek bir referans yok). Sourcing kullanıcısının elindeki tek yol
kartı `submitted` kulvarına sürüklemek — ki bu (UAT-206) denetim kapısını atlıyor ve
`submitted_by` bilgisini hiç yazmıyor, yalnız `submitted_at` damgalıyor.
**Kırık belirtisi:** Bu, backend'de var olan bir yeteneğin ön yüzde bağlanmamış olması.
**BULGU-S12.**
**Kanıt:** `tender.py:1649-1685` (`mark_tender_submitted`, sourcing'e AÇIK: satır 1652
`if not set(_tender_views()).intersection(("director", "sourcing"))`),
`tender.py:2502-2503` (sürükleme yolunun yazdığı tek alan `submitted_at`),
SPA genelinde `mark_tender_submitted` araması: 0 sonuç.

---

## 6. `/tender/po-control` — Sipariş takibi

### UAT-601 · Ekran ve sekmeler

**Ön koşul:** Sourcing kullanıcısı. **URL:** `/tender/po-control` (menüde görünür:
`v-if="can('sourcing')"`).

**Adımlar:**
1. Menüden "Tender PO control"a tıkla.
2. Deal seçmeden ekranın hâline bak.
3. Bir deal seç (UAT-402'deki Typeahead sorunu burada da geçerli — güvenli yol
   `/tender/my-tenders`'tan ya da `/tender/portfolio`'dan satıra tıklamak, ki ikisi de
   `openDeal` ile `?deal=` parametresi ekliyor).
4. Sekme şeridini oku.

**Beklenen:**
- Deal seçilmeden **hiçbir şey çizilmez** (`v-if="deal && workspace && data"`); yalnız
  başlık, iki düğme ve deal seçici kartı görünür. Boş durum mesajı bile yok.
- Deal seçilince: **3 sekme** (Overview · Vendor PO · Delivery) — Finance yok (UAT-501).
- İki API paralel çağrılır: `tender_workspace` ve `po_control_board`.

**Kırık belirtisi:** Deal seçilmeden ekranın tamamen boş kalması kullanıcıyı "sayfa
bozuk" sanmaya iter; `EmptyState` yok (karşılaştır `SourcingCompare.vue:152`, orada var).
**Kanıt:** `PoControlBoard.vue:80-97` (yükleme), `108-112` (sekmeler), `314` (koşul),
`TenderNav.vue:53-55`, `MyTenders.vue:92` / `DirectorBoard.vue:125` (`openDeal`).

---

### UAT-602 · PO kulvarları ve KPI'lar

**Ön koşul:** Seçili lota bağlı en az 4 Purchase Order olsun (`custom_crm_deal = <deal>`):
1 taslak, 1 onaylı-teslim alınmamış, 1 kısmi (%60), 1 tamamlanmış.
*(Demo seed hiç PO üretmiyor — bu veriyi elle kurmak gerekiyor.)*

**Adımlar:** "Vendor PO" sekmesini aç.

**Beklenen:**
- Dört kulvar: **Draft · To receive · Partially received · Completed**, her birinde
  sayı ve toplam tutar.
- Kart rozetleri: `draft` → sarı "Draft"; `partial:60` → sarı **"60% received"**;
  gecikmiş → kırmızı "Delayed"; tamamlanmış → yeşil "Received"; faturalanmış → mavi "Billed";
  en ucuz landed → **koyu yeşil "Cheapest (landed)"**.
- KPI şeridi: PO sayısı, toplam, teslim alınma %, tedarikçi sayısı.
- Üstte tedarikçi teklifi rozetleri: "5 quotes met" / "5 quotes needed" ve
  "2 countries met" / "2 countries needed".
- Bir PO kartına tıklamak `/purchasing/orders/<name>`'e gider.

**Kırık belirtisi:** `custom_crm_deal` alanı henüz migrate edilmemişse ekran **hata
vermez**, boş ama düzgün şekilli bir pano döner (0/0/0/0) — bu, "veri yok" ile "alan yok"u
birbirine karıştırır. Tester migrate durumunu ayrıca doğrulamalı.
**Kanıt:** `tender.py:465-497` (kulvar tanımı + migrate öncesi boş dönüş),
`tender.py:227-240` (`_po_lane`), `PoControlBoard.vue:118-127` (rozetler),
`PoControlBoard.vue:129` (`openPo`), `PoControlBoard.vue:322-335`.

---

### UAT-603 · Landed maliyet planı düzenleme (yazma yetkisi)

**Adımlar:**
1. Bir PO kartında landed düzenleme modalını aç.
2. Satır ekle: tür `customs`, ТН ВЭД kodu gir → oran çekilsin.
3. Kaydet.

**Beklenen:**
- `po_landed_charges` okur, `save_po_landed_charges` yazar.
- ТН ВЭД kodu girilince `hs_rate_lookup` çağrılır; tabloda varsa
  "from HS table · <tarih>" yazar ve tutar otomatik hesaplanır
  (`duty + excise + (KDV iade edilemiyorsa KDV)`); yoksa
  **"not in HS table — enter manually"**.
- Kaydedince yeşil bildirim "Landed plan saved." ve pano yeniden yüklenir.
- **Yetki:** yazma `_po_scope(po, write=True)` üzerinden Purchase Order **write** izni ister.
  Saf `Sales User`'ın Purchase Order üzerinde yazma izni normalde YOKTUR → beklenen sonuç
  **"Not permitted"** kırmızı bildirimi.

**Kırık belirtisi:** Sourcing kullanıcısının satın alma belgesinin maliyet planını
değiştirebilmesi — rol ayrımına aykırı. Bu, PO üzerindeki Frappe izinlerine bağlı;
UAT'ta fiilen denenmeli.
**Kanıt:** `PoControlBoard.vue:156-177` (okuma), `253-274` (kaydetme),
`229-247` (HS lookup), `192-205` (gümrük hesabı),
`tender.py:348-361` (`_po_scope`), `401-462` (`po_landed_charges` / `save_po_landed_charges`),
`tender.py:364-398` (`hs_rate_lookup`).

---

### UAT-604 · Bu ekranda gezinme çubuğu

**Beklenen:** `PoControlBoard.vue` de `TenderNav`'ı çizmiyor (import listesinde yok).
Yalnız iki düğme: "Contract board", "Sourcing comparison". `Esc` tuşu `/tender/board`'a
döndürüyor (`useEscapeBack(null, "/tender/board")`).
**Kanıt:** `PoControlBoard.vue:7-23`, `30`, `285-291`.

---

## 7. `/tender/my-tenders` — Kendi üzerimdekiler

### UAT-701 · Liste ve kapsam

**Ön koşul:** Sourcing kullanıcısı, demo veri yüklü.
**URL:** `/tender/my-tenders` (menüde `v-if="can('sourcing')"`).

**Adımlar:**
1. Menüden "My tenders"a tıkla.
2. Tabloyu oku: Tender / Landed / PO count / Delivery deadline / Risk.

**Beklenen (demo veriyle):**
- **Tablo BOŞ.** `EmptyState`: "No tenders match these filters."
- Neden: `sourcing_my_tenders` oversight olmayan kullanıcıda
  `if not oversight and (intake.get("assigned_to") or "") != me: continue` diyor.
  Demo seed hiçbir lota `intake["assigned_to"]` yazmıyor → **13 lotun 13'ü elenir**.

**Ek doğrulama (atama sonrası):**
3. Administrator/Direktör ile `/tender/portfolio` → satırdaki atama seçicisinden
   UTY-2026-4308'i `sourcing@mikas.uz`'a ata.
4. Sourcing kullanıcısıyla `/tender/my-tenders`'ı yenile.

**Beklenen:** **Tam 1 satır** görünür.
- Tender = "Signal va aloqa boshqarmasi [DEMO]" (organizasyon adı — lot no yine yok)
- Landed = `0`, PO count = `0` (seed PO üretmiyor)
- Delivery deadline = bugün + 90 gün
- Risk = sarı **"Deadline near"** (teklif son tarihi bugün → `_milestone` `days = 0` → `warn`)

**Kırık belirtisi:** Atamadan sonra hâlâ boş kalması; ya da atama YAPILMADAN 13 satırın
görünmesi (kapsam sızıntısı — kullanıcıya fazladan oversight rolü verilmiş demektir).
**Kanıt:** `tender.py:2124-2166` (`sourcing_my_tenders`), `2136` (kapsam süzgeci),
`2166` (`{"currency", "rows", "oversight"}`), `MyTenders.vue:30-40`, `100-118`,
`tender.py:1517-1545` (`_milestone` risk eşikleri: geçmiş→risk, ≤7 gün→warn),
`seed_tender_demo.py:76-85` (`DEADLINE_OFFSETS`, 4308 → 0).

**Not — iki farklı "atama" kaynağı:** `/tender/my-tenders` intake JSON'undaki
`assigned_to`'ya bakıyor; `/tender/desk` CRM Deal'in `assigned_to` **sütununa**.
Aynı kullanıcı için iki ekran farklı liste gösterir. Bkz. UAT-102 ve **BULGU-S1**.

---

### UAT-702 · Huni aşaması süzgeci

**URL:** `/tender/my-tenders?funnel_stage=sourcing`

**Adımlar:**
1. Yukarıdaki URL'yi aç (normalde panodaki bir sayıya tıklayarak gelinir).

**Beklenen:**
- Üstte filtre özeti: **"Stage: Collecting quotations"** + "Clear filters" düğmesi.
- `tender_funnel` çağrılır, o aşamadaki deal adları bir `Set`'e alınır ve liste kesişime
  indirilir. Kendi lotlarının yalnız `sourcing` aşamasında olanları kalır.
- `tender_funnel` çağrısı hata verirse süzgeç **sessizce devre dışı kalır**
  (`funnelDeals = null` → "hepsini göster"), liste boşalmaz.

**Kırık belirtisi:** Süzgeç uygulandığında listenin tamamen boşalması ve özet şeridinin de
kaybolması.
**Kanıt:** `MyTenders.vue:52-72`, `82-88`, `74-81`.

**Yan not (yetki):** `tender_funnel` yalnız `_require_tender(company)` ile korunuyor —
sourcing kullanıcısı bu uç noktayı çağırabiliyor ve **tüm şirketin** aşama dağılımını
alıyor (`tender.py:2183-2184`). Burada bu, süzgecin çalışması için gerekli; ama aynı
gevşeklik UAT-802'de sorun yaratıyor.

---

## YETKİ BULGULARI

Üç ayrı katman ayrı ayrı test edildi: **(1) menüde görünüyor mu · (2) URL elle yazılırsa
sayfa açılıyor mu · (3) backend ne dönüyor.** Sonuçlar:

| Yol | Menü (TenderNav) | Router guard | Backend | Net sonuç |
|---|---|---|---|---|
| `/tender/portfolio` (DirectorBoard) | ❌ gizli (`can('director')`) | ✅ geçirir | ⚠️ **karışık** | **KISMEN AÇIK** |
| `/tender/flow` (TenderFlow) | ❌ gizli (`can('director')`) | ✅ geçirir | ❌ **kapı yok** | **TAMAMEN AÇIK** |
| `/tender/desk?view=director` | — | ✅ geçirir | ✅ 403 | KAPALI (doğru) |

**Router'da rol penceresi kontrolü hiç yok.** `router.beforeEach` yalnız
`meta.module === "tender"` bakıyor; `director` / `sourcing` ayrımı guard'a hiç girmiyor.
— `router.js:612-635`, `router.js:265-276` (tüm tender rotalarının meta'sı aynı).

---

### BULGU-Y1 · `/tender/flow` sourcing kullanıcısına tamamen açık (YÜKSEK)

**UAT-801**

**Ön koşul:** Sourcing kullanıcısı, Mikas, demo veri yüklü.
**Adımlar:**
1. Tender gezinme çubuğunda "Process flow" bağlantısını ara → **yok**
   (`v-if="can('director')"`).
2. Adres çubuğuna `#/tender/flow` yaz, Enter.

**Beklenen (kabul kriteri):** Boş sayfa + "Not permitted", ya da yönlendirme.
**Gerçek davranış:** **Ekran tam çalışır hâlde açılır ve tüm şirketin süreç verisini gösterir.**
`tender_flow` yalnız `_require_tender(company)` + `_assert_company_scope` + `_require_company`
taşıyor; `_require_tender_view("director", company)` **çağrılmıyor**.

**Demo veriyle görülecek somut değerler (seed günü itibarıyla):**

| Adım | Açık | Ort. gün | Eşik | Durum |
|---|---|---|---|---|
| Intake — file opened | 2 | 2,0 | 3 | **At the edge** |
| GO / NO-GO decision | 2 | 4,5 | 5 | **At the edge** |
| **Quotation gathering** | **2** | **22,5** | **14** | **Over SLA** |
| Bid pricing | 2 | 7,0 | 3 | **Over SLA** |
| Bid submitted | 2 | — | 30 | **Not measurable** |

- "In process" = **10**, "Not measurable" = **2**.
- **Darboğaz (kırmızı çerçeveli düğüm) = "Bid pricing"**, sourcing değil — çünkü
  `bottleneck()` farkı değil **oranı** kullanıyor: priced 7,0/3 = **2,33**;
  sourcing 22,5/14 = **1,61**.

**Kırık belirtisi:** Ekranın açılması ve yukarıdaki tablonun dolu gelmesi.
**Kanıt:** `tender.py:3003-3018` (kapılar — view kontrolü yok; karşılaştır
`tender.py:1989` (`tender_director_board` → `_require_tender_view("director", ...)`) ve
`tender.py:2023`, `2066`, `2126`), `TenderNav.vue:40-42` (menüde gizli),
`router.js:267` + `612-635` (guard geçirir), `TenderFlow.vue:33-43`,
`_tender_flow.py:24-93`, `_tender_sla.py:30-38`,
`seed_tender_demo.py:51-71` (19/26/8/6 gün değerleri).

---

### BULGU-Y2 · `/tender/portfolio` yarı açık — huni paneli veri sızdırıyor (ORTA-YÜKSEK)

**UAT-802**

**Ön koşul:** Sourcing kullanıcısı.
**Adımlar:**
1. Menüde "Director board" bağlantısını ara → **yok** (`v-if="can('director')"`).
2. Adres çubuğuna `#/tender/portfolio` yaz, Enter.
3. Sayfanın ÜST yarısını ve ALT yarısını ayrı ayrı incele.

**Beklenen (kabul kriteri):** Sayfa hiç açılmamalı, ya da tamamen boş kalmalı.

**Gerçek davranış — üç farklı sonuç aynı sayfada:**

| Bölüm | Çağrı | Kapı | Sonuç |
|---|---|---|---|
| 6'lı KPI şeridi + "Linked ERP documents" tablosu | `tender_director_board` | `_require_tender_view("director")` | ❌ **403** → kırmızı bildirim "Could not load the director board.", KPI'lar `0`/`0%`, tablo `0 / 0 tenders` |
| Atama seçicileri | `tender_managers` | `_require_tender_view("director")` | ❌ 403 → **sessizce yutulur** (`catch { }`), seçici boş |
| **`<TenderFunnel />` paneli** | `tender_funnel` | yalnız `_require_tender` | ✅ **VERİ GELİR** |

Yani sourcing kullanıcısı `/tender/portfolio`'yu elle yazarak **tüm şirketin huni panelini**
görüyor: aşama kutuları (Under review 2 · GO 2 · Collecting quotations 2 · Priced 2 ·
Bid submitted 2 · Won 2 · Lost 1), kazanma oranı **`66.7%`** (2 kazanılan / 3 sonuçlanan),
açık hat **10**, "Risk 1", "{n} below policy" rozeti ve her kutunun altındaki kural metni.
Bunların hiçbiri kendi lotlarıyla sınırlı değil.

**Kırık belirtisi:** Huni panelinde sıfırdan farklı sayıların görünmesi.
**Kanıt:** `tender.py:2183-2184` (`tender_funnel` — view kapısı YOK) vs
`tender.py:1989` (`tender_director_board` — var) ve `tender.py:1764` (`tender_managers` — var);
`DirectorBoard.vue:40-47` (hata → toast), `48-53` (`catch { }` sessiz),
`DirectorBoard.vue:164` (`<TenderFunnel />` — kendi çağrısını yapıyor),
`TenderFunnel.vue:40-52`, `TenderNav.vue:44-46`, `router.js:273`.

**Not:** Aynı `tender_funnel` gevşekliği `MyTenders.vue:66`'da da kullanılıyor — orada
işlevsel olarak gerekli (huni süzgeci). Yani kapıyı sıkılaştırmak `/tender/my-tenders`
süzgecini de etkiler; düzeltme bunu hesaba katmalı.

---

### BULGU-Y3 · Sourcing kullanıcısı ihale sonucunu tek başına ilan edebiliyor (YÜKSEK)

Ayrıntı ve adımlar: **UAT-206**.

`move_deal_stage` hiçbir rol penceresi kapısı taşımıyor ve aşamalar arası geçiş kuralı yok.
Kartı `won`/`lost` kulvarına bırakmak `intake["result"]`'ı yazıyor; `go` kulvarına bırakmak
`intake["go_no_go"] = "go"` yazıyor; `submitted` kulvarına bırakmak `submitted_at` damgalıyor.
Bunların üçü de normalde ayrı denetim yolları olan kararlar
(`set_tender_go_no_go_from_trusted_source`, `mark_tender_submitted`).
**Kanıt:** `tender.py:2451-2460`, `2495-2504`, `1649-1653`, `1688-1690`, `1403-1413`.

---

### BULGU-Y4 · Masa, satır izinlerini atlayarak finansal veri gösteriyor (ORTA)

Ayrıntı ve adımlar: **UAT-103**.
`tender_desk.operations_desk` beş yerde `frappe.get_all` kullanıyor (izin denetimsiz) ve
sourcing için konan atama süzgeci bu listelere uygulanmıyor. Sonuç: saf `Sales User`,
şirketin gecikmiş satın alma siparişlerini ve **ödenmemiş alış faturalarının kalan
tutarlarını** metin içinde görüyor.
**Kanıt:** `tender_desk.py:66`, `98`, `125`, `146`, `165` (`get_all`);
`tender_desk.py:89-91` (süzgecin kapsamı); `_desk_rules.py:171`, `195`, `198` (tutar metni).

---

### BULGU-Y5 · Karar kutusu yanlış koşulla dolduruluyor (ORTA)

Ayrıntı ve adımlar: **UAT-104**.
`or a.get("requested_by") != user` koşulu, kullanıcıya atanmamış her onayı karar kutusuna
sokuyor ve "Awaiting my approval" sayacını şişiriyor.
**Kanıt:** `tender_desk.py:225-228`.

---

### Yetki açısından DOĞRU çalışan kapılar (regresyon için kayıt)

Bunlar da test edilmeli, çünkü düzeltme sırasında bozulabilirler:

| Uç nokta | Kapı | Sourcing sonucu |
|---|---|---|
| `tender_director_board` | `_require_tender_view("director")` — `tender.py:1989` | 403 ✅ |
| `tender_managers` | `_require_tender_view("director")` — `tender.py:1764` | 403 ✅ |
| `assign_tender` | `_is_tender_oversight()` — `tender.py:1789` | 403 ✅ |
| `declarant_queue` | `_require_tender_view("declarant")` — `tender.py:2023` | 403 ✅ |
| `logist_board` | `_require_tender_view("logist")` — `tender.py:2066` | 403 ✅ |
| `sourcing_my_tenders` | `_require_tender_view("sourcing")` + atama süzgeci — `2126`, `2136` | Kendi lotları ✅ |
| `operations_desk?view=director` | `_require_tender_view(view)` — `tender_desk.py:42` | 403 ✅ |
| `tender_workspace` → finance bloğu | `_can_view_tender_finance()` — `tender.py:955`, `2574-2576` | Blok yok ✅ |
| `tender_dashboard` | `acquisition_scope = "assigned"` — `tender.py:2690`, `2711-2712` | Kendi lotları ✅ |

---

## Sourcing'in yapamadıkları

Kabul testinde "eksik" olarak kaydedilmesi gereken, kodda karşılığı OLMAYAN şeyler:

1. **Tedarikçiden fiyat isteyemez / gelen fiyatı sisteme giremez.**
   SPA'da Supplier Quotation yaratan hiçbir ekran, rota ya da düğme yok. `/tender/sourcing`
   ekranının boş durum metni bunu açıkça söylüyor: "Tag Supplier Quotations to this deal
   to compare them here." Tek yol Frappe desk (`/app/supplier-quotation`) ve `custom_crm_deal`
   alanını elle doldurmak.
   *Kanıt:* `SourcingCompare.vue:143-148`, `router.js:326-343` (Purchasing rotalarında
   quotation yok), SPA genelinde Supplier Quotation yaratan kod: 0.

2. **RFQ (Request for Quotation) kavramı hiç yok.** Ne backend uç noktası, ne ekran,
   ne veri alanı. *Kanıt:* tüm pakette `rfq` / `Request for Quotation` araması: 0 sonuç.

3. **Lotu kendine atayamaz.** `assign_tender` `_is_tender_oversight()` istiyor; ayrıca
   ön yüzde yalnız DirectorBoard'dan çağrılıyor. Sourcing kullanıcısı iş dağıtımını
   bekler durumda. *Kanıt:* `tender.py:1786-1789`, `DirectorBoard.vue:54-63`.

4. **"Teklifi gönderdim" damgasını denetim iziyle atamaz.** `mark_tender_submitted`
   sourcing'e açık ama hiçbir ekrandan çağrılmıyor; elde kalan tek yol kartı sürüklemek,
   o da `submitted_by` yazmıyor. *Kanıt:* `tender.py:1649-1685`; SPA'da referans: 0;
   `tender.py:2502-2503`.

5. **Süreç akışını (SLA aşımını) kendi ekranlarında göremez.** Aşama başına bekleme ve
   14 günlük eşik matematiği yalnız `tender_flow` uç noktasında ve yalnız
   `/tender/flow` ekranında var; o ekran menüde director'a kapalı. Sourcing'in menüde
   gördüğü hiçbir ekran (`desk`, `crm`, `my-tenders`, `po-control`, `board`)
   "bu lot kaç gündür bu aşamada" sorusunu cevaplamıyor.
   *Kanıt:* `_tender_sla.py:30-38`, `_tender_flow.py:21-53`, `tender.py:3003+`;
   `crm_board` kart yükünde aşama yaşı alanı yok (`tender.py:2390-2408`);
   `_desk_rules.py`'de aşama SLA kuralı yok (kurallar: bid_due, bid_soon, policy_gap,
   no_parent, won_no_po, po_late, invoice_due, approval_pending).

6. **Finans zincirini göremez** (`tender_workspace` → `finance`). Bu kasıtlı bir sınır,
   eksik değil — ama UAT'ta "Finance sekmesi yok" diye kaydedilmeli.
   *Kanıt:* `tender.py:955-963`, `2574-2576`, `PoControlBoard.vue:108-112`.

7. **Direktör panosunu ve atama ekranını göremez** (menüde yok, backend 403) — kasıtlı.
   Ama huni paneli sızıyor (BULGU-Y2).

8. **Lot numarasıyla arama yapamaz.** Ne CRM kanban araması (`organization`/`name`/
   `lead_name` alanları), ne deal Typeahead'i (`organization`/`email`/`lead_name`)
   `lot_no`'ya bakıyor. Lot numarası yalnız intake JSON'unda yaşıyor.
   *Kanıt:* `TenderCrm.vue:70-79`, `crm.py:322`, `seed_tender_demo.py:129`.

9. **Demo veri bu rolü test etmeye elverişli değil.** Seed hiç Supplier Quotation,
   hiç Purchase Order, hiç Sales Order üretmiyor ve hiçbir lotu bir kullanıcıya atamıyor.
   Sonuç: sourcing kullanıcısının **üç ekranı birden boş** — `/tender/desk` (0 kalem),
   `/tender/my-tenders` (0 satır), `/tender/po-control` (0 PO) — ve teklif ölçerleri
   `0/5`. *Kanıt:* `seed_tender_demo.py:178-202` (yalnız CRM Deal + CRM Organization +
   CRM Stage Event üretiliyor).

---

## Bulgu özeti (öncelik sırasıyla)

| # | Bulgu | Şiddet | Ana kanıt |
|---|---|---|---|
| **Y1** | `/tender/flow` sourcing'e tamamen açık — backend'de view kapısı yok | Yüksek | `tender.py:3015-3017` |
| **Y3** | `move_deal_stage` rol/geçiş kuralı taşımıyor; sourcing won/lost/go/submitted yazabiliyor | Yüksek | `tender.py:2451-2504` |
| **S6** | Supplier Quotation üretme akışı SPA'da hiç yok — rolün ana işi yapılamıyor | Yüksek | `SourcingCompare.vue:143-148` |
| **Y2** | `/tender/portfolio` yarı açık; `TenderFunnel` şirket geneli veri sızdırıyor | Orta-Yüksek | `tender.py:2183` + `DirectorBoard.vue:164` |
| **S11** | Intake kaydı demo belgelerini siliyor (şema uyuşmazlığı) | Orta-Yüksek | `tender.py:1415-1425` vs `seed:134-139` |
| **S1** | "Atama" iki farklı yerde tutuluyor; desk ile my-tenders çelişiyor | Orta | `tender_desk.py:79` vs `tender.py:2136` |
| **Y4** | Masa `get_all` ile satır izinlerini atlıyor; PI kalan tutarları görünüyor | Orta | `tender_desk.py:146,165` |
| **Y5** | Karar kutusu koşulu yanlış (`requested_by != user`) | Orta | `tender_desk.py:225-228` |
| **S10** | Deal Typeahead'i `company` göndermiyor; lot no ile arama yok | Orta | `SourcingCompare.vue:27`, `crm.py:283` |
| **S4** | Seed hiç Supplier Quotation/PO üretmiyor → ölçerler `0/5`, ekranlar boş | Orta | `seed_tender_demo.py:122-151,178-202` |
| **S12** | `mark_tender_submitted` ön yüze hiç bağlanmamış | Orta | `tender.py:1649` + SPA'da 0 referans |
| **S8** | CRM "Pipeline / open deals" KPI'sı won+lost'u da sayıyor (13 yerine 10 olmalı) | Düşük-Orta | `TenderCrm.vue:105-114` |
| **S7** | Kartlarda lot no yok; 4 kart aynı başlıklı | Düşük-Orta | `tender.py:1850`, `2390-2408` |
| **S9** | `desk`, `sourcing`, `po-control` ekranlarında `TenderNav` yok; `/tender/sourcing` menüde hiç yok | Düşük | `TenderNav.vue:37-61` |
| **S5** | (Y3 ile aynı kök) `submitted` kulvarı `submitted_by` yazmıyor | Düşük | `tender.py:2502-2503` |

---

## Doğrulanamayan noktalar (canlı sitede koşulmalı)

Bu üç şeyin gövdesi incelenen pakette yok; yalnız çağrıldıkları kanıtlandı:

1. **`_assert_company_scope`** → `stabler/api/approvals.py` (dosya pakette yok).
   Şirket sınırı testleri (UAT-207) fiilen koşulmalı.
2. **`stabler.api.purchasing.tender_quotations`** → `stabler/api/purchasing.py` (yok).
   `/tender/sourcing`'in tüm çıktısı ve yetki kapısı buradan geliyor (UAT-403).
3. **`_can_access_module` / modül haritası** → `stabler/api/organization.py` (yok).
   `Sales User`'ın `crm` modülüne erişip erişmediği (UAT-402'nin (a)/(b) dallanması)
   buradan belli oluyor.
