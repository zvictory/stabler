import os
import subprocess


def run_gate(cmd):
	# Ensure this runs in the repo root
	# Since pytest runs from apps/stabler/stabler/tests/ usually, or apps/stabler,
	# we explicitly use APP_DIR assuming we're inside frappe-bench-local/apps/stabler
	app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
	env = os.environ.copy()
	env["APP_DIR"] = app_dir

	script_path = os.path.join(app_dir, "scripts", "migrate_gate.sh")

	result = subprocess.run(
		["bash", "-c", f"source '{script_path}'; {cmd}"], capture_output=True, text=True, env=env, cwd=app_dir
	)
	return result


class TestDeployMigrateGate:
	def test_b16e03b_not_needed(self):
		"""
		A release that changes only Vue or Python code (like b16e03b changing a Vue file)
		does not need a DDL migration. Skipping migrate here saves time because no
		database columns or patches are affected.
		"""
		result = run_gate("if migrate_needed b16e03b~1 b16e03b; then echo NEEDED; else echo NOT_NEEDED; fi")
		assert result.returncode == 0
		assert "NOT_NEEDED" in result.stdout

	def test_c519ddc_needed(self):
		"""
		A release that changes a doctype definition (like c519ddc changing proforma_invoice.json)
		needs a DDL migration. Skipping DDL here ships a column that exists in code but not in
		the databases, leading to 'Unknown column' errors.
		"""
		trigger = run_gate("migrate_trigger_files c519ddc~1 c519ddc")
		assert trigger.returncode == 0
		assert trigger.stdout.strip() == "stabler/stabler/doctype/proforma_invoice/proforma_invoice.json"

		result = run_gate("if migrate_needed c519ddc~1 c519ddc; then echo NEEDED; else echo NOT_NEEDED; fi")
		assert result.returncode == 0
		assert "NEEDED" in result.stdout

	def test_empty_sha_fallback(self):
		"""
		If the start SHA is empty (e.g. stamp missing on first run), we must default to migrating.
		Failing safely prevents skipping DDL when the previous state is unknown.
		"""
		result = run_gate("if migrate_needed '' HEAD; then echo NEEDED; else echo NOT_NEEDED; fi")
		assert result.returncode == 0
		assert "NEEDED" in result.stdout
		assert "migrate_needed fallback: from_sha is empty" in result.stderr

	def test_unknown_sha_fallback(self):
		"""
		If the start SHA is not reachable (e.g. prod has a stamp not in our clone), we must default
		to migrating.
		"""
		result = run_gate(
			"if migrate_needed deadbeefdeadbeefdeadbeefdeadbeefdeadbeef HEAD; then echo NEEDED; else echo NOT_NEEDED; fi"
		)
		assert result.returncode == 0
		assert "NEEDED" in result.stdout
		assert (
			"migrate_needed fallback: from_sha 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef' is not a commit reachable in this repo"
			in result.stderr
		)

	def test_same_sha_not_needed(self):
		"""
		If from_sha and to_ref are identical, the diff is empty. We don't need to migrate.
		"""
		result = run_gate("if migrate_needed HEAD HEAD; then echo NEEDED; else echo NOT_NEEDED; fi")
		assert result.returncode == 0
		assert "NOT_NEEDED" in result.stdout
