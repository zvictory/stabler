import csv
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "public/js/components/AuthTransitionOverlay.vue"
LOGIN = ROOT / "public/js/pages/Login.vue"
SIDEBAR = ROOT / "public/js/components/Sidebar.vue"
AUTH_REDIRECT = ROOT / "public/js/composables/authRedirect.js"
BUNDLE = ROOT / "public/js/stabler.bundle.js"
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
		"""Login must leave via hardRedirect, never a bare hash replace.

		The SPA and its login page share one document at /stabler; a hash-only
		`window.location.replace('/stabler#/...')` fires hashchange without
		reloading, so window.__STABLER__ keeps the Guest boot and the router
		guard bounces straight back to /login (regression 8e984ee: login only
		completed after a manual F5). hardRedirect pairs the replace with a
		document reload so www/stabler.py re-renders the boot.
		"""
		source = LOGIN.read_text(encoding="utf-8")
		self.assertIn("sanitizeStablerRedirect", source)
		self.assertIn("AuthTransitionOverlay", source)
		self.assertIn("transitioning.value = true", source)
		self.assertIn("hardRedirect(target)", source)
		self.assertNotIn("window.location.replace(", source)
		self.assertNotIn("window.location.href", source)

	def test_hard_redirect_replaces_and_reloads(self):
		source = AUTH_REDIRECT.read_text(encoding="utf-8")
		self.assertIn("export function hardRedirect", source)
		self.assertIn("window.location.replace(`/stabler#${hashTarget}`)", source)
		self.assertIn("window.location.reload()", source)

	def test_bundle_listens_for_forbidden_and_verifies_session_death(self):
		"""client.js dispatches stabler:forbidden on 403; someone must listen.

		Without this listener an expired session leaves the app looking alive
		while every call 403s. The listener must probe the session first —
		a genuine PermissionError on one endpoint must NOT log the user out.
		"""
		source = BUNDLE.read_text(encoding="utf-8")
		self.assertIn('addEventListener("stabler:forbidden"', source)
		self.assertIn("frappe.auth.get_logged_user", source)
		self.assertIn("hardRedirect", source)
		self.assertIn("session-expired=1", source)

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
		self.assertIn('hardRedirect("/login")', source)
		self.assertNotIn('window.location.replace("/stabler#/login")', source)
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
			"Remember me",
			"Your session has expired. Please sign in again.",
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
