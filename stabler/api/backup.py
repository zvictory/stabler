"""Backup & disaster-recovery API for Stabler.

Closes the "no tested off-box backup" gap with an in-Stabler control surface:

  * On-demand and scheduled backups (DB, optionally +files) via Frappe's own
    backup machinery — no shelling out, no reinventing dumps.
  * Retention that always keeps a minimum number of sets (you are never left
    with zero), pruning older ones beyond a day window.
  * Off-box copy to **Google Drive** via a service account (server-to-server,
    no interactive OAuth), Shared-Drive aware.
  * A restore-test tracker — because an untested backup is not a backup. The UI
    nags when the last successful restore test is older than the interval.

All decisions (which files form a set, what to prune, whether a restore test is
overdue) live in the frappe-free ``_backup_rules`` module and are unit tested.

Secrets: the Google service-account JSON is NEVER stored in a doctype field.
It is read from ``site_config.json`` key ``stabler_gdrive_service_account``
(an absolute path to the JSON, or the JSON object inline).
"""
from __future__ import annotations

import datetime
import os

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from stabler.api._backup_rules import (
	group_backup_sets,
	human_size,
	parse_backup_timestamp,
	prune_by_policy,
	restore_test_overdue,
	restore_test_schedule,
	select_for_retention,
	verify_checksum,
)

_SETTINGS = "Stabler Settings"


def _require_admin() -> None:
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _cfg() -> dict:
	g = frappe.db.get_single_value
	has = frappe.db.exists("DocType", _SETTINGS)
	return {
		"enabled": bool(int((has and g(_SETTINGS, "enable_scheduled_backup")) or 0)) if has else True,
		"with_files": bool(int((has and g(_SETTINGS, "backup_with_files")) or 0)),
		"retention_days": int((has and g(_SETTINGS, "backup_retention_days")) or 14),
		"to_drive": bool(int((has and g(_SETTINGS, "backup_to_google_drive")) or 0)),
		"folder_id": (has and g(_SETTINGS, "gdrive_folder_id")) or "",
		"restore_interval": int((has and g(_SETTINGS, "restore_test_interval_days")) or 90),
		"last_restore_test": (has and g(_SETTINGS, "last_restore_test_date")) or None,
	}


def _set(field: str, value) -> None:
	if frappe.db.exists("DocType", _SETTINGS):
		frappe.db.set_single_value(_SETTINGS, field, value)


# --------------------------------------------------------------------------- #
# Local backups
# --------------------------------------------------------------------------- #
def _backups_path() -> str:
	from frappe.utils.backups import get_backup_path

	return get_backup_path()


def _list_backup_files() -> list[dict]:
	path = _backups_path()
	out: list[dict] = []
	if not os.path.isdir(path):
		return out
	for fn in os.listdir(path):
		full = os.path.join(path, fn)
		if not os.path.isfile(full):
			continue
		if not parse_backup_timestamp(fn):
			continue
		st = os.stat(full)
		out.append(
			{
				"name": fn,
				"size": st.st_size,
				"modified": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
			}
		)
	return out


@frappe.whitelist()
def list_backups() -> dict:
	"""Backup sets on disk, newest first, with human sizes."""
	_require_admin()
	sets = group_backup_sets(_list_backup_files())
	for s in sets:
		s["size_label"] = human_size(s["total_size"])
	return {"sets": sets, "count": len(sets), "path": _backups_path()}


@frappe.whitelist()
def create_backup(with_files: int = 0) -> dict:
	"""Create a backup now. DB always; files when with_files=1."""
	_require_admin()
	from frappe.utils.backups import new_backup

	want_files = bool(int(with_files or 0))
	backup = new_backup(
		ignore_files=not want_files,
		force=True,
	)
	_set("last_backup_at", now_datetime())
	frappe.db.commit()

	result = {
		"database": os.path.basename(backup.backup_path_db or ""),
		"with_files": want_files,
	}
	if want_files:
		result["files"] = os.path.basename(backup.backup_path_files or "")
		result["private_files"] = os.path.basename(backup.backup_path_private_files or "")
	return result


@frappe.whitelist()
def apply_retention() -> dict:
	"""Prune old backup sets per the configured policy. Returns deleted keys."""
	_require_admin()
	cfg = _cfg()
	files = _list_backup_files()
	sets = group_backup_sets(files)
	keys = [s["key"] for s in sets]
	now_ts = now_datetime().strftime("%Y%m%d_%H%M%S")
	to_delete = set(
		select_for_retention(keys, keep_days=cfg["retention_days"], keep_min=3, now_ts=now_ts)
	)
	path = _backups_path()
	deleted = []
	for f in files:
		if parse_backup_timestamp(f["name"]) in to_delete:
			try:
				os.remove(os.path.join(path, f["name"]))
				deleted.append(f["name"])
			except OSError:
				frappe.log_error(f"backup retention: could not delete {f['name']}", "stabler.backup")
	return {"deleted": deleted, "count": len(deleted)}


