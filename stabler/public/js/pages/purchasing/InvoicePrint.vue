<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
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

// Per-box unit price: parse a trailing "(N)" from the item name (reference convention).
function pcsPerBox(name) {
	const m = (name ?? "").match(/\((\d+)\)\s*$/);
	return m ? parseInt(m[1], 10) : 1;
}

// Per-box cell: only meaningful when the item is sold in boxes of >1 pieces.
function perBox(it) {
	const pcs = pcsPerBox(it.item_name);
	return pcs > 1 ? fmt(Math.round((it.rate || 0) / pcs)) : "—";
}

// Discount column appears only when at least one line is discounted.
const hasDiscount = computed(() =>
	(doc.value?.items || []).some((i) => i.discount_percentage > 0 || i.discount_amount > 0)
);

async function load() {
	const name = route.params.name;
	if (!name) { router.push("/purchasing/invoices"); return; }
	loading.value = true;
	error.value = "";
	try {
		doc.value = await call("stabler.api.purchasing.purchase_invoice_print", { name });
	} catch (err) {
		error.value = err?.message || t("Failed to load invoice.");
	} finally {
		loading.value = false;
	}
}

function getUzbekWords(amount, currency) {
	if (!amount) return "";
	const num = Math.floor(amount);
	if (num === 0) return "Nol";

	const ones = ["", "bir", "ikki", "uch", "to'rt", "besh", "olti", "yetti", "sakkiz", "to'qqiz"];
	const tens = ["", "o'n", "yigirma", "o'ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to'qson"];
	const groups = ["", "ming", "million", "milliard"];

	function convertGroup(n) {
		let str = "";
		const hundreds = Math.floor(n / 100);
		const rest = n % 100;
		if (hundreds > 0) {
			str += ones[hundreds] + " yuz ";
		}
		if (rest > 0) {
			const t = Math.floor(rest / 10);
			const o = rest % 10;
			if (t > 0) str += tens[t] + " ";
			if (o > 0) str += ones[o] + " ";
		}
		return str.trim();
	}

	let words = "";
	let temp = num;
	let groupIdx = 0;

	while (temp > 0) {
		const groupVal = temp % 1000;
		if (groupVal > 0) {
			const groupStr = convertGroup(groupVal);
			const suffix = groups[groupIdx] ? " " + groups[groupIdx] : "";
			words = groupStr + suffix + (words ? " " + words : "");
		}
		temp = Math.floor(temp / 1000);
		groupIdx++;
	}

	let result = words.trim();
	if (result) {
		result = result.charAt(0).toUpperCase() + result.slice(1);
	}

	const currencyLower = (currency || "").toUpperCase();
	if (currencyLower === "UZS") {
		result += " so'm";
	} else if (currencyLower === "USD") {
		result += " AQSH dollari";
	} else {
		result += " " + currencyLower;
	}

	const cents = Math.round((amount - num) * 100);
	if (cents > 0) {
		let centWords = "";
		const t = Math.floor(cents / 10);
		const o = cents % 10;
		if (t > 0) centWords += tens[t] + " ";
		if (o > 0) centWords += ones[o] + " ";

		if (currencyLower === "UZS") {
			result += " u " + centWords.trim() + " tiyin";
		} else if (currencyLower === "USD") {
			result += " u " + centWords.trim() + " sent";
		} else {
			result += " u " + centWords.trim() + " tiyin";
		}
	}

	return result;
}

function triggerPrint() {
	window.print();
}

onMounted(load);
</script>

