<script setup>
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	doctype: { type: String, required: true },
	name: { type: String, required: true },
});

const router = useRouter();
const loading = ref(false);
const linked = ref({});

// Route map: doctype → in-SPA base path for ?open= navigation.
const ROUTE_MAP = {
	Quotation: "/sales/quotations",
	"Sales Order": "/sales/orders",
	"Sales Invoice": "/sales/invoices",
	"Delivery Note": null, // not yet in SPA — show name only
	"Purchase Order": "/purchasing/orders",
	"Purchase Receipt": "/purchasing/receipts",
	"Purchase Invoice": "/purchasing/invoices",
	"Payment Entry": "/money/payments",
};

const DOCTYPE_LABELS = {
	Quotation: "Quotations",
	"Sales Order": "Sales Orders",
	"Sales Invoice": "Sales Invoices",
	"Delivery Note": "Delivery Notes",
	"Purchase Order": "Purchase Orders",
	"Purchase Receipt": "Purchase Receipts",
	"Purchase Invoice": "Purchase Invoices",
	"Payment Entry": "Payment Entries",
};

const DOCSTATUS_BADGE = {
	0: "bg-secondary-lt",
	1: "bg-green-lt",
	2: "bg-red-lt",
};
const DOCSTATUS_LABEL = { 0: "Draft", 1: "Submitted", 2: "Cancelled" };

async function load() {
	if (!props.name) return;
	loading.value = true;
	linked.value = {};
	try {
		linked.value = await call("stabler.api.sales.get_linked_documents", {
			doctype: props.doctype,
			name: props.name,
		});
	} catch {
		linked.value = {};
	} finally {
		loading.value = false;
	}
}

// Doctypes converted to full-page routed forms navigate to `${base}/${name}`.
// The rest still open via the list's `?open=` drawer until their own pass.
// Payment Entry belongs here: it got its routed form but was left on the drawer
// branch, and Payments.vue never read `?open=` — so the badge navigated to the
// list and silently did nothing. Purchase Receipt is the only real drawer left.
const PATH_DETAIL = new Set([
	"Quotation",
	"Sales Order",
	"Sales Invoice",
	"Purchase Order",
	"Purchase Invoice",
	"Payment Entry",
]);

function navigate(doctype, name) {
	const base = ROUTE_MAP[doctype];
	if (!base) return;
	if (PATH_DETAIL.has(doctype)) {
		router.push(`${base}/${name}`);
	} else {
		router.push({ path: base, query: { open: name } });
	}
}

watch(() => props.name, load, { immediate: true });
</script>

<template>
	<div class="mt-4">
		<h6 class="text-uppercase text-secondary small mb-2">
			<i class="ti ti-link me-1"></i>{{ t("Related documents") }}
		</h6>
		<div v-if="loading" class="text-secondary small">
			<span class="spinner-border spinner-border-sm me-1"></span>{{ t("Loading…") }}
		</div>
		<div v-else-if="!Object.keys(linked).length" class="text-secondary small">—</div>
		<div v-else>
			<div v-for="(docs, dt) in linked" :key="dt" class="mb-2">
				<div class="small text-secondary mb-1">{{ DOCTYPE_LABELS[dt] || dt }}</div>
				<div class="d-flex flex-wrap gap-1">
					<button
						v-for="doc in docs"
						:key="doc.name"
						type="button"
						class="badge font-monospace"
						:class="[DOCSTATUS_BADGE[doc.docstatus] ?? 'bg-secondary-lt', ROUTE_MAP[dt] ? 'cursor-pointer' : '']"
						:style="ROUTE_MAP[dt] ? 'cursor:pointer;border:none' : 'border:none'"
						:title="DOCSTATUS_LABEL[doc.docstatus] ?? ''"
						@click="navigate(dt, doc.name)"
					>{{ doc.name }}</button>
				</div>
			</div>
		</div>
	</div>
</template>
