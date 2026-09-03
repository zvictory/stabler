<script setup>
/* Landed Charges Editor Modal — estimates freight, customs duties, terminal handling,
 * and insurance on a Supplier Quotation prior to Purchase Order issuance.
 *
 * Enforces IAS 2 §11 tax rules: recoverable VAT is kept in breakdown but excluded
 * from the capitalized landed cost total.
 *
 * ADR-605. `props.currency` is the COMPANY currency, because that is what every
 * total here is in: the server adds these charges to `base_grand_total`. It used
 * to be handed the quotation's currency, so an officer typed "1200" into a box
 * labelled USD and 1 200 so'm reached the sum that ranks the vendors. A line may
 * now name its own currency and rate — the same three fields a PO landed line
 * carries — and the converted figure is shown beside what was typed.
 */
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { todayIso } from "../composables/date.js";
import { t } from "../composables/i18n.js";
import { convertedPreview, unvaluedReason } from "../composables/landedLine.js";
import { chargeTypeLabel, chargeTypes, loadChargeTypes } from "../composables/landedChargeTypes.js";
import { useToast } from "../composables/useToast.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const props = defineProps({
	show: { type: Boolean, default: false },
	quotationName: { type: String, default: "" },
	supplierName: { type: String, default: "" },
	currency: { type: String, default: "USD" },
	baseGrandTotal: { type: Number, default: 0 },
});

const emit = defineEmits(["close", "saved"]);

const loading = ref(false);
// Non-empty while the modal could not load. The estimate is REPLACED on save, so
// an editor that failed to read must not offer to write — see `load`.
const loadError = ref("");
const saving = ref(false);
const charges = ref([]);
const baseTotal = ref(props.baseGrandTotal);

// The currencies a landed charge is realistically quoted in for an Uzbek
// importer. The empty option is company currency — which is every line stored
// before ADR-605, and stays the default. Same shape as remittanceCurrencies.js.
const CHARGE_CURRENCIES = ["USD", "EUR", "RUB", "CNY", "TRY"];

// ADR-606, and the review's P0. The row carries TWO type keys and they are not
// the same fact: `charge_type` is what is on disk ("Freight", "VAT", "General",
// or free text like "Local Delivery") and what `savedChargeLine` hands back;
// `charge_type_canonical` is what the <select> shows, since none of those
// spellings has an option of its own any more. Loading the canonical key into
// the field the save sends was a rewrite of stored data BY THE CLIENT —
// `update_quotation_landed` replaces the whole array, so pressing Save for any
// reason renamed every legacy line. Only `onTypeChange` moves a line.
//
// Named rather than inlined in `load()` so it can be exercised —
// `landedChargeTypes.spec.js` composes it, the way `PoControlBoard`'s
// `editorLine` is composed.
function loadedLine(c) {
	return {
		charge_type: c.charge_type || "",
		charge_type_canonical: c.charge_type_canonical || "transport",
		// An unrecognised type is the officer's own words, handed back rather
		// than swallowed into "Other". They are SHOWN — as the description's
		// placeholder — and not seeded into the model: `description` is a field
		// `savedChargeLine` sends, so seeding it wrote "Local Delivery" into the
		// description of a line that had none, on the next save made for an
		// unrelated reason. Same mistake as loading the canonical key into
		// `charge_type`, one column across.
		charge_type_unmapped: c.charge_type_unmapped || "",
		description: c.description || "",
		amount: Number(c.amount || 0),
		currency: c.currency || "",
		fx_rate: Number(c.fx_rate || 0),
		rate_date: c.rate_date || "",
		amount_original: c.amount_original == null ? null : Number(c.amount_original),
		fx_source: "",
		is_recoverable_vat: Boolean(c.is_recoverable_vat),
		// Derived, read-only, never sent back as themselves. `is_recoverable_vat`
		// above is the MERGED flag — what the checkbox shows — and these two say
		// where it came from: whether the STORED spelling is a VAT alias, and
		// what the flag was on disk before that forced it. `onVatChange` reads
		// the first, `savedChargeLine` the second.
		charge_type_is_vat: Boolean(c.charge_type_is_vat),
		is_recoverable_vat_stored: Boolean(c.is_recoverable_vat_stored),
	};
}

