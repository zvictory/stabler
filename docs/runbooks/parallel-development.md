# Paralel geliştirme kuralları (birden çok ajan / IDE aynı depoda)

> **Neden bu dosya var:** Stabler tek bir kod tabanı olarak **7 kiracıya** aynı
> anda çıkıyor ve deploy, git'i değil **çalışan ağacın HEAD'ini** gönderiyor. İki
> geliştirici (veya iki AI IDE — Claude Code ve Antigravity) aynı depoda paralel
> çalıştığında, riskler sıradan bir merge conflict değil: yarım işin canlıya
> düşmesi, işin hiçbir commit'te var olmaması, ve `main`'in kırılması. Bu dosya
> o üç riski kapatan asgari disiplini yazıya döker.
>
> İlk uygulama: 2026-08-10, mikas Belge Merkezi işi (`feat/mikas-belge-merkezi`
> dalında Antigravity, altyapı ve ortak dosyalar `main`'de Claude Code).

## 1. Dal adı ve iz

`feat/<kiracı>-<konu>` (örn. `feat/mikas-belge-merkezi`), `fix/…`, `chore/…`.
Dalın karşılığı olan bead id'si commit mesajında veya bead'in notunda geçer.
İzsiz dal = altı ay sonra kimsenin silmeye cesaret edemediği dal.

## 2. Tek dosya = tek sahip

Çakışmaların neredeyse tamamı **ortak dosyalarda** olur. Bunlar paralel çalışma
süresince **yalnızca `main`'de** ve **yalnızca bir taraf** tarafından değiştirilir:

| Dosya | Neden ortak |
|---|---|
| `stabler/public/js/router.js` | her modül buraya satır ekler |
| `stabler/public/js/components/Sidebar.vue` | aynı |
| `stabler/translations/{en,ru,uz,uzc,tr}.csv` | harvest tüm modülleri tarar; CRLF'li, satır satır çatışır |
| `CLAUDE.md` | kural metni |
| `stabler/hooks.py`, `stabler/patches.txt` | append-only listeler |

Dal sahibi bu dosyalara dokunması gerekirse **ister**, kendi yapmaz.

## 3. Dal günde en az bir kez `main`'i alır

```bash
git fetch origin && git merge origin/main
```

Bir haftalık drift, bir günlük driftin haftalık toplamı değildir — üstel büyür.

## 4. Rebase yok, merge var

Bu deponun kayıtlı kararı
(`docs/prompts/PROMPT_tender_master_finish_merge_deploy.md:20-32`): CRLF satır
sonlu çeviri CSV'leri rebase'de **her commit'te yeniden çatışıyor** (ölçülen: 23
ardışık çatışma). Birleştirme her zaman `git merge --no-ff`.

## 5. Birleştirmeden önce dalda `make check` yeşil

`Makefile:38` → `BASE := git merge-base HEAD origin/main`, yani `check` hedefi
dalda da doğru dosya kümesine bakar; dalda çalıştırmamak için sebep yok.
Kırık bir `main`, paralel çalışan **herkesi** durdurur.

## 6. Push, merge'in parçasıdır

`main`'e merge edip push etmemek = işin var olmaması. CLAUDE.md'nin "beş kapı"
tablosundaki 4. kapı budur ve sessizce kapalı kalmaya en yatkın olanıdır.
Merge ve push **aynı komut zincirinde** yapılır.

## 7. Dal deploy edilmez

`deploy_stabler.sh` HEAD'i gönderir; hangi dal checkout'taysa o çıkar. 2026-08-10
itibarıyla script'in başına bir **dal kapısı** kondu (`deploy_stabler.sh:40-76`):
`main` değilse ABORT, `origin/main` ile ayrışmışsa ABORT. Bilinçli bir hotfix dalı
için `ALLOW_BRANCH_DEPLOY=1` var ve dal adını ekrana yazar.

rsync `--delete` kullanmıyor: prod'a bir kez düşen dosya orada **kalır**. Bu yüzden
kapı uyarı değil, kapı.

## 8. Gün sonunda `git status --porcelain` boş

2026-08'de iki günlük Müşteri Merkezi işi yalnızca untracked dosya olarak yaşadı.
Deploy `git archive HEAD` kullandığından böyle bir iş **canlıya da çıkamaz** —
sessizce yok sayılır.

## 9. Kaynak dosya commit edilmeden oturum kapanmaz

`stabler/api/_tender_documents.py` bir worktree'de yazıldı, `main`'e hiç
commit'lenmedi ve geriye yalnız `.pyc` kaldı
(`.zcode/plans/plan-sess_c79fea5a-86ef-4b0a-8b73-209aedc0e2fc.md:96`). Derlenmiş
çıktıdan kaynak kurtarmak, işi ikinci kez yazmaktan pahalıdır.

---

## Birleştirme protokolü (her dal için, sırayla)

1. Dalda `git fetch origin && git merge origin/main` — çatışma sıfır olmalı
2. Dalda `make check` yeşil
3. **İnceleme** (dal sahibi değil, diğer taraf yapar):
   - değişen dosya listesi kural 2'yi ihlal ediyor mu
   - CLAUDE.md sert kuralları: MoneyInput, DateInput/`formatDate`, Desk linki yok,
     kiracı adına dallanma yok (`if company == "mikas"`), modül kapısı var mı
   - yeni kullanıcı metinleri **beş dilde** mi
4. `git checkout main && git merge --no-ff <dal> && git push` — tek zincir
5. Dal silinir. (Bayat örnek: `perf/party-center-first-paint`.)

## İş bölümü şablonu

| Taraf | Kapsam |
|---|---|
| Dal sahibi (ör. Antigravity) | Kendi modülünün dikey dilimi: `pages/<modül>/**`, `api/<modül>*.py`, o modülün testleri |
| Ana ağaç (ör. Claude Code) | Altyapı, ortak dosyalar (kural 2), deploy, inceleme, birleştirme |

Modül sınırı iş bölümünün doğal sınırıdır çünkü Stabler zaten modül kapılıdır
(`enable_*` + `_MODULE_ROLES` + route `meta.module`). Sınırı modülden geçirmek,
iki tarafın aynı dosyaya bakma olasılığını en aza indirir.
