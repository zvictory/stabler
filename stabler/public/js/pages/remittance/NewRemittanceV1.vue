<script setup>
/**
 * New Transfer — take the cash at this desk and open the obligation (Transfer V1).
 *
 * Registers through `remittance_commands.register_remittance`, not the legacy
 * `stabler.api.remittance.create_remittance`. The legacy endpoint still ships and
 * still works for a company on the JE-only engine; nothing on this screen reaches
 * for it, which is why the whole file imports `api/remittance.js` and never the
 * legacy module.
 *
 * What ADR-009 removed, and what this form therefore does NOT ask for:
 *   - No corridor record. The cashier picks the DESTINATION desk; the origin desk
 *     is their own branch and is not selectable.
 *   - No account pickers. Cash, obligation, deferred-commission and commission
 *     income accounts all come from Remittance Settings (ADR-006). The old step 3
 *     of this form made `payout_account` mandatory and the server ignores that
 *     argument outright — a required field that changed nothing. It is gone.
 *   - No mid rate anywhere on this screen. There is exactly one rate: the one the
 *     cashier quotes the sender, typed here and frozen at register.
 *   - Commission percentage and FX rate are typed by hand, and the last value each
 *     cashier used comes back as the default (per user, not per company).
 *
 * The quote below mirrors `_remittance_pricing.price_transfer` figure for figure,
 * because the two modes are not inverses (ADR-007) and a preview computed a
 * different way would drift by a minor unit against the receipt. It is still only
 * a preview: the receipt renders what the SERVER stored.
 */
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { REMITTANCE_QUEUES, remittanceApi } from "../../api/remittance.js";
import { useSession } from "../../stores/session.js";
import { t, tlang } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { CORRIDOR_CURRENCIES } from "../../composables/remittanceCurrencies.js";
import { currencyLegs, routeLabel } from "../../composables/remittanceRoute.js";
import { todayIso } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import Select from "../../components/Select.vue";
import EmptyState from "../../components/EmptyState.vue";
import PickupCodeReceipt from "./PickupCodeReceipt.vue";

const session = useSession();

// The Remittance Transfer `commission_mode` Select options, verbatim. The server
// matches case-insensitively, but the stored row spells them this way and a
// replay comparison is done on the stored spelling.
const EXCLUSIVE = "Exclusive";
const INCLUSIVE = "Inclusive";

// `remittance_commands._send_precision()` reads the system `currency_precision`
// and falls back to 2; every currency this module admits is a 2-decimal
// currency. Stated here so the assumption is visible rather than implied.
const PRECISION = 2;

const CASH_DESK_CHILD = "Remittance Cash Desk Account";
const SETTINGS_DOCTYPE = "Remittance Settings";

const company = computed(() => session.activeCompany);
const language = computed(() => tlang());

const loading = ref(false);
const loadError = ref("");
const submitting = ref(false);
const submitError = ref("");

const desks = ref([]);
const originBranch = ref("");
const originLookupFailed = ref(false);
// Tri-state on purpose: null means "not answered yet", and an unanswered
// question is not the same claim as "no policy". See the expiry row below.
const expiryPolicyConfigured = ref(null);

// The plaintext pickup code the server issued, held ONLY here and only until the
// cashier acknowledges the receipt. It is never routed, stored or logged.
const issued = ref(null);

// ---------------------------------------------------------------------------
// Remembered defaults (ADR-009: per cashier, so one desk's rate does not move
// another's screen). What is kept is a percentage and an FX rate. The pickup
// code is never written here — it never leaves `issued`.
// ---------------------------------------------------------------------------
const MEMORY_PREFIX = "stabler.remittance.lastQuote";

function memoryKey() {
	return `${MEMORY_PREFIX}.${session.user?.id || "anonymous"}`;
}

function readMemory() {
	try {
		return JSON.parse(localStorage.getItem(memoryKey())) || {};
	} catch {
		return {};
	}
}

function writeMemory(next) {
	try {
		localStorage.setItem(memoryKey(), JSON.stringify(next));
	} catch {
		// Private mode / quota. A remembered default is a convenience, never a
		// precondition — the cashier types the figures either way.
	}
}

function pairKey(send, receive) {
	return `${send}>${receive}`;
}

