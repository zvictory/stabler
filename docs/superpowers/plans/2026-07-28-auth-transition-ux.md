# Authentication Transition UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicate login navigation, reject Desk/external redirect targets, and provide recoverable full-screen progress during login and logout.

**Architecture:** Keep Frappe's native cookie-based login/logout contracts. Isolate redirect sanitization and HTTP calls in pure/testable modules, share one presentational transition overlay between Login and Sidebar, and use exactly one `window.location.replace()` after each confirmed terminal action.

**Tech Stack:** Vue 3 Composition API, native Fetch API, Frappe session endpoints, Vue Router query input, Vitest in Node, Python static contract tests, ESLint.

## Global Constraints

- Never navigate to Frappe Desk (`/app/...` or `/desk/...`).
- Keep native Frappe credential verification and session-cookie behavior.
- Login and logout must show immediate full-screen progress.
- Failure must restore an interactive recovery path.
- Successful terminal actions perform exactly one `window.location.replace()`.
- No artificial minimum animation delay.
- New copy must be translated in `en`, `ru`, `uz`, `uzc`, and `tr`.
- Do not add dependencies or a browser-only test runner.

## File map

- `stabler/public/js/composables/authRedirect.js` — pure allowlist-based redirect sanitizer.
- `stabler/public/js/api/auth.js` — login/logout HTTP contracts and safe error extraction.
- `stabler/public/js/components/AuthTransitionOverlay.vue` — shared full-screen status UI.
- `stabler/public/js/pages/Login.vue` — authenticating and transitioning state machine.
- `stabler/public/js/components/Sidebar.vue` — recoverable logout state machine.
- `stabler/public/js/tests/authRedirect.spec.js` — redirect unit tests under Vitest.
- `stabler/public/js/tests/authApi.spec.js` — login/logout request unit tests.
- `stabler/tests/test_auth_transition_spa.py` — static Vue integration contract.
- Translation CSVs — localized status and retry copy.

---

### Task 1: Define and test the Stabler redirect boundary

**Files:**
- Create: `stabler/public/js/composables/authRedirect.js`
- Create: `stabler/public/js/tests/authRedirect.spec.js`

**Interfaces:**
- Produces: `sanitizeStablerRedirect(value: unknown) -> string`
- Fallback: `"/dashboard"`

- [ ] **Step 1: Write the failing redirect tests**

Create:

```javascript
import { describe, expect, it } from "vitest";
import { sanitizeStablerRedirect } from "../composables/authRedirect.js";

describe("sanitizeStablerRedirect", () => {
	it.each([
		["/dashboard", "/dashboard"],
		["/tender/my-tenders?status=open", "/tender/my-tenders?status=open"],
		["/reports", "/reports"],
	])("keeps known Stabler paths", (input, expected) => {
		expect(sanitizeStablerRedirect(input)).toBe(expected);
	});

	it.each([
		[undefined],
		[null],
		[""],
		["dashboard"],
		["//evil.example/path"],
		["https://evil.example/path"],
		["/\\evil.example/path"],
		["/app"],
		["/app/user/test@example.com"],
		["/desk"],
		["/desk/user/test@example.com"],
		["%2Fdesk%2Fuser%2Ftest%2540example.com"],
		["/%2F%2Fevil.example"],
		["/unknown-route"],
	])("falls back for unsafe or unknown input %#", (input) => {
		expect(sanitizeStablerRedirect(input)).toBe("/dashboard");
	});
});
```

- [ ] **Step 2: Run the test and confirm RED**

```bash
npm run test:js -- stabler/public/js/tests/authRedirect.spec.js
```

Expected: failure because `authRedirect.js` does not exist.

- [ ] **Step 3: Implement the pure sanitizer**

Create:

```javascript
const FALLBACK = "/dashboard";
const ALLOWED_ROOTS = new Set([
	"/dashboard",
	"/profile",
	"/reports",
	"/pos",
	"/sales",
	"/crm",
	"/sfa",
	"/marketing",
	"/purchasing",
	"/imports",
	"/tender",
	"/inventory",
	"/manufacturing",
	"/service",
	"/bpm",
	"/money",
	"/remittance",
	"/installment",
	"/hr",
]);

function decodeOnce(value) {
	try {
		return decodeURIComponent(value);
	} catch {
		return "";
	}
}

export function sanitizeStablerRedirect(value) {
	if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return FALLBACK;
	if (/[\u0000-\u001f\\]/.test(value)) return FALLBACK;

	const decoded = decodeOnce(value);
	if (!decoded || decoded.startsWith("//") || decoded !== value && /^(?:https?:|\/{2})/i.test(decoded)) return FALLBACK;

	const path = decoded.split(/[?#]/, 1)[0];
	if (path === "/app" || path.startsWith("/app/") || path === "/desk" || path.startsWith("/desk/")) return FALLBACK;

	const root = `/${path.split("/").filter(Boolean)[0] || ""}`;
	return ALLOWED_ROOTS.has(root) ? value : FALLBACK;
}
```

This permits query/hash suffixes only after the path passes the root allowlist.
It decodes once for inspection but returns the original safe SPA path.

- [ ] **Step 4: Run the focused unit test**

```bash
npm run test:js -- stabler/public/js/tests/authRedirect.spec.js
```

Expected: all cases pass.

- [ ] **Step 5: Commit the redirect boundary**

```bash
git add \
  stabler/public/js/composables/authRedirect.js \
  stabler/public/js/tests/authRedirect.spec.js
git commit -m "fix: constrain post-login redirects to Stabler"
```

---

### Task 2: Isolate native Frappe auth calls and build the overlay

**Files:**
- Create: `stabler/public/js/api/auth.js`
- Create: `stabler/public/js/tests/authApi.spec.js`
- Create: `stabler/public/js/components/AuthTransitionOverlay.vue`
- Create: `stabler/tests/test_auth_transition_spa.py`

**Interfaces:**
- Produces: `login(usr: string, pwd: string) -> Promise<object>`
- Produces: `logout() -> Promise<void>`
- Produces component props: `title: string`, `message: string`

- [ ] **Step 1: Write failing auth API tests**

Create:

```javascript
import { afterEach, describe, expect, it, vi } from "vitest";
import { login, logout } from "../api/auth.js";

afterEach(() => {
	vi.unstubAllGlobals();
});

it("posts credentials to Frappe login with same-origin cookies", async () => {
	const fetch = vi.fn().mockResolvedValue({
		ok: true,
		json: async () => ({ message: "Logged In" }),
	});
	vi.stubGlobal("fetch", fetch);

	await login("user@example.com", "secret");

	expect(fetch).toHaveBeenCalledWith("/api/method/login", expect.objectContaining({
		method: "POST",
		credentials: "same-origin",
	}));
	expect(fetch.mock.calls[0][1].body.toString()).toBe("usr=user%40example.com&pwd=secret");
});

it("uses the documented GET logout endpoint", async () => {
	const fetch = vi.fn().mockResolvedValue({ ok: true });
	vi.stubGlobal("fetch", fetch);

	await logout();

	expect(fetch).toHaveBeenCalledWith("/api/method/logout", {
		method: "GET",
		credentials: "same-origin",
		headers: { Accept: "application/json" },
	});
});

it("rejects failed logout instead of pretending the session ended", async () => {
	vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
	await expect(logout()).rejects.toThrow("Sign out failed");
});
```

- [ ] **Step 2: Run the auth API test and confirm RED**

```bash
npm run test:js -- stabler/public/js/tests/authApi.spec.js
```

Expected: failure because `api/auth.js` does not exist.

- [ ] **Step 3: Implement the native auth wrapper**

Create `auth.js` with:

```javascript
function credentialsBody(usr, pwd) {
	const body = new URLSearchParams();
	body.append("usr", usr);
	body.append("pwd", pwd);
	return body;
}

export async function login(usr, pwd) {
	const response = await fetch("/api/method/login", {
		method: "POST",
		credentials: "same-origin",
		headers: {
			Accept: "application/json",
			"Content-Type": "application/x-www-form-urlencoded",
		},
		body: credentialsBody(usr, pwd),
	});
	const payload = await response.json().catch(() => ({}));
	if (!response.ok || payload.message !== "Logged In") {
		const error = new Error(payload.message || "Invalid username or password.");
		error.response = payload;
		throw error;
	}
	return payload;
}

export async function logout() {
	const response = await fetch("/api/method/logout", {
		method: "GET",
		credentials: "same-origin",
		headers: { Accept: "application/json" },
	});
	if (!response.ok) throw new Error("Sign out failed");
}
```

Preserve the current safe parsing of `_server_messages` by moving it into a
private `extractServerMessage(payload)` helper in this module and using it in
`login`; do not expose raw traceback text.

- [ ] **Step 4: Write the overlay static contract**

Create `test_auth_transition_spa.py`:

```python
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
```

- [ ] **Step 5: Create `AuthTransitionOverlay.vue`**

Use:

```vue
<script setup>
defineProps({
	title: { type: String, required: true },
	message: { type: String, required: true },
});
</script>

<template>
	<Teleport to="body">
		<div class="auth-transition" role="status" aria-live="polite" aria-atomic="true">
			<div class="auth-transition__content">
				<img src="/assets/stabler/icons/scale.svg" width="56" height="56" alt="" />
				<div class="auth-transition__spinner" aria-hidden="true"></div>
				<h1>{{ title }}</h1>
				<p>{{ message }}</p>
			</div>
		</div>
	</Teleport>
</template>
```

Scoped CSS uses `position: fixed; inset: 0; z-index: 1100`, the existing dark
navy visual language, an opaque-enough backdrop, and disables spinner animation
inside `@media (prefers-reduced-motion: reduce)`.

- [ ] **Step 6: Run focused tests**

```bash
npm run test:js -- stabler/public/js/tests/authApi.spec.js
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_auth_transition_spa -v
```

Expected: both commands pass.

- [ ] **Step 7: Commit auth primitives**

```bash
git add \
  stabler/public/js/api/auth.js \
  stabler/public/js/tests/authApi.spec.js \
  stabler/public/js/components/AuthTransitionOverlay.vue \
  stabler/tests/test_auth_transition_spa.py
git commit -m "feat: add safe auth transition primitives"
```

---

### Task 3: Replace duplicate login navigation with a state machine

**Files:**
- Modify: `stabler/public/js/pages/Login.vue`
- Modify: `stabler/tests/test_auth_transition_spa.py`

**Interfaces:**
- Consumes: `login` from `api/auth.js`
- Consumes: `sanitizeStablerRedirect`
- Consumes: `AuthTransitionOverlay`
- Terminal navigation: `window.location.replace(`/stabler#${target}`)`

- [ ] **Step 1: Write the failing Login integration contract**

Add:

```python
LOGIN = ROOT / "public/js/pages/Login.vue"

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
	self.assertIn(":disabled=\"loading || transitioning\"", source)
```

- [ ] **Step 2: Run the Login contract and confirm RED**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_auth_transition_spa.TestAuthTransitionSpa.test_login_uses_one_safe_terminal_navigation \
  stabler.tests.test_auth_transition_spa.TestAuthTransitionSpa.test_login_failure_restores_interaction -v
```

Expected: failure on duplicate `href` plus `reload` and missing overlay.

- [ ] **Step 3: Implement Login states**

Remove unused `useRouter`, `useSession`, and generic `call` imports. Add:

```javascript
import { nextTick, ref } from "vue";
import { useRoute } from "vue-router";
import { login } from "../api/auth.js";
import { sanitizeStablerRedirect } from "../composables/authRedirect.js";
import AuthTransitionOverlay from "../components/AuthTransitionOverlay.vue";

