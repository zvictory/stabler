# Claude ⇄ Antigravity (`agy`) orkestrasyonu

> **Kanonik belge.** Yerini aldığı belgeler: `docs/plans/ORCHESTRATOR_PROMPT.md`
> (Cowork dönemi) ve `docs/plans/2026-07-18-beads-glm-workflow.md` (GLM dönemi).
> Dal/sahiplik/merge protokolü **tekrarlanmaz**, `docs/runbooks/parallel-development.md`
> geçerlidir. Claude'un adım adım izlediği iş akışı:
> `.claude/skills/stabler-orchestrator/SKILL.md`.

Rol dağılımı tek cümlede: **Claude tasarlar ve doğrular, Antigravity uygular,
prod'a çıkma kararı Zafar'ındır.**

| | Claude | Antigravity (`agy`) |
|---|---|---|
| Depo keşfi, kök neden analizi | ✅ | ❌ |
| Mimari ve arayüz kararları | ✅ | ❌ |
| Sözleşmenin uygulanması | ❌ | ✅ |
| Sözleşmede adı geçen testleri koşturma | ✅ (bağımsız) | ✅ |
| Diff incelemesi, son doğrulama | ✅ | ❌ |
| `git add <yol>`, commit, `--no-ff` merge, push | ✅ | ❌ **asla** |
| Prod, SSH, `deploy_stabler.sh` | Zafar'ın açık onayıyla | ❌ **asla** |
| Bead'i kapatma | ✅ | ❌ |

Tek `bench restart` **yedi kiracıyı birden** etkiler. Bu yüzden deploy adımı
otomatik akışın parçası değil, ayrı bir insan kararıdır.

---

## Ölçülmüş CLI gerçekleri

2026-08-12'de bu makinede ölçüldü. Varsayım değil, çıktı:

| Gerçek | Sonuç |
|---|---|
| `agy` sürümü **1.1.12** | — |
| `agy agents` ve `agy agent` **boş** dönüyor (çıkış kodu 0) | Kurulu ajan yok. **`--agent` kullanılmaz**, yönlendirme `--model` ile yapılır. |
| `--effort high`, `-high` son ekli model id'leriyle uyumlu | `--model gemini-3.6-flash-high --effort high` sorunsuz (test edildi, SUCCESS). |
| Düz `--output-format json` zarfında yalnız serbest metin `response` var | Makine-okunur rapor için **`--json-schema` şart**. |
| `--json-schema <dosya>` zarfa şemaya göre doğrulanmış `structured_output` ekliyor | **`.structured_output` okunur, `.response` asla parse edilmez.** |
| `bd` sürümü 0.60.0; `--design`/`--design-file` ve `--notes`/`--append-notes` destekli | Sözleşme `design`'a, çalışma günlüğü `notes`'a. |

Model yönlendirmesi:

| Risk | Model | İş |
|---|---|---|
| Düşük | `gemini-3.6-flash-high` | CSS/boşluk, düz Vue bileşenleri, CRUD ekranları, çeviriler, mekanik refactor, izole testler |
| Orta | `gemini-3.1-pro-high` | Çok dosyalı iş mantığı, API değişikliği, eşzamanlılık, kolay olmayan hata düzeltmeleri |
| Yüksek | **devredilmez — Claude ana iş parçacığı** | Mimari; GL / Payment Entry / tahsis semantiği; kur; izinler; çok kiracılılık; migration; prod olayları; son inceleme; deploy kararı |

---

## Akış

```
Claude SPEC → AGY IMPLEMENT → deterministik kapılar → Claude REVIEW
   → AGY FIX (en fazla 3 tur) → Claude VERIFY → merge + push
   → ⛔ dur → Zafar'ın açık onayı → deploy
```

### 1. Bead ve sözleşme (Claude)

Takip sistemi yalnızca `bd`. Görev başına `REQUIREMENT.md` / `IMPLEMENTATION.md` /
`REVIEW.md` **üretilmez**.

```bash
bd create --title "<ne>" --description "<neden>" --type task|bug|feature|chore -p 0-4 \
  --design-file <sözleşme.md> --json
bd update <id> --claim --json
```

Sözleşme **karar-tam** olmalı: `agy` sözleşmeyi harfiyen uygular, boşluk bıraktığın
her yer uydurulmuş davranış olarak geri gelir. Zorunlu başlıklar ve tam şablon
`.claude/skills/stabler-orchestrator/SKILL.md` §1'de.

### 2. Dal ve izole worktree (Claude)

```bash
git checkout main && git pull --ff-only
git worktree add -b feat/<kiracı-veya-modül>-<konu> .worktrees/agy-<bead-id> main
```

`.worktrees/` gitignore'lu (`.gitignore:11`), worktree hiçbir commit'e girmez.
**Bir worktree'ye bir yazan ajan** — iki yazıcıyı aynı dizine bağlama.

### 3. AGY'yi başlat (Claude)

