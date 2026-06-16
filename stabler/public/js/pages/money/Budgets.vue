<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const loading = ref(false);
const error = ref("");
const search = ref("");
const rows = ref([]);

// Filters
const fiscalYear = ref("");
const costCenter = ref("");
const fiscalYears = ref([]);
const costCenters = ref([]);

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.name, r.fiscal_year, r.cost_center, r.company]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

async function loadOptions() {
	if (!activeCompany.value) return;
	try {
		const [fys, ccs] = await Promise.all([
			call("frappe.client.get_list", {
				doctype: "Fiscal Year",
				fields: ["name"],
				limit: 50,
				order_by: "year_start_date desc",
			}),
			call("frappe.client.get_list", {
				doctype: "Cost Center",
				filters: { company: activeCompany.value, is_group: 0 },
				fields: ["name"],
				limit: 200,
				order_by: "name asc",
			}),
		]);
		fiscalYears.value = (fys || []).map((r) => r.name);
		costCenters.value = (ccs || []).map((r) => r.name);
	} catch {
		// options are non-critical; list still loads
	}
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const data = await call("stabler.api.budget.list_budgets", {
			company: activeCompany.value,
			fiscal_year: fiscalYear.value || undefined,
			cost_center: costCenter.value || undefined,
			limit: 200,
		});
		rows.value = data || [];
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function openReport(r) {
	router.push({
		name: "budget-vs-actual",
		query: {
			company: r.company,
			fiscal_year: r.fiscal_year || undefined,
			cost_center: r.cost_center || undefined,
		},
	});
}

watch(activeCompany, () => { loadOptions(); load(); });
watch([fiscalYear, costCenter], load);
onMounted(() => { loadOptions(); load(); });
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Budget name, fiscal year…') + '  ⌘K'"
			:count="filteredRows.length"
		>
			<template #filters>
				<select
					v-model="fiscalYear"
					class="form-select form-select-sm"
					style="max-width: 160px"
				>
					<option value="">{{ t("All fiscal years") }}</option>
					<option v-for="fy in fiscalYears" :key="fy" :value="fy">{{ fy }}</option>
				</select>

				<select
					v-model="costCenter"
					class="form-select form-select-sm"
					style="max-width: 200px"
				>
					<option value="">{{ t("All cost centres") }}</option>
					<option v-for="cc in costCenters" :key="cc" :value="cc">{{ cc }}</option>
				</select>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Budget") }}</th>
						<th>{{ t("Fiscal Year") }}</th>
						<th>{{ t("Cost Centre") }}</th>
						<th>{{ t("Exceeded (Annual)") }}</th>
						<th>{{ t("Exceeded (Monthly)") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="7" />
				<tbody v-else>
					<tr
						v-for="r in filteredRows"
						:key="r.name"
						style="cursor: pointer"
						@click="openReport(r)"
					>
						<td class="fw-medium">{{ r.name }}</td>
						<td>{{ r.fiscal_year || "—" }}</td>
						<td>{{ r.cost_center || "—" }}</td>
						<td>{{ r.action_if_annual_budget_exceeded || "—" }}</td>
						<td>{{ r.action_if_accumulated_monthly_budget_exceeded || "—" }}</td>
						<td>
							<span
								class="badge"
								:class="getStatusBadgeClass('docstatus', r.docstatus)"
							>
								{{ r.docstatus === 1 ? t("Submitted") : r.docstatus === 2 ? t("Cancelled") : t("Draft") }}
							</span>
						</td>
						<td class="text-end">
							<button
								class="btn btn-sm btn-outline-secondary"
								@click.stop="openReport(r)"
							>
								<i class="ti ti-chart-bar me-1"></i>{{ t("View report") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-report-money"
			:title="t('No budgets found')"
			:subtitle="t('Submit a Budget document in ERPNext to see it here.')"
		/>
	</div>
</template>
