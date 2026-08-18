# Çalışma Ortamı & İzolasyon — Durum Değerlendirmesi

**Tarih:** 15.08.2026 · **Katılım:** System Architect · Dev Team · DevOps · Şüpheci
**Kapsam:** worktree'ler, branch hijyeni, disk, ve bunların bağlam protokolüyle ilişkisi
**Veri:** `apps/stabler` üzerinden ölçüldü, tahmin yok

---

## 0. Tek cümlelik teşhis

> **İzolasyon modeli ilan edilmiş ama uygulanabilir değil — çünkü bir worktree'de DoD koşamıyor.**

Bu turda yaşanan **her** koordinasyon sorunu tek bir eksik sembolik bağa kadar iniyor.

```
worktree'de node_modules yok
  → make check orada 6 alt kapının 2'sini sessizce atlıyor (yine de exit 0)
    → o worktree'de bir mikro-task "bitmiş" sayılamaz
      → herkes ana ağaçta çalışıyor (kapının çalıştığı tek yer)
        → iki oturum tek ağaç, tek branch
          → lock çakışması · yanlış branch'e düşen commit'ler
            · "benim yapmadığım değişiklik" · branch'in çöplüğe dönmesi
```

`(b)` diye takip ettiğimiz "Makefile sessiz atlama" hatası, aslında bir Makefile
hatası değil. **İzolasyon politikasının çökme sebebi.**

---

## 1. Ölçüm

### 1.1 Worktree'ler — 4 kayıt, 2 farklı gelenek, yarısı çalışamaz

| Yol | Branch | Boyut | node_modules | DoD koşar mı |
|---|---|---|---|---|
| `.worktrees/agy-stabler-bf8` | `feat/imports-lcv-cancel-action` | 42M | **YOK** | ❌ sessizce yarım |
| `.worktrees/agy-stabler-l0m.3.7` | `feat/vehicle-finance-operations-screen` | 49M | var | ✅ |
| `.worktrees/claude` | `fix/ci-expense-real-records` | 86M | var | ✅ |
| `.claude/worktrees/sweet-spence-b4bcf6` | `claude/sweet-spence-b4bcf6` | 54M | **YOK** | ❌ sessizce yarım |

İki ayrı üst dizin geleneği: `.worktrees/` (3) ve `.claude/worktrees/` (1).
CLAUDE.md yalnızca birincisini tanıyor (`.worktrees/agy-<bead-id>`).

> **Düzeltme:** Daha önce "3 worktree prunable" demiştim — yanlıştı. Cowork'ün Linux
> VM'inden `/Users/zafar/...` yolları çözülmediği için git hepsini kayıp sanıyor.
> Dördü de **gerçekten var**. `git worktree prune` Mac'ten çalıştırılmalı, VM'den asla.

### 1.2 Branch'ler — 28 branch, 24'ü ölü

