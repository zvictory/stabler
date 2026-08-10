# Antigravity devir: mikas Belge Merkezi (`feat/mikas-belge-merkezi`)

> Bu dosya bir **iş emri**dir, arka plan bilgisi değil. Kurallar
> `docs/runbooks/parallel-development.md`'de; burada yalnız bu dalın kapsamı var.

## Kurulum

| | |
|---|---|
| Dal | `feat/mikas-belge-merkezi` (ana klasörde checkout, bench önizlemesi bu ağaçtan servis ediliyor) |
| Karşı taraf | Claude Code, `.worktrees/infra-main` içinde `main` üzerinde: altyapı, ortak dosyalar, inceleme, birleştirme |
| Kiracı | **mikas** — `tender` modülünün sahibi; tek `enable_tender = 1` olan site |
| Beads | `stabler-vgk.7`, `.8`, `.10`, `.9`, `.1`, `.2`, `.4` — **bu sırayla** |

## Kararın kendisi (2026-08-10, kullanıcı verdi)

Belge merkezini kimin, nereden başlattığı bir tasarım sorusuydu ve cevaplandı:

```
Direktör    ihaleyi (Tender Master) açar ve ihale seviyesindeki zorunlu belge
            listesini ORADA tanımlar; aynı tahtadan lotu açar ve lotu bir
            sourcing kullanıcısına atar.
Atama       belge merkezinin başladığı andır.
Yükleme     satırın `role` alanına göre daralır: `customs` satırını gümrükçü,
            `logistics` satırını lojistikçi, `general`/`finance` satırını
            sourcing yükler; direktör hepsini yükleyebilir.
Okuma       dört tender görünümüne de açıktır.
```

**Bu karar `stabler/tests/test_tender_flow_contract.py` içinde çalışır durumda.**
Kararın tutmadığı yedi madde `@unittest.expectedFailure` ile işaretli: bugün
yeşiller, senin düzeltmen indiği anda *unexpected success* olarak **patlarlar**.
Bu kasıtlı. Bir işi bitirdiğinde ilgili dekoratörü kaldırmak işin parçasıdır —
`make check` seni buna zorlayacak.

İşler bu yüzden **zincirin başından** sıralandı. Önceki sürümdeki sıra (`vgk.1`
→ `.2` → `.4`) zincirin ucundan başlıyordu; kullanıcının cümlesiyle: *"tender
ucundan başlamak şu anda doğru görünmüyor."*

## Senin dokunabileceğin dosyalar

```
stabler/public/js/pages/tender/**
stabler/public/js/components/TenderMasterDrawer.vue   ← vgk.7 için genişletildi
stabler/public/js/composables/useTenderContext.js
stabler/api/tender_documents.py
stabler/api/tender.py
stabler/api/tender_master.py                          ← vgk.7 için genişletildi
stabler/tests/test_tender*.py
```

`components/` altındaki tek istisna `TenderMasterDrawer.vue`'dur — o klasördeki
başka hiçbir dosyaya dokunma; `Sidebar.vue` de orada.

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

## İş 1 — `stabler-vgk.7` · İhale seviyesi belge listesi (feature, P2)

Zorunlu belge listesini direktör **ihaleyi açarken** tanımlar. Bugün bunun hiçbir
UI'ı yok: `Tender Master.custom_tender_documents` yalnız `v76` patch'i tarafından
seed ediliyor, `TenderMasterDrawer.vue` dokuz alan yazıyor
(`tender_master.save_tender_master` → `_TENDER_FIELDS`) ve belge listesi onların
arasında değil. Liste ihalede tanımlanmazsa her lot kendi listesini uydurur.

**Yapılacak**
- `TenderMasterDrawer.vue` — satır bazlı belge listesi editörü. Kalıp hazır:
  `TenderIntake.vue:106-114` `STD_DOCS` (key / label / required / role).
- `api/tender_master.py` `save_tender_master` — `custom_tender_documents`'i kabul
  etsin; kaydederken `scope="tender"` **zorlansın** ve `role` `VALID_DOC_ROLES`
  (`api/_tender_documents.py`) ile doğrulansın. Okumada scope zaten zorlanıyor.

**Dekoratörü kaldır:** `test_the_director_authors_the_tender_level_checklist`

## İş 2 — `stabler-vgk.8` · Level 2'de "Yeni Lot" (feature, P2)

`TenderCrm.vue`'da hiçbir oluşturma eylemi yok. Kullanıcı bugün tender modülünden
çıkıp `/crm/deals`'e gidiyor ve lotu ihaleye yalnız `tender_no` seçimiyle bağlıyor
(`crm.py:120-134` `_apply_tender_parent_link`). Zincir modülün dışına çıkıyor.

**Yapılacak:** `TenderCrm.vue`'ya "Yeni Lot" eylemi + çekmece. `deal_type="Tender"`,
`custom_parent_tender` route'taki `?tender=` değerinden **otomatik** dolsun. Kayıt
mevcut `crm.save_deal` ucuyla; yeni backend gerekmiyor.

