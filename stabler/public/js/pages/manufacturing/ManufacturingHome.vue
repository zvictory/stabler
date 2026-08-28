<script setup>
import { computed, watchEffect } from "vue";
import { useRoute, useRouter, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();

const tabs = computed(() => [
	...(session.isMfgManager
		? [
				{
					name: "manufacturing-boms",
					path: "/manufacturing/boms",
					label: t("BOMs"),
					icon: "ti-list-tree",
				},
			]
		: []),
	{
		name: "manufacturing-work-orders",
		path: "/manufacturing/work-orders",
		label: t("Work Orders"),
		icon: "ti-tool",
	},
	// Manager-only, like BOMs: the board shows every line's orders, and an
	// operator's own screen is the shift log.
	...(session.isMfgManager
		? [
				{
					name: "manufacturing-plan",
					path: "/manufacturing/plan",
					label: t("Production plan"),
					icon: "ti-calendar-event",
				},
			]
		: []),
]);
const activeTab = computed(() => route.name);

// Redirect operators away from the BOMs route — the server guards it too,
// but the redirect avoids a visible error flash.
watchEffect(() => {
	if (["manufacturing-boms", "manufacturing-plan"].includes(route.name) && !session.isMfgManager) {
		router.replace("/manufacturing/work-orders");
	}
});
</script>

<template>
	<ModuleHeader :title="t('Manufacturing')" icon="ti-tools" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
