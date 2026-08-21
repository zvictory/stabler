"""Direct-URL / refresh load of a record form -- read out of the source.

What is protected: every record form under public/js/pages/**/*Form*.vue must
decide whether to fetch an existing document by reading the ROUTE PARAM
(`docName`, derived from `route.params.*`) -- never by reading the document
engine's `isCreate`. `useDocumentForm.js` defines:

	const docName = ref(null);
	const isCreate = computed(() => !docName.value);

That `docName` is the composable's OWN internal ref -- separate from a page's
own route-derived `docName` computed -- and it stays `null` (so `isCreate`
stays `true`) until `load()` actually runs. A component that branches on
`isCreate` at mount time, before its own `load()` call, gets `true` on every
mount, including a direct URL hit or a refresh of an existing record, and
renders a blank "New ..." form instead of the record the URL named.

Why that matters, not hypothetically: a user who pastes a link to an invoice
must see that invoice. A blank "New Purchase Invoice" in its place doesn't
error -- it lets them start typing and silently create a duplicate. This is
exactly the check `stabler-deploy`'s post-deploy smoke section asks a human to
run by hand on every release ("Direct-URL / refresh load of a record form"),
because until now it had no automated guard. This file is that guard.

The codebase has two compliant shapes, both covered here:

1. The route param gates the branch directly, inline in onMounted:
	`if (docName.value) { await loadDoc(); } else { form.value = blankForm(); }`
	(e.g. PurchaseInvoiceForm.vue, PurchaseOrderForm.vue, QuotationForm.vue,
	PaymentEntryForm.vue, SalesOrderFormClassic.vue, SalesOrderFormModern.vue).

2. A page that hand-rolls its own state (doesn't call useDocumentForm) may
	define its OWN `isCreate`, but only as a literal, provable alias:
	`const isCreate = computed(() => !docName.value);`
	Branching on THAT `isCreate` is safe -- it IS the route param, just under a
	different name. This is how CommercialInvoiceForm.vue, ImportOrderForm.vue,
	ImportContainerForm.vue, ImportTruckForm.vue, CustomsDeclarationForm.vue,
	TruckReceiptForm.vue and ProformaForm.vue are written.

What is NOT safe, and what this guard actually forbids: reading
`isCreate.value` as the mount-time gate in a file that has not proven, in its
own source, that `isCreate` means `!docName.value`. That is precisely the
shape of the bug -- and precisely what `useDocumentForm.js`'s destructured
`isCreate` is, absent a local override.

A Vue component cannot be mounted (@vue/test-utils is not a dependency here),
so the test reads the source. What it reads is not a fixed string: it parses
each onMounted(...) call by matching braces/parens (not a naive regex to the
next "}", which a `{...}` object-literal call argument would close
prematurely -- measured while writing this file, against PaymentEntryForm.vue)
and follows one hop into a bare-referenced or unconditionally-called
loadDoc()/load(), because that is where several of these files put the actual
branch. A form that moves this logic around keeps passing as long as the
route param still gates the decision; a form that starts trusting `isCreate`
instead fails, no matter how the surrounding code is reformatted.

Forms are discovered dynamically (glob, not a hardcoded list) so a form added
tomorrow is covered without editing this file. The three that legitimately
don't fit the pattern are named in ALLOWLIST below, each with a justification
this file also checks against router.js -- so if router.js ever grows a
":name" route for one of them, the allow-list entry itself fails instead of
quietly continuing to exempt what is now a real record form.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
PAGES = ROOT / "public" / "js" / "pages"
ROUTER = ROOT / "public" / "js" / "router.js"

ALLOWLIST = {
	"SalesOrderForm.vue": (
		"Pure variant-selector wrapper (renders SalesOrderFormClassic.vue or "
		"SalesOrderFormModern.vue depending on a feature flag) -- it reads "
		"neither the route nor useDocumentForm itself, so it has no direct-URL "
		"load behaviour of its own to check. Both delegates ARE checked below."
	),
	"SalesReturnForm.vue": (
		"Create-only: router.js routes it only at 'returns/new'. A sales return "
		"is always created fresh (optionally pre-filled from a source invoice "
		"via route.query), never re-opened by URL as an existing record -- so "
		"the isCreate-vs-route-param regression cannot occur here."
	),
	"RfqForm.vue": (
		"Create-only: router.js routes it only at '/tender/rfq/new'. An "
		"existing RFQ opens through a different component, RfqDetail.vue, "
		"registered at '/tender/rfq/:name' -- RfqForm.vue itself never "
		"receives a record's name from the route."
	),
}

# Proof the glob below actually walked the real page tree, not an empty or
# renamed directory. If PAGES ever moves, this fails loudly instead of the
# "found nothing, so nothing is broken" false green a bare count could give.
_KNOWN_FORMS = {
	"purchasing/PurchaseInvoiceForm.vue",
	"sales/SalesOrderFormClassic.vue",
	"imports/CommercialInvoiceForm.vue",
}


def _find_matching(text, open_idx, open_ch, close_ch):
	"""Index of the bracket matching text[open_idx], found by depth-counting --
	not a regex to the next close character, which a `{...}` object-literal
	call argument (e.g. `call(api, { company: x })`) inside the scanned block
	would close prematurely."""
	depth = 0
	for i in range(open_idx, len(text)):
		c = text[i]
		if c == open_ch:
			depth += 1
		elif c == close_ch:
			depth -= 1
			if depth == 0:
				return i
	return -1


def _extract_function_body(body, name):
	"""Source text between the braces of `(async )function <name>(...) {...}`,
	or None if no such function is defined in this file."""
	m = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\(", body)
	if not m:
		return None
	paren_close = _find_matching(body, m.end() - 1, "(", ")")
	if paren_close == -1:
		return None
	brace_open = body.index("{", paren_close)
	brace_close = _find_matching(body, brace_open, "{", "}")
	if brace_close == -1:
		return None
	return body[brace_open + 1 : brace_close]


def _onmounted_scopes(body):
	"""Source text of every onMounted(...) call in the file: the inline
	callback's body, or -- when onMounted is handed a bare function reference
	like `onMounted(load)` -- that function's own body."""
	scopes = []
	for m in re.finditer(r"onMounted\(", body):
		paren_close = _find_matching(body, m.end() - 1, "(", ")")
		if paren_close == -1:
			continue
		inner = body[m.end() : paren_close]
		arrow = re.search(r"=>\s*\{", inner)
		if arrow:
			brace_close = _find_matching(inner, arrow.end() - 1, "{", "}")
			if brace_close != -1:
				scopes.append(inner[arrow.end() : brace_close])
		else:
			fn_name = inner.strip()
			if re.fullmatch(r"\w+", fn_name):
				fn_body = _extract_function_body(body, fn_name)
				if fn_body is not None:
					scopes.append(fn_body)
	return scopes


