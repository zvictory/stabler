<script setup>
/**
 * Remittance Settings — the row every transfer reads before it is allowed to post.
 *
 * This screen exists because of a measured gap, not a nice-to-have:
 * `remittance_settings.json:24-26` marks all three company GL accounts `reqd 1`
 * and no patch or fixture creates the row, so on every company the FIRST
 * registration attempt throws. `get_desk_account`
 * (`remittance_settings.py:27-52`) says the same thing from the other side —
 * its error names what is missing and deliberately does NOT explain how to fix
 * it, "because that belongs on the screen itself". This is that screen.
 *
 * ## Currency is checked here, not at the cash desk
 *
 * `resolve_accounts` (`remittance_accounting.py:96-138`) runs `_require_currency`
 * on every account it touches and throws on a mismatch. A manager who learns
 * that at the first transfer learns it with a customer at the counter. So the
 * same four rules are evaluated live, as the accounts are picked:
 *
 *   deferred commission  → company base currency      (`:131`)
 *   commission revenue   → company base currency      (`:136`)
 *   receiver obligation  → the transfer's RECEIVE currency (`:126`)
 *   desk cash account    → the currency its row declares (`:105`, `:113`)
 *
 * The obligation rule has a consequence worth stating on its face: one settings
 * field holds one account, so the currency of that single account is the only
 * receive currency the company can pay out in. Every desk currency that differs
 * from it is a corridor that will be refused. The check card says which.
 *
 * A mismatch is only ever reported when it is PROVEN — the account was read and
 * its currency disagrees. When the account could not be read, or the company's
 * base currency could not be read, the finding is "not verified", never "wrong".
 * Those are different claims and only one of them is knowable here.
 *
 * ## What this screen does not invent
 *
 * - **Expiry.** `default_quote_expiry_hours` is a real stored field, but nothing
 *   writes `expires_at` onto a transfer yet. The server says so itself
 *   (`policy_configured: false`), and the screen repeats the server's answer
 *   rather than implying the number is enforced. Left blank, the field is sent
 *   as null and the doctype's own default applies — no number is hardcoded here.
 * - **Commission % and exchange rate.** They are NOT settings. ADR-009 and the
 *   plan (`:377-381`) put both in the cashier's hands at register time, with the
 *   last value pre-filled. There is no field for them on Remittance Settings and
 *   this screen does not draw one.
 * ## Endpoints
 *
 * Reads go through `frappe.client.get_list`, the same path `NewRemittanceV1.vue`
 * already uses for this doctype. The write is
 * `stabler.api.remittance_settings.save_remittance_settings`, which saves the
 * parent and replaces the desk table in one document save, with permissions ON —
 * the role gate is `remittance_settings.json`'s, not a second list in either file.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { remittanceApi, REMITTANCE_QUEUES } from "../../api/remittance.js";
import { t } from "../../composables/i18n.js";
import { accountLabel } from "../../composables/accounts.js";
import { useToast } from "../../composables/useToast.js";
import { CORRIDOR_CURRENCIES } from "../../composables/remittanceCurrencies.js";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";

const SETTINGS_DOCTYPE = "Remittance Settings";
const CASH_DESK_CHILD = "Remittance Cash Desk Account";

const SAVE_METHOD = "stabler.api.remittance_settings.save_remittance_settings";

// Only this role may configure a company. The server owns the real gate
// (`remittance_settings.json:44`); this is the UX layer that keeps a cashier from
// staring at a form they cannot submit.
const MANAGER_ROLE = "Remittance Finance Manager";

const EVIDENCE_OPTIONS = [
	{ value: "Counted", label: t("Counted") },
	{ value: "Wallet balance", label: t("Wallet balance") },
];

const session = useSession();
const { activeCompany, roles } = storeToRefs(session);
const toast = useToast();

const company = computed(() => activeCompany.value || "");
const canManage = computed(() => session.isAdmin || (roles.value || []).includes(MANAGER_ROLE));

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const saveError = ref("");

// Whether a Remittance Settings row exists for this company at all. False is the
// go-live blocker itself, so it gets its own banner rather than a silent blank form.
const configured = ref(false);

const form = ref(blankForm());
const desks = ref([]);

const accounts = ref([]);
const accountsError = ref("");
const branches = ref([]);
const currencies = ref([]);
const baseCurrency = ref(null);

// null = not asked / unanswered, true|false = the server's own answer.
const expiryPolicyConfigured = ref(null);

// Company can change under a slow load. Every response checks its ticket before
// it writes, so company A's chart of accounts never lands under company B's name.
let loadSeq = 0;

function blankForm() {
	return {
		receiver_obligation_account: "",
		deferred_commission_account: "",
		commission_income_account: "",
		// Left empty on purpose: blank means "the doctype default applies", and a
		// number typed in here would be this screen inventing policy.
		default_quote_expiry_hours: null,
		max_code_attempts: null,
		lockout_minutes: null,
		require_refund_approval: 1,
	};
}

function blankDesk() {
	return { branch: "", city: "", currency: "", account: "", evidence_type: "Counted" };
}

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------
async function loadSettingsRow() {
	const rows = await call("frappe.client.get_list", {
		doctype: SETTINGS_DOCTYPE,
		filters: { company: company.value },
		fields: [
			"name",
			"receiver_obligation_account",
			"deferred_commission_account",
			"commission_income_account",
			"default_quote_expiry_hours",
			"max_code_attempts",
			"lockout_minutes",
			"require_refund_approval",
		],
		limit_page_length: 1,
	});
	return Array.isArray(rows) && rows.length ? rows[0] : null;
}

async function loadDesks() {
	// `autoname: field:company` makes the parent docname the company name.
	const rows = await call("frappe.client.get_list", {
		doctype: CASH_DESK_CHILD,
		parent: SETTINGS_DOCTYPE,
		filters: { parenttype: SETTINGS_DOCTYPE, parent: company.value },
		fields: ["branch", "city", "currency", "account", "evidence_type"],
		limit_page_length: 0,
		order_by: "idx asc",
	});
	return Array.isArray(rows) ? rows : [];
}

async function loadAccounts() {
	const rows = await call("frappe.client.get_list", {
		doctype: "Account",
		filters: { company: company.value, is_group: 0, disabled: 0 },
		fields: [
			"name",
			"account_name",
			"account_number",
			"account_currency",
			"root_type",
			"account_type",
		],
		limit_page_length: 0,
		order_by: "account_name asc",
	});
	return Array.isArray(rows) ? rows : [];
}

async function loadBaseCurrency() {
	const rows = await call("frappe.client.get_list", {
		doctype: "Company",
		filters: { name: company.value },
		fields: ["name", "default_currency"],
		limit_page_length: 1,
	});
	return rows?.[0]?.default_currency || null;
}

async function loadBranches() {
	const rows = await call("frappe.client.get_list", {
		doctype: "Branch",
		fields: ["name"],
		limit_page_length: 0,
		order_by: "name asc",
	});
	return Array.isArray(rows) ? rows : [];
}

async function loadCurrencies() {
	const rows = await call("frappe.client.get_list", {
		doctype: "Currency",
		filters: { enabled: 1 },
		fields: ["name"],
		limit_page_length: 0,
		order_by: "name asc",
	});
	return Array.isArray(rows) ? rows : [];
}

// The only honest source for "does expiry mean anything yet". The queries module
// answers `policy_configured` itself; nothing here infers it.
async function loadExpiryPolicy() {
	const res = await remittanceApi.workQueue(company.value, REMITTANCE_QUEUES.EXPIRING_12H, 1, 0);
	return typeof res?.policy_configured === "boolean" ? res.policy_configured : null;
}

async function load() {
	if (!company.value || !canManage.value) {
		loading.value = false;
		return;
	}
	const seq = ++loadSeq;
	loading.value = true;
	loadError.value = "";
	saveError.value = "";
	accountsError.value = "";

	try {
		const [row, deskRows] = await Promise.all([loadSettingsRow(), loadDesks()]);
		if (seq !== loadSeq) return;
		configured.value = !!row;
		form.value = row
			? {
					receiver_obligation_account: row.receiver_obligation_account || "",
					deferred_commission_account: row.deferred_commission_account || "",
					commission_income_account: row.commission_income_account || "",
					default_quote_expiry_hours: row.default_quote_expiry_hours ?? null,
					max_code_attempts: row.max_code_attempts ?? null,
					lockout_minutes: row.lockout_minutes ?? null,
					require_refund_approval: row.require_refund_approval ? 1 : 0,
				}
			: blankForm();
		desks.value = deskRows.map((d) => ({
			branch: d.branch || "",
			city: d.city || "",
			currency: d.currency || "",
			account: d.account || "",
			evidence_type: d.evidence_type || "Counted",
		}));
	} catch (err) {
		if (seq !== loadSeq) return;
		loadError.value = err?.message || String(err);
		loading.value = false;
		return;
	}

	// Everything below is verification input, not the settings themselves: each
	// failure narrows what can be checked and is reported as such, but none of
	// them should blank the form the manager came here to edit.
	const [accountRes, baseRes, branchRes, currencyRes, expiryRes] =
		await Promise.allSettled([
			loadAccounts(),
			loadBaseCurrency(),
			loadBranches(),
			loadCurrencies(),
			loadExpiryPolicy(),
		]);
	if (seq !== loadSeq) return;

	if (accountRes.status === "fulfilled") {
		accounts.value = accountRes.value;
	} else {
		accounts.value = [];
		accountsError.value = accountRes.reason?.message || String(accountRes.reason);
	}
	baseCurrency.value = baseRes.status === "fulfilled" ? baseRes.value : null;
	branches.value = branchRes.status === "fulfilled" ? branchRes.value : [];
	currencies.value = currencyRes.status === "fulfilled" ? currencyRes.value : [];
	expiryPolicyConfigured.value = expiryRes.status === "fulfilled" ? expiryRes.value : null;

	loading.value = false;
}

onMounted(load);
watch(company, load);
// Roles can arrive after the first paint (`session.boot()`), and `load` refuses to
// run without them. Without this, a Finance Manager who lands here mid-boot is
// left looking at the "you cannot manage this" panel until they navigate away.
watch(canManage, (allowed) => {
	if (allowed) load();
});

// ---------------------------------------------------------------------------
// Account lookup + currency rules
// ---------------------------------------------------------------------------
const accountByName = computed(() => {
	const map = new Map();
	for (const a of accounts.value) map.set(a.name, a);
	return map;
});

/**
 * The currency an account is actually held in, or null when it cannot be told.
 * Mirrors `_account_currency` (`remittance_accounting.py:76-78`): an account with
 * no currency of its own is held in the company's base currency.
 */