// ADR-606: `other` is the only type that names no cost by itself. Flagged, never
// blocked — the same stance the unvalued-line warning takes, for the same reason.
// Reads the DISPLAYED type: the officer is being asked about the option in front
// of them, not about the spelling the row happens to hold on disk.
//
// The unmapped text counts as an answer. A line stored "Local Delivery" resolves
// to `other` and its words live in the placeholder now, so asking it to say what
// it is would be demanding a name it already has, on disk.
function needsChargeLabel(line) {
	if (line.charge_type_canonical !== "other") return false;
	return !String(line.description || "").trim() && !String(line.charge_type_unmapped || "").trim();
}

// The one thing that renames a stored line: the officer choosing another type.
// Everything else — an amount, a currency, a rate — leaves `charge_type` exactly
// as it was read. See `loadedLine`.
function onTypeChange(line) {
	line.charge_type = line.charge_type_canonical;
}

// …and the one exception, because here leaving `charge_type` alone is what
// discards the edit. The server forces `is_recoverable_vat` ON for every line
// whose STORED spelling is a VAT alias (`_landed.py`, `charge_type_is_vat`), so
// clearing the box on a legacy "VAT" line and sending "VAT" back means the flag
// returns on the next read: the footer here gains the amount while
// `base_landed_total` — the figure that ranks the vendors — does not, and the
// box is ticked again when the modal reopens. Moving the stored type onto the
// canonical key (`other`, for every VAT spelling) is what makes the un-tick
// true. The row is then flagged for a description, which is the right question:
// a charge that is not recoverable VAT has to say what it is.
//
// Only on the un-tick. Ticking the box back on renames nothing — a recoverable
// line needs no type change, and rewriting on both edges would rename lines
// nobody renamed.
function onVatChange(line) {
	if (line.is_recoverable_vat || !line.charge_type_is_vat) return;
	line.charge_type = line.charge_type_canonical;
	line.charge_type_is_vat = false;
}

async function load() {
	if (!props.show || !props.quotationName) return;
	loading.value = true;
	loadError.value = "";
	try {
		// Sequential, and in ONE try, so either failure blocks the editor. That
		// includes the type list: a <select> with no options cannot be used, so
		// an editor that could not read the nine types must not offer to save
		// over the array it would replace. Both failures land in `loadError` —
		// the review's P1: `Promise.all` put them in a catch that toasted and
		// left Save enabled over an EMPTY row array, and this save REPLACES the
		// stored array, so one press after a transient failure wiped the
		// estimate.
		await loadChargeTypes();
		const res = await call("stabler.api.sourcing.get_quotation_landed", {
			quotation: props.quotationName,
			company: activeCompany.value,
		});
		baseTotal.value = res.base_grand_total || props.baseGrandTotal;
		charges.value = (res.charges || []).map(loadedLine);
		if (!charges.value.length) {
			addChargeLine();
		}
	} catch (err) {
		loadError.value = err?.message || t("Could not load landed charges.");
		charges.value = [];
		toast.error(loadError.value);
	} finally {
		loading.value = false;
	}
}

watch([() => props.show, () => props.quotationName], load, { immediate: true });

function addChargeLine() {
	charges.value.push({
		charge_type: "transport",
		charge_type_canonical: "transport",
		charge_type_unmapped: "",
		charge_type_is_vat: false,
		is_recoverable_vat_stored: false,
		description: "",
		amount: 0,
		currency: "",
		fx_rate: 0,
		rate_date: "",
		amount_original: null,
		fx_source: "",
		is_recoverable_vat: false,
	});
}

function removeChargeLine(idx) {
	charges.value.splice(idx, 1);
}

// `null` means the line cannot be valued at all. Counting those is the whole
// point: adding them as zero is how a total silently shrinks.
function priceLines(lines) {
	let total = 0;
	let unvalued = 0;
	for (const line of lines || []) {
		const value = convertedPreview(line);
		if (value === null) unvalued += 1;
		// IAS 2 §11 and the currency rule are independent: a VAT line is still
		// converted for display, it just never reaches the capitalized total.
		// ADR-606: the flag is the whole rule now — VAT stopped being a type, and
		// the server turns the flag ON for every line that was stored as one, so
		// a legacy VAT line arrives here with the checkbox already ticked.
		else if (!line.is_recoverable_vat) total += value;
	}
	return { total, unvalued };
}

async function fetchChargeRate(line) {
	line.fx_source = "";
	if (!line.currency) return;
	if (!line.rate_date) line.rate_date = todayIso();
	try {
		const raw = await call("stabler.api.money.get_exchange_rate_for_currencies", {
			from_currency: line.currency,
			to_currency: props.currency,
			posting_date: line.rate_date,
		});
		const rate = Number(raw) || 0;
		if (rate > 0) {
			line.fx_rate = rate;
			line.fx_source = t("from CBU") + " · " + line.rate_date;
		} else {
			line.fx_source = t("No exchange rate for this date — enter manually.");
		}
	} catch {
		line.fx_source = t("No exchange rate for this date — enter manually.");
	}
}

