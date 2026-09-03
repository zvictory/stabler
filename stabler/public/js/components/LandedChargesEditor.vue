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
const saving = ref(false);
const charges = ref([]);
const baseTotal = ref(props.baseGrandTotal);

// The currencies a landed charge is realistically quoted in for an Uzbek
// importer. The empty option is company currency — which is every line stored
// before ADR-605, and stays the default. Same shape as remittanceCurrencies.js.
const CHARGE_CURRENCIES = ["USD", "EUR", "RUB", "CNY", "TRY"];

// ADR-606. A stored line names its type in whatever spelling its era used
// ("Freight", "VAT", or free text like "Local Delivery"); the server resolves it
// to one of the nine and says so in `charge_type_canonical`. Reading THAT is what
// puts a 2025 quotation and a 2026 purchase order on the same option.
//
// Named rather than inlined in `load()` so it can be exercised —
// `landedChargeTypes.spec.js` composes it, the way `PoControlBoard`'s
// `editorLine` is composed.
function loadedLine(c) {
	return {
		charge_type: c.charge_type_canonical || "transport",
		// An unrecognised type is the officer's own words. The server hands them
		// back rather than swallowing them into "Other"; they belong in the box
		// that holds words, and only when it is empty.
		description: c.description || c.charge_type_unmapped || "",
		amount: Number(c.amount || 0),
		currency: c.currency || "",
		fx_rate: Number(c.fx_rate || 0),
		rate_date: c.rate_date || "",
		amount_original: c.amount_original == null ? null : Number(c.amount_original),
		fx_source: "",
		is_recoverable_vat: Boolean(c.is_recoverable_vat),
	};
}

// ADR-606: `other` is the only type that names no cost by itself. Flagged, never
// blocked — the same stance the unvalued-line warning takes, for the same reason.
function needsChargeLabel(line) {
	return line.charge_type === "other" && !String(line.description || "").trim();
}

async function load() {
	if (!props.show || !props.quotationName) return;
	loading.value = true;
	try {
		const [res] = await Promise.all([
			call("stabler.api.sourcing.get_quotation_landed", {
				quotation: props.quotationName,
				company: activeCompany.value,
			}),
			// In the same try as the charges: with no list there is nothing to pick
			// a type from, so a failed fetch must surface, not leave an empty select.
			loadChargeTypes(),
		]);
		baseTotal.value = res.base_grand_total || props.baseGrandTotal;
		charges.value = (res.charges || []).map(loadedLine);
		if (!charges.value.length) {
			addChargeLine();
		}
	} catch (err) {
		toast.error(err?.message || t("Could not load landed charges."));
	} finally {
		loading.value = false;
	}
}

watch([() => props.show, () => props.quotationName], load, { immediate: true });

function addChargeLine() {
	charges.value.push({
		charge_type: "transport",
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

async function save() {
	if (saving.value) return;
	saving.value = true;
	try {
		const validCharges = charges.value
			.filter((c) => !isBlankLine(c))
			.map((c) => ({
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
				is_recoverable_vat: Boolean(c.is_recoverable_vat),
			}));

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
											<select v-model="line.charge_type" class="form-select form-select-sm">
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
												:placeholder="t('Optional details (e.g. FOB shipping, duty rate)')"
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
											<input
												v-model="line.is_recoverable_vat"
												type="checkbox"
												class="form-check-input"
												:title="t('IAS 2 §11: Recoverable VAT is excluded from capitalized landed cost')"
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
						:disabled="saving || loading"
						@click="save"
					>
						<i class="ti ti-check me-1"></i>{{ saving ? t("Saving…") : t("Save estimate") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