function currencyOf(account) {
	if (!account) return null;
	const meta = accountByName.value.get(account);
	if (!meta) return null;
	return meta.account_currency || baseCurrency.value || null;
}

function accountDisplay(name) {
	if (!name) return "";
	const meta = accountByName.value.get(name);
	if (!meta) return name;
	const cur = currencyOf(name);
	return cur ? `${accountLabel(meta)} (${cur})` : accountLabel(meta);
}

function norm(s) {
	return String(s || "").toLowerCase();
}

/**
 * Account picker options. The accounts that belong on this field come first under
 * a heading, the rest stay reachable below it — the server enforces no root type,
 * so hiding the others would be this screen inventing a rule it cannot back up.
 */
function accountSearch(preferred, preferredLabel) {
	return (q) => {
		const n = norm(q);
		const match = (a) =>
			!n ||
			norm(a.account_name).includes(n) ||
			norm(a.name).includes(n) ||
			norm(a.account_number).includes(n);
		const wanted = [];
		const other = [];
		for (const a of accounts.value) {
			if (!match(a)) continue;
			(preferred(a) ? wanted : other).push(a);
		}
		const out = [];
		if (wanted.length) out.push({ __group: preferredLabel }, ...wanted);
		if (other.length) out.push({ __group: t("Other accounts") }, ...other);
		return out;
	};
}

