<script setup>
// Access review & segregation-of-duties dashboard (System Manager only).
// Two views: SoD violations (who holds a toxic combination) and a
// users × capabilities grid. Read-only — a control surface for review/audit.
import { computed, onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import SkeletonRows from "../../components/SkeletonRows.vue";

const toast = useToast();
const loading = ref(false);
const tab = ref("violations");
const scan = ref(null);
const grid = ref(null);
const matrix = ref(null);

const SEV = {
	critical: "bg-red text-white",
	high: "bg-orange-lt",
	medium: "bg-yellow-lt",
	info: "bg-secondary-lt",
};

const summary = computed(() => scan.value?.summary || {});

async function load() {
	loading.value = true;
	try {
		const [s, g, m] = await Promise.all([
			call("stabler.api.access_review.sod_scan"),
			call("stabler.api.access_review.access_review"),
			call("stabler.api.access_review.sod_matrix"),
		]);
		scan.value = s;
		grid.value = g;
		matrix.value = m;
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		loading.value = false;
	}
}

function exportCsv() {
	const rows = [["User", "Conflict", "Severity", "Holds (A)", "Holds (B)"]];
	for (const v of scan.value?.violations || []) {
		rows.push([v.full_name, v.label, v.severity, v.matched_a.join(" / "), v.matched_b.join(" / ")]);
	}
	const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
	const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
	const a = document.createElement("a");
	a.href = url;
	a.download = "sod-violations.csv";
	a.click();
	URL.revokeObjectURL(url);
}

onMounted(load);
</script>

<template>
	<div>
		<!-- Summary cards -->
		<div class="row row-cards mb-3">
			<div class="col">
				<div class="card card-sm">
					<div class="card-body">
						<div class="text-secondary small">{{ t("Critical conflicts") }}</div>
						<div class="h2 mb-0 text-red">{{ summary.critical || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col">
				<div class="card card-sm">
					<div class="card-body">
						<div class="text-secondary small">{{ t("High conflicts") }}</div>
						<div class="h2 mb-0 text-orange">{{ summary.high || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col">
				<div class="card card-sm">
					<div class="card-body">
						<div class="text-secondary small">{{ t("Users flagged") }}</div>
						<div class="h2 mb-0">{{ summary.users_flagged || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col">
				<div class="card card-sm">
					<div class="card-body">
						<div class="text-secondary small">{{ t("Enforcement") }}</div>
						<div class="h2 mb-0">
							<span v-if="matrix?.enforce" class="text-green">{{ t("On") }}</span>
							<span v-else class="text-secondary">{{ t("Warn only") }}</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<div class="card">
			<div class="card-header">
				<ul class="nav nav-tabs card-header-tabs">
					<li class="nav-item">
						<a class="nav-link" :class="{ active: tab === 'violations' }" href="#" @click.prevent="tab = 'violations'">
							{{ t("SoD violations") }}
						</a>
					</li>
					<li class="nav-item">
						<a class="nav-link" :class="{ active: tab === 'grid' }" href="#" @click.prevent="tab = 'grid'">
							{{ t("Capability grid") }}
						</a>
					</li>
					<li class="nav-item">
						<a class="nav-link" :class="{ active: tab === 'policy' }" href="#" @click.prevent="tab = 'policy'">
							{{ t("Policy") }}
						</a>
					</li>
				</ul>
				<div class="card-actions">
					<button class="btn btn-sm btn-outline-secondary" :disabled="tab !== 'violations'" @click="exportCsv">
						<i class="ti ti-download me-1"></i>{{ t("Export") }}
					</button>
				</div>
			</div>

			<!-- Violations -->
			<div v-if="tab === 'violations'" class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("User") }}</th>
							<th>{{ t("Conflict") }}</th>
							<th>{{ t("Severity") }}</th>
							<th>{{ t("Why it matters") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="4" />
					<tbody v-else>
						<tr v-for="(v, i) in scan?.violations || []" :key="i">
							<td>{{ v.full_name }}</td>
							<td>
								<div class="fw-medium">{{ v.label }}</div>
								<div class="text-secondary small">
									{{ v.matched_a.join(" / ") }} <i class="ti ti-plus"></i> {{ v.matched_b.join(" / ") }}
								</div>
							</td>
							<td><span class="badge" :class="SEV[v.severity]">{{ t(v.severity) }}</span></td>
							<td class="small">
								{{ v.rationale }}
								<div v-if="v.mitigation" class="text-secondary fst-italic">{{ v.mitigation }}</div>
							</td>
						</tr>
						<tr v-if="!loading && (scan?.violations || []).length === 0">
							<td colspan="4" class="text-center text-green py-4">
								<i class="ti ti-circle-check me-1"></i>{{ t("No segregation-of-duties conflicts found.") }}
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Capability grid -->
			<div v-else-if="tab === 'grid'" class="table-responsive">
				<table class="table card-table table-vcenter">
					<thead>
						<tr>
							<th>{{ t("User") }}</th>
							<th v-for="c in grid?.capabilities || []" :key="c.key" class="text-center small">{{ t(c.label) }}</th>
							<th class="text-center">{{ t("Conflicts") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="8" />
					<tbody v-else>
						<tr v-for="u in grid?.users || []" :key="u.user">
							<td>
								<div class="fw-medium">{{ u.full_name }}</div>
								<div class="text-secondary small font-monospace">{{ u.user }}</div>
							</td>
							<td v-for="c in grid?.capabilities || []" :key="c.key" class="text-center">
								<i v-if="u.capabilities[c.key]" class="ti ti-check text-green"></i>
								<span v-else class="text-secondary">·</span>
							</td>
							<td class="text-center">
								<span v-if="u.violation_count" class="badge" :class="SEV[u.max_severity]">{{ u.violation_count }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<!-- Policy -->
			<div v-else class="card-body">
				<p class="text-secondary">
					{{ t("These are the toxic role combinations Stabler checks for. Findings are advisory — accept them with a compensating control, or split the duties.") }}
				</p>
				<div v-for="c in matrix?.conflicts || []" :key="c.id" class="mb-3 pb-2 border-bottom">
					<div class="d-flex align-items-center gap-2">
						<span class="badge" :class="SEV[c.severity]">{{ t(c.severity) }}</span>
						<strong>{{ c.label }}</strong>
					</div>
					<div class="small text-secondary mt-1">
						<span class="badge bg-secondary-lt">{{ c.group_a }}</span>
						<i class="ti ti-plus mx-1"></i>
						<span class="badge bg-secondary-lt">{{ c.group_b }}</span>
					</div>
					<div class="small mt-1">{{ c.rationale }}</div>
					<div v-if="c.mitigation" class="small text-secondary fst-italic">{{ t("Mitigation:") }} {{ c.mitigation }}</div>
				</div>
			</div>
		</div>
	</div>
</template>
