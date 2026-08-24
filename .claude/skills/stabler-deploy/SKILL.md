---
name: stabler-deploy
description: Deploy stabler to production — the five gates that decide whether work actually lands, prod site topology across the 7 tenants, the rsync + on-server build procedure, rollback, and post-deploy smoke checks. Use when deploying, when a change "disappeared" in production, when verifying a release, or when asked about the prod site, bench build, migrate scope or restart procedure.
---

# Stabler deploy runbook

Moved verbatim out of CLAUDE.md on 2026-08-15 — this is ~2,150 tokens that used to be
loaded in every session, including sessions that only touched a Vue file.
Original: `docs/archive/CLAUDE.md.2026-08-15.bak`.

**Production deploy always requires explicit approval from Zafar** — one `bench restart`
blips every stabler tenant at once. Never infer approval. Deploy only from a clean
tree.
`./deploy_stabler.sh` is denied to the agent in `.claude/settings.json` by design: the
agent prepares the deploy, the human runs it.

## The five gates (why work "disappears")
Between a saved file and a running feature there are five gates, and **every one of
them is opened by hand**:

| # | Layer | Command that opens it |
|---|-------|-----------------------|
| 1 | Disk (working tree) | — |
| 2 | Commit | `git add <path>` + `git commit` |
| 3 | Branch merge | `git merge` |
| 4 | Remote (GitLab/GitHub) | `git push` — gated by `make check` |
| 5 | Prod | `rsync` + `bench build` (+ `migrate`) |

**Gate 5 never reads gates 2–4.** Prod is not a git repo; `rsync` copies this
laptop's *current disk*. Three consequences, all of which have actually happened:
- Uncommitted work **can reach prod** and exist nowhere in git.
- Work that is committed and merged **can be missing from prod** if nobody rsynced.
- Deploys run without `--delete`, so a file that ever landed on prod **stays there
  forever**, even after it is deleted locally.

Standing discipline — `main` is the single source of truth, and prod is fed from
`main`, never from a working tree:

| Rule | What it prevents |
|------|------------------|
| Every agent works on its own branch, and **merges to `main` when the work is done** | gate 3 silently staying shut |
| **Pushing is part of merging** — a merge that is not pushed means "the work does not exist" | gate 4 silently staying shut |
| Deploy only from a clean tree (`git status --porcelain` empty for tracked files) | uncommitted work leaking to prod; prod files that exist in no commit |
| Leave `git status --porcelain` empty at the end of the day | the 2026-08 case where two days of Customer Center work lived only as untracked files |
| Keep `make check` green per commit, not per 172 commits | the lint backlog that blocked every push for months |

One-glance status check:
```
git rev-parse main origin/main    # must match
git status --porcelain            # must be empty
git branch --no-merged main       # must be empty (bar deliberately open branches)
```

When two agents/IDEs work the repo at the same time, the file-ownership split,
the merge protocol and the branch gate in `deploy_stabler.sh` are written out in
`docs/runbooks/parallel-development.md`.

## Prod site
- **Primary prod = `anjan.erpstable.com`.** Stabler is actually installed on
  **8 sites** on the shared bench (`/home/frappe/frappe-bench`, ~22 tenants):
  `anjan`, `dts`, `horeca`, `laminor`, `mikas`, `msa`, `smartbox`, `zuma` — measured
  2026-08-20 with `bench --site <site> list-apps` across every tenant. It said seven
  until then and `zuma` had already been added, which silently shortened every
  "run this on all sites" step below by one site. **Re-measure rather than trust
  this number** — it is the kind of fact that goes stale without anything failing:
  `for s in $(ls sites | grep '\.'); do bench --site $s list-apps | grep -q '^stabler' && echo $s; done` `msa` DOES carry stabler and
  the PI / imports feature lives there. The remaining tenants do NOT have stabler installed.