def _mount_time_scope(body):
	"""Every onMounted(...) scope, plus one more hop into any `loadDoc()` or
	`load()` call found inside one of them -- the shape used by forms that
	hand-roll their own state, where the onMounted callback just calls
	loadDoc() and the actual create-vs-load branch lives inside loadDoc
	itself."""
	scopes = _onmounted_scopes(body)
	resolved = list(scopes)
	for raw in scopes:
		for fn_name in set(re.findall(r"\b(loadDoc|load)\(\s*\)\s*;", raw)):
			fn_body = _extract_function_body(body, fn_name)
			if fn_body is not None:
				resolved.append(fn_body)
	return "\n".join(resolved)


_ROUTE_PARAM = re.compile(r"route\.params\.\w+")
_IS_CREATE_VALUE = re.compile(r"\bisCreate\.value\b")
# The only way this codebase makes `isCreate` a safe stand-in for the route
# param: a literal, local, one-line negation of it. Anything else -- reading
# straight off useDocumentForm(), or basing it on a loaded-document ref -- is
# exactly the null-until-load() flag the smoke check warns about.
_SAFE_ISCREATE_ALIAS = re.compile(r"const\s+isCreate\s*=\s*computed\(\s*\(\)\s*=>\s*!docName\.value\s*\)")


def _check_form(path):
	"""None if compliant, else a message explaining what is missing."""
	body = path.read_text(encoding="utf-8")
	scope = _mount_time_scope(body)
	if not scope:
		return "no onMounted(...) call found -- cannot verify direct-URL load behaviour"

	reads_route_directly = "docName.value" in scope or bool(_ROUTE_PARAM.search(scope))
	uses_is_create = bool(_IS_CREATE_VALUE.search(scope))
	is_create_is_safe = bool(_SAFE_ISCREATE_ALIAS.search(body))

	if uses_is_create and not is_create_is_safe:
		return (
			"onMounted's create-vs-load decision reads isCreate.value, and this file "
			"has no local `const isCreate = computed(() => !docName.value)` proving "
			"that flag tracks the route param. Left as useDocumentForm()'s own "
			"isCreate, it is null-based until load() runs, so a direct URL or a "
			"refresh of an existing record renders a blank 'New' form instead."
		)
	if not reads_route_directly and not (uses_is_create and is_create_is_safe):
		return (
			"onMounted never reads docName.value / route.params.* (directly, or "
			"through a proven-safe local isCreate alias) -- cannot prove this form "
			"loads an existing record instead of rendering blank on a direct URL"
		)
	return None