// The remembered values as they stood when this form was built, kept beside the
// live form so the screen can say WHICH figures were filled in for the cashier
// rather than typed by them. A silently pre-filled percentage is the one number
// on this form nobody looked at, and it is frozen onto the transfer at register.
// Re-read after a register, because the next customer's form is built from the
// values that one just wrote.
const memorySnapshot = ref(readMemory());

// ---------------------------------------------------------------------------
// Idempotency
// ---------------------------------------------------------------------------
// One id per form, reused across retries so a timeout that actually posted comes
// back as the original transfer instead of registering a second one. A new id is
// minted only when the form is reset for the next customer.
function newRequestId() {
	return crypto.randomUUID();
}

const clientRequestId = ref(newRequestId());

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------
function blankForm() {
	// The snapshot, not storage: `writeMemory` swallows a quota or private-mode
	// failure, and the form has to be built from the same values the captions
	// below describe as remembered. Two reads of two different copies would put a
	// "same as your last transfer" caption on a figure that is not.
	const memory = memorySnapshot.value;
	return {
		posting_date: todayIso(),
		destination_branch: "",
		send_currency: "USD",
		receive_currency: "USD",
		sender_name: "",
		receiver_name: "",
		amount: null,
		commission_mode: EXCLUSIVE,
		commission_pct: Number.isFinite(memory.commission_pct) ? memory.commission_pct : null,
		exchange_rate: null,
	};
}

const form = ref(blankForm());

const isCrossCurrency = computed(() => form.value.send_currency !== form.value.receive_currency);

// Same currency on both legs is rate 1 — the identity, not an invented number.
// The server refuses a rate of zero or less, so it has to be sent.
const appliedRate = computed(() =>
	isCrossCurrency.value ? Number(form.value.exchange_rate) || 0 : 1,
);

// A rate belongs to a currency pair, so changing either leg drops it and pulls
// whatever this cashier last used for the new pair.
watch(
	() => [form.value.send_currency, form.value.receive_currency],
	([send, receive]) => {
		if (send === receive) {
			form.value.exchange_rate = null;
			return;
		}
		const remembered = memorySnapshot.value.rates?.[pairKey(send, receive)];
		form.value.exchange_rate = Number.isFinite(remembered) ? remembered : null;
	},
);

// True exactly while the field still holds the value that was put there for the
// cashier. One keystroke makes it false, because a caption claiming they did not
// type this figure has to stop the moment they do — and a stale "same as last
// time" on a hand-typed rate is worse than no caption at all.
const pctIsRemembered = computed(() => {
	const remembered = memorySnapshot.value.commission_pct;
	return Number.isFinite(remembered) && typedNumber(form.value.commission_pct) === remembered;
});

const rateIsRemembered = computed(() => {
	if (!isCrossCurrency.value) return false;
	const remembered =
		memorySnapshot.value.rates?.[pairKey(form.value.send_currency, form.value.receive_currency)];
	return Number.isFinite(remembered) && typedNumber(form.value.exchange_rate) === remembered;
});

// ---------------------------------------------------------------------------
// Cash desks
// ---------------------------------------------------------------------------
// One entry per configured desk, carrying the currencies that desk actually has
// a cash account in (ADR-006: no account in that currency means that desk cannot
// take or hand over that currency).
const deskByBranch = computed(() => {
	const map = new Map();
	for (const row of desks.value) {
		const branch = row?.branch || "";
		if (!branch) continue;
		if (!map.has(branch)) {
			map.set(branch, { branch, city: "", currencies: new Set() });
		}
		const desk = map.get(branch);
		if (!desk.city && row.city) desk.city = row.city;
		if (row.currency) desk.currencies.add(row.currency);
	}
	return map;
});

function deskLabel(desk) {
	if (!desk) return "";
	return desk.city ? t("{branch} — {city}", { branch: desk.branch, city: desk.city }) : desk.branch;
}

const originDesk = computed(() => deskByBranch.value.get(originBranch.value) || null);
const destinationDesk = computed(
	() => deskByBranch.value.get(form.value.destination_branch) || null,
);

// `city · branch`, not the `branch — city` of the selector above: this is the
// route as it is READ, and the Operations table has to spell it the same way
// (stabler-t1j9), so the composition lives in `composables/remittanceRoute.js`
// rather than here.
const routeText = computed(() => routeLabel(originDesk.value, destinationDesk.value));

