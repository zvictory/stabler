import csv
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "public/js/components/AuthTransitionOverlay.vue"
LOGIN = ROOT / "public/js/pages/Login.vue"
SIDEBAR = ROOT / "public/js/components/Sidebar.vue"
TRANSLATIONS = ROOT / "translations"


class TestAuthTransitionSpa(unittest.TestCase):
	def test_overlay_is_full_screen_accessible_and_motion_safe(self):
		source = OVERLAY.read_text(encoding="utf-8")
		self.assertIn('role="status"', source)
		self.assertIn('aria-live="polite"', source)
		self.assertIn("position: fixed", source)
		self.assertIn("inset: 0", source)
		self.assertIn("prefers-reduced-motion", source)
		self.assertNotIn("<button", source)

	def test_login_uses_one_safe_terminal_navigation(self):
		source = LOGIN.read_text(encoding="utf-8")
		self.assertIn("sanitizeStablerRedirect", source)
		self.assertIn("AuthTransitionOverlay", source)
		self.assertIn("transitioning.value = true", source)
		self.assertIn("window.location.replace(", source)
		self.assertEqual(source.count("window.location.replace("), 1)
		self.assertNotIn("window.location.href", source)
		self.assertNotIn("window.location.reload", source)

	def test_login_failure_restores_interaction(self):
		source = LOGIN.read_text(encoding="utf-8")
		self.assertIn("transitioning.value = false", source)
		self.assertIn('role="alert"', source)
		self.assertIn(':disabled="loading || transitioning"', source)

	def test_logout_is_busy_single_fire_and_recoverable(self):
		source = SIDEBAR.read_text(encoding="utf-8")
		self.assertIn("logoutPending.value = true", source)
		self.assertIn("if (logoutPending.value) return", source)
		self.assertIn("await logoutSession()", source)
		self.assertIn('window.location.replace("/stabler#/login")', source)
		self.assertIn("logoutPending.value = false", source)
		self.assertIn("toast.error", source)
		self.assertIn("AuthTransitionOverlay", source)
		self.assertNotIn('await call("logout")', source)
		self.assertNotIn('window.location.href = "/login"', source)

	def test_all_auth_transition_keys_are_translated(self):
		new_keys = [
			"Session opened",
			"Preparing your Dashboard…",
			"Signing out",
			"Signing out securely…",
			"Could not sign out. Please try again.",
		]

		languages = ["en", "ru", "uz", "uzc", "tr"]
		for lang in languages:
			csv_path = TRANSLATIONS / f"{lang}.csv"
			self.assertTrue(csv_path.exists(), f"Missing translation file for {lang}")
			translations = {}
			with csv_path.open("r", encoding="utf-8") as f:
				reader = csv.reader(f)
				for row in reader:
					if len(row) >= 2:
						translations[row[0].strip()] = row[1].strip()

			for key in new_keys:
				self.assertIn(key, translations, f"Key '{key}' missing in {lang}.csv")
				self.assertTrue(bool(translations[key]), f"Key '{key}' has empty translation in {lang}.csv")

