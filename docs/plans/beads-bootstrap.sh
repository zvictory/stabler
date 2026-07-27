#!/usr/bin/env bash
# Beads bootstrap for stabler — embedded mode + invariants + pilot bead.
# Idempotent: safe to re-run. Requires `bd` installed on YOUR machine
#   (brew install beads   OR   npm install -g @beads/bd)
# Run from repo root:
#   cd /Users/zafar/frappe-bench-local/apps/stabler
#   bash docs/plans/beads-bootstrap.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
echo "==> repo: $(pwd)"

command -v bd >/dev/null 2>&1 || { echo "HATA: 'bd' kurulu değil. brew install beads  (veya npm i -g @beads/bd)"; exit 1; }

# 1) init (embedded Dolt) — skip if already initialized
if [ -d ".beads" ] && bd ready >/dev/null 2>&1; then
  echo "==> beads zaten init edilmiş, atlanıyor."
else
  echo "==> bd init (embedded)"
  bd init
fi

# 2) Claude Code entegrasyonu (hooks + AGENTS.md beads bölümü)
bd setup claude || echo "   (bd setup claude atlandı/başarısız — manuel: bd onboard)"

# 3) Invariants → kalıcı hafıza (GLM/ajan `bd prime` ile okur).
#    `bd remember` tekrarda duplicate yaratmaz varsayımıyla; yaratırsa zararsız.
remember() { bd remember "$1" >/dev/null 2>&1 || true; echo "   remembered: ${1:0:60}…"; }

echo "==> invariants (bd remember)"
remember "STABLER INVARIANT: SPA asla Frappe Desk'e (/app/...) link vermez — href/window.open/router hiçbiri. Eksik CRUD Stabler içinde yapılır."
remember "STABLER INVARIANT: Money = MoneyInput, Date = DateInput + formatDate/formatDateTime (dd.mm.yyyy). Bare <input type=number|date> ve ham ISO interpolasyonu YASAK."
remember "STABLER INVARIANT: Currency orijinal para biriminde gösterilir; base/USD alt-satır YOK. Sembol (\$, сўм), ISO kodu değil."
remember "STABLER INVARIANT: Striped tablo global (stabler.css). class=table-striped ekleme; opt-out class=table-no-stripe."
remember "STABLER INVARIANT: Görsel bölge başına tek .btn-primary. İkincil = .btn-outline-secondary / .btn-ghost-secondary."
remember "STABLER INVARIANT: Status rozetleri merkezî getStatusBadgeClass (composables/status.js). Sayfa-içi status mapping YASAK."
remember "STABLER INVARIANT: Liste sayfaları ListToolbar (auto-apply, Apply/Refresh butonu yok) + SkeletonRows (spinner değil). Arama placeholder ⌘K ile biter."
remember "STABLER INVARIANT: Module gating — route meta:{module}, rol haritası api/organization.py:_MODULE_ROLES. Kassa/imports değişiklikleri enable_tender/enable_imports arkasında (sadece Mikas etkilensin)."
remember "STABLER INVARIANT: i18n 5 dil (en/ru/uz/uzc/tr). Yeni kullanıcı-metni beşine de. CSV'ler tek tek stage; translations/ dizini tümden ASLA."
remember "STABLER INVARIANT: patches.txt pre-model-sync. Yeni kolon okuyan/yazan patch frappe.db.has_column(...) ile guard'lı + idempotent olmalı."
remember "STABLER INVARIANT: Commit — asla git add -A; explicit path; trailer 'Co-Authored-By: Claude <noreply@anthropic.com>' (model adı YOK — CLAUDE.md bunu bilerek sürümsüz tutuyor: sabitlenmiş bir ad bayatlar)."
remember "STABLER INVARIANT: Money path deterministik (LLM yok). JE base-anchored via anchorJEAccountsInBaseCurrency(), her satır explicit debit/credit, kur >=6dp. Kullanıcının yazdığı tutar ground-truth."
remember "STABLER INVARIANT: Telegram bot integrations/kassa/_flow.py FRAPPE-FREE; tüm veri ctx'ten. DB/muhasebe sadece bot.py -> money.py."
remember "STABLER INVARIANT: Sır sızdırma yok — Telegram token/secret/initData asla loglanmaz."
remember "STABLER INVARIANT: Deploy = insan + Opus. rsync bench apps/ dizininden (asla apps/stabler/ içinden). --delete yok, önce -rltzn dry-run. GLM ASLA deploy etmez."
remember "WORKFLOW: Opus planlar+review+deploy; GLM-5.2 iyi-tanımlı işi worktree'de uygular; her diff Opus review kapısından geçer. Detay: docs/plans/2026-07-18-beads-glm-workflow.md"

# 4) Pilot bead
echo "==> pilot bead"
PILOT_TITLE="WP-P1 · Kassa dönem özeti (pure helper + testler)"
if bd list --json 2>/dev/null | grep -q "WP-P1 · Kassa dönem özeti"; then
  echo "   pilot zaten var, atlanıyor."
else
  bd create "$PILOT_TITLE" -p 2 -t task -d "$(cat <<'BODY'
AMAÇ: account_transactions çıktısı için saf dönem-özeti hesabı. Toplam kirim (sum debit),
toplam chiqim (sum credit), net, kapanış. Muhasebe/DB'ye DOKUNMAZ.

DOSYALAR (YENİ):
- stabler/integrations/kassa/_summary.py  (frappe import YOK)
- stabler/tests/test_kassa_summary.py     (plain unittest)

ÖNCE OKU:
- stabler/api/money.py:account_transactions (~826) — entries satır şekli:
  {posting_date, voucher_type, voucher_no, against, account, debit(float),
   credit(float), remarks, balance} + top-level opening_base(float).
  Kirim = debit, Chiqim = credit.
- stabler/tests/test_kassa_flow.py — unittest stilini birebir taklit et.

İMZA:
  def summarize_period(entries: list[dict], opening_base: float = 0.0) -> dict:
      # {'total_in','total_out','net','count','opening','closing'}
      # total_in=sum(debit); total_out=sum(credit); net=in-out;
      # closing=opening_base+net; eksik debit/credit -> 0.0 (savunmacı .get)

KABUL:
- [ ] Boş liste -> 0.0/0, closing==opening_base
- [ ] Karışık satırlar doğru; net=in-out; closing=opening+net
- [ ] opening_base default 0.0; verilince closing'e yansır
- [ ] None/eksik debit|credit -> 0.0
- [ ] Test: PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_kassa_summary -v (>=5 test, yeşil)
- [ ] py_compile temiz

HARD-RULE: _summary.py FRAPPE-FREE; currency dönüşüm/base-USD alt-satır YOK; PEP8 + type annotation.
KAPSAM DIŞI: money.py/_flow.py/bot.py/miniapp.py'ye DOKUNMA; yeni endpoint/doctype/patch/i18n YOK.
BODY
)" && echo "   pilot oluşturuldu."
fi

echo ""
echo "==> HAZIR. Sonraki adım (GLM terminalinde, ayrı worktree):"
echo "    git worktree add ../stabler-glm -b glm/WP-P1-summary"
echo "    cd ../stabler-glm && glm"
echo "    # GLM içinde: bd ready -> bd update <id> --claim -> uygula -> test -> bd close"
echo "    # Sonra Opus (buraya dön) diff'i review eder."
