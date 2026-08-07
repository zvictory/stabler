# Tender Document Vault — v1 (mikas pilot)

## Karar özeti (araştırma sonucu)

**Hazır file manager var mı?** En güçlü aday **VueFinder** (596★, dün release 4.7.3, MIT, aktif). Ama mimari gerilim var: VueFinder **dosya-sistemi ağacı** modeliyle (dir/basename/`storage://yol`, klasör gezinme) tasarlanmış; senin ihtiyacın ise **yapısal uyumluluk kaseti** (Shartnoma slot, Protokol slot, ГТД slot — her biri `required` ile). Ayrıca Uppy+CodeMirror 6+Papa Parse bağımlılıkları tender belgeleri (çoğunlukla PDF/image) için ölü ağırlık, ve Frappe File doctype için özel `BaseAdapter` subclass yazmak (~200 satır) gerekir.

**v1 kararı:** VueFinder'ı şimdilik **kullanma** — mevcut `/api/method/upload_file` pattern'ini (`sfa/Photos.vue:118-144`) yeniden kullanan hafif `FileSlot`/`FileList` bileşenleri yaz. VueFinder **escalation path** olarak belgelensin (v2, belge hacmi gerçekten hak ederse). Bu, sıfır yeni dependency, mevcut kodla uyumlu, checklist-binding'i mükemmel korur.

