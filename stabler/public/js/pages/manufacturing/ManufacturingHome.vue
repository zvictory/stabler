<script setup>
import { computed, watchEffect } from "vue";
import { useRoute, useRouter, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const router = useRouter();
const session = useSession();

const tabs = computed(() => [
	...(session.isMfgManager
		? [{ name: "manufacturing-boms", path: "/manufacturing/boms", label: t("BOMs"), icon: "ti-list-tree" }]
		: []),
	{ name: "manufacturing-work-orders", path: "/manufacturing/work-orders", label: t("Work Orders"), icon: "ti-tool" },
]);
const activeTab = computed(() => route.name);

// Redirect operators away from the BOMs route — the server guards it too,
// but the redirect avoids a visible error flash.
watchEffect(() => {
	if (route.name === "manufacturing-boms" && !session.isMfgManager) {
		router.replace("/manufacturing/work-orders");
	}
});
</script>

<template>
	<ModuleHeader :title='t("Manufacturing")' icon="ti-tools" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