const currencyLegsText = computed(() =>
	currencyLegs(form.value.send_currency, form.value.receive_currency),
);

const destinationOptions = computed(() =>
	[...deskByBranch.value.values()]
		.filter((desk) => desk.branch !== originBranch.value)
		.map((desk) => ({ value: desk.branch, label: deskLabel(desk) }))
		.sort((a, b) => a.label.localeCompare(b.label)),
);

// Read off the configured desks, not guessed. The server refuses at register and
// names the missing account; this says so before the cash is on the counter.
const originCurrencyMissing = computed(
	() => !!originDesk.value && !originDesk.value.currencies.has(form.value.send_currency),
);
const destinationCurrencyMissing = computed(
	() =>
		!!destinationDesk.value && !destinationDesk.value.currencies.has(form.value.receive_currency),
);

// One sentence per problem, rendered under the select that caused it AND returned
// by `validate()`. Written once because it has to appear twice and must not drift.
//
// It lives here rather than only in `validate()` for a reason found in review:
// `validate()` runs from `register()`, `register()` runs from the Register button,
// and that button is now disabled under exactly these two conditions — so a
// message produced only by `validate()` could never reach the screen. The state
// that blocks the button has to explain itself where the blocked cashier is
// already looking.
const originCurrencyProblem = computed(() =>
	originCurrencyMissing.value
		? t(
				"Your desk ({branch}) has no {currency} cash account — add it in Remittance Settings before registering.",
				{
					branch: deskLabel(originDesk.value) || originBranch.value,
					currency: form.value.send_currency,
				},
			)
		: "",
);

const destinationCurrencyProblem = computed(() =>
	destinationCurrencyMissing.value
		? t(
				"The destination desk ({branch}) has no {currency} cash account — add it in Remittance Settings before registering.",
				{
					branch: deskLabel(destinationDesk.value) || form.value.destination_branch,
					currency: form.value.receive_currency,
				},
			)
		: "",
);

// ---------------------------------------------------------------------------
// Quote — mirrors `_remittance_pricing.price_transfer`
// ---------------------------------------------------------------------------
// Decimal ROUND_HALF_UP over the decimal text. Binary floats round 1.005 down;
// the server uses Python's Decimal with ROUND_HALF_UP, so this is the same rule
// and the preview agrees with the stored triple at the minor unit.
function roundHalfUp(value, places = PRECISION) {
	const n = Number(value);
	if (!Number.isFinite(n)) return 0;
	const shifted = Number(`${n}e${places}`);
	const rounded = Math.round(Number.isFinite(shifted) ? shifted : n * 10 ** places);
	const out = Number(`${rounded}e-${places}`);
	return Number.isFinite(out) ? out : rounded / 10 ** places;
}

// `receiver_amount` is NOT priced by `_remittance_pricing`. The server writes
// `flt(principal * rate, 2)`, and `frappe.utils.rounded` normalises the product
// to 8 decimals BEFORE it rounds a tie up. That normalisation is load-bearing:
// 3 × 1.005 is 3.0149999999999997 in binary, so `roundHalfUp` above answers 3.01
// where the server answers 3.02. Measured over 20,042 random principal/rate
// pairs: 2 divergences, both exact half-cent ties. Hence the second helper —
// two server functions, two mirrors, rather than one that is wrong for one of
// them. (This mirrors Frappe's default `Banker's Rounding (legacy)`, which is
// half-up at a non-zero precision; a site switched to `Banker's Rounding` would
// round ties to even and this preview line would drift a cent on them again.)
function roundLikeFlt(value, places = PRECISION) {
	const n = Number(value);
	if (!Number.isFinite(n)) return 0;
	const multiplier = 10 ** places;
	const shifted = Number((n * multiplier).toFixed(8));
	const floorPart = Math.floor(shifted);
	// The explicit tie branch is what makes the plain `Math.round` below safe:
	// it never sees a .5 fraction, so JS and Python cannot disagree on it.
	const rounded = shifted - floorPart === 0.5 ? floorPart + 1 : Math.round(shifted);
	return rounded / multiplier;
}