# --------------------------------------------------------------------------- #
# Restore-test tracker
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def mark_restore_tested(note: str | None = None) -> dict:
	"""Record that a restore was successfully tested today (DR hygiene)."""
	_require_admin()
	_set("last_restore_test_date", today())
	frappe.db.commit()
	return {"last_restore_test_date": today()}


# --------------------------------------------------------------------------- #
# Google Drive (service account, Shared-Drive aware)
# --------------------------------------------------------------------------- #
def _gdrive_service_account():
	"""Return the parsed service-account dict from site_config, or None.

	site_config key ``stabler_gdrive_service_account`` may be an absolute path
	to the JSON file, or the JSON object inline.
	"""
	import json

	raw = frappe.conf.get("stabler_gdrive_service_account")
	if not raw:
		return None
	if isinstance(raw, dict):
		return raw
	if isinstance(raw, str):
		if os.path.isfile(raw):
			with open(raw, encoding="utf-8") as fh:
				return json.load(fh)
		try:
			return json.loads(raw)
		except Exception:
			return None
	return None


def _gdrive_client(sa: dict):
	"""Build a Drive v3 client from a service-account dict. Raises if libs missing."""
	try:
		from google.oauth2 import service_account
		from googleapiclient.discovery import build
	except Exception as exc:  # pragma: no cover - depends on host libs
		frappe.throw(
			_(
				"Google Drive libraries are not installed on the server. "
				"Run: pip install google-api-python-client google-auth"
			)
			+ f" ({exc})"
		)
	creds = service_account.Credentials.from_service_account_info(
		sa, scopes=["https://www.googleapis.com/auth/drive.file"]
	)
	return build("drive", "v3", credentials=creds, cache_discovery=False)


@frappe.whitelist()
def gdrive_status() -> dict:
	"""Is Google Drive backup configured and reachable?"""
	_require_admin()
	cfg = _cfg()
	sa = _gdrive_service_account()
	libs = True
	try:
		import google.oauth2.service_account
		import googleapiclient.discovery
	except Exception:
		libs = False
	return {
		"enabled": cfg["to_drive"],
		"folder_id": cfg["folder_id"],
		"service_account_configured": bool(sa),
		"service_account_email": (sa or {}).get("client_email") if sa else None,
		"libraries_installed": libs,
		"last_upload_at": frappe.db.get_single_value(_SETTINGS, "last_gdrive_upload_at")
		if frappe.db.exists("DocType", _SETTINGS)
		else None,
		"ready": bool(cfg["to_drive"] and cfg["folder_id"] and sa and libs),
	}


def _upload_file_to_drive(service, folder_id: str, path: str) -> str:
	from googleapiclient.http import MediaFileUpload

	meta = {"name": os.path.basename(path)}
	if folder_id:
		meta["parents"] = [folder_id]
	media = MediaFileUpload(path, resumable=True)
	created = (
		service.files()
		.create(body=meta, media_body=media, fields="id", supportsAllDrives=True)
		.execute()
	)
	return created.get("id")


@frappe.whitelist()
def upload_latest_to_drive() -> dict:
	"""Upload the newest backup set's files to the configured Drive folder."""
	_require_admin()
	cfg = _cfg()
	if not cfg["folder_id"]:
		frappe.throw(_("Set a Google Drive folder ID first."))
	sa = _gdrive_service_account()
	if not sa:
		frappe.throw(
			_("No Google service account configured (site_config: stabler_gdrive_service_account).")
		)
	sets = group_backup_sets(_list_backup_files())
	if not sets:
		frappe.throw(_("No local backups to upload. Create one first."))

	service = _gdrive_client(sa)
	path = _backups_path()
	uploaded = []
	for fn in sets[0]["files"]:
		fid = _upload_file_to_drive(service, cfg["folder_id"], os.path.join(path, fn))
		uploaded.append({"name": fn, "drive_id": fid})
	_set("last_gdrive_upload_at", now_datetime())
	frappe.db.commit()
	return {"uploaded": uploaded, "count": len(uploaded), "set": sets[0]["key"]}


# --------------------------------------------------------------------------- #
# Status (for the dashboard) + scheduled task
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def backup_status() -> dict:
	"""Everything the Backup & DR page needs in one call."""
	_require_admin()
	cfg = _cfg()
	sets = group_backup_sets(_list_backup_files())
	last_backup = (
		frappe.db.get_single_value(_SETTINGS, "last_backup_at")
		if frappe.db.exists("DocType", _SETTINGS)
		else None
	)
	overdue = restore_test_overdue(
		str(cfg["last_restore_test"]) if cfg["last_restore_test"] else None,
		interval_days=cfg["restore_interval"],
		today=today(),
	)
	return {
		"config": cfg,
		"set_count": len(sets),
		"latest": sets[0] if sets else None,
		"last_backup_at": str(last_backup) if last_backup else None,
		"total_size_label": human_size(sum(s["total_size"] for s in sets)),
		"restore_test_overdue": overdue,
		"last_restore_test": str(cfg["last_restore_test"]) if cfg["last_restore_test"] else None,
	}



