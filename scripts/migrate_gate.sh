# This library decides whether 'bench migrate' must run on production.
# The Stabler application code is shared across all 7 tenants on the bench:
# rsync, build, and restart are bench-wide one-shot operations that deploy
# new code to all sites. However, 'bench migrate' executes per-site DDL.
# If we omit migrating any site, code changes referencing new columns or tables
# will crash with database errors on skipped tenants. Thus, the gate compares
# the last successfully migrated commit stamp on prod against HEAD to see
# if any schema-relevant files changed.

migrate_trigger_files() {
  local from_sha="$1"
  local to_ref="$2"
  local repo_dir="${APP_DIR:-.}"

  if [ -z "${APP_DIR:-}" ] && [ -n "${BASH_SOURCE[0]:-}" ]; then
    repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi

  # Only doctypes (.json), patches.txt, patch files, fixtures, and hooks.py
  # can trigger DDL modifications or run database migration code. Other files
  # (like Vue templates or standard Python logic) do not affect the database
  # schema, so a release containing only those files safely skips migration.
  #
  # ADD EVERY NEW SCHEMA-MUTATING PATH TO THIS REGEX. A miss here is permanent,
  # not merely a skipped migrate: the "Skipping migrate" branch advances prod's
  # stamp anyway (deploy_stabler.sh:266), so the next deploy compares against a
  # commit that already contains the change this pattern failed to classify. The
  # change is then invisible to the gate forever, and the only symptom is a
  # tenant crashing on a column that was never created.
  #
  # The gate is fail-safe about what it does not KNOW — an unreadable or missing
  # stamp migrates (deploy_stabler.sh:248-249) — but it trusts a confident "no
  # triggers" completely. That asymmetry is deliberate and it is why this list,
  # not the fallback, is the thing to keep correct.
  git -C "$repo_dir" diff --name-only "$from_sha" "$to_ref" | grep -E '(^|/)doctype/[^/]+/[^/]+\.json$|^stabler/patches\.txt$|^stabler/patches/|^stabler/fixtures/|^stabler/hooks\.py$|(^|/)custom/[^/]+\.json$' || true
}

migrate_needed() {
  local from_sha="$1"
  local to_ref="$2"
  local repo_dir="${APP_DIR:-.}"

  if [ -z "${APP_DIR:-}" ] && [ -n "${BASH_SOURCE[0]:-}" ]; then
    repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi

  # Fallback decisions must prioritize safety over speed. If we migrate when
  # it's not needed, we waste a few minutes of deploy time. If we skip when
  # it IS needed, we ship mismatched schema/code and break all tenants with
  # 'Unknown column' errors. Thus, any error or unknown state defaults to
  # migrating. There is deliberately no force-skip override.

  # If the stamp is empty (e.g. on first run when the stamp file does not yet
  # exist on the production server), we must default to migrating.
  if [ -z "$from_sha" ]; then
    echo "migrate_needed fallback: from_sha is empty" >&2
    return 0
  fi

  # Since production is not a git repository, the stamp commit might not exist
  # in this clone (e.g. if the local clone is not up to date or the commit was
  # force-pushed/rewritten). Without this commit, we cannot evaluate the git diff,
  # so we must default to migrating.
  if ! git -C "$repo_dir" cat-file -e "${from_sha}^{commit}" 2>/dev/null; then
    echo "migrate_needed fallback: from_sha '${from_sha}' is not a commit reachable in this repo" >&2
    return 0
  fi

  # If the git diff command fails for any other reason (e.g. workspace issues or
  # invalid refs), we cannot guarantee the schema hasn't changed and must migrate.
  if ! git -C "$repo_dir" diff --name-only "$from_sha" "$to_ref" >/dev/null 2>&1; then
    echo "migrate_needed fallback: git diff command failed" >&2
    return 0
  fi

  local files
  files=$(migrate_trigger_files "$from_sha" "$to_ref")
  if [ -n "$files" ]; then
    return 0
  else
    return 1
  fi
}

