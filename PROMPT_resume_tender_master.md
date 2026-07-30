# Devralma — Tender Master CRM temeli (Codex limiti doldu, kaldığı yerden)

Bu dosyanın tamamını Claude Code'a yapıştır. **ONAY yazan yerde dur ve sor.**

Gece Codex subagent'larla `docs/superpowers/plans/2026-07-30-tender-master-crm-foundation.md`
planını uyguluyordu ve **Task 4'ün 3. inceleme turunun ortasında** kotası doldu.
Aşağıdaki durum tespiti kodu okuyarak yapıldı — plandaki checkbox'lar (42'si de boş)
**güvenilmez**, kod gerçeği söylüyor.

---

## Durum tespiti (2026-07-30)

### Nerede çalışıyoruz

```
worktree : .worktrees/tender-ops-foundation
branch   : codex/tender-ops-foundation   (feat/crm-tender-to-cash üzerine kurulu)
HEAD     : 16f26d9  fix(tender): derive CRM filters from lot lifecycle
testler  : 1810 yeşil (worktree içinde), tender-master'a ait 17 test dahil
```

Ana worktree'ye (`main`) DOKUNMA — orada başka bir oturumun işi var.

### Plana göre ne bitti

| Task | Durum | Commit'ler |
|---|---|---|
| 1 · Tender Master şeması + lot link + izinler | **bitti, incelendi** | `3825da0`, `462e7b4` |
| 2 · Company-safe Tender Master API | **bitti, incelendi** (modül kapısı düzeltmesiyle) | `634eb11`, `8798c91` |
| 3 · Tender CRM liste/Kanban + lot drill-down | **bitti, 3 tur incelendi** (request-token yarış düzeltmeleri) | `52ced81`, `240b76d`, `eefc15b`, `ebda960` |
| 4 · Route + rol menüsü + i18n + tam doğrulama | **kod bitti, inceleme yarım** | `ce9c129`, `b326494`, `16f26d9` + **commit'lenmemiş dosya** |

Doğruladım, hepsi yerinde: `Tender Master` doctype + controller, `v61_tender_master_link`
patch'i (patches.txt satır 66), `api/tender_master.py`, `composables/tenderMaster.js`,
`pages/tender/TenderCrm.vue`, 3 test dosyası, `hooks.py`'de permission_query + has_permission
+ CRM Deal validate hook'u, `router.js`'de `/tender/crm`, `Sidebar.vue`'de director+sourcing
girişleri, `TenderNav.vue`'de router-link, ve 9 çeviri anahtarı **5 dilde tam**.

### ⚠️ Elde kalan tek iş parçası

`stabler/api/tender_master.py` **commit'lenmemiş durumda.** Bu, reviewer'ın 3. turda
istediği düzeltmenin ta kendisi:

> "`deal` ile başka filtreler birlikte geldiğinde parent'taki **başka bir lot** seçili lot
> yerine eşleşebiliyor — deal filtresi aday lot kümesini önce tek lota daraltmalı."