**Kapsam:** tender-only, mikas pilot. Scope verilen cevap: "1 tender only pilot yaparız" — uygulanır.
**Veri modeli:** JSON genişlet (`custom_tender_intake.documents[]`'a file meta ekle). Backward-compatible.

---

## Tasarım kararları

### D1 — `done` vs `file_url` ilişkisi (önerilen: yumuşak geçiş)
İki kavram ayrı kalsın:
- **`file_url`** (yeni): o belge slot'una eklenen dosya. Boş ise "ekle" dropzone'u göster.
- **`done`** (mevcut): süreçsel tamamlandı bayrağı.

**Required-gate (`current_ready`, `_docs_summary`)** artık `file_url` varlığına da baksın: required slot "satisfied" sayılsın eğer `done` **VEYA** `file_url` mevcut. Bu, backward-compat'i korur (eski `done=1` & file yok kayıtlar bozulmaz) ve aynı zamanda "kutu işaretli ama dosya yok" yanıltıcı durumunu yumuşatır — UI `file_url`'i gösterdiği için eksik göze çarpar. Gelecekte (v2) `done` tamamen kaldırılıp file-driven olabilir.

### D2 — Dosya depolama
Standart Frappe `File` doctype, `CRM Deal`'e attach. Upload sırasında `attached_to_doctype="CRM Deal"`, `attached_to_name=<deal>` parametreleri (Frappe `upload_file` destekler). `is_private=1` (tender belgeleri fiyat/müşteri içerir — bid package'da zaten böyle, `tender.py:1273`). Böylece File hem intake JSON'unda referanslanır hem de doğrudan Deal'e linklenir (service tickets pattern'i gibi sorgulanabilir).

### D3 — `key` (stabil slot id)
Mevcut `documents[]` index-bazlı. File meta'yı doğru slot'a bağlamak için stabil `key` gerek (seed sırasında slug: `shartnoma`, `gtd`, vb.). Seed fonksiyonu bunu üretir; manuel eklenen satırlara `doc-<n>` veya `crypto.randomUUID()` kısa hali. Backward-compat: key yoksa label'dan slug türet (geçici).

---

## Uygulama adımları

### Adım 1 — Backend: intake documents[] şemasını genişlet
**Dosya:** `stabler/api/tender.py`, `_clean_intake` (~`:1415-1424`)

`documents[]` item normalizasyonuna ekle:
```python
{
  "key": str(d.get("key") or "").strip()[:60] or _slug(d.get("label")),
  "label": str(d.get("label") or "").strip()[:140],
  "required": 1 if d.get("required") else 0,
  "done": 1 if d.get("done") else 0,
  "date": str(d.get("date") or "").strip()[:20],
  # YENİ — file meta:
  "file_url": str(d.get("file_url") or "").strip()[:500],
  "file_name": str(d.get("file_name") or "").strip()[:255],
  "file_size": _num(d.get("file_size")) or 0,
  "attached_by": str(prior_doc.get("attached_by") or "")[:140],  # server-owned
  "attached_at": str(prior_doc.get("attached_at") or "")[:40],   # server-owned
}
```
`attached_by/at` server-owned (client'tan kabul etme, prior'dan koru — go_no_go audit pattern'i gibi `:1388-1400`). `_slug` helper ekle (cyrillic + latin destekli basit slugify).

`_docs_summary`'ı (`:1478`) güncelle: `done_required` → `satisfied_required` = `sum(1 for d in req if d.get("done") or d.get("file_url"))`. `missing` = `required && !(done or file_url)`.

`current_ready` (`:1428`) aynı yumuşak mantıkla güncellensin.

### Adım 2 — Backend: whitelist endpoint'ler
**Dosya:** `stabler/api/tender.py` (veya önce `.pyc`'den `_tender_documents.py`'ı kurtarıp oraya — aşağıda Adım 0).

Yeni whitelist fonksiyonlar:
- `attach_tender_document(deal, key, file_url, file_name, file_size)` — intake'i oku, `key`'e uyan slot'a file meta yaz + `attached_by=session.user`, `attached_at=now()`, kaydet. Slot yoksa hata. Transaction-safe (lock deal).
- `remove_tender_document(deal, key, delete_file=False)` — intake'ten file meta'yı temizle. `delete_file=True` ise ilgili `File` doc'u `frappe.delete_doc("File", ...)` ile sil (opsiyonel, default False — dosya kalır, sadece link kalkar).
- `list_tender_documents(deal)` — intake documents[] + `frappe.get_all("File", filters={attached_to_doctype:"CRM Deal", attached_to_name:deal})` birleştirip döndür (Documents tab'ı için).

Permission: `permission_query_conditions` company-scoping (`hooks.py:37`) zaten var; bu endpoint'ler de aynı `custom_parent_tender`/deal company kontrolü yapsın.

### Adım 3 — Frontend: `FileSlot.vue` bileşeni
**Yeni dosya:** `stabler/public/js/components/files/FileSlot.vue`

Tek bir belge slot'u için; props: `fileUrl, fileName, fileSize, uploading, disabled`; emits: `attach(file)`, `remove()`. Drag-drop + click + paste. Upload kendisi yapmaz (parent'ın `attach` handler'ı yapar) — bileşen sadece dropzone UI + mevcut dosya chip'i (isim, boyut, indir/sil ikonları). Mevcut `sfa/Photos.vue:118-144` upload mantığını parent'ta yeniden kullan. Tabler stilleri, `ti-paperclip`/`ti-download`/`ti-trash` ikonları, `font-monospace` boyut.

### Adım 4 — Frontend: `TenderIntake.vue` entegrasyon
**Dosya:** `stabler/public/js/pages/tender/TenderIntake.vue`

- Document tablosuna (`:239-256`) yeni **"File" sütunu** ekle. Her satırda `<FileSlot>` — `attach` eventi → `onAttachDoc(i, file)` → `/api/method/upload_file` (Photos.vue pattern) → `attach_tender_document(deal, key, file_url, ...)` → intake reactive güncelle.
- `apply()` (`:66-68`) file meta'yı da map'lesin.
- Badge `done/required` (`:144-146`) artık `satisfied/required` olarak güncellenmiş `docs`'tan gelsin.
- `seedDocs()` (`:92-95`) artık `key` de üretsin (slug).

### Adım 5 — Frontend: `FileList.vue` + Documents tab'ı (file-manager hissi)
**Yeni dosya:** `stabler/public/js/components/files/FileList.vue` — grid/list view, PDF (`<iframe>`) / image lightbox preview, sıralama, "eksik zorunlu" filtresi, download/delete. Hafif, VueFinder'sız.

**Dosya:** `stabler/public/js/pages/tender/TenderWorkspaceTabs.vue` (`:14-19`) — tabs'a `{ key: "documents", label: t("Documents"), icon: "ti-files" }` ekle.

**Dosya:** `stabler/public/js/pages/tender/PoControlBoard.vue` — `documents` tab'ı render ettiğinde `list_tender_documents(deal)` çağırıp `<FileList>` bağla.

### Adım 6 — i18n + test
- **Çeviriler:** `stabler/translations/{en,ru,tr,uz,uzc}.csv` — yeni string'ler ("Attach", "Drag & drop or click", "No file", "Missing required", "Documents", "File size", "Remove file").
- **Test:** `stabler/tests/test_tender_documents.py` (yeni) — `_clean_intake` file meta normalizasyonu, `attach_tender_document`/`remove_tender_document` happy path + permission + audit (`attached_by/at`), backward-compat (key yoksa slug). Mevcut `test_tender_*.py` pattern'ini izle.
- Manuel smoke: mikas tenant'ta bir deal aç, ГТД slot'una PDF ekle, preview göster, sil, badge güncellensin.

---

## Önceden yapılması gereken (Adım 0 — kritik)
`stabler/api/_tender_documents.py` **sadece `.pyc` olarak var** (worktree'de yazıldı, main'e commitlenmedi). Endpoint'leri sıfırdan yazmadan **önce kaynak kurtarılmalı** — `.worktrees/crm-tender-to-cash` ve `.worktrees/tender-ops-foundation` dizinlerinde olabilir, veya `.pyc` decompile ile. Eğer kurtarılırsa Adım 2 oraya gider; aksi halde `tender.py`'a eklenir. Bu, çift iş + geçmiş planla (`crm-tender-to-cash.md` Task 5) çelişme riskini önler.

## Açık riskler (build sırasında karar)
1. **Mobil/declarant akışı** — gümrükçü yolda belge tarıyor. v1 desktop upload; mobil capture v1.5. UI responsive olsun ama kamera akışı yok.
2. **Versiyonlama** — v1 latest-only, üzerine yazınca uyarı. Versiyonlama v2.
3. **Retention** — lot kapandıktan saklama politikası ayrı bir konu (v1'de silme manuel).

## Out of scope (v1)
Generic app-wide file manager, OCR/full-text search, klasör etiketleri, VueFinder entegrasyonu, mobil kamera capture, çoklu sürüm.