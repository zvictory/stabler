# MSA PI/CI sandbox envanteri — ne var, ne portlandı, ne kaldı

**Kaynak:** `~/msa-sandbox` — bugün (28.07) kurulmuş yerel Vue 3 + Python
prototipi. Amacı ürün değil **kanıt**: gerçek Excel'e (`MSA tegma obshiy.xlsx`,
6 223 CI satırı) karşı PI ↔ CI eşleme anahtarını doğrulamak ve UX'i Stabler'a
taşımadan önce oturtmak. Prod'a bağlantısı yok; Stabler repo dışında yaşıyor.

---

## 1 · Sandbox'ın kanıtladığı 5 kural (asıl değer)

1. **Eşleme anahtarı kategori/ürün adıdır, Article değil.** PI satırı kompanse
   paket (`CM60/40 = BUFFALO COMPENSATED`), CI onu alt-kesimlere bölüp sevk
   eder. Article ile eşleşme %19,5; ürün adıyla **%98,3** (6 119/6 223).
2. **Anahtar normalizasyonu zorunlu** (`WHOLE LEG` ≡ `Whole leg`): ham metin
   eşleşmesi 40 hayalet "hiçbir PI'da yok" satırı üretiyor. Ham metin ekranda
   korunur, sadece anahtar normalize edilir.
3. **Fiyatlar 4 haneye yuvarlanarak karşılaştırılır** — ham float eşitliği 273
   sahte fark üretir (IEEE-754 kalıntısı).
4. **Agreed price ≠ Docs price** — iki ayrı ticari değer; hiçbiri diğerinden
   türetilmez, çoklu adaylar açıkça listelenir, hiçbir aday sessizce seçilmez.
5. **Hiçbir şey sessizce düzeltilmez:** over-shipment `max(0,…)` ile yutulmaz
   (kendi kolonunda), PI'sız CI satırı bakiyeden düşülmez (`unattributable`).

## 2 · Sandbox'taki özellik yüzeyi

| Alan | İçerik |
|---|---|
| Sayfalar | `#/pis` (sevk %, kalan, **over-shipment ayrı kolon**, çoklu seçim + seçili metrikler), `#/pis/new`, `#/pis/deleted` (soft-delete + geri alma), `#/pis/compare` (seçili PI'ların normalize ürün-düzeyi kıyası), `#/pis/:pi` (satır CRUD, agreed/docs ayrı, discrepancy paneli, bağlı CI'lar, alt-kesim dökümü), `#/cis`, `#/cis/:ci` (konteyner+kalem açılımı, fiyat aday çözümü) |
| Paylaşımlı durum | `/api/pi-groups` + `/api/pi-overrides` — **versiyon kontrollü** (bayat istemci 409 alır), atomik dosya persist |
| Saf çekirdek | `lib/match.js` (eşleme matematiği) + `lib/prices.js` (4-hane aday çözümü) |
| Kalite | `verify_match.mjs`: Python↔JS eşitliği 33 kontrol **geçiyor**; Python testleri 25 OK |

## 3 · Stabler'a portlanma durumu

### ✅ Portlanmış (bugünkü `8dd1cc2` + `e62647b` commit'leri)

- Çekirdek matematik `_imports_rules.py`'de birebir: `norm_key`, `match_key`,
  `contract_index`, `over_shipped`, `unattributable`, agreed/docs fiyat setleri,
  `_round4`. Beş kural dosya başındaki yorumda gerekçeleriyle belgeli.
- Stabler bir adım **öteye geçmiş**: yarım-sent toleransı (`PRICE_TOLERANCE`) —
  canlı defterde PI 3 hane (4.865) / CI 2 hane (4.86) yazınca 4-hane eşitliğinin
  ürettiği 1 067 sahte farkı da çözüyor. Ve: "boş kategori anahtar değil, delik"
  kuralı (sandbox README'sinde yok, Stabler'da var).
- `get_ci_pi_discrepancies` ucu + CommercialInvoiceForm'da discrepancy kullanımı.

### 🟡 Henüz portlanmamış (UX katmanı — sandbox'ın "settle the UX" kısmı)

| Sandbox özelliği | Stabler'da durum |
|---|---|
| PI listesinde **sevk % / kalan / over-shipment ayrı kolon** | Yok (`ProformaInvoices.vue`'da 0 iz) |
| `#/pis/compare` — çoklu PI normalize kıyas ekranı | Yok |
| Soft-delete + `#/pis/deleted` denetim/geri alma | Yok (Frappe'de iptal var ama bu UX değil) |
| PI formunda discrepancy paneli + alt-kesim dökümü | Kısmi (discrepancy CI formunda var, PI formunda yok) |
| Agreed/docs **çoklu aday** çözümünün UI'da açık gösterimi | Kısmi (backend sette tutuyor; UI aday listelemiyor) |
| Seçim + seçili-metrikler (çoklu satır toplamları) | Yok |

### 🔴 Sandbox'ın kendi içindeki kusur (bilgi — dokunulmadı)

`lib/data.js:30` modül seviyesinde `localStorage` okuyor → Node'da 3 test
dosyası (`ci-amounts`, `compare`, `pi-amounts`) import aşamasında ölüyor.
Bugün 16:03 düzenlemesiyle girmiş; sandbox aktif başka bir oturumun çalışma
alanı olduğu için düzeltilmedi, sadece raporlandı. (Düzeltme tek satır:
storage erişimini fonksiyon içine alıp `typeof localStorage` guard'ı.)

## 4 · Öneri — port sırası

1. **PI listesi kolonları** (sevk %, kalan, over-shipment ayrı ve kırmızı) —
   matematik hazır, sadece `contract_index`/match çıktısını listeye bağlamak.
   En yüksek görünür değer, ~yarım gün.
2. **PI formu discrepancy paneli + alt-kesim dökümü** — `get_ci_pi_discrepancies`
   zaten var, PI perspektifinden çağırıp panellemek.
3. **PI compare ekranı** — sandbox'taki `lib/compare.js` mantığı porta hazır.
4. Soft-delete UX'i ve aday-fiyat listesi UI'ı — değerli ama acil değil;
   sandbox'taki sürüm-kontrollü override deseni Stabler'da gereksiz (Frappe
   versiyonlama + submit akışı bu işi görüyor).

*İnceleme: 2026-07-28 · sandbox testleri: JS 9/12 dosya yeşil (3'ü localStorage
kusuru), Python 25/25, verify_match 33/33.*
