<script setup>
import { computed, ref, onMounted, watch } from "vue";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { call } from "../../api/client.js";
import EHFStatus from "./compliance/EHFStatus.vue";
import OneCSyncLog from "./compliance/OneCSyncLog.vue";
import AslBelgisi from "./compliance/AslBelgisi.vue";
import ARCA from "./compliance/ARCA.vue";
import ExchangeRates from "./compliance/ExchangeRates.vue";
import AuditLog from "./compliance/AuditLog.vue";
import Backup from "./compliance/Backup.vue";

const session = useSession();

const tabs = computed(() => [
	{ key: "ehf", label: t("EHF Status"), icon: "ti-file-invoice", component: EHFStatus },
	{ key: "onec", label: t("1C Sync Log"), icon: "ti-refresh", component: OneCSyncLog },
	{ key: "asl", label: t("Asl Belgisi"), icon: "ti-barcode", component: AslBelgisi },
	{ key: "arca", label: t("ARCA"), icon: "ti-credit-card", component: ARCA },
	{ key: "rates", label: t("Exchange Rates"), icon: "ti-currency-dollar", component: ExchangeRates },
	{ key: "audit", label: t("Audit Trail"), icon: "ti-history", component: AuditLog },
	{ key: "backup", label: t("Backup & DR"), icon: "ti-database-export", component: Backup },
]);

const active = ref("ehf");
const activeComponent = computed(() => tabs.value.find((tab) => tab.key === active.value)?.component);

const gated = computed(() => {
	const mods = session.modules || {};
	return mods.compliance !== false && mods.compliance !== 0;
});

const glIntegritySummary = ref(null);
const glIntegrityLoading = ref(false);

const glIntegrityTotal = computed(() => {
	if (!glIntegritySummary.value) return 0;
	return Object.values(glIntegritySummary.value).reduce((a, b) => a + b, 0);
});

async function loadGLIntegrity() {
	glIntegrityLoading.value = true;
	try {
		glIntegritySummary.value = await call("stabler.api.compliance.gl_integrity_scan", {
			company: session.activeCompany,
		});
	} catch (err) {
		console.error("Failed to load GL integrity status:", err);
	} finally {
		glIntegrityLoading.value = false;
	}
}

onMounted(() => {
	if (gated.value && session.isAdmin) {
		loadGLIntegrity();
	}
});

watch(
	() => session.activeCompany,
	() => {
		if (gated.value && session.isAdmin) {
			loadGLIntegrity();
		}
	}
);
</script>

<template>
	<div v-if="!session.isAdmin" class="alert alert-warning">
		{{ t("You need administrator access to view this page.") }}
	</div>
	<div v-else-if="!gated" class="alert alert-info">
		{{ t("The Compliance module is disabled for this company.") }}
	</div>
	<div v-else>
		<!-- GL Integrity Alert Card -->
		<div v-if="glIntegritySummary && glIntegrityTotal > 0" class="card border-danger mb-4">
			<div class="card-body">
				<div class="d-flex align-items-center mb-3">
					<span class="avatar bg-danger-lt me-2">
						<i class="ti ti-alert-triangle text-danger fs-2"></i>
					</span>
					<div>
						<h3 class="card-title text-danger m-0">{{ t("GL Integrity Anomaly Alert") }}</h3>
						<div class="text-secondary small">
							{{ t("The GL ledger scan detected {0} issues that require immediate attention.", [glIntegrityTotal]) }}
						</div>
					</div>
				</div>
				<div class="row g-2">
					<div v-if="glIntegritySummary.d2_postings" class="col-sm-6 col-md-3">
						<div class="border rounded p-2 bg-light">
							<div class="text-secondary small">{{ t("1:1 Foreign Postings") }}</div>
							<div class="h3 m-0 text-danger font-monospace">{{ glIntegritySummary.d2_postings }}</div>
						</div>
					</div>
					<div v-if="glIntegritySummary.multi_currency_parties" class="col-sm-6 col-md-3">
						<div class="border rounded p-2 bg-light">
							<div class="text-secondary small">{{ t("Multi-Currency Parties") }}</div>
							<div class="h3 m-0 text-danger font-monospace">{{ glIntegritySummary.multi_currency_parties }}</div>
						</div>
					</div>
					<div v-if="glIntegritySummary.off_cbu_docs" class="col-sm-6 col-md-3">
						<div class="border rounded p-2 bg-light">
							<div class="text-secondary small">{{ t("Off-CBU Documents") }}</div>
							<div class="h3 m-0 text-danger font-monospace">{{ glIntegritySummary.off_cbu_docs }}</div>
						</div>
					</div>
					<div v-if="glIntegritySummary.wrong_account_type_postings" class="col-sm-6 col-md-3">
						<div class="border rounded p-2 bg-light">
							<div class="text-secondary small">{{ t("Wrong Account Postings") }}</div>
							<div class="h3 m-0 text-danger font-monospace">{{ glIntegritySummary.wrong_account_type_postings }}</div>
						</div>
					</div>
				</div>
			</div>
		</div>

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