# --------------------------------------------------------------------------- #
# Phase 2: policy-based pruning (daily + weekly retention tiers)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def apply_retention_policy(
	keep_daily: int = 7,
	keep_weekly: int = 4,
) -> dict:
	"""Prune backups per a daily + weekly retention policy.

	Keeps the newest ``keep_daily`` sets (daily tier) and one set per ISO
	calendar week for the most recent ``keep_weekly`` weeks (weekly tier).
	Everything outside both windows is deleted.  Returns the list of deleted
	file names.
	"""
	_require_admin()
	files = _list_backup_files()
	sets = group_backup_sets(files)
	keys = [s["key"] for s in sets]
	now_ts = now_datetime().strftime("%Y%m%d_%H%M%S")
	to_delete = set(
		prune_by_policy(
			keys,
			keep_daily=int(keep_daily),
			keep_weekly=int(keep_weekly),
			now_ts=now_ts,
		)
	)
	path = _backups_path()
	deleted = []
	for f in files:
		if parse_backup_timestamp(f["name"]) in to_delete:
			try:
				os.remove(os.path.join(path, f["name"]))
				deleted.append(f["name"])
			except OSError:
				frappe.log_error(f"backup retention_policy: could not delete {f['name']}", "stabler.backup")
	return {"deleted": deleted, "count": len(deleted)}


# --------------------------------------------------------------------------- #
# Phase 2: restore-test scheduling
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def restore_test_due() -> dict:
	"""Return scheduling info for the next restore-test (without marking it done)."""
	_require_admin()
	cfg = _cfg()
	return restore_test_schedule(
		str(cfg["last_restore_test"]) if cfg["last_restore_test"] else None,
		interval_days=cfg["restore_interval"],
		today=today(),
	)


# --------------------------------------------------------------------------- #
# Phase 2: checksum verification
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def check_backup_checksum(
	filename: str,
	expected_hash: str,
	algorithm: str = "sha256",
) -> dict:
	"""Verify a backup file on disk against an expected checksum.

	Reads the file from the local backup directory, computes its hash, and
	returns pass/fail via the pure ``verify_checksum`` helper.

	``algorithm`` must be a name accepted by Python's ``hashlib`` module
	(e.g. ``sha256``, ``sha512``, ``md5``).  Default is ``sha256``.
	"""
	_require_admin()
	import hashlib

	if not filename or "/" in filename or ".." in filename:
		frappe.throw(_("Invalid filename."))
	path = os.path.join(_backups_path(), filename)
	if not os.path.isfile(path):
		frappe.throw(_("Backup file not found: {0}").format(filename))

	try:
		h = hashlib.new(algorithm)
	except ValueError:
		frappe.throw(_("Unknown hash algorithm: {0}").format(algorithm))

	try:
		with open(path, "rb") as fh:
			for chunk in iter(lambda: fh.read(1 << 20), b""):
				h.update(chunk)
		actual = h.hexdigest()
	except OSError as exc:
		frappe.throw(_("Could not read backup file: {0}").format(str(exc)))

	result = verify_checksum(expected_hash, actual, algorithm=algorithm)
	result["filename"] = filename
	if not result["ok"]:
		frappe.log_error(
			f"Checksum {result['reason']} for {filename}: expected={expected_hash!r} actual={actual!r}",
			"stabler.backup checksum",
		)
	return result


def run_scheduled_backup() -> None:
	"""Daily scheduler entrypoint: backup → prune → upload (best effort).

	Never raises into the scheduler; a failure is logged so the worker keeps
	running the rest of the daily jobs.
	"""
	try:
		cfg = _cfg()
		if not cfg["enabled"]:
			return
		from frappe.utils.backups import new_backup

		new_backup(ignore_files=not cfg["with_files"], force=True)
		_set("last_backup_at", now_datetime())
		frappe.db.commit()

		# Prune locally.
		try:
			files = _list_backup_files()
			keys = [s["key"] for s in group_backup_sets(files)]
			now_ts = now_datetime().strftime("%Y%m%d_%H%M%S")
			to_delete = set(
				select_for_retention(keys, keep_days=cfg["retention_days"], keep_min=3, now_ts=now_ts)
			)
			path = _backups_path()
			for f in files:
				if parse_backup_timestamp(f["name"]) in to_delete:
					try:
						os.remove(os.path.join(path, f["name"]))
					except OSError:
						pass
		except Exception:
			frappe.log_error(frappe.get_traceback(), "stabler.backup retention")

		# Off-box copy.
		if cfg["to_drive"] and cfg["folder_id"] and _gdrive_service_account():
			try:
				upload_latest_to_drive()
			except Exception:
				frappe.log_error(frappe.get_traceback(), "stabler.backup gdrive upload")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "stabler.backup scheduled")