const searchObligation = accountSearch((a) => a.root_type === "Liability", t("Liability accounts"));
const searchDeferred = accountSearch((a) => a.root_type === "Liability", t("Liability accounts"));
const searchIncome = accountSearch((a) => a.root_type === "Income", t("Income accounts"));
const searchDeskCash = accountSearch(
	(a) => a.account_type === "Bank" || a.account_type === "Cash",
	t("Bank and cash accounts")
);

const branchOptions = computed(() => branches.value.map((b) => ({ value: b.name, label: b.name })));
const currencyOptions = computed(() =>
	currencies.value.map((c) => ({ value: c.name, label: c.name }))
);

// Distinct receive currencies the desks can pay out in — the set the single
// obligation account has to cover.
const deskCurrencies = computed(() => {
	const seen = new Set();
	for (const d of desks.value) if (d.currency) seen.add(d.currency);
	return [...seen];
});

function deskCurrencyMismatch(row) {
	if (!row.account || !row.currency) return null;
	const actual = currencyOf(row.account);
	if (!actual || actual === row.currency) return null;
	return actual;
}

// Per desk (branch), the currencies it actually holds a complete cash-account row
// for. The factual question the data already answers — not a comparison against
// an expected set, because nothing records which currencies a desk is SUPPOSED to
// carry and inventing that record is a migration, not this fix.
//
// Every currency is collected, not only the corridor ones: the Currency select on
// this screen is fed from every enabled Currency, so a desk can legitimately hold
// a UZS drawer. That row is real, and it is also useless for a transfer.
const deskReadiness = computed(() => {
	const map = new Map();
	for (const row of desks.value) {
		const branch = row.branch || "";
		if (!branch) continue;
		if (!map.has(branch)) map.set(branch, { covered: new Set() });
		// A row still being filled in has no currency or no account yet; it
		// contributes nothing rather than counting against the desk. The
		// half-filled row is already reported by its own blocker below.
		if (!row.currency || !row.account) continue;
		map.get(branch).covered.add(row.currency);
	}
	return map;
});