Rapor şemasını bir kez yaz (worktree'de, commit edilmez):

```json
{
  "type": "object",
  "required": ["changed_files", "behavior_implemented", "commands_run", "deviations"],
  "properties": {
    "changed_files":        { "type": "array", "items": { "type": "string" } },
    "behavior_implemented": { "type": "string" },
    "tests_added":          { "type": "array", "items": { "type": "string" } },
    "commands_run": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["command", "exit_code"],
        "properties": {
          "command":   { "type": "string" },
          "exit_code": { "type": "integer" }
        }
      }
    },
    "deviations": { "type": "array", "items": { "type": "string" } }
  }
}
```

Sonra worktree'nin **içinden**:

```bash
cd .worktrees/agy-<bead-id>
agy \
  --model gemini-3.1-pro-high \
  --effort high \
  --mode accept-edits \
  --sandbox \
  --dangerously-skip-permissions \
  --output-format json \
  --json-schema .worktrees/agy-report.schema.json \
  --print-timeout 60m \
  --print "<sınırlanmış uygulama talimatı>" > /tmp/agy-<bead-id>.json
```

Talimatta şunlar açıkça yazılı olmalı: değişiklikleri **commit etme**; yalnız
izinli dosyalara dokun; prod, SSH, deploy, merge, push ve yıkıcı git komutları
yasak; CLAUDE.md sert kuralları (SKILL.md sonundaki değişmezler listesi) aynen
geçirilir.

#### `--dangerously-skip-permissions` neden meşru

Yalnızca **altı kontrolün aynı anda** geçerli olmasıyla. Biri bile düşerse bayrak
kaldırılır:

1. Çalışma `.worktrees/agy-<bead-id>` içinde, ayrı bir dalda.
2. `--sandbox` açık.
3. `--add-dir` **yok** — kapsam worktree dışına genişletilmiyor.
4. Prompt prod/SSH/deploy/merge/push/yıkıcı git/ilgisiz dosyaları açıkça yasaklıyor.
5. Claude, `agy` bitene kadar o worktree'ye dokunmuyor.
6. Claude, kabul etmeden önce **tam diff'i** bağımsız inceliyor.

### 4. `conversation_id`'yi yakala (Claude)

Gerçek, koşturulmuş çıktı (bu makinede, `--mode plan` ile alınan smoke run):

```json
{
  "conversation_id": "50188036-2c74-4d01-a7fd-1994965c1069",
  "status": "SUCCESS",
  "duration_seconds": 5.28,
  "num_turns": 2,
  "structured_output": {
    "changed_files": ["stabler/api/money.py"],
    "behavior_implemented": "Updated stabler/api/money.py and added one test.",
    "tests_added": ["tests/test_money.py"],
    "commands_run": [{ "command": "make check", "exit_code": 0 }],
    "deviations": []
  }
}
```

`--json-schema` olmadan aynı çağrı yalnızca serbest metin veriyor — karşılaştırma
için, gerçek çıktı:

```json
{
  "conversation_id": "77a70c7c-01fd-4a32-bcdd-9c656363db9a",
  "status": "SUCCESS",
  "response": "OK\n",
  "duration_seconds": 3.14,
  "num_turns": 1
}
```

Kaydet:

```bash
CID=$(jq -r .conversation_id /tmp/agy-<bead-id>.json)
bd update <bead-id> --append-notes "agy conversation_id: $CID (tur 1)" --json
```

`conversation_id` kaybolursa düzeltme turu için konuşmayı sürdüremezsin — sıfırdan
bağlamsız bir tur açman gerekir. Notlara **hemen** yaz.

### 5. Bağımsız inceleme (Claude)

Tamamlanma raporu bir **iddia**dır, kanıt değil.

```bash
cd .worktrees/agy-<bead-id>
git status --short
git diff $(git merge-base HEAD origin/main)
```

Değişen her dosya baştan sona okunur; kabul kriterleri tek tek işaretlenir; mevcut
çağıranlar ve arayüzler kontrol edilir; deterministik kontroller Claude tarafından
**yeniden** koşturulur. Ardından `stabler-diff-reviewer` ajanı çağrılır (salt-okunur,
düzeltemez) ve bulguları Claude hakem sıfatıyla değerlendirir.

Bulgular bead notlarına **P0** (doğruluk, para, güvenlik, veri kaybı) / **P1**
(sözleşme ihlali, karşılanmamış kabul kriteri) / **P2** (kural ihlali, eksik i18n
veya UI durumu) / **P3** (cila) olarak yazılır. P0–P2 merge'i bloklar.

> **"Ekran açıldı" gösterilen finansal verinin gerçek olduğunu kanıtlamaz.**
> Para/miktar gösteren her yeni blok, arkasındaki API veya veritabanıyla ve aynı
> ekrandaki mevcut gerçek-veri kartıyla karşılaştırılır. Yeni `ref()`'lerin
> başlangıç değerleri okunur. Bu, 2026-08-11'de fiilen prod'a çıktı
> (`CommercialInvoiceForm.vue`, sabit demo verisi; md5 manifest, migrate, restart
> ve bundle grep'in hiçbiri yakalamadı).

### 6. Düzeltme turu — en fazla üç

Aynı worktree, aynı konuşma:

```bash
agy --conversation "$CID" \
  --mode accept-edits \
  --sandbox \
  --dangerously-skip-permissions \
  --output-format json \
  --json-schema .worktrees/agy-report.schema.json \
  --print-timeout 60m \
  --print "<bulgular ve istenen tam düzeltmeler>"
```

Üçüncü tur da geçmezse **durulur**: bead açık/in-progress kalır, engel ve kanıt
notlara yazılır, Zafar'dan yön istenir. İşi sessizce Claude bitirip devri başarılı
ilan etmek yasak — devir başarısız olduysa bu bilgi kayıt altına girer.

### 7. Doğrulama kapıları

Her değişiklik için asgari: `make check` ve `git diff --check`. Etkiye göre eklenir:

| Değişiklik | Ek doğrulama |
|---|---|
| Frontend | hedefli ESLint/Vitest + `bench build --app stabler` |
| Form | `qa-forms` iş akışı (`.claude/workflows/qa-forms.js`) + doğrudan URL yenileme |
| DB / GL / Payment Entry | odaklı testler + `make test-bench` |
| Patch / doctype | yerel migrate provası + idempotens için ikinci koşu |
| Çeviri | beş katalog da dolu (en, ru, uz, uzc, tr); deploy sonrası Redis okuması |
| Çok kiracılı özellik | sahip kiracı **ve** en az bir sahip-olmayan kiracıda sızıntı smoke'u |

`make check`, GitLab CI, `qa-forms.js`, `deploy_stabler.sh` ve `bd` kendi alanlarında
yetkilidir. İkinci formatter, ikinci test hook'u, ikinci deploy script'i, ikinci
issue tracker, ikinci tarayıcı çerçevesi **eklenmez**.

### 8. Birleştirme (Claude)

```bash
cd .worktrees/agy-<bead-id>
git add <açık yollar>                          # asla `git add -A`; çeviriler beş CSV olarak
git commit                                     # trailer: Co-Authored-By: Claude <noreply@anthropic.com>
git fetch origin && git merge origin/main      # merge, rebase değil
make check                                     # merge sonrası tekrar
cd <ana ağaç> && git checkout main
git merge --no-ff feat/<...> && git push       # tek zincir
git rev-parse main origin/main                 # eşit olmalı
git status --porcelain                         # boş olmalı
bd close <bead-id> --reason "<ne çıktı>"
git worktree remove .worktrees/agy-<bead-id>   # yalnız kendi açtığını
```

Trailer'da **model sürümü olmaz** — sabitlenmiş bir ad bayatlar ve harness'ın
eklediğiyle çakışır.

Rebase yasağı zevk değil ölçüm: CRLF satır sonlu çeviri CSV'leri rebase'de her
commit'te yeniden çatışıyor (23 ardışık çatışma —
`docs/runbooks/parallel-development.md:42`).

### 9. Deploy sınırı

Push'tan sonra **durulur ve Zafar'dan açık onay istenir.** Onay geldikten sonra:

1. `main` temiz ve `main == origin/main` doğrulanır.
2. Kanonik `deploy_stabler.sh` çalıştırılır. rsync/migrate/restart komutları
   **elle yeniden kurulmaz**.
3. Sahip kiracı doğrulanır, ardından en az bir ikincil Stabler kiracısı.
4. Patch/doctype değiştiyse: her Stabler kiracısında DDL doğrulanır — önce
   `frappe.db.table_exists`, çünkü doctype'ı olmayan sitede `has_column` istisna
   fırlatır ve eksik tablo "migrate atlandı" değil **"bu sitede geçerli değil"**
   demektir.
5. Çeviri katalogları değiştiyse: yedi sitede `bench --site <s> clear-cache` ve
   `_load_translations` üzerinden yeni bir anahtar geri okunur (Redis cache
   `stabler:translations:<lang>`, 3600 s — `bench restart` bunu temizlemez).
6. Dokunulan her modülden bir kayıt formunda doğrudan URL yenileme smoke'u.
7. İlgili operasyon logları kontrol edilir.

Antigravity `deploy_stabler.sh`'yi **asla** çalıştırmaz.

---

## Yeni skill / agent sonrası Claude Code yeniden başlatılır

`.claude/skills/**/SKILL.md` ve `.claude/agents/*.md` oturum açılışında okunur.
Bu dosyalar eklendikten veya frontmatter'ları değiştikten sonra Claude Code
yeniden başlatılmadan `stabler-orchestrator` ve `stabler-diff-reviewer` görünmez.
Yeniden başlattıktan sonra ajanın mevcut ajan listesinde göründüğünü doğrula.

## Bakım

Bu belgede `agy` veya `bd` davranışına dair bir iddia varsa, **ölçülmüş** olmalıdır.
CLI sürümü yükseldiğinde "Ölçülmüş CLI gerçekleri" tablosu yeniden koşturularak
güncellenir; hatırlanarak değil. Uydurma JSON örneği konmaz — buradaki iki
`conversation_id` gerçek koşulardan gelir.
