<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../../api/client.js";
import { formatMoney } from "../../../composables/money.js";
import { formatDateTime } from "../../../composables/date.js";
import { t } from "../../../composables/i18n.js";
import { useSession } from "../../../stores/session.js";

const session = useSession();
const rows = ref([]);
const loading = ref(false);
const refreshing = ref(false);
const error = ref("");
const lastRefresh = ref(null);

const language = computed(() => session.user?.language || "en");

async function load() {
	loading.value = true;
	error.value = "";
	try {
		const data = await call("stabler.api.compliance.list_exchange_rates", { days: 30 });
		rows.value = Array.isArray(data) ? data : [];
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

async function refresh() {
	refreshing.value = true;
	error.value = "";
	try {
		lastRefresh.value = await call("stabler.api.compliance.refresh_cbu_rates");
		await load();
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		refreshing.value = false;
	}
}

function fmt(value) {
	if (value === null || value === undefined) return "—";
	return formatMoney(value, "UZS", language.value);
}

onMounted(load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center justify-content-between">
			<h3 class="card-title mb-0">{{ t("CBU.uz exchange rates (last 30 days)") }}</h3>
			<button
				type="button"
				class="btn btn-primary btn-sm"
				:disabled="refreshing"
				@click="refresh"
			>
				<i class="ti ti-refresh me-1"></i>
				{{ refreshing ? t("Refreshing…") : t("Refresh now") }}
			</button>
		</div>
		<div class="card-body">
			<div v-if="error" class="alert alert-danger">{{ error }}</div>
			<div v-if="loading && !rows.length" class="text-secondary">{{ t("Loading…") }}</div>
			<div v-else-if="!rows.length" class="text-secondary">
				{{ t("No exchange rates yet. Click Refresh now to fetch today's rates from cbu.uz.") }}
			</div>
			<div v-else class="table-responsive">
				<table class="table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("Date") }}</th>
							<th class="text-end">{{ t("USD → UZS") }}</th>
							<th class="text-end">{{ t("EUR → UZS") }}</th>
							<th class="text-end">{{ t("RUB → UZS") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="row in rows" :key="row.date">
							<td>{{ formatDateTime(row.date) }}</td>
							<td class="text-end">{{ fmt(row.USD) }}</td>
							<td class="text-end">{{ fmt(row.EUR) }}</td>
							<td class="text-end">{{ fmt(row.RUB) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>