<template>
	<div class="print-wrapper">
		<!-- Controls — hidden when printing (.no-print). No waybill for purchase invoices. -->
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

		<!-- WYSIWYG A5 page: what renders on screen is what prints. -->
		<div v-else-if="doc" class="a5-print">
			<!-- 1. Header — brand left, contact right -->
			<div class="inv-head">
				<div>
					<div class="inv-brand">{{ doc.company_name }}</div>
				</div>
				<div class="inv-contact">
					<div v-if="doc.company_tax_id">{{ t("TIN") }}: {{ doc.company_tax_id }}</div>
				</div>
			</div>

			<hr class="inv-rule" />

			<!-- 2. Meta — invoice id + date left, supplier right -->
			<div class="inv-meta">
				<div>
					<div class="inv-id font-monospace">{{ doc.name }}</div>
					<div v-if="doc.bill_no" class="inv-sub font-monospace">{{ t("Supplier invoice") }}: {{ doc.bill_no }}</div>
					<div class="inv-sub">{{ formatDateTime(doc.posting_date) }}</div>
				</div>
				<div class="text-end">
					<div class="inv-cust">{{ doc.supplier_name }}</div>
					<div class="inv-sub font-monospace">{{ doc.supplier }}</div>
				</div>
			</div>

			<!-- 3. Items -->
			<table class="inv-table">
				<thead>
					<tr>
						<th class="inv-th">#</th>
						<th class="inv-th">{{ t("Item") }}</th>
						<th class="inv-th inv-num">{{ t("Qty") }}</th>
						<th class="inv-th inv-center">{{ t("UOM") }}</th>
						<th class="inv-th inv-num">{{ t("Rate") }}</th>
						<th class="inv-th inv-num">{{ t("Per box") }}</th>
						<th v-if="hasDiscount" class="inv-th inv-num">{{ t("Disc %") }}</th>
						<th class="inv-th inv-num">{{ t("Amount") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(it, i) in doc.items" :key="i" :class="{ 'inv-row--alt': i % 2 }">
						<td class="inv-faint">{{ i + 1 }}</td>
						<td>
							<div class="inv-item-name">{{ it.item_name || it.item_code }}</div>
							<div v-if="it.item_name && it.item_code !== it.item_name" class="inv-item-code font-monospace">
								{{ it.item_code }}
							</div>
						</td>
						<td class="inv-num">{{ it.qty }}</td>
						<td class="inv-center inv-muted">{{ it.uom || "—" }}</td>
						<td class="inv-num">{{ fmt(it.rate) }}</td>
						<td class="inv-num inv-muted">{{ perBox(it) }}</td>
						<td v-if="hasDiscount" class="inv-num" :class="it.discount_percentage > 0 ? 'inv-neg' : 'inv-faint'">
							{{ it.discount_percentage > 0 ? it.discount_percentage + "%" : "—" }}
						</td>
						<td class="inv-num inv-amount">{{ fmt(it.amount) }}</td>
					</tr>
				</tbody>
			</table>

			<!-- 4. Totals -->
			<div class="inv-totals-wrap">
				<div class="inv-totals">
					<div class="inv-trow inv-muted">
						<span>{{ t("Subtotal") }}</span>
						<span class="inv-num">{{ fmt(doc.net_total) }}</span>
					</div>
					<div v-if="doc.discount_amount > 0" class="inv-trow inv-neg">
						<span>{{ t("Chegirma") }}</span>
						<span class="inv-num">-{{ fmt(doc.discount_amount) }}</span>
					</div>
					<div class="inv-trow inv-total">
						<span>{{ t("Jami") }}</span>
						<span class="inv-num">{{ fmt(doc.grand_total) }}</span>
					</div>
				</div>
			</div>

			<!-- 5. Amount in words + supplier balance + remarks -->
			<div v-if="doc.in_words || doc.grand_total" class="inv-words">
				<strong>{{ t("So'z bilan:") }}</strong> {{ getUzbekWords(doc.grand_total, doc.currency) }}
			</div>

			<div class="inv-balance">
				<span>
					{{ t("Supplier balance") }}:
					<strong :class="doc.supplier_balance > 0 ? 'inv-neg' : 'inv-pos'">{{ fmt(doc.supplier_balance) }}</strong>
				</span>
			</div>

			<div v-if="doc.remarks" class="inv-words">
				<strong>{{ t("Terms:") }}</strong> {{ doc.remarks }}
			</div>

			<!-- 6. Footer -->
			<div class="inv-foot">
				<div class="inv-thanks">
					<div>Xarid uchun rahmat!</div>
					<div>Спасибо за покупку!</div>
					<div class="inv-foot-link">erpstable.com</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style>
@page {
	size: A5 portrait;
	margin: 5mm 5mm 10mm 5mm;
}

@media print {
	/* Print isolation by inclusion: hide everything, reveal only the invoice.
	   More robust than enumerating SPA chrome — never needs updating. */
	body * {
		visibility: hidden;
	}
	.a5-print,
	.a5-print * {
		visibility: visible;
	}
	.a5-print {
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

/* On-screen WYSIWYG A5 page. */
.a5-print {
	display: flex;
	flex-direction: column;
	width: 148mm;
	min-height: 190mm;
	margin: 0 auto;
	padding: 5mm;
	box-sizing: border-box;
	background: #fff;
	color: #111;
	line-height: 1.5;
	font-family: Inter, system-ui, -apple-system, sans-serif;
	font-size: 9pt;
}

/* Header */
.inv-head {
	display: flex;
	justify-content: space-between;
	align-items: flex-start;
	margin-bottom: 3mm;
}
.inv-brand {
	font-size: 16pt;
	font-weight: 700;
	letter-spacing: -0.02em;
}
.inv-contact {
	text-align: right;
	font-size: 7.5pt;
	color: #555;
}
.inv-rule {
	border: none;
	border-top: 1.5px solid #000;
	margin: 0 0 3mm;
}

/* Meta */
.inv-meta {
	display: flex;
	justify-content: space-between;
	margin-bottom: 3mm;
}
.inv-id {
	font-size: 11pt;
	font-weight: 700;
	letter-spacing: 0.02em;
}
.inv-cust {
	font-size: 10pt;
	font-weight: 600;
}
.inv-sub {
	font-size: 8pt;
	color: #666;
}

/* Items table */
.inv-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 8pt;
	margin-bottom: 2mm;
}
.inv-th {
	text-align: left;
	padding: 1.5mm 1mm;
	font-weight: 600;
	color: #555;
	font-size: 7pt;
	border-bottom: 1px solid #ddd;
}
.inv-table td {
	padding: 1.5mm 1mm;
	border-bottom: 0.5px solid #eee;
}
.inv-row--alt {
	background: #fafafa;
}
.inv-num {
	text-align: right;
	font-variant-numeric: tabular-nums;
}
.inv-center {
	text-align: center;
}
.inv-item-name {
	font-weight: 500;
}
.inv-item-code {
	font-size: 6.5pt;
	color: #999;
}
.inv-amount {
	font-weight: 600;
}
.inv-muted {
	color: #666;
}
.inv-faint {
	color: #999;
	font-size: 7pt;
}
.inv-neg {
	color: #c00;
}
.inv-pos {
	color: #080;
}

/* Totals */
.inv-totals-wrap {
	display: flex;
	justify-content: flex-end;
	margin-bottom: 2mm;
}
.inv-totals {
	width: 55mm;
	font-size: 8.5pt;
}
.inv-trow {
	display: flex;
	justify-content: space-between;
	padding: 1mm 0;
}
.inv-total {
	padding: 2mm 0 1mm;
	border-top: 1.5px solid #000;
	font-size: 11pt;
	font-weight: 700;
	color: #111;
}

/* Words / balance / remarks */
.inv-words {
	font-size: 8pt;
	color: #555;
	margin-bottom: 2mm;
}
.inv-balance {
	display: flex;
	justify-content: flex-end;
	font-size: 8pt;
	color: #666;
	margin-bottom: 2mm;
}

/* Footer */
.inv-foot {
	display: flex;
	justify-content: flex-end;
	align-items: flex-end;
	margin-top: auto;
	padding-top: 4mm;
}
.inv-thanks {
	text-align: right;
	font-size: 7pt;
	color: #999;
}
.inv-foot-link {
	margin-top: 1mm;
}
</style>