function readinessFor(branch) {
	return deskReadiness.value.get(branch) || null;
}

/** This row, on its own: a complete account row in a currency a corridor uses. */
function rowUsable(row) {
	return !!row.currency && !!row.account && CORRIDOR_CURRENCIES.includes(row.currency);
}

// A desk verdict belongs to the desk, not to each of its rows. Rendered on the
// first row carrying that branch so it is stated once; rows of one branch need
// not be adjacent, so this is by index rather than by comparing with the row above.
const firstRowIndexByBranch = computed(() => {
	const first = new Map();
	desks.value.forEach((row, index) => {
		const branch = row.branch || "";
		if (branch && !first.has(branch)) first.set(branch, index);
	});
	return first;
});

function isFirstRowOfDesk(row, index) {
	return !!row.branch && firstRowIndexByBranch.value.get(row.branch) === index;
}

/**
 * A desk that cannot serve ANY transfer — it holds no corridor currency at all.
 *
 * Deliberately the intersection with CORRIDOR_CURRENCIES and NOT `covered.size`.
 * Two failures came out of the size test in review:
 *   - it can never fire on saved data, because branch, currency and account are
 *     all `reqd: 1` on Remittance Cash Desk Account, so a saved desk always
 *     covers something and the whole signal was inert;
 *   - and it says nothing about the case that matters — a desk holding only a
 *     non-corridor currency (a UZS drawer) covers one currency, passes the size
 *     test, and is reported ready while it can serve nothing.
 *
 * The half-filled-row case is deliberately NOT folded in here. It is desk-wide
 * only by accident of grouping, and folding it in made every row of a desk claim
 * the desk was unusable while the green badges in the same cell said otherwise.
 * An unfinished row is reported as an unfinished row, by the existing blocker.
 */
function deskNotReady(branch) {
	const r = readinessFor(branch);
	if (!r) return false;
	return !CORRIDOR_CURRENCIES.some((currency) => r.covered.has(currency));
}