- A code change under `apps/stabler/` (shared app code, not per-site) plus
  `bench restart` takes effect on ALL stabler sites at once — no per-site
  redeploy needed. Backend fixes should be spot-checked on at least one
  secondary site (not just anjan) before calling a deploy done.
- Before ANY `migrate` / `restart` / data command aimed at "prod", confirm the
  target: `bench --site <site> list-apps | grep stabler`. Never assume the site.
- SSH alias: `ice-production`. Prod is **NOT a git repo** — deploy is rsync.

## Prod-only supervisor edit (re-apply after any `bench setup supervisor`)

Prod's `config/supervisor.conf` carries **one hand edit that is not in bench's
template**: `startsecs=20` on the three programs whose `command=` goes through the
`bench` wrapper — `frappe-schedule`, `frappe-short-worker`, `frappe-long-worker`.
Applied 2026-08-24; backup at `config/supervisor.conf.bak-2026-08-24`.

Why, measured from `supervisord.log` + `bench.log`: on 2026-07-28 18:59 redis-queue
began refusing connections and `bench` could no longer resolve `./env/bin/python`
(`bench/cli.py:201`, `os.execv`). Supervisor respawned those three programs **85 297
times over 43.7 h**, until 2026-07-30 14:41, dumping 68 100 identical tracebacks into
`logs/worker.error.log`. `startretries=10` never engaged — it only counts processes
that die *inside* `startsecs`, and the failing `bench` lives ~2.2 s (0 of 17 047
samples under 1 s), so supervisor kept declaring RUNNING and `autorestart=true`
looped with no limit. Background jobs were dead on every tenant for 43.7 h and the
only symptom was a growing log file.

`startsecs=20` clears the longest observed failure (15 s), so a fast-failing start now
trips `startretries` and lands in **FATAL** — visible in `supervisorctl status` —
instead of looping. It does not prevent the outage, only the silence and the flood.
Web/socketio need no edit: gunicorn's `command=` is an absolute path, so a missing
binary is a real spawn error that supervisor already gives up on.

`bench setup supervisor` regenerates this file from the template and drops the edit
without saying so. Re-apply after any `bench update`:

```
ssh ice-production 'sudo sed -i -E "\|^command=/home/frappe/\.local/bin/bench |a startsecs=20" /home/frappe/frappe-bench/config/supervisor.conf && sudo supervisorctl reread && sudo supervisorctl update'
```

Proof it took effect: `supervisord.log` must read `stayed up for > than 20 seconds
(startsecs)`, not `> than 1 seconds`.

## Deploy procedure (rsync + on-server build)
1. Commit locally (specific paths) and `bench build --app stabler` to prove it compiles.
2. Backup first: `ssh ice-production 'tar czf /root/stabler-app-$(date +%F-%H%M).tgz -C /home/frappe/frappe-bench/apps stabler'`.
3. rsync source → `ice-production:/home/frappe/frappe-bench/apps/stabler/` with
   `-rltz --no-owner --no-group` (NO `--delete`) and
   `--exclude-from=apps/stabler/.rsync-exclude`. **The exclude list lives in that
   file, not here** — it used to be copy-pasted into three deploy scripts plus this
   doc, and the four copies drifted. Add new excludes there only.
   Then `chown -R frappe:frappe …/apps/stabler`.
   **cwd trap (near-miss 2026-07-17):** run rsync from the bench **`apps/`** dir so
   the relative source `stabler/` = the whole app `apps/stabler/`. Running it from
   inside `apps/stabler/` makes `stabler/` resolve to the inner Python module
   (`apps/stabler/stabler/`) while the remote is the whole app — rsync then shows a
   bogus 1500+ deletions and (with `--delete*`) would wipe the sibling
   `stable-erp-website/`. **ALWAYS `-rltzvn` dry-run first and abort if any sibling
   dir or `stable-erp-website/` appears in the delete list.** The `-v` is not
   optional: `rsync -n` without it prints nothing, so an empty dry-run reads as
   "clean" when it actually verified nothing (this cost us a bogus 2026-07-24
   verification).
