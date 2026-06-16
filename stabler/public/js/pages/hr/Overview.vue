<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";

const router = useRouter();
const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const dash = ref(null);
const today = computed(() => new Date().toISOString().slice(0, 10));

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		dash.value = await call("stabler.api.hr_payroll.attendance_dashboard", {
			company: activeCompany.value,
		});
	} catch {
		dash.value = null;
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, load);

const tiles = computed(() => {
	const d = dash.value || {};
	return [
		{ label: t("Present today"), value: d.present ?? 0, cls: "text-success" },
		{ label: t("Absent"), value: d.absent ?? 0, cls: "text-danger" },
		{ label: t("Late"), value: d.late ?? 0, cls: "text-warning" },
		{ label: t("On leave"), value: d.on_leave ?? 0, cls: "" },
		{ label: t("Marked"), value: d.total_marked ?? 0, cls: "text-muted" },
	];
});

const attention = computed(() => {
	const d = dash.value || {};
	return [
		{ label: t("Open exceptions"), value: d.open_exceptions ?? 0, icon: "ti-alert-triangle", to: "/hr/exceptions-queue", cls: "text-warning" },
		{ label: t("Corrections to approve"), value: d.pending_corrections ?? 0, icon: "ti-edit", to: "/hr/corrections", cls: "text-blue" },
		{ label: t("Payroll-impacting pending"), value: d.payroll_impacting_pending ?? 0, icon: "ti-cash", to: "/hr/corrections", cls: "text-danger" },
	];
});

const areas = [
	{ label: t("People"), icon: "ti-id-badge-2", to: "/hr/employees" },
	{ label: t("Attendance"), icon: "ti-calendar-clock", to: "/hr/attendance-dashboard" },
	{ label: t("Payroll"), icon: "ti-cash", to: "/hr/payroll-readiness" },
	{ label: t("Settings"), icon: "ti-settings", to: "/hr/attendance-rules" },
];
</script>

<template>
	<div class="row row-cards mb-3">
		<div v-for="ti in tiles" :key="ti.label" class="col">
			<div class="card card-sm">
				<div class="card-body">
					<div class="subheader">{{ ti.label }}</div>
					<div class="h1 mb-0 mt-1" :class="ti.cls">{{ ti.value }}</div>
				</div>
			</div>
		</div>
	</div>

	<div class="row">
		<div class="col-lg-7">
			<div class="card">
				<div class="card-header">
					<h3 class="card-title"><i class="ti ti-bell me-2"></i>{{ t("Needs your attention") }}</h3>
					<div class="card-actions text-muted small">{{ formatDate(today) }}</div>
				</div>
				<div class="list-group list-group-flush">
					<RouterLink v-for="a in attention" :key="a.label" :to="a.to"
						class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
						<span><i class="ti me-2" :class="[a.icon, a.cls]"></i>{{ a.label }}</span>
						<span class="badge" :class="a.value > 0 ? 'bg-yellow-lt' : 'bg-secondary-lt'">{{ a.value }}</span>
					</RouterLink>
				</div>
			</div>
		</div>

		<div class="col-lg-5">
			<div class="row row-cards">
				<div v-for="area in areas" :key="area.label" class="col-6">
					<button type="button" class="card card-link w-100 text-center p-3 border-0"
						@click="router.push(area.to)">
						<i class="ti d-block mb-1" :class="area.icon" style="font-size: 1.6rem"></i>
						<span class="small">{{ area.label }}</span>
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
