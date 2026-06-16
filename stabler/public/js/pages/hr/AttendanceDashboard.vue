<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { todayIso } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import KpiCard from "../../components/KpiCard.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const date = ref(todayIso());
const loading = ref(false);
const error = ref("");

const data = ref(null);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		data.value = await call("stabler.api.hr_payroll.attendance_dashboard", {
			company: activeCompany.value,
			date: date.value,
		});
	} catch (e) {
		error.value = e?.message || String(e);
		data.value = null;
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([activeCompany, date], load);

const exceptionsByType = computed(() => {
	if (!data.value?.exceptions_by_type) return [];
	return Object.entries(data.value.exceptions_by_type).map(([type, count]) => ({ type, count }));
});

function goExceptions() {
	router.push({ name: "hr-exceptions-queue" });
}

function goCorrections() {
	router.push({ name: "hr-exceptions-queue", query: { status: "Open" } });
}
</script>

<template>
	<div class="container-xl py-3">
		<!-- Header / date picker -->
		<div class="page-header mb-3">
			<div class="row align-items-center">
				<div class="col">
					<h2 class="page-title">{{ t("Attendance Dashboard") }}</h2>
				</div>
				<div class="col-auto d-flex align-items-center gap-2">
					<label class="form-label mb-0 text-secondary small">{{ t("Date") }}</label>
					<div style="width: 160px">
						<DateInput v-model="date" />
					</div>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- KPI tiles row 1: main counts -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<KpiCard
					:label="t('Present')"
					:value="data ? String(data.present ?? 0) : '—'"
					icon="ti-user-check"
					tone="success"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg-3">
				<KpiCard
					:label="t('Absent')"
					:value="data ? String(data.absent ?? 0) : '—'"
					icon="ti-user-x"
					tone="danger"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg-3">
				<KpiCard
					:label="t('Late')"
					:value="data ? String(data.late ?? 0) : '—'"
					icon="ti-clock-exclamation"
					tone="warning"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg-3">
				<KpiCard
					:label="t('On Leave')"
					:value="data ? String(data.on_leave ?? 0) : '—'"
					icon="ti-calendar-off"
					tone="info"
					:loading="loading"
				/>
			</div>
		</div>

		<!-- KPI tiles row 2: totals + exceptions -->
		<div class="row row-cards mb-4">
			<div class="col-sm-6 col-lg-3">
				<KpiCard
					:label="t('Total Marked')"
					:value="data ? String(data.total_marked ?? 0) : '—'"
					icon="ti-checkbox"
					tone="primary"
					:loading="loading"
				/>
			</div>
			<div class="col-sm-6 col-lg-3">
				<!-- Open exceptions tile — router-link to Exceptions Queue -->
				<div class="card card-sm" style="cursor:pointer" @click="goExceptions">
					<div class="card-body">
						<div class="row align-items-center">
							<div class="col-auto">
								<span class="bg-orange text-white avatar">
									<i class="ti ti-alert-triangle"></i>
								</span>
							</div>
							<div class="col">
								<div class="font-weight-medium text-secondary small">{{ t("Open Exceptions") }}</div>
								<div class="h2 mb-0">
									<span v-if="loading" class="placeholder col-6">&nbsp;</span>
									<span v-else>{{ data ? (data.open_exceptions ?? 0) : "—" }}</span>
								</div>
								<div class="text-secondary small mt-1">
									<i class="ti ti-arrow-right me-1"></i>{{ t("View exceptions queue") }}
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<!-- Pending corrections tile -->
				<div class="card card-sm" style="cursor:pointer" @click="goCorrections">
					<div class="card-body">
						<div class="row align-items-center">
							<div class="col-auto">
								<span
									class="text-white avatar"
									:class="data && data.payroll_impacting_pending > 0 ? 'bg-danger' : 'bg-purple'"
								>
									<i class="ti ti-file-pencil"></i>
								</span>
							</div>
							<div class="col">
								<div class="font-weight-medium text-secondary small">{{ t("Pending Corrections") }}</div>
								<div class="h2 mb-0">
									<span v-if="loading" class="placeholder col-6">&nbsp;</span>
									<span v-else>{{ data ? (data.pending_corrections ?? 0) : "—" }}</span>
								</div>
								<div
									v-if="!loading && data && data.payroll_impacting_pending > 0"
									class="text-danger small mt-1 fw-semibold"
								>
									<i class="ti ti-alert-circle me-1"></i>
									{{ t("{0} payroll-impacting").replace("{0}", String(data.payroll_impacting_pending)) }}
								</div>
								<div v-else class="text-secondary small mt-1">
									<i class="ti ti-arrow-right me-1"></i>{{ t("View corrections queue") }}
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Exceptions by type breakdown -->
		<div v-if="!loading && exceptionsByType.length > 0" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Exceptions by Type") }}</h3>
			</div>
			<div class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("Exception Type") }}</th>
							<th class="text-end font-monospace">{{ t("Count") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="row in exceptionsByType" :key="row.type">
							<td>{{ t(row.type) }}</td>
							<td class="text-end font-monospace">{{ row.count }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>
