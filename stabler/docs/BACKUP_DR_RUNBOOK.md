# Backup & Disaster Recovery Runbook — Stabler

The backup is the easy half. **The restore is the half that matters**, and a
backup nobody has ever restored is a guess, not a safety net. This runbook is
the procedure; the Stabler UI (Admin → Compliance → **Backup & DR**) is the
day-to-day surface.

---

## 1. What is backed up

A Frappe backup "set" is a group of files sharing a timestamp prefix
(`YYYYMMDD_HHMMSS-<site>-…`):

| File | Contents | Needed to restore ledgers? |
|---|---|---|
| `…-database.sql.gz` | The entire MariaDB database — all doctypes, GL entries, settings | **Yes — this alone restores the books** |
| `…-files.tar` | Public files (attachments, logos) | Only for attachments |
| `…-private-files.tar` | Private files (uploaded docs) | Only for private attachments |
| `…-site_config_backup.json` | Site config **without** secret keys | Reference only |

The database dump is what you protect first. Files are optional (toggle
"Include files in backup") and much larger.

---

## 2. Daily automatic backup

`stabler.api.backup.run_scheduled_backup` runs from the Frappe **daily**
scheduler (registered in `hooks.py`). Each run:

1. Creates a backup (DB; +files if enabled).
2. Prunes old sets — deletes sets older than *Keep backups for (days)*, but
   **always keeps the most recent 3 sets**, so retention can never leave you
   with zero backups.
3. If "Copy backups to Google Drive" is on and configured, uploads the newest
   set off-box.

Confirm the scheduler is actually running:

```bash
bench --site anjan.erpstable.com doctor
bench --site anjan.erpstable.com show-pending-tasks
```

If the scheduler is paused, **no automatic backups happen** — `bench --site <site> enable-scheduler`.

---

## 3. Off-box copy to Google Drive (one-time setup)

A backup that only lives on the same server as the database is not a disaster
plan — if the box dies, both die. Google Drive gives you an off-box copy.

We use a **service account** (server-to-server, no interactive login):

1. In Google Cloud Console: create a project → enable the **Google Drive API**
   → create a **Service Account** → create a **JSON key**. Download the JSON.
2. Put the JSON on the server and point `site_config.json` at it:

   ```bash
   bench --site anjan.erpstable.com set-config \
     stabler_gdrive_service_account /home/frappe/secrets/stabler-gdrive.json
   ```

   (You may also paste the JSON object inline as the value. The path is read
   server-side only — it is never stored in a doctype field.)
3. Install the client libraries in the bench Python env:

   ```bash
   ./env/bin/pip install google-api-python-client google-auth
   ```
4. Create a **Shared Drive** in Google Drive (not a personal "My Drive"
   folder — a service account has no personal storage quota and uploads to
   My Drive will fail with a quota error). Make a folder in it.
5. **Share that Shared Drive** with the service-account email
   (`…@….iam.gserviceaccount.com`, shown on the Backup & DR page) as a
   **Content manager**.
6. Copy the folder ID (the part after `/folders/` in the URL) into Stabler
   Settings → *Google Drive folder ID*, and tick *Copy backups to Google Drive*.

The Backup & DR page shows a green **Ready** once libraries, service account,
and folder are all in place. Use **Upload latest to Drive** to test it now.

> Why a Shared Drive: service accounts get 0 bytes of personal Drive quota.
> Uploading to a folder inside a **Shared Drive** (uploaded with
> `supportsAllDrives=true`, which we do) avoids the quota error. If you must use
> a personal Drive, switch to OAuth user credentials instead — out of scope here.

---

## 4. Restore procedure (the drill you must actually run)

**Never practice a restore on production.** Restore onto a throwaway site.

```bash
cd /home/frappe/frappe-bench

# 1. Get the backup set onto the server (download from Drive if needed).
#    You need at least the …-database.sql.gz file.

# 2. Create a scratch site.
bench new-site restore-test.local --admin-password admin

# 3. Install the same apps the production site has.
bench --site restore-test.local install-app erpnext stabler

# 4. Restore the database dump (add --with-private-files / --with-public-files
#    if you also captured files).
bench --site restore-test.local restore /path/to/20260615_120000-anjan_erpstable_com-database.sql.gz

# 5. Migrate to the current code (in case schema moved since the dump).
bench --site restore-test.local migrate
```

### Verify the restore (do not skip)

```bash
# Row counts sanity — should match production order of magnitude.
bench --site restore-test.local mariadb -e \
  "SELECT (SELECT COUNT(*) FROM \`tabGL Entry\`) AS gl_entries,
          (SELECT COUNT(*) FROM \`tabSales Invoice\`) AS sales_invoices,
          (SELECT COUNT(*) FROM \`tabPayment Entry\`) AS payments;"
```

Then log into the scratch site and check, at minimum:

- The **Trial Balance** for the last closed period balances (debits = credits).
- A few recent **Payment Entries** and **Journal Entries** open with correct amounts.
- The most recent **Sales Invoices** are present.

If all three pass, the backup is trustworthy.

### Record it

Open **Admin → Compliance → Backup & DR → "Mark restore tested."** This stamps
today as the last successful restore test. The page turns the *Restore test*
card **red / Overdue** when the last test is older than the configured interval
(default 90 days) — so an untested backup can't quietly rot.

Then destroy the scratch site:

```bash
bench drop-site restore-test.local --force
```

---

## 5. RTO / RPO (set expectations explicitly)

- **RPO (data loss window):** up to 24 h with daily backups. For a tighter RPO,
  raise backup frequency (an hourly scheduler event) or enable MariaDB binlog
  point-in-time recovery.
- **RTO (time to recover):** dominated by provisioning a site + restoring the
  dump — minutes-to-an-hour depending on DB size. Practising the drill above is
  what makes the RTO real instead of theoretical.

---

## 6. Known limitations (be honest)

- **Shared-bench blast radius.** Production runs on a shared bench (~22 tenants).
  A bench-level failure affects all of them. Backups protect *data*, not
  *uptime*; true HA needs an isolated bench/VM per commercial tenant (see
  DECISIONS D3).
- **Backups are not tamper-evident.** A System Manager with shell access can
  delete or alter backup files. For audit-grade retention, ship dumps to a
  write-once / object-lock bucket the app user cannot overwrite.
- **Drive uploads are best-effort in the scheduler.** A failed upload is logged
  (`stabler.backup gdrive upload`) and does not abort the backup. Watch the
  *Last Drive upload* timestamp on the page; if it stops advancing, investigate.
- **Encryption.** Frappe dumps are not encrypted at rest by default. If the
  Drive folder or server disk is a confidentiality concern, encrypt the dump
  before upload (e.g. `gpg`/`age`) — not yet automated here.