// A blank percentage is not zero. `MoneyInput` emits null for an empty field and
// `Number(null)` is 0, so reading it straight through would quote a free transfer
// for a cashier who simply had not typed the rate yet — and then register one.
// Zero is a legal commission (ADR-002); it has to be typed.
function typedNumber(value) {
	if (value === null || value === undefined || value === "") return null;
	const n = Number(value);
	return Number.isFinite(n) ? n : null;
}

const quote = computed(() => {
	const typed = typedNumber(form.value.amount);
	const pct = typedNumber(form.value.commission_pct);
	if (typed === null || typed <= 0) return null;
	if (pct === null || pct < 0) return null;

	let principal;
	let commission;
	let tendered;
	if (form.value.commission_mode === INCLUSIVE) {
		tendered = typed;
		commission = roundHalfUp((tendered * pct) / (100 + pct));
		// The plug. `roundHalfUp` here strips the binary tail of a subtraction —
		// it is not a second rounding, and ADR-007 allows exactly one.
		principal = roundHalfUp(tendered - commission);
		if (principal <= 0) return null;
	} else {
		principal = typed;
		commission = roundHalfUp((principal * pct) / 100);
		tendered = roundHalfUp(principal + commission);
	}

	const rate = appliedRate.value;
	return {
		principal,
		commission,
		tendered,
		rate,
		// ADR-006: the obligation opens at the principal in the receive currency —
		// the commission never crosses the corridor.
		receiverAmount: rate > 0 ? roundLikeFlt(principal * rate) : null,
	};
});

const rateFormatter = computed(
	() =>
		new Intl.NumberFormat(language.value === "en" ? "en-US" : "ru-RU", {
			minimumFractionDigits: 2,
			maximumFractionDigits: 6,
		}),
);

function formatRate(value) {
	const n = Number(value);
	if (!Number.isFinite(n) || n <= 0) return "—";
	return rateFormatter.value.format(n);
}

// ---------------------------------------------------------------------------
// The mode flip announces itself
// ---------------------------------------------------------------------------
// ADR-007: the two modes are NOT inverses. Flipping the toggle is a RE-QUOTE —
// the figure already typed now means something else, and every amount in the
// panel moves. Said inline under the toggle rather than in a modal: the cashier
// flipped it deliberately, and a dialog would make them dismiss news they asked
// for. What they might miss is that the numbers they had already read changed.
const modeJustFlipped = ref(false);

watch(
	() => form.value.commission_mode,
	() => {
		// Only when there are amounts to move. On an empty form the flip changes
		// nothing, and announcing a recalculation that did not happen is noise.
		modeJustFlipped.value = !!quote.value;
	},
);

// Cleared by the next keystroke on either priced figure: from then on the panel
// shows what the cashier just typed, not what the flip produced.
watch(
	() => [form.value.amount, form.value.commission_pct],
	() => {
		modeJustFlipped.value = false;
	},
);

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------
async function loadDesks() {
	const rows = await call("frappe.client.get_list", {
		doctype: CASH_DESK_CHILD,
		parent: SETTINGS_DOCTYPE,
		filters: { parenttype: SETTINGS_DOCTYPE, parent: company.value },
		fields: ["branch", "city", "currency"],
		limit_page_length: 0,
		order_by: "idx asc",
	});
	return Array.isArray(rows) ? rows : [];
}

// The cashier's own desk. `Employee.branch` is the only per-user branch this
// stack has, so it is what "your own desk" resolves to. When it resolves to
// nothing the form is blocked rather than defaulted — registering a transfer out
// of the wrong desk moves real cash out of the wrong drawer.
async function resolveOriginBranch() {
	try {
		const rows = await call("frappe.client.get_list", {
			doctype: "Employee",
			filters: { user_id: session.user?.id || "", company: company.value, status: "Active" },
			fields: ["branch"],
			limit_page_length: 1,
		});
		return rows?.[0]?.branch || "";
	} catch {
		originLookupFailed.value = true;
		return "";
	}
}

async function loadExpiryPolicy() {
	try {
		const res = await remittanceApi.workQueue(company.value, REMITTANCE_QUEUES.EXPIRING_12H, 1, 0);
		return res?.policy_configured === true;
	} catch {
		// Unanswered. The expiry row says nothing rather than guessing a number.
		return null;
	}
}