def _form_files():
	return sorted(
		(p for p in PAGES.rglob("*.vue") if "Form" in p.name),
		key=lambda p: str(p.relative_to(PAGES)),
	)


def _component_has_dynamic_route(router_src, component_name):
	"""True if router.js maps any ':param' path to this component -- i.e. an
	existing record's name can reach it through the URL."""
	for m in re.finditer(
		rf'path:\s*"([^"]+)"[^}}]*?component:\s*\b{re.escape(component_name)}\b',
		router_src,
	):
		if ":" in m.group(1):
			return True
	return False


class TestFormDirectUrlLoad(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.files = _form_files()
		cls.relpaths = [str(p.relative_to(PAGES)) for p in cls.files]
		cls.names = {p.name for p in cls.files}
		cls.violations = []
		for p in cls.files:
			if p.name in ALLOWLIST:
				continue
			msg = _check_form(p)
			if msg:
				cls.violations.append((str(p.relative_to(PAGES)), msg))

	def test_the_scan_actually_found_the_known_forms(self):
		"""Anchor: if PAGES has moved or the glob has drifted, the scan below
		would silently check zero files and vacuously pass. It must find the
		real, known record forms first."""
		self.assertGreaterEqual(
			len(self.files),
			15,
			f"only found {len(self.files)} *Form*.vue files under {PAGES} -- "
			f"the glob or the path has drifted",
		)
		for known in _KNOWN_FORMS:
			self.assertIn(known, self.relpaths, f"expected to find {known} -- glob has drifted")

	def test_every_record_form_branches_on_the_route_param_not_on_isCreate(self):
		"""A user who pastes a link to an invoice must see that invoice, not
		an empty 'New Invoice' that silently creates a duplicate the moment
		they start typing. See useDocumentForm.js: isCreate is
		`computed(() => !docName.value)` on the composable's OWN internal ref,
		which stays null (isCreate stays true) until load() runs -- so
		branching on it at mount time is true on every mount, including a
		direct URL hit or a refresh of a real, existing record."""
		if self.violations:
			lines = [f"{rel}: {msg}" for rel, msg in self.violations]
			self.fail(
				"the following record forms do not provably load an existing "
				"document from the route param on mount:\n  " + "\n  ".join(lines)
			)

	def test_the_allowlist_entries_are_still_justified(self):
		"""The allow-list doesn't just trust its own justification text -- it
		re-checks the claim each entry makes, so a form that quietly grows a
		record URL (or stops being a pure wrapper) fails here instead of
		silently keeping an exemption it no longer deserves."""
		router_src = ROUTER.read_text(encoding="utf-8")

		wrapper = PAGES / "sales" / "SalesOrderForm.vue"
		wrapper_body = wrapper.read_text(encoding="utf-8")
		self.assertNotIn(
			"route.params",
			wrapper_body,
			"SalesOrderForm.vue now reads the route itself -- it is no longer a "
			"pure wrapper and needs its own direct-URL-load check",
		)
		self.assertNotIn(
			"onMounted",
			wrapper_body,
			"SalesOrderForm.vue now has its own onMounted -- it is no longer a "
			"pure wrapper and needs its own direct-URL-load check",
		)
		for delegate in ("SalesOrderFormClassic.vue", "SalesOrderFormModern.vue"):
			self.assertIn(
				delegate,
				self.names,
				f"{delegate} (SalesOrderForm.vue's delegate) is no longer found by "
				f"the scan -- the wrapper's exemption assumes it is covered",
			)

		for fname, component in (
			("SalesReturnForm.vue", "SalesReturnForm"),
			("RfqForm.vue", "RfqForm"),
		):
			self.assertFalse(
				_component_has_dynamic_route(router_src, component),
				f"{fname} is allow-listed as create-only, but router.js now routes "
				f"an existing record's URL to it -- remove the allow-list entry and "
				f"let this guard check {fname} instead",
			)


if __name__ == "__main__":
	unittest.main()
