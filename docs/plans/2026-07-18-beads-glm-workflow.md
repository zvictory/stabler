# Beads + GLM-5.2 çalışma modeli — Opus planlar, GLM uygular

**Sahip:** Zafar · **Tasarım/yönetim:** Opus 4.8 (senior dev) · **Tarih:** 2026-07-18
**Karar:** stabler'a embedded beads + tek tam-spec pilot task ile başla.

Bu doküman iki şeyi kurar:
1. **beads** — AI ajanları için bağımlılık-farkında iş takip grafiği (koordinasyon + kalıcı hafıza).
2. **GLM-5.2 köprüsü** — implementasyonu ucuz/güçlü GLM'e devret, Opus burada plan + review + deploy kapısında kalır.

> Altın kural: **beads iş kalemini takip eder, git kodu takip eder, Opus onaylar, insan deploy eder.** GLM asla prod'a dokunmaz.

---

## 0. Neden bu kurulum

- Bizde son 3 ayda stabler'da 329 commit var; iş markdown planlara + Cowork task listesine dağılmış. beads bunu tek bağımlılık grafiğinde toplar, `bd ready` bloklanmamış işi gösterir, `bd remember`/`bd prime` context sıkışmasından sağ çıkan proje hafızası verir.
- GLM-5.2 (13 Haz 2026, 1M context, MIT, coding-first) Claude Code'a z.ai'nin Anthropic-uyumlu endpoint'iyle drop-in girer. Terminal-Bench 2.1'de 81.0 (Opus 4.8 = 85.0). Ucuz. Ama bizim domain (çift taraflı muhasebe, çok-para FX, Frappe patch sırası, rsync cwd tuzağı) yüksek riskli → GLM'e **tam-spec** verilmezse landmine.
- Çözüm: Opus her işi eksiksiz spec'ler (dosya + kabul kriteri + test + hard-rule'lar), GLM izole bir git worktree'de uygular, Opus diff'i review eder.

---

## 1. beads kurulumu (stabler, embedded mod)

