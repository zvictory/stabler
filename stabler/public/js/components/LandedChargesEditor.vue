<script setup>
/* Landed Charges Editor Modal — estimates freight, customs duties, terminal handling,
 * and insurance on a Supplier Quotation prior to Purchase Order issuance.
 *
 * Enforces IAS 2 §11 tax rules: recoverable VAT is kept in breakdown but excluded
 * from the capitalized landed cost total.
 */
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { formatMoney } from "../composables/money.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import MoneyInput from "./MoneyInput.vue";

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

const landedChargesTotal = computed(() => {
	return charges.value.reduce((sum, c) => {
		if (c.is_recoverable_vat || c.charge_type === "VAT") return sum;
		return sum + (Number(c.amount) || 0);
	}, 0);
});

const totalDeliveredCost = computed(() => {
	return (Number(baseTotal.value) || 0) + landedChargesTotal.value;
});

async function save() {
	if (saving.value) return;
	saving.value = true;
	try {
		const validCharges = charges.value
			.filter((c) => Number(c.amount) > 0 || c.description.trim())
			.map((c) => ({
				charge_type: c.charge_type,
				description: c.description,
				amount: Number(c.amount || 0),
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
												<MoneyInput
												v-model="line.amount"
												:currency="props.currency"
												size="sm"
											/>
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
					<button type="button" class="btn btn-primary" :disabled="saving || loading" @click="save">
						<i class="ti ti-check me-1"></i>{{ saving ? t("Saving…") : t("Save estimate") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