async function load() {
	if (!company.value) return;
	loading.value = true;
	loadError.value = "";
	originLookupFailed.value = false;
	try {
		desks.value = await loadDesks();
	} catch (err) {
		desks.value = [];
		loadError.value = err?.message || t("Could not read the configured remittance cash desks.");
		loading.value = false;
		return;
	}
	originBranch.value = await resolveOriginBranch();
	expiryPolicyConfigured.value = await loadExpiryPolicy();
	loading.value = false;
}

watch(company, load);
onMounted(load);

// ---------------------------------------------------------------------------
// Register
// ---------------------------------------------------------------------------
function validate() {
	if (!company.value) return t("Choose a company first.");
	if (!originBranch.value) return t("Your own cash desk could not be resolved.");
	if (!form.value.destination_branch) return t("Choose the destination cash desk.");
	if (form.value.destination_branch === originBranch.value) {
		return t("The destination desk has to be a different desk from your own.");
	}
	// Kept as a backstop even though the button is disabled in these two states:
	// `validate()` is the gate, the disabled button is the courtesy. If the
	// binding is ever loosened, this still refuses before the cash moves.
	if (originCurrencyProblem.value) return originCurrencyProblem.value;
	if (destinationCurrencyProblem.value) return destinationCurrencyProblem.value;
	if (!form.value.sender_name.trim()) return t("Enter the sender's name.");
	if (!form.value.receiver_name.trim()) return t("Enter the receiver's name.");
	const amount = typedNumber(form.value.amount);
	if (amount === null || amount <= 0) return t("Enter an amount greater than zero.");
	const pct = typedNumber(form.value.commission_pct);
	if (pct === null || pct < 0) return t("Enter a commission percentage of zero or more.");
	if (isCrossCurrency.value && !(typedNumber(form.value.exchange_rate) > 0)) {
		return t("Enter the exchange rate you quoted the sender.");
	}
	if (!quote.value) return t("The commission cannot be the whole amount tendered.");
	return "";
}

function rememberQuote() {
	const rates = { ...(memorySnapshot.value.rates || {}) };
	if (isCrossCurrency.value && appliedRate.value > 0) {
		rates[pairKey(form.value.send_currency, form.value.receive_currency)] = appliedRate.value;
	}
	const next = { commission_pct: Number(form.value.commission_pct), rates };
	writeMemory(next);
	// Not re-read from storage: `writeMemory` swallows a quota or private-mode
	// failure, so the stored copy may not exist. What the next form is built from
	// is what the captions have to describe.
	memorySnapshot.value = next;
}

async function register() {
	submitError.value = validate();
	if (submitError.value) return;

	submitting.value = true;
	try {
		const res = await remittanceApi.registerRemittance({
			company: company.value,
			origin_branch: originBranch.value,
			destination_branch: form.value.destination_branch,
			origin_city: originDesk.value?.city || null,
			destination_city: destinationDesk.value?.city || null,
			send_currency: form.value.send_currency,
			receive_currency: form.value.receive_currency,
			sender_name: form.value.sender_name.trim(),
			receiver_name: form.value.receiver_name.trim(),
			amount: form.value.amount,
			exchange_rate: appliedRate.value,
			commission_mode: form.value.commission_mode,
			commission_pct: Number(form.value.commission_pct),
			posting_date: form.value.posting_date,
			client_request_id: clientRequestId.value,
		});
		rememberQuote();
		// Every figure on the receipt is the SERVER's, not the preview's.
		issued.value = {
			name: res?.name || "",
			pickupCode: res?.pickup_code || "",
			replayed: res?.replayed === true,
			receiverName: form.value.receiver_name.trim(),
			receiverAmount: Number.isFinite(Number(res?.receiver_amount))
				? Number(res.receiver_amount)
				: null,
			receiveCurrency: form.value.receive_currency,
		};
	} catch (err) {
		submitError.value = err?.message || t("Could not register the transfer.");
	} finally {
		submitting.value = false;
	}
}

// The code leaves memory here and nowhere else. A fresh request id follows,
// because the next customer is a different transfer.
function finish() {
	issued.value = null;
	form.value = blankForm();
	clientRequestId.value = newRequestId();
	submitError.value = "";
}
</script>