Yazılmış hali (diff'i okudum) şunu yapıyor: `_qualifying_parent_names(...)` artık `deal`
parametresi alıyor ve `if deal and row.name != deal: continue` ile aday lot kümesini
daraltıyor; `deal` izin/şirket kontrolü de yaşam-döngüsü taramasından ÖNCE yapılıyor.
Mantık doğru görünüyor ama **testi yok ve commit'lenmemiş.**

### İki tuzak

1. **Plan yanlış yol veriyor:** Task 4'te `stabler/public/js/locales/{en,ru,uz,uzc,tr}.csv`
   yazıyor. Böyle bir dizin YOK. Doğrusu `stabler/translations/*.csv` — Codex doğrusunu
   kullandı, sen de onu kullan. Dosyalar **CRLF**; satır eklerken `\r\n` kullan, tüm
   dosyayı yeniden yazma (LF'e çevirirsen 4700 satırlık sahte diff çıkar).
2. **`make check` bu dalda zaten kırık** — Codex'in raporuna göre dalda ÖNCEDEN var olan
   lint borcu var. Yeni ürettiğimiz lint hatasıyla eski borcu **ayırmadan** düzeltmeye
   kalkışma.

---

# YAPILACAKLAR

## Adım 1 — Elde kalan düzeltmeyi bitir (test + commit)

```bash
cd ~/frappe-bench-local/apps/stabler/.worktrees/tender-ops-foundation
git status --short
git diff stabler/api/tender_master.py
```

`stabler/tests/test_tender_master_api.py` içine bu davranışı **kilitleyen** test ekle:
aynı parent tender altında iki lot varken `deal=LOT-A` + bir yaşam-döngüsü filtresi
(`stage`/`status`/`risk`) birlikte gelirse, LOT-B'nin eşleşmesi sonucu getirmemeli;
ayrıca yetkisiz/başka şirkete ait `deal` PermissionError atmalı. Testi **önce kırmızı**
gör (düzeltmeyi geçici olarak geri alıp), sonra yeşile al.

```bash
python3 -m unittest stabler.tests.test_tender_master_api -v
python3 -m unittest $(grep -v '^#' .github/frappe-free-tests.txt | grep -v '^$' | tr '\n' ' ') 2>&1 | tail -5
```

1810 test yeşil kalmalı. Sonra yol yol stage edip commit et
(`git add -A` YASAK), trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`.

## Adım 2 — Task 4'ün tam doğrulama kapısı

```bash
npm run test:js
make check 2>&1 | tail -40
```

`make check` hata verirse **iki listeye ayır** ve bana göster:
(a) bu dalın bizim commit'lerimizden gelen hatalar → düzelt,
(b) dalda önceden var olan borç (`git stash` + `git checkout 5f5e5d7 -- <dosya>` ile
teyit et, ya da merge-base'te aynı hatanın çıktığını göster) → **dokunma**, raporla.

## Adım 3 — Planı gerçekle hizala

`docs/superpowers/plans/2026-07-30-tender-master-crm-foundation.md` içindeki 42 checkbox
boş; kod bitmiş. Task 1–4'ün tamamlanan adımlarını `- [x]` yap, Task 4'ün doğrulama
adımını sonucuna göre işaretle. Ayrıca planın locale yolu hatasını düzelt
(`public/js/locales` → `translations`) ki sonraki okuyan yanılmasın.

## Adım 4 — Dal bütünü incelemesi

`pr-review-toolkit:code-reviewer` (ya da eşdeğeri) ile **merge-base'ten HEAD'e** tüm diff'i
incelet:

```bash
git log --oneline $(git merge-base main HEAD)..HEAD | cat
git diff --stat $(git merge-base main HEAD)..HEAD
```

Özellikle şunlara bak: `Tender Master` üst kaydının **hiçbir** finansal/sourcing belgesi
üretmediği (plan kuralı), parent toplamlarının child lotları **bir kez** topladığı,
`/app` linki olmadığı, para alanlarının `font-monospace` + MoneyInput kullandığı,
tabloların `table-striped` EKLEMEDİĞİ.

Bulguları bana getir. **ONAY almadan Adım 5'e geçme.**

## Adım 5 — main ile birleştirme kararı (ONAY GEREKLİ)

Dal **main'den 9 commit geride kaldı**. Merge-base `5f5e5d7`. Main'de bu arada şunlar oldu:

```
70beec6 docs: design hierarchical tender CRM
77d7c94 feat(imports): deleting a PI or CI shows what it would take with it   ← PI/CI silme BİTTİ
4014798 feat(lists): add truthful row ordinals
09717c6 docs(imports): master prompt — PI/CI CRUD, deploy, payment import
2cd9e45 docs(imports): plan for PI/CI full CRUD
069bc95 feat(imports): re-book a drifted invoice, with the plan shown first
4ce31e7 feat(imports): a CI corrected after booking no longer hides from the ledger
fe25fec feat(purchasing): the supplier ledger speaks in business documents
cad5ebf fix(rates): cbu.uz date-archive URL was missing the all/ segment
```

Dal aynı zamanda `feat/crm-tender-to-cash`'in 11 commit'ini de taşıyor (CRM aktivite/
aşama geçmişi, şirket kapsamı, satır sıra numaraları). Yani main'e almak **iki iş
paketini birlikte** almak demek.

Bana şu tabloyu çıkar, sonra ONAY bekle:
- dalın main'e göre değiştirdiği dosyalar
- bunlardan main'de de değişmiş olanlar (**çatışma adayları** — özellikle
  `stabler/api/tender.py`, `router.js`, `Sidebar.vue`, `translations/*.csv`,
  `.github/frappe-free-tests.txt`)
- önerin: `git rebase main` mi, `git merge main` mi (çeviri CSV'lerinde CRLF çatışması
  rebase'te acı verir — merge önerisi mantıklıysa söyle)

Onaydan sonra birleştir, **1810+ testi ve `make check`'i tekrar koş**, sonuçları getir.

## Adım 6 — Ne kaldı, ne bekliyor

Bana kısa bir kapanış raporu ver:
- Tender Master temeli: bitti / eksik kalan
- Sıradaki plan adımı (planın §10 "Delivery Sequence"inde 3–6 arası: parent CRM
  agregasyonu, RFQ/teklif/değerlendirme/award akışı, rol-türevi kuyruklar, uçtan uca
  testler) — hangisi bir sonraki dilim olmalı
- Ve **hâlâ deploy edilmemiş** olan main'deki imports zinciri
  (`PROMPT_pi_ci_crud_deploy_import.md` İŞ B) — sıralamayı bana sor

---

# Yapma

- `git add -A` yok; ana worktree'de (`main`) hiçbir şey stage etme, orada başka bir
  oturumun işi var.
- Plandaki `public/js/locales` yolunu kullanma — o dizin yok.
- Çeviri CSV'lerini toptan yeniden yazma (CRLF!).
- Dalda ÖNCEDEN var olan lint borcunu "temizlik" diye bu commit'e karıştırma.
- Adım 5 birleştirmesini onay almadan yapma.
- Prod'a hiçbir şey deploy etme — bu prompt yalnızca yerel dal işi.