**Dekoratörü kaldır:** `test_the_lot_is_opened_from_the_tender_board`

## İş 3 — `stabler-vgk.10` · Atanabilir kullanıcı listesi (bug, P2)

`api/tender.py:1791` `tender_managers()` yalnız `Sales User` / `Sales Manager`
tarıyor. Oysa `_TENDER_VIEW_ROLES["sourcing"]` (`:1718-1734`) `Stabler Tender
Sourcing`'i de içeriyor: sourcing ekranlarını **görebilen** bir kullanıcı
direktörün atama listesinde **çıkmıyor**. İki sabit liste aynı soruyu farklı
cevaplıyor.

**Yapılacak:** rol kümesini `_TENDER_VIEW_ROLES["sourcing"]`'ten **türet**, ikinci
bir sabit liste tutma. Pencere değişince atama listesi kendiliğinden takip etsin.

**Dekoratörü kaldır:** `test_a_pure_sourcing_role_can_be_assigned_a_lot`

## İş 4 — `stabler-vgk.9` · Atama, lotun açıldığı ekranda (feature, P2)

`assign_tender` yalnız `DirectorBoard.vue`'dan çağrılıyor. Atama belge merkezini
**başlatan olay** olduğu için lotun görüldüğü yerde olmalı; bugün lotu açan kişi
ekran değiştirmeden akışı başlatamıyor.

**Yapılacak:** `TenderCrm.vue` lot kartına/çekmecesine atama kontrolü
(`tender_managers` listesinden sourcing kullanıcısı seç → `assign_tender`).
Mevcut uçlar yeniden kullanılacak.

**Dekoratörü kaldır:** `test_the_lot_is_assigned_where_the_lot_is_opened`

## İş 5 — `stabler-vgk.1` · Rol kapısı — **yeniden kapsandı** (bug, P2)

`api/tender_documents.py:33` — `_get_deal_and_master()` içindeki
`_require_tender_view("sourcing", selected_company)` beş ucun **hepsini**
sourcing'e kapatıyor. Oysa `DeclarantQueue.vue:153` ve `LogistBoard.vue:156`
gümrükçü ve lojistikçiyi doğrudan `/tender/documents`'a linkliyor → orada
`tender.py:1748` `frappe.throw(_("Not permitted"), frappe.PermissionError)`.

> **Bu maddenin kapsamı 2026-08-10'da değişti.** Önceki metin "yazma uçlarında
> mevcut sıkı kapı korunsun" diyordu; kullanıcının kararı bunu geçersiz kıldı.

**Yapılacak**
- **Okuma / liste:** dört tender görünümünden **herhangi biri** yeterli
  (`director|sourcing|declarant|logist`). Test bunu `_require_any_tender_view(wanted,
  company)` imzasıyla bekliyor — stub o adla hazır.
- **Yazma (`upload` / `waive` / `remove`):** tek pencereye değil, **satırın `role`
  alanına** göre daralsın:

  | Satırın `role`'ü | Yazabilen |
  |---|---|
  | `customs` | declarant + director |
  | `logistics` | logist + director |
  | `general`, `finance` | sourcing + director |

  Rol alanı zaten her satırda taşınıyor (`VALID_DOC_ROLES`) — **ek şema yok**.
  Bugünkü sorun rolün hiçbir yerde okunmaması: "kim yükler" sorusunun kodda
  cevabı yok.

**Dekoratörleri kaldır:** `test_customs_can_read_the_document_center`,
`test_customs_uploads_its_own_customs_row`,
`test_sourcing_does_not_upload_a_customs_row`

## İş 6 — `stabler-vgk.2` · Lot seçici (feature, P2)

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

## İş 7 — `stabler-vgk.4` · Yinelenen sekme (bug, P3)

`TenderWorkspaceTabs.vue:16` ve `:19` byte-byte aynı
`{ key: "documents", label: t("Documents"), icon: "ti-files" }` satırını taşıyor.
Tek import eden `PoControlBoard.vue`. Birini sil.

---

## Bitirirken

1. `git fetch origin && git merge origin/main` — çatışma sıfır olmalı
2. Bitirdiğin her iş için **karşılık gelen `@unittest.expectedFailure`
   dekoratörünü kaldır.** Kaldırmazsan `make check` "unexpected success" ile
   kırılır; bu bir kaza değil, kararın kodu yakalama biçimidir.
3. `make check` yeşil (`lint-changed lint-js-changed compile guards test test-js`)
4. Her bead'i `bd close <id> --reason="…"` ile kapat
5. `git push` — dalda push et, `main`'e **sen merge etme**; inceleme + birleştirme
   karşı tarafta (`docs/runbooks/parallel-development.md`, protokol adım 3-5)

Prod'a çıkış bu dalın kapsamında değil. `deploy_stabler.sh` zaten dal
checkout'undayken ABORT ediyor (`:40-76`).