<template>
	<PickupCodeReceipt
		v-if="issued"
		:remittance-id="issued.name"
		:pickup-code="issued.pickupCode"
		:replayed="issued.replayed"
		:receiver-name="issued.receiverName"
		:receiver-amount="issued.receiverAmount"
		:receive-currency="issued.receiveCurrency"
		@acknowledge="finish"
	/>

	<div v-else-if="loading" class="text-center py-5">
		<div class="spinner-border text-primary" role="status"></div>
	</div>

	<div v-else-if="loadError" class="alert alert-danger">{{ loadError }}</div>

	<EmptyState
		v-else-if="!desks.length"
		icon="ti-building-bank"
		accent-icon="ti-alert-triangle"
		tone="warning"
		:title="t('No remittance cash desks are configured')"
		:subtitle="t('A Finance Manager has to add the cash desk accounts to Remittance Settings before a transfer can be registered.')"
	/>

	<EmptyState
		v-else-if="!originBranch"
		icon="ti-user-off"
		accent-icon="ti-alert-triangle"
		tone="warning"
		:title="t('Your own cash desk could not be resolved')"
		:subtitle="originLookupFailed
			? t('This screen could not read your employee record, so it cannot tell which desk you are registering from. Ask a Finance Manager to grant the access or to link your desk.')
			: t('Your user is not linked to an employee record with a branch, so this screen cannot tell which desk you are registering from. Ask a Finance Manager to link it.')"
	/>

	<div v-else class="row g-3">
		<!-- ── Form ─────────────────────────────────────────────────────────── -->
		<div class="col-lg-7">
			<div class="card">
				<div class="card-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<!-- 1. Desks. The origin is stated, not chosen: it is this cashier's
					     own branch and picking it would let cash leave another drawer. -->
					<div class="row g-3">
						<div class="col-md-6">
							<div class="form-label">{{ t("Your cash desk") }}</div>
							<div class="form-control-plaintext fw-semibold">{{ deskLabel(originDesk) || originBranch }}</div>
						</div>
						<div class="col-md-6">
							<label class="form-label required">{{ t("Destination cash desk") }}</label>
							<Select
								v-model="form.destination_branch"
								:options="destinationOptions"
								:placeholder="t('Select a desk…')"
							/>
							<div v-if="!destinationOptions.length" class="form-text text-warning">
								{{ t("No other desk is configured, so there is nowhere to send to yet.") }}
							</div>
						</div>

						<!-- 2. Currencies -->
						<div class="col-md-6">
							<label class="form-label required">{{ t("Send currency") }}</label>
							<Select v-model="form.send_currency" :options="CORRIDOR_CURRENCIES" />
							<!-- text-danger, not text-warning: this state now DISABLES the
							     Register button, so it is a refusal and not advice. The old
							     wording ("registering will be refused") also described a
							     future event that no longer happens. -->
							<div v-if="originCurrencyProblem" class="form-text text-danger">
								{{ originCurrencyProblem }}
							</div>
						</div>
						<div class="col-md-6">
							<label class="form-label required">{{ t("Receive currency") }}</label>
							<Select v-model="form.receive_currency" :options="CORRIDOR_CURRENCIES" />
							<div v-if="destinationCurrencyProblem" class="form-text text-danger">
								{{ destinationCurrencyProblem }}
							</div>
						</div>

						<!-- 3. Parties -->
						<div class="col-md-6">
							<label class="form-label required">{{ t("Sender name") }}</label>
							<input v-model="form.sender_name" type="text" class="form-control" autocomplete="off" />
						</div>
						<div class="col-md-6">
							<label class="form-label required">{{ t("Receiver name") }}</label>
							<input v-model="form.receiver_name" type="text" class="form-control" autocomplete="off" />
						</div>

						<!-- 4. Money. One typed figure, one percentage, one rate — all
						     three frozen on the transfer at register (ADR-009). -->
						<div class="col-12"><hr class="my-1" /></div>

						<div class="col-12">
							<label class="form-label">{{ t("Commission basis") }}</label>
							<div class="btn-group w-100" role="group">
								<input
									id="mode-exclusive"
									v-model="form.commission_mode"
									type="radio"
									class="btn-check"
									:value="EXCLUSIVE"
								/>
								<label class="btn btn-outline-secondary" for="mode-exclusive">{{ t("Exclusive") }}</label>
								<input
									id="mode-inclusive"
									v-model="form.commission_mode"
									type="radio"
									class="btn-check"
									:value="INCLUSIVE"
								/>
								<label class="btn btn-outline-secondary" for="mode-inclusive">{{ t("Inclusive") }}</label>
							</div>
							<div class="form-text text-secondary">
								<template v-if="form.commission_mode === INCLUSIVE">
									{{ t("Inclusive: you type what the sender puts on the counter, and the commission comes out of it.") }}
								</template>
								<template v-else>
									{{ t("Exclusive: you type the principal, and the commission is added on top.") }}
								</template>
							</div>
							<!-- The flip is a re-quote, not a display toggle (ADR-007). Inline
							     under the control that caused it, so it is read where the
							     cashier is already looking. -->
							<div v-if="modeJustFlipped" class="form-text text-primary stbl-mode-notice">
								<i class="ti ti-refresh me-1"></i>{{ t("Quote updated — switching how the fee is charged recalculates the amounts.") }}
							</div>
						</div>

						<div class="col-md-7">
							<label class="form-label required">
								<template v-if="form.commission_mode === INCLUSIVE">
									{{ t("Amount the sender hands over") }}
								</template>
								<template v-else>{{ t("Principal") }}</template>
							</label>
							<MoneyInput
								v-model="form.amount"
								:currency="form.send_currency"
								:language="language"
							/>
						</div>

						<div class="col-md-5">
							<label class="form-label required">{{ t("Commission %") }}</label>
							<div class="input-group">
								<MoneyInput
									v-model="form.commission_pct"
									hide-currency
									:max-fraction-digits="4"
									:language="language"
									:min="0"
									placeholder="0.00"
								/>
								<span class="input-group-text">%</span>
							</div>
							<!-- This figure was put here, not typed, and it is frozen onto the
							     transfer at register. Saying so is the difference between a
							     convenience and a number nobody looked at. -->
							<div v-if="pctIsRemembered" class="form-text text-secondary">
								<i class="ti ti-history me-1"></i>{{ t("Same as your last transfer") }}
							</div>
						</div>

						<div v-if="isCrossCurrency" class="col-md-7">
							<label class="form-label required">
								{{ t("Rate quoted to the sender") }}
							</label>
							<div class="input-group">
								<span class="input-group-text small text-uppercase">
									{{ t("1 {currency} =", { currency: form.send_currency }) }}
								</span>
								<MoneyInput
									v-model="form.exchange_rate"
									hide-currency
									:max-fraction-digits="6"
									:language="language"
									:min="0"
								/>
								<span class="input-group-text small text-uppercase">{{ form.receive_currency }}</span>
							</div>
							<div v-if="rateIsRemembered" class="form-text text-secondary">
								<i class="ti ti-history me-1"></i>{{ t("Same as your last transfer") }}
							</div>
						</div>

						<div class="col-md-5">
							<label class="form-label">{{ t("Posting date") }}</label>
							<DateInput v-model="form.posting_date" />
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- ── Quote ────────────────────────────────────────────────────────── -->
		<div class="col-lg-5">
			<div class="card stbl-quote">
				<div class="card-header">
					<h3 class="card-title">{{ t("Quote") }}</h3>
				</div>
				<div class="card-body">
					<!-- Seven rows in two named groups, because a flat list of six made
					     the cashier work out which figures the SENDER is quoted and which
					     the RECEIVER collects — in a form where the two are in different
					     currencies. `<div>` is a legal child of `<dl>` and carries the
					     group heading without pretending to be a term. -->
					<dl v-if="quote" class="row mb-0 g-1">
						<dt class="col-4 text-secondary small">{{ t("Route") }}</dt>
						<dd class="col-8 text-end small mb-0">
							<div>{{ routeText || "—" }}</div>
							<div v-if="currencyLegsText" class="stbl-quote-note">{{ currencyLegsText }}</div>
						</dd>

						<div class="col-12 stbl-quote-group text-secondary">
							{{ t("What the customer pays") }}
						</div>

						<dt class="col-6 text-secondary small">{{ t("Principal") }}</dt>
						<dd class="col-6 text-end font-monospace small mb-0">
							{{ formatMoney(quote.principal, form.send_currency, language) }}
						</dd>

						<dt class="col-6 text-secondary small">{{ t("Commission") }}</dt>
						<dd class="col-6 text-end font-monospace small text-primary mb-0">
							{{ formatMoney(quote.commission, form.send_currency, language) }}
							<!-- ALWAYS the principal, never the tendered amount. Under
							     Inclusive the cashier types the tendered figure, so the
							     obvious reading — "1% of what I typed" — is the wrong one,
							     and the base is what makes the commission checkable. -->
							<div class="stbl-quote-note">
								{{ t("{pct}% of principal ({principal})", {
									pct: form.commission_pct,
									principal: formatMoney(quote.principal, form.send_currency, language),
								}) }}
							</div>
						</dd>

						<dt class="col-6 small fw-semibold">{{ t("Sender hands over") }}</dt>
						<dd class="col-6 text-end font-monospace small fw-semibold mb-0">
							{{ formatMoney(quote.tendered, form.send_currency, language) }}
						</dd>

						<div class="col-12 stbl-quote-group text-secondary">
							{{ t("What the receiver collects") }}
						</div>

						<dt class="col-6 text-secondary small">{{ t("Applied rate") }}</dt>
						<dd class="col-6 text-end font-monospace small mb-0">{{ formatRate(quote.rate) }}</dd>

						<dt class="col-6 small fw-semibold text-success">{{ t("Receiver gets") }}</dt>
						<dd class="col-6 text-end font-monospace small fw-semibold text-success mb-0">
							{{ formatMoney(quote.receiverAmount, form.receive_currency, language) }}
						</dd>

						<!-- No number is invented here. Nothing in this product writes
						     `expires_at` yet, so the server answers
						     `policy_configured: false` and this row says that instead of
						     printing a deadline that would not be honoured. -->
						<dt class="col-6 text-secondary small">{{ t("Expiration time") }}</dt>
						<dd class="col-6 text-end small text-secondary mb-0">
							<template v-if="expiryPolicyConfigured === false">
								{{ t("Not configured yet") }}
							</template>
							<template v-else-if="expiryPolicyConfigured === true">
								{{ t("Recorded at register") }}
							</template>
							<template v-else>—</template>
						</dd>
					</dl>

					<p v-else class="text-secondary small mb-0">
						{{ t("Enter an amount and a commission percentage to see the quote.") }}
					</p>

					<div v-if="quote && expiryPolicyConfigured === false" class="form-text text-secondary mt-2">
						{{ t("A pickup expiry policy is not configured yet, so this transfer does not expire.") }}
					</div>
				</div>
				<div class="card-footer">
					<button
						type="button"
						class="btn btn-primary w-100"
						:disabled="submitting || !quote || originCurrencyMissing || destinationCurrencyMissing"
						@click="register"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>{{ t("Register transfer") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
@media (min-width: 992px) {
	.stbl-quote {
		position: sticky;
		top: 1rem;
	}
}

/* The group heading and the rule above it are the same device: they separate
   what the sender pays from what the receiver collects. */
.stbl-quote-group {
	margin-top: 0.5rem;
	padding-top: 0.5rem;
	border-top: 1px solid var(--tblr-border-color);
	font-size: 0.6875rem;
	font-weight: 600;
	letter-spacing: 0.04em;
	text-transform: uppercase;
}

/* Notes sit under the figure they explain and must never compete with it. */
.stbl-quote-note {
	font-size: 0.75rem;
	font-weight: 400;
	color: var(--tblr-secondary);
}

.stbl-mode-notice {
	animation: stbl-mode-notice-in 0.15s ease-out;
}

@keyframes stbl-mode-notice-in {
	from {
		opacity: 0;
	}
	to {
		opacity: 1;
	}
}

@media (prefers-reduced-motion: reduce) {
	.stbl-mode-notice {
		animation: none;
	}
}

/* 40px touch targets on a phone — this form is worked standing at a counter. */
@media (max-width: 575.98px) {
	.stbl-quote .btn,
	.btn-group .btn {
		min-height: 40px;
	}
}
</style>