| Durum | Adet |
|---|---|
| `main` | 1 |
| Canlı iş (+1 veya fazlası) | **3** — `work-queue` +19, `operations-screen` +3, `sweet-spence` +1 |
| **Ölü (main'e göre +0)** | **24** — 10 ila 172 commit geride |

Ve bir uyarı: `feat/vehicle-finance-work-queue` **+19 / −2**. Yani main **2 commit
ilerlemiş** ve work-queue onları içermiyor. Merge öncesi güncellenmesi gerekiyor —
ve *kimin main'e push ettiği* teyit edilmeli.

CLAUDE.md'nin tek bakışta kontrolü `git branch --no-merged main` diyor. Bu, ölü
branch'leri **yakalamaz** — yanlış yöne bakıyor. 24 ölü branch tam da `--merged`'in
göstereceği şey.

### 1.3 Disk — ~600M gereksiz

| Kalem | Boyut | Not |
|---|---|---|
| **`graphify-out/`** | **220M** | En büyük tek kalem. Gitignore'lu ama üretiliyor — bugün 16:02, 16:13, 16:24'te. Kapalı olması gereken bir skill'den. Worktree'lerin içinde de kopyaları var. |
| `.worktrees/` | 176M | |
| `.git/` | 149M | içinde **526 `tmp_obj_*`** artığı (Cowork commit'lerinden, mount `unlink` edemiyor) |
| `node_modules/` | 109M | meşru |
| `.claude/worktrees/` | 54M | terk edilmiş gelenek |
| `.git/*.lock.*` | 11 dosya | kenara alınmış, 6 ve 17 Temmuz'dan beri biriken |

`_to_delete/` boş ama takip dışı — silinsin. `gui-test-screenshots/` **gitignore
kapsamında değil**; kasıtlı mı, kontrol edilmeli.

---

## 2. Toplantı

**System Architect —**
> "Sorun worktree'lerin varlığı değil, **birinci sınıf vatandaş olmamaları**. Bir
> worktree'de iş bitiremiyorsanız worktree yoktur; sadece bir dizin vardır. İzolasyon
> ilan edilerek değil, **alternatifi çalışmaz kılarak** sağlanır.
>
> Kimlik zinciri tek olmalı: **bead → branch → worktree → oturum.** Bu kurulduğunda
> koordinasyon kimlikten bağımsız hale gelir — kimin çalıştığını bilmenize gerek
> kalmaz, hangi bead'in açık olduğunu bilmeniz yeter. C'nin bu tur soket kovalarken
> vardığı sonuç buydu: *kirli dosya tek başına yeterli sinyal.* Doğru, ama bir adım
> eksik — kirli dosyayı hiç görmemeniz gerekirdi."

**Dev Team —**
> "Uygulamada olan şu: worktree açıyorsun, `make check` yeşil veriyor, güveniyorsun,
> sonra iki kapının hiç koşmadığını öğreniyorsun. İkinci sefer worktree açmıyorsun.
> **Politika değil, sürtünme kazanıyor.**
>
> `.worktrees/` mi `.claude/worktrees/` mi — bunu her seferinde düşünmek zorunda
> olmamalıyım. Ve worktree açmak tek komut olmalı; node_modules'ü elle bağlamayı
> hatırlamam gereken bir dünyada kimse worktree kullanmaz."

**DevOps —**
> "220M `graphify-out`, kapalı olduğu iddia edilen bir skill tarafından üç kez
> yeniden üretilmiş — bugün. Gitignore'lu olması onu görünmez yapıyor, yok etmiyor;
> ve worktree'lere de kopyalanıyor. Önce **neden koştuğunu** bulun.
>
> 24 ölü branch tek komutla gider. 526 `tmp_obj` `git gc` ile gider. Bunlar
> tartışılacak şeyler değil, çalıştırılacak şeyler. Tartışılacak olan tek şey:
> **temizlik kim tarafından, ne zaman koşuyor?** Bugüne kadar cevap 'kimse' olduğu
> için 600M birikti."

**Şüpheci —**
> "Üç itirazım var.
>
> **Bir:** node_modules'ü symlink'lemek eslint/vitest'i çalıştırır ama `.bin`
> içindeki mutlak yollar ve platform-native binary'ler symlink'te sürprizler
> çıkarabilir. Önce **kanıtlayın**, sonra kurala yazın — tam da bu turda üç kez
> yanıldığımız yer burası.
>
> **İki:** 24 branch'i silmek geri alınamaz gibi görünür. Değil — hepsi main'e
> merge edilmiş, commit'ler main'de duruyor. Ama silmeden önce **her birinin
> gerçekten +0 olduğunu** komutla gösterin, listeye güvenmeyin.
>
> **Üç, ve en önemlisi:** ortam temizliği ölçülebilir bir sonucu olmayan, sonsuza
> kadar sürebilen bir iştir. Bunun bir **bitiş kriteri** olmalı, yoksa remittance
> işine hiç dönemezsiniz. Ben şunu öneriyorum: *bir worktree'de sıfırdan bir
> mikro-task bitirilebiliyorsa ortam temizdir.* Ondan fazlası kapsam kayması."

**System Architect (karar) —**
> "Şüphecinin bitiş kriterini aynen alıyorum. Ortam işi tek bir kanıtla kapanır:
> **taze bir worktree'de `/mt` → `make check` → `/mt-done` uçtan uca çalışıyor.**"

---

## 3. Kararlar

| # | Karar | Gerekçe |
|---|---|---|
| **E1** | **Tek gelenek: `.worktrees/<bead-id>`.** `.claude/worktrees/` emekli. | İki gelenek = her seferinde bir karar = sürtünme |
| **E2** | **Worktree açmak scripted.** `scripts/new-worktree.sh <bead-id>` — worktree + branch + node_modules bağı + DoD doğrulaması, tek komut. | Elle adım hatırlatan bir akış kullanılmaz |
| **E3** | **`make check` koşamadığı alt kapı varsa KIRMIZI verir**, "atladım" notuyla yeşil değil. | (b)'nin doğru hali. Bir kapı ya kapıdır ya değildir. |
| **E4** | **Kimlik zinciri: bead → branch → worktree → oturum.** Branch adı bead id'sinden türer. | Koordinasyon kimlikten bağımsızlaşır |
| **E5** | **24 ölü branch silinir**, ölçümle doğrulandıktan sonra. Tek-bakış kontrolüne `--merged` eklenir. | Mevcut kontrol yanlış yöne bakıyor |
| **E6** | **`work-queue` main'e inip emekli olur.** Cherry-pick ile geçmiş ameliyatı YOK. | 19 commit'in hepsi main'e isteniyor; branch adı yanlış ama içerik doğru |
| **E7** | **`graphify-out` soruşturulur.** 220M, kapalı sanılan bir skill'den, worktree'lere kopyalanıyor. | Görünmez ≠ zararsız |
| **E8** | **Bitiş kriteri:** taze worktree'de `/mt` → `make check` → `/mt-done` uçtan uca. Ondan fazlası kapsam kayması. | Ortam işinin sonsuza kadar sürmesini engeller |

---

## 4. Uygulama

### 4.1 `scripts/new-worktree.sh` (E2)

```bash
#!/usr/bin/env bash
# Bir bead icin izole calisma alani acar. Tek komut, elle adim yok.
#   scripts/new-worktree.sh stabler-abc [base-branch]
set -euo pipefail

BEAD="${1:?kullanim: new-worktree.sh <bead-id> [base]}"
BASE="${2:-main}"
ROOT="$(git rev-parse --show-toplevel)"
WT="$ROOT/.worktrees/$BEAD"
BRANCH="work/$BEAD"

[ -e "$WT" ] && { echo "zaten var: $WT"; exit 1; }

git -C "$ROOT" fetch --quiet origin "$BASE" 2>/dev/null || true
git -C "$ROOT" worktree add -b "$BRANCH" "$WT" "$BASE"

# node_modules: KOPYALAMA, bagla. Kopyalasak worktree basina 109M.
ln -s "$ROOT/node_modules" "$WT/node_modules"

# DoD gercekten kosuyor mu — iddia degil kanit
cd "$WT"
if [ ! -x node_modules/.bin/eslint ] || [ ! -x node_modules/.bin/vitest ]; then
  echo "HATA: eslint/vitest bu worktree'de calistirilamiyor."
  echo "Bu worktree DoD kosamaz — kurulum yarim, devam etme."
  exit 1
fi

echo "hazir : $WT"
echo "branch: $BRANCH"
echo "sonraki: cd $WT && claude   (proje scope icin bu dizinden baslat)"
```

**Şüphecinin 1. itirazı gereği:** script'i yazdıktan sonra taze bir worktree'de
`make check`'in **tam** koştuğunu kanıtlayın. Symlink'in yeterli olduğu bir iddia
değil, ölçüm olmalı. Yetmezse `npm install --no-save` fallback'i ekleyin.

### 4.2 Temizlik runbook'u (Mac'ten, VM'den ASLA)

```bash
cd /Users/zafar/frappe-bench-local/apps/stabler

# 1) Gercek worktree durumu (VM'den okunan "prunable" GUVENILMEZ)
git worktree list

# 2) Olu branch'leri once GOSTER, sonra sil
git branch --merged main | grep -v -E '^\*|main' | tee /tmp/dead-branches.txt
wc -l /tmp/dead-branches.txt          # 24 bekleniyor
xargs -n1 git branch -d < /tmp/dead-branches.txt

# 3) Terk edilmis worktree gelenegi
git worktree remove .claude/worktrees/sweet-spence-b4bcf6   # once icindeki isi kontrol et
git worktree prune

# 4) .git sismesi
git gc --prune=now                     # 526 tmp_obj + 149M
rm -f .git/*.lock.*                     # 11 kenara alinmis kilit
rm -rf _to_delete/

# 5) graphify-out — SILMEDEN once nicin kostugunu bul
du -sh graphify-out                     # 220M
ls -la graphify-out/.graphify_root
# skill kapali mi: /context ile Skills listesinde graphify var mi bak

# 6) Sonuc
du -sh .git .worktrees .claude/worktrees graphify-out
git branch | wc -l                      # ~4 bekleniyor
```

### 4.3 CLAUDE.md'ye eklenecek (E1, E3, E4)

```markdown
## Isolation — one session, one worktree, one branch, one bead

- Every concurrent session works in its own worktree: `.worktrees/<bead-id>`,
  branch `work/<bead-id>`. Create it with `scripts/new-worktree.sh <bead-id>`;
  never by hand — the script is what guarantees the DoD can run there.
- `.claude/worktrees/` is retired. One convention only.
- Start Claude Code from the worktree root, not from the bench root — project
  scope resolves from cwd (measured 2026-08-15; from the bench root the whole
  of `.claude/` is ignored).
- **A tree where `make check` cannot run every sub-gate is not a place to work.**
  `make check` fails there; it does not pass with a note.
- You never need to know *who* else is working. You need to know *which bead*.
  If a file you want is dirty, it is not yours this round.

One-glance status check:

    git worktree list                          # every entry accounted for
    git branch --merged main | grep -v main    # must be empty — the graveyard
    git branch --no-merged main                # only deliberately open work
    git status --porcelain                     # empty
```

---

## 5. Sıralama

Sizin istediğiniz sıra korunuyor: **ortam → bağlam/prompt → remittance/installment.**

| Faz | İş | Kim | Bitiş kriteri |
|---|---|---|---|
| **E** | Temizlik runbook'u + `new-worktree.sh` + CLAUDE.md izolasyon bölümü | ana ağaç (C) | Taze worktree'de `/mt` → `make check` → `/mt-done` uçtan uca |
| **G** | Kapı ailesi: (a) test-bench, (b) node_modules→**kırmızı**, (c) i18n harvest | B (Makefile tek elden) | Üçü de aynı desende; C'nin `t(değişken)` ölçümü girdi |
| **M** | Gerçek `make check` → `work-queue` → main → push → branch emekli | ana ağaç | main == origin/main, work-queue silinmiş |
| **A** | Operations ekranı canlı doğrulama → rebase → merge | A (kendi worktree'si) | Kabul kriteri 1 karşılandı |
| **C** | T4 (`agy-delegation` → skill), T7 (plugin skill denetimi) | ana ağaç | Memory 8.4k'dan düşük |
| **→** | **remittance / installment** | yeni worktree'ler | — |

**E ve G paralel yürüyebilir** — farklı dosyalar (scripts/ + CLAUDE.md vs Makefile).
Ama E3 (`make check` kırmızı versin) G'nin içinde; yani E'nin bitiş kriteri G'ye bağlı.
Sıra: G(b) → E doğrulaması → M.

---

## 6. Açık sorular (cevabı bende yok)

1. **main 2 commit ilerlemiş** — `work-queue` +19/−2. Kim push etti, ne push etti?
   Merge planından önce cevaplanmalı.
2. **`graphify-out` neden koşuyor?** `graphify` skill'i `settings.local.json`'da
   kapalı. Kapalıysa 220M'yi kim üretiyor — başka bir oturum mu, bench root'tan mı?
3. **`gui-test-screenshots/`** gitignore dışında ve takip ediliyor. Kasıtlı baseline
   mı, artık mı?
4. **`.worktrees/agy-stabler-bf8`** ve **`sweet-spence-b4bcf6`** içinde
   commit'lenmemiş iş var mı? Silmeden önce bakılmalı — bu turda tam da bu yüzden
   iki kez durduk.
