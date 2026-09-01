<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";

const props = defineProps({
	purchase: { type: Object, required: true },
	sales: { type: Object, required: true },
	currency: { type: String, default: "" },
});

const router = useRouter();
const session = useSession();
const language = computed(() => session.user?.language);
const sides = computed(() => [
	{ key: "purchase", title: t("Purchase execution"), chain: props.purchase, labels: [t("PO"), t("Receipt"), t("Invoice")] },
	{ key: "sales", title: t("Sales execution"), chain: props.sales, labels: [t("Sales order"), t("Delivery"), t("Invoice")] },
]);

// Each document in the chain carries its own currency — the server sends it per
// row — and a tender routinely pairs a USD purchase order to a foreign supplier
// with a UZS-invoiced sales order. The tender's own currency is only the
// fallback, the same way the board's charge lines already read `c.currency || ccy`.
function rowCurrency(row) {
	return row.currency || props.currency;
}

function openOrder(side, name) {
	router.push(side === "purchase" ? `/purchasing/orders/${name}` : `/sales/orders/${name}`);
}
</script>

<template>
	<div class="row g-3">
		<section v-for="side in sides" :key="side.key" class="col-12 col-xl-6">
			<div class="card h-100">
				<div class="card-header py-2"><span class="fw-semibold">{{ side.title }}</span></div>
				<div class="card-body p-0">
					<div v-for="(rows, index) in [side.chain.orders, side.key === 'purchase' ? side.chain.receipts : side.chain.deliveries, side.chain.invoices]" :key="side.labels[index]" class="border-bottom p-3">
						<div class="small text-uppercase text-secondary fw-semibold mb-2">{{ side.labels[index] }}</div>
						<div v-for="row in rows || []" :key="`${row.name}-${row.purchase_order || row.sales_order || ''}`" class="d-flex justify-content-between gap-2 py-1">
							<button v-if="index === 0" type="button" class="btn btn-link p-0 text-start font-monospace" @click="openOrder(side.key, row.name)">{{ row.name }}</button>
							<span v-else class="font-monospace">{{ row.name }}</span>
							<span class="text-secondary text-nowrap">{{ row.posting_date ? formatDate(row.posting_date) : "—" }}</span>
							<span class="font-monospace text-end text-nowrap">{{ formatMoney(row.grand_total, rowCurrency(row), language) }}</span>
						</div>
						<div v-if="!(rows || []).length" class="text-secondary small">{{ t("No linked documents") }}</div>
					</div>
				</div>
			</div>
		</section>
	</div>
</template>
