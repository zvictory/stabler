<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
// Grouped logically: Operations (CI / Containers / Trucks / GRN),
// Documents (Customs / Vet / Freight / Expenses). Landed Cost is reached from a
// GRN, so it maps onto the GRN tab rather than getting its own.
const tabs = [
	{ name: "imports-dashboard", path: "/imports/dashboard", label: t("Dashboard"), icon: "ti-layout-dashboard" },
	{ name: "imports-orders", path: "/imports/orders", label: t("Import Orders"), icon: "ti-clipboard-list" },
	{ name: "imports-proformas", path: "/imports/proformas", label: t("Proforma Invoices"), icon: "ti-file-dollar" },
	{ name: "imports-commercial-invoices", path: "/imports/commercial-invoices", label: t("Commercial Invoices"), icon: "ti-file-invoice" },
	{ name: "imports-containers", path: "/imports/containers", label: t("Containers"), icon: "ti-box" },
	{ name: "imports-trucks", path: "/imports/trucks", label: t("Trucks"), icon: "ti-truck" },
	{ name: "imports-grn-checklists", path: "/imports/grn-checklists", label: t("GRN"), icon: "ti-clipboard-check" },
	{ name: "imports-customs", path: "/imports/customs", label: t("Customs"), icon: "ti-file-certificate" },
	{ name: "imports-vet-certificates", path: "/imports/vet-certificates", label: t("Vet"), icon: "ti-vaccine" },
	{ name: "imports-freight", path: "/imports/freight", label: t("Freight"), icon: "ti-truck-delivery" },
	{ name: "imports-expenses", path: "/imports/expenses", label: t("Expenses"), icon: "ti-receipt" },
	{ name: "imports-bills", path: "/imports/bills", label: t("Bills"), icon: "ti-file-dollar" },
];
// Keep the child form / detail routes highlighting their list tab.
const activeTab = computed(() => {
	const n = String(route.name || "");
	if (n.startsWith("imports-order")) return "imports-orders";
	if (n.startsWith("imports-commercial-invoice")) return "imports-commercial-invoices";
	if (
		n.startsWith("imports-grn-checklist") ||
		n.startsWith("imports-truck-receipt") ||
		n === "imports-landed-cost"
	)
		return "imports-grn-checklists";
	if (n === "imports-container-ledger") return "imports-containers";
	if (n === "imports-bills") return "imports-bills";
	if (n.startsWith("imports-container")) return "imports-containers";
	if (n.startsWith("imports-truck")) return "imports-trucks";
	if (n.startsWith("imports-customs")) return "imports-customs";
	if (n.startsWith("imports-vet")) return "imports-vet-certificates";
	if (n === "imports-freight") return "imports-freight";
	if (n === "imports-expenses") return "imports-expenses";
	return n;
});
</script>

<template>
	<ModuleHeader :title='t("Imports")' icon="ti-plane" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