const transitioning = ref(false);
const errorSummary = ref(null);
```

Replace the successful path with:

```javascript
try {
	await login(username.value.trim(), password.value);
	transitioning.value = true;
	const target = sanitizeStablerRedirect(route.query["redirect-to"]);
	window.location.replace(`/stabler#${target}`);
} catch (err) {
	transitioning.value = false;
	error.value = err?.message || t("Invalid username or password.");
	await nextTick();
	errorSummary.value?.focus();
} finally {
	if (!transitioning.value) loading.value = false;
}
```

Bind `ref="errorSummary"` and `tabindex="-1"` to the existing error alert. Disable
all form controls while `loading || transitioning`.

- [ ] **Step 4: Render the terminal overlay**

Add:

```vue
<AuthTransitionOverlay
	v-if="transitioning"
	:title='t("Session opened")'
	:message='t("Preparing your Dashboard…")'
/>
```

Keep the current button spinner for the authenticating state; the full-screen
overlay starts only after the server confirms login.

- [ ] **Step 5: Run focused auth tests**

```bash
npm run test:js -- \
  stabler/public/js/tests/authRedirect.spec.js \
  stabler/public/js/tests/authApi.spec.js
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_auth_transition_spa -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit Login flow**

```bash
git add \
  stabler/public/js/pages/Login.vue \
  stabler/tests/test_auth_transition_spa.py
git commit -m "fix: make login transition single and visible"
```

---

### Task 4: Add recoverable logout progress and translated copy

**Files:**
- Modify: `stabler/public/js/components/Sidebar.vue`
- Modify: `stabler/tests/test_auth_transition_spa.py`
- Modify: `stabler/translations/en.csv`
- Modify: `stabler/translations/ru.csv`
- Modify: `stabler/translations/uz.csv`
- Modify: `stabler/translations/uzc.csv`
- Modify: `stabler/translations/tr.csv`

**Interfaces:**
- Consumes: `logout` from `api/auth.js`
- Consumes: `AuthTransitionOverlay`
- Success destination: `/stabler#/login`

- [ ] **Step 1: Write the failing Sidebar logout contract**

Add:

```python
SIDEBAR = ROOT / "public/js/components/Sidebar.vue"

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
```

- [ ] **Step 2: Run the logout contract and confirm RED**

```bash
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_auth_transition_spa.TestAuthTransitionSpa.test_logout_is_busy_single_fire_and_recoverable -v
```

Expected: failure because Sidebar still waits silently.

- [ ] **Step 3: Implement the logout state machine**

Replace the generic logout import/handler with:

```javascript
import { logout as logoutSession } from "../api/auth.js";
import AuthTransitionOverlay from "./AuthTransitionOverlay.vue";

const logoutPending = ref(false);

async function logout() {
	if (logoutPending.value) return;
	closeUserMenu();
	logoutPending.value = true;
	try {
		await logoutSession();
		window.location.replace("/stabler#/login");
	} catch (err) {
		logoutPending.value = false;
		toast.error(err?.message || t("Could not sign out. Please try again."));
	}
}
```

Disable the logout button with `:disabled="logoutPending"` and
`:aria-busy="logoutPending"`.

Render:

```vue
<AuthTransitionOverlay
	v-if="logoutPending"
	:title='t("Signing out")'
	:message='t("Signing out securely…")'
/>
```

- [ ] **Step 4: Add translations**

Add natural, non-empty translations for:

```text
Session opened
Preparing your Dashboard…
Signing out
Signing out securely…
Could not sign out. Please try again.
```

Update the auth static test to load all five translation CSVs and assert every
literal `t()` key from `Login.vue`, `Sidebar.vue`, and
`AuthTransitionOverlay.vue` has a non-empty translation.

- [ ] **Step 5: Run complete auth and project checks**

```bash
npm run test:js
PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_auth_transition_spa -v
npm run lint:js
bench build --app stabler
```

Expected: every command exits `0`; no test is skipped; ESLint reports no new
warnings.

- [ ] **Step 6: Commit logout and translations**

```bash
git add \
  stabler/public/js/components/Sidebar.vue \
  stabler/tests/test_auth_transition_spa.py \
  stabler/translations/en.csv \
  stabler/translations/ru.csv \
  stabler/translations/uz.csv \
  stabler/translations/uzc.csv \
  stabler/translations/tr.csv
git commit -m "fix: add recoverable logout transition"
```