// A rate belongs to the currency it was quoted for. Carrying it across a currency
// change would price this charge with another currency's quote — the transfer form
// shipped exactly that bug (P0-TRF-1) and it inverted transfers.
function onChargeCurrency(line) {
	line.fx_rate = 0;
	line.rate_date = "";
	line.fx_source = "";
	if (!line.currency) {
		// Clearing the currency is one of the two remedies the row offers, and it
		// means "this number is already in company currency" — so the figure has to
		// survive the move. Nulling `amount_original` without carrying it across
		// destroyed whatever the officer had typed on a line created this session.
		line.amount = Number(line.amount_original) || Number(line.amount) || 0;
		line.amount_original = null;
		return;
	}
	// Deliberately NOT seeding `amount_original` from `amount`: that figure is
	// company currency by construction and copying it into a USD box would relabel
	// it. The line shows as unvalued until the officer types the figure in the
	// currency they just named.
	fetchChargeRate(line);
}

// A row is dropped on save only when it is empty on EVERY field the officer can
// fill. The old test — `Number(c.currency ? c.amount_original : c.amount) > 0 ||
// description` — asked the wrong box the moment a currency was picked: a legacy
// so'm line onto which USD had just been chosen still has `amount_original` null,
// so it read as blank, was never sent, and the stored charge was deleted without a
// word. If it was the only line, `custom_landed_charges` went NULL and the whole
// estimate vanished. A named currency is itself a thing the officer did.
function isBlankLine(line) {
	return (
		!line.currency &&
		!(Number(line.amount) > 0) &&
		!(Number(line.amount_original) > 0) &&
		!String(line.description || "").trim()
	);
}

const landedChargesTotal = computed(() => priceLines(charges.value).total);
const unvaluedCount = computed(() => priceLines(charges.value).unvalued);

const totalDeliveredCost = computed(() => {
	return (Number(baseTotal.value) || 0) + landedChargesTotal.value;
});

// The inverse of `loadedLine`: what a row becomes on the wire. Named so the round
// trip can be exercised — a read must hand the editor something the editor can
// hand back unchanged, and `charge_type` is the half the review's P0 was about.
function savedChargeLine(c) {
	return {
		// The STORED spelling, never the one the <select> displayed. `onTypeChange`
		// is what moves it, and only when the officer picks another type.
		charge_type: c.charge_type,
		description: c.description,
		// Both figures travel because they are two different facts, not one
		// fact twice: `amount` is what was typed in company currency and
		// `amount_original` what was typed in the line's own. The server
		// stores exactly what it is given and derives the company-currency
		// value on every read, so sending only `amount_original` would drop
		// the so'm figure of a half-switched line — the evidence that the
		// line is unfinished, and the only thing left to fix it with.
		amount: Number(c.amount || 0),
		amount_original: c.currency ? Number(c.amount_original || 0) : null,
		currency: c.currency || "",
		fx_rate: Number(c.fx_rate) || 0,
		rate_date: c.rate_date || "",
		// The last stored key a no-edit save still moved. On a line whose stored
		// spelling is a VAT alias the server FORCES this flag on, so sending the
		// displayed value back wrote the alias table's verdict into the evidence
		// field: `{"charge_type": "VAT", "is_recoverable_vat": false}` on disk
		// became true after one save made for an unrelated reason.
		//
		// So the same rule `charge_type` follows — hand back what was loaded
		// unless the officer changed it. No "touched" tracking is needed to know
		// that: on an alias-spelled line the box is displayed ticked, so the only
		// edit available is the un-tick, and `onVatChange` clears
		// `charge_type_is_vat` on exactly that edge, after which the displayed
		// flag is what travels. `flag && !charge_type_is_vat` would not do — it
		// merely inverts the drift, normalising to false the rows an older editor
		// had already persisted as true.
		is_recoverable_vat: c.charge_type_is_vat
			? Boolean(c.is_recoverable_vat_stored)
			: Boolean(c.is_recoverable_vat),
	};
}

