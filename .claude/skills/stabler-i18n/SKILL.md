---
name: stabler-i18n
description: Stabler translation workflow across the five languages (en, ru, uz, uzc, tr) — when to translate, how to harvest new keys, what reviewers reject. Use when adding user-facing strings, landing a feature that introduced t()/__() keys, before make check and git push on a string-bearing change, or when translations look stale in production.
---

# i18n workflow

Moved verbatim out of CLAUDE.md on 2026-08-15.
Original: `docs/archive/CLAUDE.md.2026-08-15.bak`.

> **Faz 0 note:** `AGENTS.md` carries a near-duplicate section
> ("Language & Translation Discipline"). Reconcile to one home — this file — and
> delete the other. Two copies drift; that is exactly how the `.rsync-exclude`
> list ended up with four divergent copies.

- **Prototypes vs. Code**: Mockups, drafts (e.g. `docs/uat/...`), and discussions can be in Turkish or English. Real implementation code (Vue components, Python backend, error messages, docstrings, UI labels, `t("...")` keys) MUST be English-first.
- **Five languages**: **en, ru, uz, uzc, tr**. Source strings live in `t()` (Vue) / `__()` (py).
- **Translation Timing**:
  1. During active feature development, only update `en.csv` if needed to keep English tests green. Do not translate into `tr/ru/uz/uzc` while code is still changing.
  2. Once the feature is finished and unit/feature tests pass, backfill the other 4 language catalogs (`tr.csv`, `ru.csv`, `uz.csv`, `uzc.csv`) before `make check` and `git push`.
- Harvest new keys: `bench --site <site> execute stabler.translations.harvest.run`
  (scans .vue/.js/.py, appends missing keys to `{lang}.csv`, sorted). `en` target =
  source; `ru/uz/uzc/tr` are filled in.
- Reviewers reject PRs that leave new user-facing strings untranslated in any of
  the five languages when landing the feature.

## Staging translations (from CLAUDE.md git discipline)
Stage the five CSVs explicitly (`en/ru/uz/uzc/tr.csv`), never the whole
`translations/` dir — it pulls the `.tx_*.json` caches.

## After deploying a translation change
`bench restart` does NOT clear the Redis translation cache. Run
`bench --site <site> clear-cache` on all 7 sites — see the `stabler-deploy` skill, step 7.
