# Antigravity devir: mikas Belge Merkezi (`feat/mikas-belge-merkezi`)

> Bu dosya bir **iş emri**dir, arka plan bilgisi değil. Kurallar
> `docs/runbooks/parallel-development.md`'de; burada yalnız bu dalın kapsamı var.

## Kurulum

| | |
|---|---|
| Dal | `feat/mikas-belge-merkezi` (ana klasörde checkout, bench önizlemesi bu ağaçtan servis ediliyor) |
| Karşı taraf | Claude Code, `.worktrees/infra-main` içinde `main` üzerinde: altyapı, ortak dosyalar, inceleme, birleştirme |
| Kiracı | **mikas** — `tender` modülünün sahibi; tek `enable_tender = 1` olan site |
| Beads | `stabler-vgk.1`, `stabler-vgk.2`, `stabler-vgk.4` |

## Senin dokunabileceğin dosyalar

```
stabler/public/js/pages/tender/**
stabler/public/js/composables/useTenderContext.js
stabler/api/tender_documents.py
stabler/api/tender.py
stabler/tests/test_tender*.py
```

## Dokunma — ortak dosyalar, `main`'de Claude Code'da

```
stabler/public/js/router.js
stabler/public/js/components/Sidebar.vue
stabler/translations/{en,ru,uz,uzc,tr}.csv
CLAUDE.md   stabler/hooks.py   stabler/patches.txt
```

Yeni bir kullanıcı metni gerekiyorsa **`t("…")` ile kodda kullan, CSV'ye ekleme** —
beş dilin harvest'ini `main` tarafı yapacak (`stabler-vgk.5`).

---

## İş 1 — `stabler-vgk.1` · Rol kapısı (bug, P2)

`stabler/api/tender_documents.py:33` — `_get_deal_and_master()` içindeki
`_require_tender_view("sourcing", selected_company)` beş ucun **hepsini**
sourcing'e kapatıyor. Oysa `DeclarantQueue.vue:153` ve `LogistBoard.vue:156`
gümrükçü ve lojistikçiyi doğrudan `/tender/documents`'a linkliyor → orada
`tender.py:1748` `frappe.throw(_("Not permitted"), frappe.PermissionError)`.

**Yapılacak:** okuma/liste uçları için `director|sourcing|declarant|logist`
görünümlerinden **herhangi biri** yeterli olsun. Yazma uçları (`attach`, `remove`)
mevcut sıkı kapıda kalsın — belge yükleyip silmek okumakla aynı yetki değil.

**Kanıt testi:** `stabler/tests/` altında declarant rolüyle liste 200 döner,
attach 403 döner.

## İş 2 — `stabler-vgk.2` · Lot seçici (feature, P2)

`TenderDocuments.vue:204` `?deal=` yoksa `:218` `load()` erken dönüyor ve `:182`
yalnız bir `EmptyState` çiziyor — ekranda **lot seçmenin bir yolu yok.** Menüden
gelen kullanıcı bugün çıkmaz sokağa düşer; bu yüzden sidebar satırı (`vgk.3`)
bu işten sonra shipleniyor.

**Yapılacak:**
- Yeni whitelist uç `tender_document_targets(company)` — şirket kapsamlı, bir
  tender'a bağlı CRM Deal'leri döndürür: lot, tender, aşama, **eksik zorunlu belge
  sayısı**. Mevcut kalıplar: `tender.py:2313 sourcing_my_tenders`, `:2527 crm_board`.
- `TenderDocuments.vue` — `?deal=` yokken seçilebilir liste. Seçim route'a
  `documentsLocation()` (`composables/useTenderContext.js:70-76`) üzerinden yazılır;
  link üretimi tek yerde kalsın, ikinci bir yerde `{ name: "tender-documents" }`
  kurma.
- Liste kiracı adına değil **şirket + modül** kapısına göre süzülür
  (`if company == "mikas"` yasak — CLAUDE.md sert kuralı).

## İş 3 — `stabler-vgk.4` · Yinelenen sekme (bug, P3)

`TenderWorkspaceTabs.vue:16` ve `:19` byte-byte aynı
`{ key: "documents", label: t("Documents"), icon: "ti-files" }` satırını taşıyor.
Tek import eden `PoControlBoard.vue`. Birini sil.

---

## Bitirirken

1. `git fetch origin && git merge origin/main` — çatışma sıfır olmalı
2. `make check` yeşil (`lint-changed lint-js-changed compile guards test test-js`)
3. Her bead'i `bd close <id> --reason="…"` ile kapat
4. `git push` — dalda push et, `main`'e **sen merge etme**; inceleme + birleştirme
   karşı tarafta (`docs/runbooks/parallel-development.md`, protokol adım 3-5)

Prod'a çıkış bu dalın kapsamında değil. `deploy_stabler.sh` zaten dal
checkout'undayken ABORT ediyor (`:40-76`).