4. **Node deps, then** `bench build --app stabler` on prod.
   `node_modules` is (correctly) in `.rsync-exclude`, so **no deploy step creates
   it** — while `bench build` silently depends on it: esbuild resolves
   `@vue-flow/*` out of `apps/stabler/node_modules`. Measured 2026-08-07: the
   directory was simply gone and the build died on `ProcessEditor.vue`'s
   `@vue-flow/controls` import. A newly added runtime dependency is the same trap
   with a fuse — prod keeps building against the previous install. So install when
   the tree is missing **or** when the manifests just shipped differ from the ones
   it was built from (prod is not a git repo; the only comparison available is a
   checksum stamp — `deploy_stabler.sh` keeps it at
   `node_modules/.stabler-deps-md5` over `package.json` + `package-lock.json`):
   ```
   sudo -H -u frappe npm install --omit=dev --no-save --ignore-scripts --no-audit --no-fund
   ```
   `--ignore-scripts` is required, not tidy: `preinstall` is `npx only-allow npm`,
   a network fetch mid-deploy. `--omit=dev` keeps eslint/prettier/vitest off prod.
   `npm ci` is the command we actually want and is blocked until `package-lock.json`
   is back in sync with `package.json` (`stabler-qee`).
5. `bench --site anjan.erpstable.com migrate` (only if patches.txt / doctypes changed)
   — **run for EVERY stabler site, not just anjan.** `migrate` is per-site; rsync+restart
   are bench-wide, so a doctype/patch change reaches every site's code but only the
   sites you migrate get the DDL. (Near-miss 2026-07-18: `msa` was skipped and its
   new `Import PI Group` columns were missing until a follow-up migrate.)
6. `bench restart` if any `.py` changed.
7. `bench --site <site> clear-cache` on **every stabler site** if any
   `translations/*.csv` changed. `bench restart` does **not** cover this:
   `stabler/www/stabler.py:_load_translations` caches each language map in Redis
   under `stabler:translations:<lang>` with `expires_in_sec=3600`, and restart
   never touches Redis. Skip it and the CSVs are correct on disk while users see
   the old strings for up to an hour — and an md5 manifest reads clean the whole
   time, because the files really are identical (measured 2026-08-12, the PI
   Advance Ledger i18n deploy). Verify by reading the map back on prod:
   `_load_translations("ru").get("<a new key>")` must be non-empty.
- **`bench restart` restarts the whole bench → brief blip for ALL tenants**, not
  just anjan. Schedule for low traffic, or accept the blip explicitly.
- Rollback = restore the step-2 tar, `chown`, `bench build`, `bench restart`.
  **This is a code rollback only.** Step 2 archives `apps/stabler`, never the
  database. If step 5 (`migrate`) ran, the schema and the data it touched stay
  migrated while the code goes back — that is not "the previous state". Read the
  patches that landed since the sha prod was stamped with and check whether any of
  them mutate data one way; `v86_remittance_pickup_code_hash` is the worked
  example (one-way by design, `:11`), and undoing it needs a refund or an admin
  override (`:83`), not a tar.

## Post-deploy smoke checks (run every release)
- **Direct-URL / refresh load of a record form.** Open an existing record by
  pasting its URL (not by clicking from the list) and hit refresh, e.g.
  `…/stabler#/purchasing/invoices/<an existing PINV>`. It MUST open populated and
  in the correct view/edit state — NOT a blank "New …" form. Repeat for one
  Sales Invoice, Purchase Order, Quotation and Payment Entry. (Regression class:
  record forms must branch on the **route param**, not the document engine's
  `isCreate`, which is null-based until `load()` runs — so direct loads/refreshes
  would otherwise render blank. See the `if (docName.value)` guard in the
  `*Form.vue` `onMounted`.)
- **Money/GL log is flowing.** After recording one payment, confirm a line lands
  in `sites/anjan.erpstable.com/logs/stabler.payments.log`.
