from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "public/js/components/AuthTransitionOverlay.vue"


class TestAuthTransitionSpa(unittest.TestCase):
	def test_overlay_is_full_screen_accessible_and_motion_safe(self):
		source = OVERLAY.read_text(encoding="utf-8")
		self.assertIn('role="status"', source)
		self.assertIn('aria-live="polite"', source)
		self.assertIn("position: fixed", source)
		self.assertIn("inset: 0", source)
		self.assertIn("prefers-reduced-motion", source)
		self.assertNotIn("<button", source)
