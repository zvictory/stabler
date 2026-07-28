from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "public/js/components/AuthTransitionOverlay.vue"
LOGIN = ROOT / "public/js/pages/Login.vue"


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