async function save() {
	if (saving.value) return;
	// The button is already disabled; this is the guarantee behind it. A save
	// after a failed load posts an empty array over an estimate that read fine
	// yesterday.
	if (loadError.value) return;
	saving.value = true;
	try {
		const validCharges = charges.value.filter((c) => !isBlankLine(c)).map(savedChargeLine);

		await call("stabler.api.sourcing.update_quotation_landed", {
			quotation: props.quotationName,
			charges: JSON.stringify(validCharges),
			company: activeCompany.value,
		});
		toast.success(t("Landed charges estimate saved."));
		emit("saved");
		emit("close");
	} catch (err) {
		toast.error(err?.message || t("Could not save landed charges."));
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<div v-if="props.show" class="modal modal-blur show d-block" tabindex="-1" style="background: rgba(0,0,0,0.5);">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header bg-light">
					<div>
						<h5 class="modal-title fw-bold">
							<i class="ti ti-truck-delivery me-1 text-primary"></i>
							{{ t("Estimate landed charges") }} — {{ props.quotationName }}
						</h5>
						<div class="text-secondary small">{{ props.supplierName }}</div>
					</div>
					<button type="button" class="btn-close" @click="emit('close')"></button>
				</div>

				<div class="modal-body">
					<div v-if="loading" class="py-4 text-center text-secondary">
						{{ t("Loading landed charges…") }}
					</div>

					<!-- Not an empty table: this estimate is REPLACED on save, and a table
					     with no rows is indistinguishable from a quotation that has no
					     estimate at all. -->
					<div v-else-if="loadError" class="alert alert-danger mb-0">
						<i class="ti ti-alert-triangle me-1"></i>{{ loadError }}
						<div class="small text-secondary mt-1">{{ t("Close this and open it again — nothing has been changed.") }}</div>
					</div>

					<template v-else>
						<!-- Summary Card -->
						<div class="card bg-primary-lt mb-3">
							<div class="card-body py-2">
								<div class="row align-items-center text-center">
									<div class="col-4 border-end">
										<div class="text-secondary small text-uppercase">{{ t("Sticker price") }}</div>
										<div class="fw-bold font-monospace text-body">
											{{ formatMoney(baseTotal, props.currency, user.language) }}
										</div>
									</div>
									<div class="col-4 border-end">
										<div class="text-secondary small text-uppercase">{{ t("Landed charges") }}</div>
										<div class="fw-bold font-monospace text-warning">
											+{{ formatMoney(landedChargesTotal, props.currency, user.language) }}
										</div>
									</div>
									<div class="col-4">
										<div class="text-secondary small text-uppercase">{{ t("Total delivered cost") }}</div>
										<div class="h4 mb-0 font-monospace text-primary fw-bold">
											{{ formatMoney(totalDeliveredCost, props.currency, user.language) }}
										</div>
									</div>
								</div>
							</div>
						</div>

						<!-- The totals above are SHORT while any line cannot be valued, so say
						     so where they are read, not only on the row that caused it. The
						     estimate still saves: the server excludes and flags those lines. -->
						<div v-if="unvaluedCount" class="alert alert-warning py-2 mb-3">
							<i class="ti ti-alert-triangle me-1"></i>
							{{ t("{count} charge line(s) have a currency with no exchange rate and are excluded from these totals.", { count: unvaluedCount }) }}
						</div>

						<div class="table-responsive mb-3">
							<table class="table table-vcenter">
								<thead>
									<tr>
										<th style="width: 30%;">{{ t("Charge type") }}</th>
										<th>{{ t("Description") }}</th>
										<th style="width: 25%;" class="text-end">{{ t("Amount") }}</th>
										<th style="width: 10%;" class="text-center">{{ t("Recoverable VAT") }}</th>
										<th style="width: 5%;"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(line, idx) in charges" :key="idx">
										<td>
											<!-- Binds the DISPLAY key; `onTypeChange` is what writes the
											     officer's pick into the stored `charge_type`. See `loadedLine`. -->
											<select v-model="line.charge_type_canonical" class="form-select form-select-sm" @change="onTypeChange(line)">
												<option v-for="opt in chargeTypes" :key="opt.key" :value="opt.key">
													{{ chargeTypeLabel(opt.key) }}
												</option>
											</select>
										</td>
										<td>
											<input
												v-model="line.description"
												type="text"
												class="form-control form-control-sm"
												:class="{ 'is-invalid': needsChargeLabel(line) }"
												:placeholder="line.charge_type_unmapped || t('Optional details (e.g. FOB shipping, duty rate)')"
											/>
											<!-- ADR-606: "Other" names no cost on its own. Flagged, not
											     blocked — the save still goes through, like an unvalued line. -->
											<div v-if="needsChargeLabel(line)" class="small text-danger mt-1">
												{{ t("Say what this charge is.") }}
											</div>
										</td>
										<td>
											<!-- ADR-605: typed in the line's OWN currency and shown converted
											     underneath. An empty pick means it is already in company
											     currency, which is every line stored before this. -->
											<div class="d-flex gap-1">
												<MoneyInput
													v-if="line.currency"
													v-model="line.amount_original"
													:currency="line.currency"
													:language="user.language"
													size="sm"
												/>
												<MoneyInput
													v-else
													v-model="line.amount"
													:currency="props.currency"
													:language="user.language"
													size="sm"
												/>
												<select
													v-model="line.currency"
													class="form-select form-select-sm"
													style="max-width:74px"
													:title="t('Currency this charge is quoted in')"
													@change="onChargeCurrency(line)"
												>
													<option value="">{{ props.currency }}</option>
													<option v-for="cc in CHARGE_CURRENCIES" :key="cc" :value="cc">{{ cc }}</option>
												</select>
											</div>
											<div v-if="line.currency" class="input-group input-group-sm mt-1">
												<span class="input-group-text px-1 small">1&nbsp;{{ line.currency }}</span>
												<MoneyInput
													v-model="line.fx_rate"
													currency=""
													:language="user.language"
													:group-while-typing="true"
													size="sm"
												/>
												<button
													type="button"
													class="btn btn-outline-secondary"
													:title="t('Fetch the Central Bank rate')"
													@click="fetchChargeRate(line)"
												>
													<i class="ti ti-refresh"></i>
												</button>
											</div>
											<div v-if="line.currency" class="d-flex align-items-center justify-content-end gap-1 mt-1">
												<span class="small text-secondary">{{ t("Rate date") }}</span>
												<DateInput v-model="line.rate_date" size="sm" @update:model-value="fetchChargeRate(line)" />
											</div>
											<div v-if="line.currency" class="small text-end mt-1">
												<span v-if="convertedPreview(line) !== null" class="font-monospace text-secondary">
													= {{ formatMoney(convertedPreview(line), props.currency, user.language) }}
												</span>
												<span v-else class="text-danger">
													<i class="ti ti-alert-triangle me-1"></i>
													<template v-if="unvaluedReason(line) === 'rate'">
														{{ t("No rate for {ccy} — enter a rate or clear the currency", { ccy: line.currency }) }}
													</template>
													<template v-else>
														{{ t("Enter the amount in {ccy} and a rate, or clear the currency", { ccy: line.currency }) }}
													</template>
												</span>
											</div>
											<div v-if="line.fx_source" class="small text-secondary text-end">{{ line.fx_source }}</div>
										</td>
										<td class="text-center">
											<!-- Clearing this on a line whose STORED type is a VAT spelling
											     also moves the type, or the server flags it again on the
											     next read and the edit never happened. See `onVatChange`. -->
											<input
												v-model="line.is_recoverable_vat"
												type="checkbox"
												class="form-check-input"
												:title="t('IAS 2 §11: Recoverable VAT is excluded from capitalized landed cost')"
												@change="onVatChange(line)"
											/>
										</td>
										<td class="text-center">
											<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeChargeLine(idx)">
												<i class="ti ti-trash"></i>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
						</div>

						<button type="button" class="btn btn-outline-primary btn-sm" @click="addChargeLine">
							<i class="ti ti-plus me-1"></i>{{ t("Add charge line") }}
						</button>

						<div class="text-secondary small mt-3">
							<i class="ti ti-info-circle me-1"></i>
							{{ t("Landed cost estimates let buyers compare delivered totals before issuing a Purchase Order. Recoverable VAT lines are excluded from landed rankings.") }}
						</div>
					</template>
				</div>

				<div class="modal-footer">
					<button type="button" class="btn btn-secondary" @click="emit('close')">
						{{ t("Cancel") }}
					</button>
					<!-- An unvaluable line does NOT block the save. The server stores it,
					     excludes it from the total and returns `has_unvalued_charges`, which
					     the comparison row, the winner selector, the award snapshot and the
					     pre-win bid estimate all show. Blocking here would contradict that
					     contract and make every one of those flags unreachable through the
					     product — an estimate typed under deadline must be saveable
					     half-finished. The alert above and the row message are the flag. -->
					<button
						type="button"
						class="btn btn-primary"
						:disabled="saving || loading || Boolean(loadError)"
						@click="save"
					>
						<i class="ti ti-check me-1"></i>{{ saving ? t("Saving…") : t("Save estimate") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
