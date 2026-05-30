<script setup>
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { useSession } from "../../stores/session.js";
import { storeToRefs } from "pinia";
const route = useRoute();
const router = useRouter();
const session = useSession();
const { user } = storeToRefs(session);

const loading = ref(true);
const error = ref("");
const doc = ref(null);

function fmt(val) {
	return formatMoney(val ?? 0, doc.value?.currency, user.value.language);
}

async function load() {
	const name = route.params.name;
	if (!name) { router.push("/sales/invoices"); return; }
	loading.value = true;
	error.value = "";
	try {
		doc.value = await call("stabler.api.sales.sales_invoice_print", { name });
	} catch (err) {
		error.value = err?.message || "Failed to load invoice.";
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="print-wrapper">
		<!-- Controls — hidden when printing -->
		<div class="no-print mb-3 d-flex gap-2">
			<button type="button" class="btn btn-sm btn-outline-secondary" @click="router.back()">
				<i class="ti ti-arrow-left me-1"></i>Back
			</button>
			<button type="button" class="btn btn-sm btn-primary ms-auto" @click="window.print()">
				<i class="ti ti-printer me-1"></i>Print
			</button>
		</div>

		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="alert alert-danger">{{ error }}</div>

		<div v-else-if="doc" class="receipt">
			<!-- Company header -->
			<div class="receipt-header text-center mb-4">
				<h4 class="mb-0">{{ doc.company_name }}</h4>
				<div v-if="doc.company_tax_id" class="small text-secondary">
					TIN: {{ doc.company_tax_id }}
				</div>
				<div class="small text-secondary">{{ doc.company_abbr }}</div>
			</div>

			<hr />

			<!-- Invoice meta -->
			<div class="row g-2 mb-3 small">
				<div class="col-6">
					<strong>Invoice #</strong><br />
					<span class="font-monospace">{{ doc.name }}</span>
				</div>
				<div class="col-6 text-end">
					<strong>Date</strong><br />{{ formatDateTime(doc.posting_date) }}
				</div>
				<div class="col-6">
					<strong>Customer</strong><br />{{ doc.customer_name }}
				</div>
				<div v-if="doc.due_date" class="col-6 text-end">
					<strong>Due date</strong><br />{{ formatDateTime(doc.due_date) }}
				</div>
			</div>

			<hr />

			<!-- Items -->
			<table class="table table-sm table-vcenter table-no-stripe mb-0">
				<thead>
					<tr>
						<th>Item</th>
						<th class="text-end">Qty</th>
						<th>UOM</th>
						<th class="text-end">Rate</th>
						<th v-if="doc.items?.some(it => it.discount_percentage > 0)" class="text-end">Disc %</th>
						<th class="text-end">Amount</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(it, i) in doc.items" :key="i">
						<td>
							<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
							<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
						</td>
						<td class="text-end font-monospace">{{ it.qty }}</td>
						<td>{{ it.uom || "—" }}</td>
						<td class="text-end font-monospace">{{ fmt(it.rate) }}</td>
						<td v-if="doc.items?.some(it2 => it2.discount_percentage > 0)" class="text-end font-monospace">
							{{ it.discount_percentage > 0 ? it.discount_percentage + "%" : "—" }}
						</td>
						<td class="text-end font-monospace">{{ fmt(it.amount) }}</td>
					</tr>
				</tbody>
			</table>

			<!-- In words -->
			<div v-if="doc.in_words" class="mt-3 small text-secondary">
				<strong>In words:</strong> {{ doc.in_words }}
			</div>

			<!-- Remarks -->
			<div v-if="doc.remarks" class="mt-2 small text-secondary">
				<strong>Terms:</strong> {{ doc.remarks }}
			</div>
		</div>
	</div>
</template>

<style>
@media print {
	/* Hide the entire SPA chrome — only .receipt renders */
	.navbar, .sidebar, .footer, .no-print { display: none !important; }
	.print-wrapper { padding: 0; }
	.receipt { font-size: 12px; }
}
.receipt { max-width: 680px; margin: 0 auto; }
.receipt-header {}
</style>
