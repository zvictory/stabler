<script setup>
import { computed, ref } from "vue";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import EHFStatus from "./compliance/EHFStatus.vue";
import OneCSyncLog from "./compliance/OneCSyncLog.vue";
import AslBelgisi from "./compliance/AslBelgisi.vue";
import ARCA from "./compliance/ARCA.vue";
import ExchangeRates from "./compliance/ExchangeRates.vue";

const session = useSession();

const tabs = computed(() => [
	{ key: "ehf", label: t("EHF Status"), icon: "ti-file-invoice", component: EHFStatus },
	{ key: "onec", label: t("1C Sync Log"), icon: "ti-refresh", component: OneCSyncLog },
	{ key: "asl", label: t("Asl Belgisi"), icon: "ti-barcode", component: AslBelgisi },
	{ key: "arca", label: t("ARCA"), icon: "ti-credit-card", component: ARCA },
	{ key: "rates", label: t("Exchange Rates"), icon: "ti-currency-dollar", component: ExchangeRates },
]);

const active = ref("ehf");
const activeComponent = computed(() => tabs.value.find((tab) => tab.key === active.value)?.component);

const gated = computed(() => {
	const mods = session.modules || {};
	return mods.compliance !== false && mods.compliance !== 0;
});
</script>

<template>
	<div v-if="!session.isAdmin" class="alert alert-warning">
		{{ t("You need administrator access to view this page.") }}
	</div>
	<div v-else-if="!gated" class="alert alert-info">
		{{ t("The Compliance module is disabled for this company.") }}
	</div>
	<div v-else>
		<ul class="nav nav-pills mb-3">
			<li v-for="tab in tabs" :key="tab.key" class="nav-item">
				<button
					type="button"
					class="nav-link"
					:class="{ active: active === tab.key }"
					@click="active = tab.key"
				>
					<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
				</button>
			</li>
		</ul>

		<component :is="activeComponent" />
	</div>
</template>