// ---------------------------------------------------------------------------
// Verification — every finding is either proven or explicitly unproven
// ---------------------------------------------------------------------------
const findings = computed(() => {
	const out = [];
	const push = (level, text) => out.push({ level, text });

	if (accountsError.value) {
		push(
			"warning",
			t(
				"The chart of accounts could not be read, so no account currency on this page was verified: {error}",
				{
					error: accountsError.value,
				}
			)
		);
	}
	if (!baseCurrency.value) {
		push(
			"warning",
			t(
				"The company's base currency could not be read, so the two commission accounts were not verified."
			)
		);
	}

	// --- the two accounts that must be held in the company's base currency ---
	const baseFields = [
		{ key: "deferred_commission_account", label: t("Deferred commission") },
		{ key: "commission_income_account", label: t("Commission revenue") },
	];
	for (const f of baseFields) {
		const account = form.value[f.key];
		if (!account) {
			push(
				"blocker",
				t("{label} account is not set. It is required before anything can be saved.", {
					label: f.label,
				})
			);
			continue;
		}
		const actual = currencyOf(account);
		if (!actual) {
			push(
				"warning",
				t("{label} account {account} could not be read, so its currency was not verified.", {
					label: f.label,
					account,
				})
			);
			continue;
		}
		if (baseCurrency.value && actual !== baseCurrency.value) {
			push(
				"blocker",
				t(
					"{label} account {account} is held in {actual}, but it must be held in the company's base currency {expected}. Every transfer would be refused when it posts.",
					{ label: f.label, account, actual, expected: baseCurrency.value }
				)
			);
		}
	}

	// --- the obligation account, whose currency IS the payout currency ---
	const obligation = form.value.receiver_obligation_account;
	if (!obligation) {
		push(
			"blocker",
			t("Receiver obligation account is not set. It is required before anything can be saved.")
		);
	} else {
		const actual = currencyOf(obligation);
		if (!actual) {
			push(
				"warning",
				t(
					"Receiver obligation account {account} could not be read, so its currency was not verified.",
					{
						account: obligation,
					}
				)
			);
		} else {
			for (const cur of deskCurrencies.value) {
				if (cur === actual) continue;
				push(
					"warning",
					t(
						"A desk is configured for {desk}, but the receiver obligation account is held in {actual}. A transfer paying out in {desk} would be refused.",
						{ desk: cur, actual }
					)
				);
			}
		}
	}

	// --- the desks ---
	if (!desks.value.length) {
		push(
			"blocker",
			t(
				"No cash desk is mapped. A desk cannot take cash in or pay it out until it has an account for that currency."
			)
		);
	}
	const pairs = new Set();
	desks.value.forEach((row, i) => {
		const n = i + 1;
		if (!row.branch || !row.currency || !row.account) {
			push(
				"blocker",
				t("Cash desk row {row} is incomplete. Desk, currency and cash account are all required.", {
					row: n,
				})
			);
			return;
		}
		const pair = JSON.stringify([row.branch, row.currency]);
		if (pairs.has(pair)) {
			push(
				"blocker",
				t(
					"Desk {branch} has more than one {currency} account. One account per desk per currency.",
					{
						branch: row.branch,
						currency: row.currency,
					}
				)
			);
		}
		pairs.add(pair);

		const actual = currencyOf(row.account);
		if (!actual) {
			push(
				"warning",
				t(
					"Cash account {account} on desk {branch} could not be read, so its currency was not verified.",
					{
						account: row.account,
						branch: row.branch,
					}
				)
			);
			return;
		}
		if (actual !== row.currency) {
			push(
				"blocker",
				t(
					"Desk {branch}: cash account {account} is held in {actual}, but the row declares {declared}. Cash counted at this desk would post to the wrong drawer, so it would be refused.",
					{ branch: row.branch, account: row.account, actual, declared: row.currency }
				)
			);
		}
	});

	// Only a desk row is checked here: the three accounts are already blockers
	// above, and the server refuses the same save for the same reason. Stating it
	// as a blocker means the manager reads it before Save is pressed rather than
	// after it is refused. Unconditional since the engine flag was retired — it
	// used to run only when V1 was being picked, and V1 is now the only engine
	// there is.
	if (!desks.value.length) {
		push(
			"blocker",
			t("Every cash account comes from the desk table. Add at least one desk before saving.")
		);
	}
	if (expiryPolicyConfigured.value === false) {
		push(
			"warning",
			t(
				"No pickup expiry policy is configured yet: nothing writes an expiry time onto a transfer, so the quote expiry below is stored but not yet enforced."
			)
		);
	}

	return out;
});

const blockers = computed(() => findings.value.filter((f) => f.level === "blocker"));
const warnings = computed(() => findings.value.filter((f) => f.level === "warning"));
const canSave = computed(
	() => canManage.value && !loading.value && !saving.value && !blockers.value.length
);

// ---------------------------------------------------------------------------
// Edit
// ---------------------------------------------------------------------------
function addDesk() {
	desks.value.push(blankDesk());
}

function removeDesk(i) {
	desks.value.splice(i, 1);
}

// A blank Int is not a zero. Send null so the doctype's own default applies
// rather than writing "0 hours" or "0 attempts" into the row.
function intOrNull(value) {
	if (value === "" || value === null || value === undefined) return null;
	const n = Number(value);
	return Number.isFinite(n) ? Math.trunc(n) : null;
}

