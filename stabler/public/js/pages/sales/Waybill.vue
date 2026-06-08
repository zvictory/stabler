<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";

const route = useRoute();
const router = useRouter();
const session = useSession();
const { user } = storeToRefs(session);

const loading = ref(true);
const error = ref("");
const doc = ref(null);

// Signatory fields — editable on screen, printed on page, never persisted.
const sigSotuv = ref("");
const sigKamera = ref("");
const sigHaydovchi = ref("");
const sigMashina = ref("");
const sigQabul = ref("");

// Parse pcs-per-box from item name: "Item Name (20)" → 20
function parsePcsPerBox(itemName) {
	const m = (itemName || "").match(/\((\d+)\)\s*$/);
	return m ? Number(m[1]) : null;
}

const enrichedItems = computed(() => {
	if (!doc.value?.items) return [];
	return doc.value.items.map((it) => {
		const pcs = parsePcsPerBox(it.item_name || it.item_code);
		const qty = Number(it.qty || 0);
		return { ...it, pcs_per_box: pcs, total_pcs: pcs != null ? qty * pcs : null };
	});
});

async function load() {
	const name = route.params.name;
	if (!name) {
		router.push("/sales/invoices");
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		doc.value = await call("stabler.api.sales.sales_invoice_print", { name });
	} catch (err) {
		error.value = err?.message || t("Failed to load invoice.");
	} finally {
		loading.value = false;
	}
}

function triggerPrint() {
	if (loading.value || !doc.value) return;
	window.print();
}

onMounted(load);
</script>

<template>
	<div class="waybill-wrapper">
		<!-- Controls — hidden when printing -->
		<div class="no-print mb-3 d-flex gap-2 flex-wrap align-items-center">
			<button type="button" class="btn btn-sm btn-outline-secondary" @click="router.back()">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
			</button>
			<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="loading || !doc" @click="triggerPrint">
				<i class="ti ti-printer me-1"></i>{{ t("Print") }}
			</button>
		</div>

		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="alert alert-danger">{{ error }}</div>

		<div v-else-if="doc" class="waybill waybill-print">
			<div class="waybill-header text-center mb-3">
				<div class="small text-secondary">{{ doc.company_name }}</div>
				<h4 class="mb-0 mt-1">YUK XATI</h4>
				<div class="small font-monospace text-secondary">{{ doc.name }} · {{ formatDate(doc.posting_date) }}</div>
			</div>

			<div class="row g-2 mb-3 small">
				<div class="col-6">
					<strong>{{ t("Customer") }}:</strong> {{ doc.customer_name }}
				</div>
				<div class="col-6 text-end">
					<strong>{{ t("Date") }}:</strong> {{ formatDate(doc.posting_date) }}
				</div>
			</div>

			<table class="table table-sm table-bordered table-vcenter table-no-stripe waybill-table mb-3">
				<thead>
					<tr>
						<th style="width: 32px">№</th>
						<th>{{ t("Mahsulot nomi") }}</th>
						<th class="text-end" style="width: 80px">{{ t("Soni (korobka)") }}</th>
						<th class="text-end" style="width: 90px">{{ t("O'lchov birlik") }}</th>
						<th class="text-end" style="width: 90px">{{ t("Jami muzqaymoq soni (dona)") }}</th>
						<th class="text-end" style="width: 90px">{{ t("Narxi") }}</th>
						<th class="text-end" style="width: 100px">{{ t("Jami summa") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(it, i) in enrichedItems" :key="i">
						<td class="text-center">{{ i + 1 }}</td>
						<td>{{ it.item_name || it.item_code }}</td>
						<td class="text-end font-monospace">{{ it.qty }}</td>
						<td class="text-end">{{ it.uom || "—" }}</td>
						<td class="text-end font-monospace">{{ it.total_pcs ?? "—" }}</td>
						<td class="text-end font-monospace">{{ formatMoney(it.rate, doc.currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(it.amount, doc.currency, user.language) }}</td>
					</tr>
				</tbody>
				<tfoot>
					<tr>
						<td colspan="6" class="text-end fw-semibold">{{ t("Jami") }}:</td>
						<td class="text-end font-monospace fw-bold">{{ formatMoney(doc.grand_total, doc.currency, user.language) }}</td>
					</tr>
				</tfoot>
			</table>

			<!-- Signatory block: fill on screen, prints on the page -->
			<div class="waybill-signatories mt-4">
				<div class="row g-3">
					<div class="col-6">
						<div class="sig-label">SOTUV BO'LIMI</div>
						<input v-model="sigSotuv" type="text" class="form-control form-control-sm no-print" :placeholder="t('F.I.O.')" />
						<div class="sig-print-line">(imzo) ________________ {{ sigSotuv }}</div>
					</div>
					<div class="col-6">
						<div class="sig-label">KAMERA MUDIRI</div>
						<input v-model="sigKamera" type="text" class="form-control form-control-sm no-print" :placeholder="t('F.I.O.')" />
						<div class="sig-print-line">(imzo) ________________ {{ sigKamera }}</div>
					</div>
					<div class="col-6">
						<div class="sig-label">HAYDOVCHI</div>
						<input v-model="sigHaydovchi" type="text" class="form-control form-control-sm no-print" :placeholder="t('F.I.O.')" />
						<div class="sig-print-line">(imzo) ________________ {{ sigHaydovchi }}</div>
					</div>
					<div class="col-6">
						<div class="sig-label">MASHINA RAQAMI</div>
						<input v-model="sigMashina" type="text" class="form-control form-control-sm no-print" :placeholder="t('Raqam')" />
						<div class="sig-print-line">________________ {{ sigMashina }}</div>
					</div>
					<div class="col-12">
						<div class="sig-label">QABUL QILUVCHI</div>
						<input v-model="sigQabul" type="text" class="form-control form-control-sm no-print" :placeholder="t('F.I.O.')" />
						<div class="sig-print-line">(imzo) ________________ {{ sigQabul }}</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style>
.waybill-wrapper {
	max-width: 960px;
	margin: 0 auto;
	padding: 1.5rem;
}
.waybill-table th {
	font-size: 0.75rem;
}
.sig-label {
	font-weight: 600;
	font-size: 0.8rem;
	text-transform: uppercase;
	margin-bottom: 0.25rem;
}
.sig-print-line {
	display: none;
	margin-top: 0.25rem;
	font-size: 0.85rem;
}

@media print {
	@page {
		size: A4 portrait;
		margin: 10mm 10mm 10mm 10mm;
	}
	body * {
		visibility: hidden;
	}
	.waybill-print,
	.waybill-print * {
		visibility: visible;
	}
	.waybill-print {
		position: absolute;
		left: 0;
		top: 0;
		width: 100%;
		-webkit-print-color-adjust: exact;
		print-color-adjust: exact;
	}
	.no-print {
		display: none !important;
	}
	.waybill-wrapper {
		padding: 0;
		max-width: 100%;
	}
	.waybill {
		font-size: 10px;
	}
	.waybill-table th,
	.waybill-table td {
		padding: 3px 4px !important;
		font-size: 9px;
	}
	.sig-print-line {
		display: block !important;
	}
}
</style>
