<script setup>
import { computed, watch } from "vue";
import { useRoute, useRouter, RouterView } from "vue-router";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();

// The one role that may configure a company. The server owns the real gate
// (`remittance_settings.json` grants write to it alone); this only decides whether
// a tab is worth offering.
const MANAGER_ROLE = "Remittance Finance Manager";

// The routes that exist on a Legacy company. Written as the complement of the V1
// set rather than a copy of it: anything added to this module later is V1-only
// until somebody says otherwise, which is the safe direction for a money surface.
//
// Settings is on BOTH sides, and that is the point. It is the only screen that can
// move a company from Legacy to V1, and every company ships as Legacy — a Settings
// tab that appears only once you are already on V1 is a door locked from the
// inside, and the Transfer V1 surface would be unreachable on every tenant forever.
// It is the one Legacy tab that is role-gated: a cashier has nothing to do on it.
const LEGACY_ROUTES = new Set(["remittance-new", "remittance-transfers", "remittance-settings"]);

const canManage = computed(() => session.isAdmin || (session.roles || []).includes(MANAGER_ROLE));

const tabs = computed(() => {
	if (!session.isRemittanceV1) {
		// Legacy — the strip this module has always had, plus the way in to Settings.
		// A company that has not switched its engine loses no tab.
		return [
			{
				name: "remittance-new",
				path: "/remittance/new",
				label: t("New Transfer"),
				icon: "ti-plus",
				show: true,
			},
			{
				name: "remittance-transfers",
				path: "/remittance/transfers",
				label: t("Transfers"),
				icon: "ti-list",
				show: true,
			},
			{
				name: "remittance-settings",
				path: "/remittance/settings",
				label: t("Settings"),
				icon: "ti-settings",
				show: canManage.value,
			},
		].filter((tab) => tab.show);
	}

	// Every Transfer V1 route appears here. Payout and Refunds are tabs and not
	// merely destinations of an Operations row button, because both are screens a
	// cashier starts a day on: the payout desk carries its own search, and the
	// refund chain has no other way in at all — the row buttons for the refund
	// actions push to the read-only transfer detail page.
	const list = [
		{
			name: "remittance-new",
			path: "/remittance/new",
			label: t("New Transfer"),
			icon: "ti-plus",
			show: true,
		},
		{
			name: "remittance-operations",
			path: "/remittance/operations",
			label: t("Operations"),
			icon: "ti-layout-dashboard",
			show: true,
		},
		{
			name: "remittance-payout",
			path: "/remittance/payout",
			label: t("Payout"),
			icon: "ti-cash-banknote",
			show: true,
		},
		{
			name: "remittance-refund",
			path: "/remittance/refund",
			label: t("Refunds"),
			icon: "ti-receipt-refund",
			show: true,
		},
		{
			name: "remittance-transfers",
			path: "/remittance/transfers",
			label: t("Transfers"),
			icon: "ti-list",
			show: true,
		},
		{
			name: "remittance-reconciliation",
			path: "/remittance/reconciliation",
			label: t("Reconciliation"),
			icon: "ti-scale",
			show: true,
		},
		{
			name: "remittance-settings",
			path: "/remittance/settings",
			label: t("Settings"),
			icon: "ti-settings",
			show: canManage.value,
		},
	];
	return list.filter((tab) => tab.show);
});

// The transfer detail page is reached from the Transfers list, not from a tab, so
// no tab is active while it is open. That is deliberate — it is a page you drill
// into, not a section you switch to.
const activeTab = computed(() => route.name);

// Switching companies changes the engine without navigating anywhere, so the router
// guard never sees it. Without this, a cashier who switches from a V1 company to a
// Legacy one is left standing on a screen no tab points at any more, still sending
// V1 requests about a company that does not run V1.
watch(
	() => session.isRemittanceV1,
	(v1) => {
		if (!v1 && route.name && !LEGACY_ROUTES.has(String(route.name))) {
			router.replace("/remittance/new");
		}
	}
);
</script>

<template>
	<ModuleHeader :title="t('Remittance')" icon="ti-send" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>

<style scoped>
/* The module header is one row that never wraps (`flex-nowrap`), with the title
   pinned (`flex-shrink-0`) and the tab strip scrolling horizontally under it. On
   a desk that is fine; on the tablet a cashier works the counter with, remittance
   carries the most tabs of any module and the last of them sit off-screen behind
   a horizontal scroll nobody discovers.

   Below 992px the title goes and the strip takes the row. The title is the one
   thing on that row a cashier never needs: the tab strip says where they are, and
   the sidebar says which module they are in.

   Scoped and `:deep`, deliberately NOT a rule in stabler.css: ModuleHeader is
   shared by every module and all seven tenants, and hiding page titles app-wide
   is a decision for all of them, not a side effect of the remittance redesign. */
@media (max-width: 991.98px) {
	:deep(.stbl-module-title) {
		display: none;
	}

	:deep(.stbl-module-tabs) {
		width: 100%;
	}
}

/* Same 40px the counter's own controls get — a tab is a touch target too. */
@media (max-width: 767.98px) {
	:deep(.stbl-module-tabs .nav-link) {
		align-items: center;
		display: flex;
		min-height: 40px;
	}
}
</style>
