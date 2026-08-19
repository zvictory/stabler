"""Static guard: `stabler/patches.txt` may only ever grow at the end.

Frappe records "this patch already ran" as a Patch Log row keyed by the patch's
dotted module path — nothing else. Rename a patch module, and every site's Patch
Log has no row for the new name, so the renamed patch runs a second time on the
next `bench migrate`. Reorder or move a patch across the `[pre_model_sync]` /
`[post_model_sync]` marker and you change whether the columns it touches exist
yet when it runs. None of this raises an error; it just silently re-executes
code that assumed it would run once, on every one of the seven production
tenants.

This nearly shipped: commit bf8b4a3 renamed `v87_lcv_distribution_method` to
`v88_lcv_distribution_method` only because a human noticed, by chance, that two
unmerged branches had both claimed `v87`. Renumbering was "free" only because
neither branch's patch had ever run on a real site yet — the same rename on an
already-deployed patch would have been silent data corruption. No automated
check caught it either way.

This test pins `stabler/patches.txt` against a snapshot taken at a known-good
state (`stabler/tests/data/patches_snapshot.txt`) and requires the *sequence* of
(section, patch) pairs in the snapshot to be an exact, in-order prefix of the
sequence in the live file. That means:

  - appending a new patch after the last line is invisible to this test and
    stays green — that is the only normal way `patches.txt` grows.
  - renaming, reordering, removing, or moving any existing entry across the
    pre/post marker changes the sequence at that position, so it no longer
    matches the pinned prefix, and the test goes red.

To add a patch: append it to the end of `stabler/patches.txt` (respecting the
`[pre_model_sync]` / `[post_model_sync]` split), then refresh the pin so the new
tail is protected too:

    cp stabler/patches.txt stabler/tests/data/patches_snapshot.txt

If instead you hit red because you renamed, reordered, or removed an existing
line: don't touch the snapshot. Either put the entry back exactly as it was, or
if the rename is truly necessary, confirm no site has ever run that patch
(check Patch Log on every tenant) and make the change provably safe to
re-run — the guard is telling you the truth, not getting in your way.
"""

from __future__ import annotations

import os
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.dirname(_TESTS_DIR)  # .../stabler
_PATCHES_TXT = os.path.join(_APP_ROOT, "patches.txt")
_SNAPSHOT_TXT = os.path.join(_TESTS_DIR, "data", "patches_snapshot.txt")


def _parse_patches(text: str) -> list[tuple[str | None, str]]:
	"""Turn patches.txt content into an ordered list of (section, patch) pairs.

	`section` is the most recent `[pre_model_sync]` / `[post_model_sync]` marker
	line, carried forward, so moving a patch across the marker changes its pair
	even though the patch name is unchanged. Blank lines are ignored; order of
	the remaining lines is exactly what gets compared.
	"""
	section: str | None = None
	entries: list[tuple[str | None, str]] = []
	for raw in text.splitlines():
		line = raw.strip()
		if not line:
			continue
		if line.startswith("[") and line.endswith("]"):
			section = line
			continue
		entries.append((section, line))
	return entries


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


def _first_divergence(pinned: list[tuple[str | None, str]], live: list[tuple[str | None, str]]) -> str:
	for i, expected in enumerate(pinned):
		got = live[i] if i < len(live) else None
		if got != expected:
			return f"at position {i}: snapshot has {expected!r}, stabler/patches.txt has {got!r}"
	return "snapshot is a prefix of stabler/patches.txt (no divergence found)"


class TestPatchesPin(unittest.TestCase):
	"""stabler/patches.txt may only grow by appending at the end."""

	def test_snapshot_is_an_exact_prefix_of_patches_txt(self):
		pinned = _parse_patches(_read(_SNAPSHOT_TXT))
		live = _parse_patches(_read(_PATCHES_TXT))

		self.assertEqual(
			live[: len(pinned)],
			pinned,
			"stabler/patches.txt has diverged from the pinned snapshot "
			"(stabler/tests/data/patches_snapshot.txt): "
			+ _first_divergence(pinned, live)
			+ ".\n\nA patch was renamed, reordered, removed, or moved across the "
			"[pre_model_sync]/[post_model_sync] marker. Frappe's Patch Log is "
			"keyed by dotted module path, so any of those changes make every "
			"site run the patch again on its next migrate (see bf8b4a3, where "
			"this nearly happened for real).\n\n"
			"If this is a plain append of a new patch at the end of the file, "
			"refresh the pin:\n"
			"    cp stabler/patches.txt stabler/tests/data/patches_snapshot.txt\n"
			"Otherwise: put the entry back exactly as it was, or prove the "
			"rename/move is safe (no site has ever run that patch) before "
			"changing it.",
		)

	def test_guard_is_not_vacuous(self):
		"""A snapshot that drifted to empty, or a parser matching nothing, would
		make the pin test above pass no matter what patches.txt says — an empty
		list is a prefix of anything. Fail loudly if that has happened, and
		prove the comparison itself actually distinguishes a mutated sequence
		from the original.
		"""
		pinned = _parse_patches(_read(_SNAPSHOT_TXT))

		self.assertGreater(
			len(pinned),
			50,
			"stabler/tests/data/patches_snapshot.txt parsed to "
			f"{len(pinned)} entries — the snapshot or the parser has drifted "
			"and this guard is no longer protecting anything.",
		)
		sections = {section for section, _ in pinned}
		self.assertEqual(
			sections,
			{"[pre_model_sync]", "[post_model_sync]"},
			"expected exactly the two known markers in the pinned snapshot, "
			f"got {sorted(s for s in sections if s)!r}",
		)

		# Simulate the three dangerous edits against a copy and confirm the
		# same comparison the real test uses actually catches each one.
		mutated_rename = list(pinned)
		section, name = mutated_rename[-1]
		mutated_rename[-1] = (section, name + "_renamed")
		self.assertNotEqual(mutated_rename, pinned, "rename was not detected")

		mutated_reorder = list(pinned)
		mutated_reorder[-1], mutated_reorder[-2] = mutated_reorder[-2], mutated_reorder[-1]
		self.assertNotEqual(mutated_reorder, pinned, "reorder was not detected")

		mutated_remove = list(pinned)
		del mutated_remove[len(mutated_remove) // 2]
		self.assertNotEqual(mutated_remove, pinned, "removal was not detected")

		mutated_marker = list(pinned)
		for i, (section, name) in enumerate(mutated_marker):
			if section == "[post_model_sync]":
				mutated_marker[i] = ("[pre_model_sync]", name)
				break
		self.assertNotEqual(mutated_marker, pinned, "move across pre/post marker was not detected")


if __name__ == "__main__":
	unittest.main()