async function save() {
	if (!canSave.value) return;
	saving.value = true;
	saveError.value = "";
	try {
		await call(SAVE_METHOD, {
			company: company.value,
			payload: JSON.stringify({
				receiver_obligation_account: form.value.receiver_obligation_account,
				deferred_commission_account: form.value.deferred_commission_account,
				commission_income_account: form.value.commission_income_account,
				default_quote_expiry_hours: intOrNull(form.value.default_quote_expiry_hours),
				max_code_attempts: intOrNull(form.value.max_code_attempts),
				lockout_minutes: intOrNull(form.value.lockout_minutes),
				require_refund_approval: form.value.require_refund_approval ? 1 : 0,
				cash_desk_accounts: desks.value.map((d) => ({
					branch: d.branch,
					city: d.city || "",
					currency: d.currency,
					account: d.account,
					evidence_type: d.evidence_type || "Counted",
				})),
			}),
		});
		toast.success(t("Remittance settings saved."));
		await load();
	} catch (err) {
		saveError.value = err?.message || String(err);
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<EmptyState
		v-if="!company"
		icon="ti-building-bank"
		:title="t('No company selected')"
		:subtitle="t('Pick a company to configure its remittance accounts.')"
	/>

	<EmptyState
		v-else-if="!canManage"
		icon="ti-lock"
		tone="secondary"
		:title="t('Remittance settings are managed by the Finance Manager')"
		:subtitle="
			t('Only a Remittance Finance Manager can set the GL accounts and desk mapping for a company.')
		"
	/>

	<template v-else>
		<div class="d-flex flex-wrap align-items-center gap-2 mb-3">
			<div>
				<h2 class="page-title mb-0">{{ t("Remittance Settings") }}</h2>
				<div class="text-secondary small">
					{{ t("The accounts every transfer posts to, and the desk that holds the cash.") }}
				</div>
			</div>
			<div class="ms-auto d-flex align-items-center gap-2">
				<button type="button" class="btn btn-primary" :disabled="!canSave" @click="save">
					<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save") }}
				</button>
			</div>
		</div>

		<div v-if="loadError" class="alert alert-danger">{{ loadError }}</div>

		<SkeletonRows v-if="loading" :rows="6" :cols="3" />

		<template v-else>
			<div v-if="!configured" class="alert alert-danger">
				<div class="fw-semibold">
					{{ t("Remittance is not configured for {company}.", { company }) }}
				</div>
				<div class="small">
					{{
						t("Until these accounts are saved, every attempt to register a transfer is refused.")
					}}
				</div>
			</div>

			<div v-if="saveError" class="alert alert-danger">{{ saveError }}</div>

			<!-- Configuration check ------------------------------------------------->
			<div v-if="blockers.length || warnings.length" class="card mb-3">
				<div class="card-header">
					<h3 class="card-title">{{ t("Configuration check") }}</h3>
				</div>
				<ul class="list-group list-group-flush">
					<li
						v-for="(f, i) in blockers"
						:key="`b${i}`"
						class="list-group-item d-flex gap-2 align-items-start"
					>
						<i class="ti ti-alert-triangle text-danger mt-1"></i>
						<span>{{ f.text }}</span>
					</li>
					<li
						v-for="(f, i) in warnings"
						:key="`w${i}`"
						class="list-group-item d-flex gap-2 align-items-start"
					>
						<i class="ti ti-info-circle text-warning mt-1"></i>
						<span class="text-secondary">{{ f.text }}</span>
					</li>
				</ul>
			</div>

			<!-- Company accounts ---------------------------------------------------->
			<div class="card mb-3">
				<div class="card-header">
					<h3 class="card-title">{{ t("Company accounts") }}</h3>
					<div class="card-subtitle">
						{{ t("Base currency: {currency}", { currency: baseCurrency || t("unknown") }) }}
					</div>
				</div>
				<div class="card-body">
					<div class="mb-3">
						<label class="form-label">{{ t("Receiver obligation") }}</label>
						<Typeahead
							v-model="form.receiver_obligation_account"
							:search="searchObligation"
							:display="accountDisplay(form.receiver_obligation_account)"
							:placeholder="t('Search account…')"
							open-on-focus
							@pick="
								(item) => {
									if (!item.__group) form.receiver_obligation_account = item.name;
								}
							"
							@clear="() => (form.receiver_obligation_account = '')"
						>
							<template #option="{ item }">
								<template v-if="item.__group">
									<span
										class="text-uppercase text-secondary fw-semibold"
										style="font-size: 0.7em; letter-spacing: 0.04em"
										>{{ item.__group }}</span
									>
								</template>
								<template v-else>
									<span>{{ accountLabel(item) }}</span>
									<span v-if="item.account_number" class="text-secondary ms-1 small">{{
										item.account_number
									}}</span>
									<span class="ms-auto text-secondary small font-monospace">{{
										item.account_currency || baseCurrency
									}}</span>
								</template>
							</template>
						</Typeahead>
						<div class="form-hint">
							{{
								t(
									"What the company owes the receiver until the cash is handed over. Its currency is the only currency this company can pay out in."
								)
							}}
						</div>
					</div>

					<div class="mb-3">
						<label class="form-label">{{ t("Deferred commission") }}</label>
						<Typeahead
							v-model="form.deferred_commission_account"
							:search="searchDeferred"
							:display="accountDisplay(form.deferred_commission_account)"
							:placeholder="t('Search account…')"
							open-on-focus
							@pick="
								(item) => {
									if (!item.__group) form.deferred_commission_account = item.name;
								}
							"
							@clear="() => (form.deferred_commission_account = '')"
						>
							<template #option="{ item }">
								<template v-if="item.__group">
									<span
										class="text-uppercase text-secondary fw-semibold"
										style="font-size: 0.7em; letter-spacing: 0.04em"
										>{{ item.__group }}</span
									>
								</template>
								<template v-else>
									<span>{{ accountLabel(item) }}</span>
									<span v-if="item.account_number" class="text-secondary ms-1 small">{{
										item.account_number
									}}</span>
									<span class="ms-auto text-secondary small font-monospace">{{
										item.account_currency || baseCurrency
									}}</span>
								</template>
							</template>
						</Typeahead>
						<div class="form-hint">
							{{
								t(
									"Commission taken at registration but not yet earned. Must be held in the company's base currency."
								)
							}}
						</div>
					</div>

					<div>
						<label class="form-label">{{ t("Commission revenue") }}</label>
						<Typeahead
							v-model="form.commission_income_account"
							:search="searchIncome"
							:display="accountDisplay(form.commission_income_account)"
							:placeholder="t('Search account…')"
							open-on-focus
							@pick="
								(item) => {
									if (!item.__group) form.commission_income_account = item.name;
								}
							"
							@clear="() => (form.commission_income_account = '')"
						>
							<template #option="{ item }">
								<template v-if="item.__group">
									<span
										class="text-uppercase text-secondary fw-semibold"
										style="font-size: 0.7em; letter-spacing: 0.04em"
										>{{ item.__group }}</span
									>
								</template>
								<template v-else>
									<span>{{ accountLabel(item) }}</span>
									<span v-if="item.account_number" class="text-secondary ms-1 small">{{
										item.account_number
									}}</span>
									<span class="ms-auto text-secondary small font-monospace">{{
										item.account_currency || baseCurrency
									}}</span>
								</template>
							</template>
						</Typeahead>
						<div class="form-hint">
							{{
								t(
									"Where the commission is recognised once the transfer is paid out. Must be held in the company's base currency."
								)
							}}
						</div>
					</div>
				</div>
			</div>

			<!-- Cash desks ---------------------------------------------------------->
			<div class="card mb-3 rs-desks">
				<div class="card-header">
					<h3 class="card-title">{{ t("Cash desks") }}</h3>
					<div class="card-subtitle">
						{{
							t(
								"One cash account per desk per currency, so a desk's book balance equals the count in that drawer."
							)
						}}
					</div>
				</div>
				<div class="table-responsive">
					<table class="table card-table align-middle">
						<thead>
							<tr>
								<th style="min-width: 160px">{{ t("Desk") }}</th>
								<th style="min-width: 120px">{{ t("City") }}</th>
								<th style="min-width: 110px">{{ t("Currency") }}</th>
								<th style="min-width: 220px">{{ t("Cash account") }}</th>
								<th style="min-width: 150px">{{ t("Evidence") }}</th>
								<th style="min-width: 160px">{{ t("Readiness") }}</th>
								<th class="w-1"></th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(row, i) in desks" :key="i">
								<td>
									<Select
										v-model="row.branch"
										:options="branchOptions"
										:placeholder="t('Select desk…')"
										size="sm"
									/>
								</td>
								<td>
									<input
										v-model="row.city"
										type="text"
										class="form-control form-control-sm"
										:placeholder="t('City')"
									/>
								</td>
								<td>
									<Select
										v-model="row.currency"
										:options="currencyOptions"
										:placeholder="t('Currency')"
										size="sm"
									/>
								</td>
								<td>
									<Typeahead
										v-model="row.account"
										:search="searchDeskCash"
										:display="accountDisplay(row.account)"
										:placeholder="t('Search account…')"
										size="sm"
										open-on-focus
										@pick="
											(item) => {
												if (!item.__group) row.account = item.name;
											}
										"
										@clear="() => (row.account = '')"
									>
										<template #option="{ item }">
											<template v-if="item.__group">
												<span
													class="text-uppercase text-secondary fw-semibold"
													style="font-size: 0.7em; letter-spacing: 0.04em"
													>{{ item.__group }}</span
												>
											</template>
											<template v-else>
												<span>{{ accountLabel(item) }}</span>
												<span class="ms-auto text-secondary small font-monospace">{{
													item.account_currency || baseCurrency
												}}</span>
											</template>
										</template>
									</Typeahead>
									<div v-if="deskCurrencyMismatch(row)" class="text-danger small mt-1">
										{{
											t("Held in {actual}, but this row declares {declared}.", {
												actual: deskCurrencyMismatch(row),
												declared: row.currency,
											})
										}}
									</div>
								</td>
								<td>
									<Select v-model="row.evidence_type" :options="EVIDENCE_OPTIONS" size="sm" />
								</td>
								<!-- Per ROW, this row's own usability; per DESK, once, on that desk's
								     first row. The first draft printed the whole corridor set on
								     every row, so a three-currency desk repeated the same three
								     badges three times and said nothing about the row you were
								     looking at. -->
								<td>
									<div v-if="rowUsable(row)" class="badge bg-green-lt text-green">
										{{ row.currency }}
									</div>
									<div v-else-if="row.currency && row.account" class="badge bg-secondary-lt text-secondary">
										{{ t("{currency} — not a corridor currency", { currency: row.currency }) }}
									</div>
									<div v-if="isFirstRowOfDesk(row, i) && deskNotReady(row.branch)" class="text-danger small mt-1">
										{{ t("Not ready — this desk cannot take or hand over a transfer.") }}
									</div>
								</td>
								<td>
									<button
										type="button"
										class="btn btn-ghost-secondary btn-sm"
										:aria-label="t('Remove desk')"
										@click="removeDesk(i)"
									>
										<i class="ti ti-trash"></i>
									</button>
								</td>
							</tr>
							<tr v-if="!desks.length">
								<td colspan="7" class="text-secondary">
									{{
										t(
											"No desk is mapped yet. Add one for every desk and currency that takes or pays out cash."
										)
									}}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div class="card-footer">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="addDesk">
						<i class="ti ti-plus me-1"></i>{{ t("Add desk") }}
					</button>
				</div>
			</div>

			<!-- Policy -------------------------------------------------------------->
			<div class="card mb-3">
				<div class="card-header">
					<h3 class="card-title">{{ t("Policy") }}</h3>
				</div>
				<div class="card-body">
					<div class="row g-3">
						<div class="col-12 col-md-4">
							<label class="form-label">{{ t("Default quote expiry (hours)") }}</label>
							<input
								v-model="form.default_quote_expiry_hours"
								type="number"
								min="1"
								class="form-control"
								:placeholder="t('Leave blank for the default')"
							/>
							<div v-if="expiryPolicyConfigured === false" class="form-hint text-warning">
								{{ t("Stored, but not enforced yet — no expiry time is written onto a transfer.") }}
							</div>
						</div>
						<div class="col-12 col-md-4">
							<label class="form-label">{{ t("Max pickup code attempts") }}</label>
							<input
								v-model="form.max_code_attempts"
								type="number"
								min="1"
								class="form-control"
								:placeholder="t('Leave blank for the default')"
							/>
						</div>
						<div class="col-12 col-md-4">
							<label class="form-label">{{ t("Lockout (minutes)") }}</label>
							<input
								v-model="form.lockout_minutes"
								type="number"
								min="0"
								class="form-control"
								:placeholder="t('Leave blank for the default')"
							/>
							<div class="form-hint">
								{{ t("A locked code is reopened by a Finance Manager, never by a timer.") }}
							</div>
						</div>
						<div class="col-12">
							<label class="form-check form-switch mb-0">
								<input
									v-model="form.require_refund_approval"
									class="form-check-input"
									type="checkbox"
									:true-value="1"
									:false-value="0"
								/>
								<span class="form-check-label">{{ t("Refund requires approval") }}</span>
							</label>
						</div>
					</div>
					<div class="form-hint mt-3">
						{{
							t(
								"Commission percentage and exchange rate are not configured here: the cashier enters both at registration, pre-filled with the last value used."
							)
						}}
					</div>
				</div>
			</div>

			<div class="d-flex">
				<button type="button" class="btn btn-primary ms-auto" :disabled="!canSave" @click="save">
					<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save") }}
				</button>
			</div>
			<div v-if="blockers.length" class="text-secondary small text-end mt-1">
				{{
					t("Saving is blocked until the {count} item(s) above are fixed.", {
						count: blockers.length,
					})
				}}
			</div>
		</template>
	</template>
</template>

<style scoped>
/* Desktop keeps the compact grid density; a finger needs 40px. */
@media (max-width: 767.98px) {
	.rs-desks :deep(.form-control),
	.rs-desks :deep(.form-select),
	.rs-desks :deep(.btn) {
		min-height: 40px;
	}
}
</style>