`bd` **senin makinende** kurulu olmalı (sandbox'ta yok). Bir kez:

```bash
brew install beads          # veya: npm install -g @beads/bd
```

Sonra `scripts` yerine repo kökünde (bootstrap script'i bu klasörde: `docs/plans/beads-bootstrap.sh`):

```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
bash docs/plans/beads-bootstrap.sh
```

Bootstrap şunları yapar (hepsi idempotent):
- `bd init` — embedded Dolt (tek-yazar, `.beads/embeddeddolt/`). Eski server-modu (msaerp/erpnext-ui'deki ağır `dolt sql-server`) **kullanılmıyor**.
- `bd setup claude` — Claude Code hook/ayarlarını kurar, AGENTS.md'yi beads workflow'uyla günceller.
- `bd remember "…"` — aşağıdaki invariant'ları kalıcı hafızaya yazar (GLM `bd prime` ile okur).
- İlk pilot bead'i oluşturur (`bd create`).

`.beads/` git'e commit'lenir (embedded mod origin remote'u otomatik bağlar). **Not:** `.beads/issues.jsonl` sadece export/görüntüleme içindir, source-of-truth Dolt DB'sidir.

> Eğer stabler repo'sunu kirletmek istemezsen: `bd init --stealth` (yerelde tutar, commit etmez). Ama paylaşımlı ekip için normal mod önerilir.

msaerp/erpnext-ui'deki ölü beads DB'leri: şimdilik dokunma. İş orada tekrar başlarsa `bd backup` ile taşınır veya fresh `bd init` yapılır.

---

## 2. beads'e gömülü invariant'lar (`bd remember`)

Bunlar bootstrap'ta yazılıyor. GLM (ve her ajan) `bd prime` çağırınca bunları görür. CLAUDE.md'nin **ihlal edilmesi en olası** kurallarının özeti:

1. **No Frappe Desk redirect** — SPA asla `/app/...`'e link vermez (href/window.open/router). Eksik CRUD → Stabler içinde yap.
2. **Money = MoneyInput**, **Date = DateInput + formatDate/formatDateTime** (dd.mm.yyyy). Asla bare `<input type=number|date>`, asla ham ISO interpolasyonu.
3. **Currency orijinal para biriminde** — base/USD alt-satırı gösterme. Semboller (`$`, `сўм`), ISO kodu değil.
4. **Striped tablo global** — `table-striped` ekleme; opt-out `table-no-stripe`.
5. **Tek `.btn-primary`** / görsel bölge. İkincil = `.btn-outline-secondary`/`.btn-ghost-secondary`.
6. **Status merkezî** — `getStatusBadgeClass` (composables/status.js). Sayfa-içi mapping yok.
7. **Liste = ListToolbar** (auto-apply, Apply/Refresh butonu yok) + **SkeletonRows** (spinner değil). Arama placeholder'ı `⌘K` ile bitsin.
8. **Module gating** — parent route `meta:{module:"…"}`, rol haritası `api/organization.py:_MODULE_ROLES`, enable default doctype field `default`'ında. Kassa/imports değişiklikleri **enable_tender/enable_imports gated** olmalı (sadece Mikas etkilensin).
9. **i18n 5 dil** — en/ru/uz/uzc/tr. Yeni kullanıcı-metni beşine de. CSV'ler **tek tek** stage'lenir, `translations/` dizini tümden değil.
10. **patches.txt pre-model-sync** — yeni kolon okuyan/yazan patch `frappe.db.has_column(...)` ile guard'lı ve idempotent olmalı.
11. **Commit hijyeni** — asla `git add -A`; explicit path; trailer `Co-Authored-By: …`.
12. **Money path deterministik** — LLM yok. JE base-anchored, `anchorJEAccountsInBaseCurrency()`, her satırda explicit debit/credit, kur ≥6 dp. Kullanıcının yazdığı tutar ground-truth.
13. **Bot `_flow.py` frappe-free** — tüm veri `ctx`'ten. DB/muhasebe sadece bot.py → money.py.
14. **Sır sızdırma yok** — Telegram token/secret/initData asla loglanmaz.
15. **Deploy = insan + Opus** — rsync bench `apps/` dizininden (asla `apps/stabler/` içinden; sibling `stable-erp-website/`'i siler). `--delete` yok, önce `-rltzn` dry-run. **GLM asla deploy etmez.**

---

## 3. GLM-5.2'yi Claude Code'a bağlama — Opus'u EZMEDEN

**Tehlike:** z.ai'yi global `~/.claude/settings.json`'a yazarsan buradaki Opus'un da GLM'e döner. Bunun yerine **env-scoped launcher** kullan.

### 3a. z.ai anahtarı (asla commit etme)
z.ai coding plan al (Lite $10/ay … Max ~$80/ay), API key'i gitignored bir dosyaya:

```bash
# ~/.zai.env  (chmod 600, git'e girmez)
export ZAI_API_KEY="senin_zai_anahtarin"
```

### 3b. `glm` launcher (~/.zshrc'ye ekle)

```bash
glm() {
  source ~/.zai.env
  ANTHROPIC_BASE_URL="https://api.z.ai/api/anthropic" \
  ANTHROPIC_AUTH_TOKEN="$ZAI_API_KEY" \
  ANTHROPIC_DEFAULT_OPUS_MODEL="glm-5.2" \
  ANTHROPIC_DEFAULT_SONNET_MODEL="glm-5.2" \
  ANTHROPIC_DEFAULT_HAIKU_MODEL="glm-4.5-air" \
  API_TIMEOUT_MS=3000000 \
  claude "$@"
}
```

Artık: `claude` = Opus (bu ortam + normal), `glm` = GLM-5.2. İkisi ayrı terminalde.

> Model string'lerini (`glm-5.2`, `glm-4.5-air`) z.ai docs'a karşı doğrula — değişebilir: https://docs.z.ai/scenario-example/develop-tools/claude

### 3c. İzolasyon: GLM ayrı git worktree'de çalışsın
GLM'in edit'leri senin aktif çalışma ağacını kirletmesin diye:

```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
git worktree add ../stabler-glm -b glm/WP-XX-kisa-ad
cd ../stabler-glm
glm            # GLM burada uygular; pure testler PYTHONPATH ile çalışır, bench gerekmez
```

Pilot pure-Python olduğu için worktree'de `PYTHONPATH=$PWD python3 -m unittest …` yeter; bench/Frappe gerekmez. Bittiğinde Opus (ben) diff'i review eder → ana branch'e merge/cherry-pick → commit (explicit path + trailer). Worktree silinir: `git worktree remove ../stabler-glm`.

---

## 4. Model-routing (kim neyi yapar)

anjan-hr'daki tablonun GLM'li hali. **Yargı Opus'ta, iyi-tanımlı yürütme GLM'de, mekanik Haiku'da.**

| Katman | Model | İşler |
|--------|-------|-------|
| Plan / tasarım / review | **Opus 4.8 (burada)** | Mimari, muhasebe doğruluğu (çift-taraflı, FX anchoring), migration/patch sırası, güvenlik, module-gating kararı, i18n review, **deploy**, GLM diff review |
| İyi-tanımlı yürütme | **GLM-5.2** | Tam-spec feature/refactor, pure-logic modüller, test yazımı, UI bileşeni, bot `_flow.py` state adımları (frappe-free), belirli-repro bug fix |
| Mekanik | **Haiku / glm-air** | Rename, format/lint, tek-satır edit, 5-dil CSV kopyala, versiyon bump |

**GLM'e ASLA gitmeyen işler:** JE/ödeme posting mantığı, yeni patch/migration, güvenlik sınırı (permission/webhook secret), FX kur anchoring, prod deploy, `translations/` toplu stage.

---

## 5. İş akışı (her task)

1. **Opus** bead yazar: `bd create "WP-XX · …" -p <0-3> -t task` + tam gövde (bkz §7 şablon). Bağımlılık varsa `bd dep add <child> <parent>`.
2. **GLM** worktree'de: `bd ready` → işi görür → `bd update <id> --claim` → `bd show <id>` ile spec'i okur → **önce ilgili dosyaları okur** → uygular → testi çalıştırır → diff'i bırakır → `bd close <id> "özet + test sonucu"`.
3. **Opus** review kapısı (§6) → geçerse ana branch'e alır, commit + gerekirse deploy prompt'u üretir.
4. Öğrenilen tuzak → `bd remember "…"` (bir dahaki ajan görür).

---

## 6. Opus review kapısı (GLM diff'ini kabul etmeden önce)

- [ ] Kabul kriterinin **tamamı** karşılandı mı? Testler yeşil mi (kendim çalıştır)?
- [ ] §2 invariant ihlali var mı? (Desk redirect, bare input, currency alt-satır, git add -A, frappe import _flow.py'de, loglanan sır…)
- [ ] Money path'e dokunduysa: base-anchored mı, explicit debit/credit mi, kullanıcı-tutarı ground-truth mu?
- [ ] Yeni kolon/doctype → patch has_column-guard'lı + idempotent mi?
- [ ] Yeni kullanıcı-metni 5 dilde mi?
- [ ] Kapsam sızması yok mu? (Sadece spec'teki dosyalar; alakasız dosya değişmemiş.)
- [ ] Module-gated mı? (Kassa/imports → enable_* arkasında.)
- Reddedersem: bead'i `bd update <id> --status open` + net düzeltme notu, GLM tekrar dener.

---

## 7. Bead gövde şablonu (Opus doldurur)

```
## Amaç
<tek cümle: ne + neden>

## Dosyalar
- <yol> — <ne yapılacak>

## Önce oku (read-before-code)
- <yol:fonksiyon> — <veri şeklini/imzayı buradan al, varsayma>

## Kabul kriteri
- [ ] <ölçülebilir sonuç>
- [ ] Test: `<komut>` yeşil

## Uyulacak hard-rule'lar (bu task için)
- <§2'den ilgili maddeler>

## Kapsam DIŞI (dokunma)
- <alakasız alanlar>
```

---

## 8. PILOT (ilk tam-spec task) — `WP-P1 · Kassa dönem özeti (pure helper + testler)`

**Neden bu pilot:** düşük risk (read-only saf hesap, muhasebe posting'i yok, migration yok), **izole yeni dosya** (bekleyen deploy'daki dosyalarla çakışmaz), tam test edilebilir (frappe-free, `unittest`), ve gerçekten faydalı (mini-app + bot statement'ına "Jami" satırı besler). Beğenmezsen swap ederiz — akış aynı.

```
## Amaç
account_transactions çıktısı için saf bir dönem-özeti hesabı ekle: toplam kirim,
toplam chiqim, net ve kapanış bakiyesi. Sonradan mini-app ve bot "Jami" satırını
besleyecek. Muhasebe/DB'ye DOKUNMAZ — sadece verilen satırlar üzerinden aritmetik.

## Dosyalar
- stabler/integrations/kassa/_summary.py  (YENİ, frappe import YOK)
- stabler/tests/test_kassa_summary.py       (YENİ, plain unittest)

## Önce oku (read-before-code)
- stabler/api/money.py:account_transactions (satır ~826) — dönüş şekli:
  {"entries": [{posting_date, voucher_type, voucher_no, against, account,
   debit(float), credit(float), remarks, balance}], "opening_base": float,
   "total_count": int, "has_more": bool}. Kirim = debit (cash hesabına para girişi),
   Chiqim = credit (çıkış). Bu semantiği koru.
- stabler/tests/test_kassa_flow.py — plain-unittest stilini birebir taklit et.

## İmza
def summarize_period(entries: list[dict], opening_base: float = 0.0) -> dict:
    """Saf. Dönüş: {
        'total_in': float,   # sum(debit)
        'total_out': float,  # sum(credit)
        'net': float,        # total_in - total_out
        'count': int,        # len(entries)
        'opening': float,    # opening_base
        'closing': float,    # opening_base + net
    }"""

## Kabul kriteri
- [ ] Boş liste → tümü 0.0/0, closing == opening_base.
- [ ] Karışık debit/credit satırları doğru toplanır; net = in - out; closing = opening + net.
- [ ] opening_base default 0.0; verilince closing'e yansır.
- [ ] Float toplama; None/eksik debit|credit'i 0.0 say (savunmacı .get).
- [ ] Test: `cd /Users/zafar/frappe-bench-local/apps/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_summary -v` → hepsi yeşil (≥5 test).
- [ ] py_compile temiz.

## Uyulacak hard-rule'lar
- _summary.py FRAPPE-FREE (import yok), tüm veri parametreden.
- Currency dönüşümü/base-USD alt-satır YOK — sadece verilen sayılar.
- Named export stili; PEP8; type annotation.

## Kapsam DIŞI
- money.py, _flow.py, bot.py, miniapp.py'ye DOKUNMA (wiring sonraki bead).
- Yeni endpoint, doctype, patch, i18n YOK.
```

Bu bead bootstrap script'inde otomatik oluşturuluyor. GLM `bd ready` → `--claim` → uygular; ben (Opus) diff'i §6 ile review edip merge ederim, sonra ayrı bir bead ile mini-app/bot'a bağlarız.

---

## 7b. Bead spec yazım kalıpları (Claude Code prompt library'den)

Anthropic'in prompt kütüphanesinin 6 çekirdek kalıbı — GLM'e verdiğim her bead bunları taşımalı (§7 şablonu zaten uygular). GLM'in çıktı kalitesi doğrudan buna bağlı:

1. **Adımı değil sonucu tarif et** — "şu dosyaları düzenle" değil, "ne + neden". GLM ilgili dosyaları kendi bulur (ama bizim domainde riskli dosyaları §7 "Kapsam DIŞI" ile kilitle).
2. **Kendini denetleme döngüsü ver** — her bead'de bir test/çalıştır/karşılaştır komutu ("Kabul: `PYTHONPATH=$PWD python3 -m unittest …` yeşil"). GLM tek denemede durmaz, geçene kadar iterler.
3. **Referans göster** — "şu pattern'i taklit et" (`test_kassa_flow.py` stilini, `account_transactions` şeklini). Referanssız GLM generic best-practice'e kayar, bizim konvansiyonu tutturamaz. §7 "Önce oku" tam bunun için.
4. **Ölçülebilir hedef** — performans/coverage işlerinde eşik ver (">=5 test", "p95 < 500ms"). "Bitti" tanımı tartışmasız olur.
5. **Artefaktı ver** — hata/log/screenshot/plan'ı spec'e göm, `@dosya` ile referansla. GLM kaynağı okur, senin tarifini değil.
6. **Cevabın formatını söyle** — çıktı şekli (yeni dosya mı, hangi imza, hangi dönüş tipi). §7 "İmza" bloğu bunu sabitler.

**Uyarı:** kütüphanenin "describe outcome, let Claude find the files" varsayılanı açık-uçlu; bizim yüksek-riskli repo'da GLM'e bunu ham verme — her zaman §2 hard-rule'ları + "Kapsam DIŞI" kilidiyle sınırla. Kütüphane kaynağı: https://code.claude.com/docs/en/common-workflows

---

## 9. Günlük komut hatırlatması

| Komut | Ne |
|-------|----|
| `bd ready` | Bloklanmamış işler |
| `bd create "…" -p 1 -t task` | İş aç |
| `bd update <id> --claim` | Atomik kap (assignee + in_progress) |
| `bd show <id>` | Detay + audit |
| `bd close <id> "özet"` | Kapat |
| `bd dep add <child> <parent>` | Bağımlılık |
| `bd prime` | Ajan workflow + kalıcı hafıza |
| `bd remember "insight"` | Kalıcı proje hafızası |

Kaynaklar: z.ai Claude Code entegrasyonu — https://docs.z.ai/scenario-example/develop-tools/claude · beads — https://gastownhall.github.io/beads/
