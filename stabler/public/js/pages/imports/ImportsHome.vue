<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();

// Streamlined tabs fitting on exactly 1 crisp single line:
// Core operational tabs + Costs & Finance dropdown.
// Deliberately absent: the dashboard (it is the module landing page — see the
// `/imports` redirect in router.js) and PI Groups (reached from the PI list page).
const tabs = [
	{ name: "imports-orders", path: "/imports/orders", label: t("Orders"), icon: "ti-clipboard-list" },
	{ name: "imports-proformas", path: "/imports/proformas", label: t("PI"), icon: "ti-file-dollar" },
	{ name: "imports-commercial-invoices", path: "/imports/commercial-invoices", label: t("CI"), icon: "ti-file-invoice" },
	{ name: "imports-containers", path: "/imports/containers", label: t("Containers"), icon: "ti-box" },
	{ name: "imports-trucks", path: "/imports/trucks", label: t("Trucks"), icon: "ti-truck" },
	{ name: "imports-grn-checklists", path: "/imports/grn-checklists", label: t("GRN"), icon: "ti-clipboard-check" },
	{ name: "imports-customs", path: "/imports/customs", label: t("Customs"), icon: "ti-file-certificate" },
	{ name: "imports-vet-certificates", path: "/imports/vet-certificates", label: t("Vet"), icon: "ti-vaccine" },
	{
		label: t("Costs & Finance ▾"),
		icon: "ti-coin",
		children: [
			{ name: "imports-advances", path: "/imports/advances", label: t("PI Advances"), icon: "ti-cash" },
			{ name: "imports-freight", path: "/imports/freight", label: t("Freight Bookings"), icon: "ti-truck-delivery" },
			{ name: "imports-expenses", path: "/imports/expenses", label: t("Import Expenses"), icon: "ti-receipt" },
			{ name: "imports-bills", path: "/imports/bills", label: t("Landed Cost Bills"), icon: "ti-file-dollar" },
			{ name: "imports-transporters", path: "/imports/transporters", label: t("Transport operations desk"), icon: "ti-steering-wheel" },
		],
	},
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
