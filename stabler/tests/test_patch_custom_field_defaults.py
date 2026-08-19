"""Every Custom Field `default` a patch declares must be a string.

Measured on zuma 2026-08-19. The site was created after all 903 patches existed, so
Frappe stamped them applied at install without running one — and Custom Fields, unlike
doctype JSON, exist only because patch code creates them. Re-running the patches to
create the 206 missing fields worked; running them a SECOND time did not:

    v72_crm_activity_automation_fields  TypeError: expected string or bytes-like object, got 'int'
    v73_communication_retry_fields      TypeError: expected string or bytes-like object, got 'int'

Both declare `"default": 1` on an Int field. The insert path never notices — the
column write coerces. The update path does: an existing field sends
`create_custom_fields` through `doc.save()`, which builds a Version diff, which calls
`format_value` on the changed field, which runs `BLOCK_TAGS_PATTERN.search(value)` —
and `re` refuses an int (`frappe/utils/formatters.py:108`).

So the failure appears only on the second run, which is precisely the run the house
rule requires to be safe: "Every patch must be **idempotent**." A patch that installs
once and throws forever after is not idempotent; it is a patch whose breakage is
hidden until someone repairs a site.

This locks the shape, not the behaviour — no bench, no DB.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_patch_custom_field_defaults -v
"""

from __future__ import annotations

import ast
import pathlib
import unittest

PATCHES = pathlib.Path(__file__).resolve().parents[1] / "patches"


def _custom_field_defaults() -> list[tuple[str, int, str, object]]:
	"""(patch, lineno, fieldname, default) for every Custom Field spec carrying a default."""
	found = []
	for path in sorted(PATCHES.glob("*.py")):
		tree = ast.parse(path.read_text(encoding="utf-8"))
		for node in ast.walk(tree):
			if not isinstance(node, ast.Dict):
				continue
			pairs = {
				k.value: v
				for k, v in zip(node.keys, node.values, strict=True)
				if isinstance(k, ast.Constant) and isinstance(k.value, str)
			}
			# A Custom Field spec is the dict that names a field.
			if "fieldname" not in pairs or "default" not in pairs:
				continue
			name_node = pairs["fieldname"]
			default = pairs["default"]
			found.append(
				(
					path.name,
					default.lineno,
					name_node.value if isinstance(name_node, ast.Constant) else "?",
					default.value if isinstance(default, ast.Constant) else None,
				)
			)
	return found


class PatchCustomFieldDefaultsTest(unittest.TestCase):
	def test_the_scan_finds_something_to_check(self):
		# Without this, a broken extractor turns the real assertion below into a
		# test that passes because it looked at nothing.
		self.assertGreater(len(_custom_field_defaults()), 5)

	def test_every_declared_default_is_a_string(self):
		offenders = [
			f"{patch}:{line} {fieldname} -> {default!r} ({type(default).__name__})"
			for patch, line, fieldname, default in _custom_field_defaults()
			if not isinstance(default, str)
		]
		self.assertEqual(
			offenders,
			[],
			"A non-string Custom Field default survives the first run and raises "
			"TypeError on every one after it, so the patch stops being re-runnable:\n  "
			+ "\n  ".join(offenders),
		)


if __name__ == "__main__":
	unittest.main()
