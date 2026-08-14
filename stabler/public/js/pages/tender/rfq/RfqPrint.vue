<script setup>
// RFQ print view — the letter a supplier is handed. What renders is what
// prints. Buyer-internal facts (target rates) never appear here: the letter
// asks for a price, it does not hint at one.
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../../stores/session.js";
import { call } from "../../../api/client.js";
import { formatDate } from "../../../composables/date.js";
import { t } from "../../../composables/i18n.js";

const route = useRoute();
const router = useRouter();
const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(true);
const error = ref("");
const doc = ref(null);

async function load() {
	const name = route.params.name;
	if (!name) {
		router.push("/tender/rfq");
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		doc.value = await call("stabler.api.sourcing.rfq_print", {
			name,
			company: activeCompany.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load the request for quotation.");
	} finally {
		loading.value = false;
	}
}

function triggerPrint() {
	window.print();
}

onMounted(load);
</script>

<template>
	<div class="print-wrapper">
		<div class="no-print mb-3 d-flex gap-2">
			<button type="button" class="btn btn-sm btn-outline-secondary" @click="router.back()">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
			</button>
			<button type="button" class="btn btn-sm btn-primary ms-auto" @click="triggerPrint">
				<i class="ti ti-printer me-1"></i>{{ t("Print") }}
			</button>
		</div>

		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="alert alert-danger">{{ error }}</div>

		<div v-else-if="doc" class="a4-print">
			<div class="rfq-head">
				<div>
					<div class="rfq-brand">{{ doc.company_name }}</div>
					<div v-if="doc.company_tax_id" class="rfq-sub">{{ t("TIN") }}: {{ doc.company_tax_id }}</div>
					<div v-if="doc.company_phone" class="rfq-sub">{{ doc.company_phone }}</div>
					<div v-if="doc.company_email" class="rfq-sub">{{ doc.company_email }}</div>
				</div>
				<div class="text-end">
					<div class="rfq-id font-monospace">{{ doc.name }}</div>
					<div class="rfq-sub">{{ formatDate(doc.transaction_date) }}</div>
				</div>
			</div>

			<hr class="rfq-rule" />

			<h1 class="rfq-title">{{ t("Request for quotation") }}</h1>
			<p class="rfq-lead">
				{{
					t(
						"We kindly ask you to quote your prices and delivery terms for the following items.",
					)
				}}
			</p>
			<div class="rfq-meta">
				<div v-if="doc.schedule_date">
					<strong>{{ t("Please respond by") }}:</strong> {{ formatDate(doc.schedule_date) }}
				</div>
			</div>

			<table class="rfq-table">
				<thead>
					<tr>
						<th class="rfq-th">#</th>
						<th class="rfq-th">{{ t("Item") }}</th>
						<th class="rfq-th rfq-num">{{ t("Qty") }}</th>
						<th class="rfq-th rfq-center">{{ t("UOM") }}</th>
						<th class="rfq-th rfq-center" style="width: 30mm">{{ t("Needed by") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(line, i) in doc.items" :key="i" :class="{ 'rfq-row--alt': i % 2 }">
						<td class="rfq-faint">{{ i + 1 }}</td>
						<td>
							<div class="rfq-item-name">{{ line.item_name || line.item_code }}</div>
							<div v-if="line.description && line.description !== line.item_name" class="rfq-sub">
								{{ line.description }}
							</div>
						</td>
						<td class="rfq-num">{{ line.qty }}</td>
						<td class="rfq-center rfq-muted">{{ line.uom || "—" }}</td>
						<td class="rfq-center rfq-muted">
							{{ line.schedule_date ? formatDate(line.schedule_date) : "—" }}
						</td>
					</tr>
				</tbody>
			</table>

			<p class="rfq-lead mt-3">
				{{ t("Please state: unit price, currency, validity period, and delivery time.") }}
			</p>

			<div class="rfq-sign">
				<div>
					<div class="rfq-sub">{{ t("Requested by") }}</div>
					<div class="rfq-sign-line"></div>
				</div>
				<div>
					<div class="rfq-sub">{{ t("Supplier signature / stamp") }}</div>
					<div class="rfq-sign-line"></div>
				</div>
			</div>
		</div>
	</div>
</template>

<style>
@page {
	size: A4 portrait;
	margin: 15mm;
}

@media print {
	/* Print isolation by inclusion — the InvoicePrint approach, unchanged. */
	body * {
		visibility: hidden;
	}
	.a4-print,
	.a4-print * {
		visibility: visible;
	}
	.a4-print {
		position: absolute;
		left: 0;
		top: 0;
		width: 100%;
		padding: 0 !important;
		-webkit-print-color-adjust: exact;
		print-color-adjust: exact;
	}
	.no-print {
		display: none !important;
	}
	table {
		page-break-inside: auto;
	}
	tr {
		page-break-inside: avoid;
	}
}

/* On-screen WYSIWYG A4 page. */
.a4-print {
	display: flex;
	flex-direction: column;
	width: 186mm;
	min-height: 250mm;
	margin: 0 auto;
	padding: 15mm;
	box-sizing: border-box;
	background: #fff;
	color: #111;
	line-height: 1.5;
	font-family: Inter, system-ui, -apple-system, sans-serif;
	font-size: 10pt;
}

.rfq-head {
	display: flex;
	justify-content: space-between;
	align-items: flex-start;
	margin-bottom: 4mm;
}
.rfq-brand {
	font-size: 16pt;
	font-weight: 700;
	letter-spacing: -0.02em;
}
.rfq-sub {
	font-size: 8pt;
	color: #666;
}
.rfq-rule {
	border: none;
	border-top: 1.5px solid #000;
	margin: 0 0 5mm;
}
.rfq-id {
	font-size: 11pt;
	font-weight: 700;
}
.rfq-title {
	font-size: 14pt;
	font-weight: 700;
	margin: 0 0 3mm;
}
.rfq-lead {
	font-size: 9.5pt;
	color: #333;
	margin: 0 0 3mm;
}
.rfq-meta {
	font-size: 10pt;
	margin-bottom: 4mm;
}

.rfq-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 9pt;
	margin-bottom: 3mm;
}
.rfq-th {
	text-align: left;
	padding: 2mm 1.5mm;
	font-weight: 600;
	color: #555;
	font-size: 8pt;
	border-bottom: 1px solid #ddd;
}
.rfq-table td {
	padding: 2mm 1.5mm;
	border-bottom: 0.5px solid #eee;
}
.rfq-row--alt {
	background: #fafafa;
}
.rfq-num {
	text-align: right;
	font-variant-numeric: tabular-nums;
}
.rfq-center {
	text-align: center;
}
.rfq-item-name {
	font-weight: 500;
}
.rfq-muted {
	color: #666;
}
.rfq-faint {
	color: #999;
	font-size: 8pt;
}

.rfq-sign {
	display: flex;
	justify-content: space-between;
	gap: 20mm;
	margin-top: auto;
	padding-top: 12mm;
}
.rfq-sign-line {
	border-bottom: 1px solid #999;
	width: 60mm;
	height: 8mm;
}
</style>
