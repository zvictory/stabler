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

const CHARGE_TYPES = [
	{ value: "Freight", label: t("Freight & Logistics") },
	{ value: "Customs Duty", label: t("Customs Duty & Tariff") },
	{ value: "Handling & Terminal", label: t("Handling & Terminal Fees") },
	{ value: "Insurance", label: t("Cargo Insurance") },
	{ value: "VAT", label: t("Import VAT (Recoverable)") },
	{ value: "Other", label: t("Other Charge") },
];
// The same list the PO landed editor offers (PoControlBoard.vue:47) — a forwarder
// or a declarant quotes in one of these, and an empty pick means company currency.
const CHARGE_CURRENCIES = ["USD", "EUR", "RUB", "CNY", "TRY"];

async function load() {
	if (!props.show || !props.quotationName) return;
	loading.value = true;
	try {
		const res = await call("stabler.api.sourcing.get_quotation_landed", {
			quotation: props.quotationName,
			company: activeCompany.value,
		});
		baseTotal.value = res.base_grand_total || props.baseGrandTotal;
		charges.value = (res.charges || []).map((c) => ({
			charge_type: c.charge_type || "Freight",
			description: c.description || "",
			amount: Number(c.amount || 0),
			currency: c.currency || "",
			fx_rate: Number(c.fx_rate || 0),
			rate_date: c.rate_date || "",
			amount_original: c.amount_original == null ? null : Number(c.amount_original),
			fx_source: "",
			is_recoverable_vat: Boolean(c.is_recoverable_vat),
		}));
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
		charge_type: "Freight",
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

function onTypeChange(line) {
	if (line.charge_type === "VAT") {
		line.is_recoverable_vat = true;
	}
}

// Mirrors `tender_landed_math.converted_amount`, which the server applies to the
// stored figure. This is only the preview while typing, and it returns null on an
// unusable rate for the same reason: a charge shown at its unconverted number
// reads as CHEAP and hands the tender to the wrong vendor.
function convertedPreview(line) {
	if (!line.currency) return Number(line.amount) || 0;
	const rate = Number(line.fx_rate) || 0;
	if (rate <= 0) return null;
	return Math.round((Number(line.amount_original) || 0) * rate * 100) / 100;
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
		else if (!(line.is_recoverable_vat || line.charge_type === "VAT")) total += value;
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
	if (!line.currency) line.amount_original = null;
	else fetchChargeRate(line);
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
			.filter((c) => Number(c.currency ? c.amount_original : c.amount) > 0 || c.description.trim())
			.map((c) => ({
				charge_type: c.charge_type,
				description: c.description,
				// Both figures travel: the server re-derives `amount` from
				// `amount_original × fx_rate`, so sending only one of them would let
				// an already-converted figure be converted again on the next save.
				amount: Number(c.amount || 0),
				amount_original: c.currency ? Number(c.amount_original || 0) : null,
				currency: c.currency || "",
				fx_rate: Number(c.fx_rate) || 0,
				rate_date: c.rate_date || "",
				is_recoverable_vat: c.is_recoverable_vat || c.charge_type === "VAT",
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
						     so where they are read, not only on the row that caused it. -->
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
											<select v-model="line.charge_type" class="form-select form-select-sm" @change="onTypeChange(line)">
												<option v-for="opt in CHARGE_TYPES" :key="opt.value" :value="opt.value">
													{{ opt.label }}
												</option>
											</select>
										</td>
										<td>
											<input
												v-model="line.description"
												type="text"
												class="form-control form-control-sm"
												:placeholder="t('Optional details (e.g. FOB shipping, duty rate)')"
											/>
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
													{{ t("No rate for {ccy} — enter a rate or clear the currency", { ccy: line.currency }) }}
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
					<!-- Saving with an unvaluable line stores an estimate the server then
					     ranks short, with nothing on the comparison saying which line went
					     missing. Two ways out, both named on the row itself. -->
					<button
						type="button"
						class="btn btn-primary"
						:disabled="saving || loading || unvaluedCount > 0"
						:title="unvaluedCount ? t('Enter an exchange rate or clear the currency on every flagged line') : ''"
						@click="save"
					>
						<i class="ti ti-check me-1"></i>{{ saving ? t("Saving…") : t("Save estimate") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
