<script setup>
import { onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const drawerOpen = ref(false);
const drawerMode = ref("create");
const form = ref(blankForm());
const submitting = ref(false);
const submitError = ref("");

function blankForm() {
	return {
		name: "",
		visit: "",
		outlet: "",
		company: activeCompany.value || "",
		audited_at: "",
		lines: [],
	};
}

function blankLine() {
	return { item: "", expected_facings: 0, actual_facings: 0, present: 0 };
}

const osaBadge = (pct) => {
	if (pct >= 90) return "bg-success-lt";
	if (pct >= 70) return "bg-warning-lt";
	return "bg-danger-lt";
};

const fmtPct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_osa_audits", {
			company: activeCompany.value,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function openCreate() {
	form.value = blankForm();
	drawerMode.value = "create";
	submitError.value = "";
	drawerOpen.value = true;
}

async function openEdit(row) {
	submitError.value = "";
	drawerMode.value = "edit";
	try {
		const full = await call("stabler.api.sfa.get_osa_audit", { name: row.name });
		form.value = {
			name: full.name,
			visit: full.visit || "",
			outlet: full.outlet || "",
			company: full.company || activeCompany.value || "",
			audited_at: full.audited_at || "",
			lines: (full.lines || []).map((ln) => ({
				item: ln.item || "",
				expected_facings: ln.expected_facings ?? 0,
				actual_facings: ln.actual_facings ?? 0,
				present: ln.present ? 1 : 0,
			})),
		};
		drawerOpen.value = true;
	} catch (e) {
		error.value = e?.message || t("Failed to load OSA audit.");
	}
}

function closeDrawer() {
	if (submitting.value) return;
	drawerOpen.value = false;
	submitError.value = "";
}

function addLine() {
	form.value.lines.push(blankLine());
}

function removeLine(idx) {
	form.value.lines.splice(idx, 1);
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.outlet?.trim()) return (submitError.value = t("Outlet is required."));
	if (!f.company?.trim()) return (submitError.value = t("Company is required."));
	for (const [i, ln] of f.lines.entries()) {
		if (!ln.item?.trim()) {
			return (submitError.value = t("Item is required on row {0}.").replace("{0}", String(i + 1)));
		}
	}
	submitting.value = true;
	try {
		const payload = {
			visit: f.visit || null,
			outlet: f.outlet,
			company: f.company,
			audited_at: f.audited_at || null,
			lines: f.lines.map((ln) => ({
				item: ln.item,
				expected_facings: Number(ln.expected_facings) || 0,
				actual_facings: Number(ln.actual_facings) || 0,
				present: ln.present ? 1 : 0,
			})),
		};
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_osa_audit", { payload });
		} else {
			await call("stabler.api.sfa.update_osa_audit", { name: f.name, payload });
		}
		drawerOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Failed to save OSA audit.");
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<h3 class="card-title mb-0">{{ t("OSA Audits") }}</h3>
			<div class="ms-auto">
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-checkup-list"
			:title="t('No OSA audits yet')"
			:description="t('On-Shelf-Availability audits compare expected vs actual facings during visits.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Outlet") }}</th>
						<th>{{ t("Audited At") }}</th>
						<th class="text-end">{{ t("Total SKUs") }}</th>
						<th class="text-end">{{ t("Present SKUs") }}</th>
						<th>{{ t("OSA %") }}</th>
						<th class="w-1"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.name }}</td>
						<td>{{ r.outlet }}</td>
						<td>{{ formatDateTime(r.audited_at) }}</td>
						<td class="text-end">{{ r.total_skus ?? 0 }}</td>
						<td class="text-end">{{ r.present_skus ?? 0 }}</td>
						<td>
							<span class="badge" :class="osaBadge(r.osa_pct ?? 0)">
								{{ fmtPct(r.osa_pct) }}
							</span>
						</td>
						<td class="text-end">
							<button type="button" class="btn btn-sm btn-link" @click="openEdit(r)">
								{{ t("Edit") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<template v-if="drawerOpen">
		<div class="modal-backdrop fade show" @click="closeDrawer"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-dialog-centered modal-lg" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">
							{{ drawerMode === "create" ? t("New OSA audit") : t("Edit OSA audit") }}
						</h5>
						<button
							type="button"
							class="btn-close"
							:aria-label="t('Close')"
							@click="closeDrawer"
						></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label">{{ t("Outlet") }} <span class="text-danger">*</span></label>
								<input v-model="form.outlet" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Visit") }}</label>
								<input v-model="form.visit" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Company") }} <span class="text-danger">*</span></label>
								<input v-model="form.company" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Audited At") }}</label>
								<input v-model="form.audited_at" type="datetime-local" class="form-control" />
							</div>
						</div>

						<h6 class="text-uppercase text-secondary small mt-4 mb-2">{{ t("Lines") }}</h6>
						<div class="form-hint small mb-2">
							{{ t("Total / Present / OSA % are computed server-side.") }}
						</div>
						<div class="table-responsive">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("Item") }} <span class="text-danger">*</span></th>
										<th style="width: 130px">{{ t("Expected") }}</th>
										<th style="width: 130px">{{ t("Actual") }}</th>
										<th style="width: 100px">{{ t("Present") }}</th>
										<th class="w-1"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-if="!form.lines.length">
										<td colspan="5" class="text-secondary text-center small">
											{{ t("No lines yet.") }}
										</td>
									</tr>
									<tr v-for="(ln, idx) in form.lines" :key="idx">
										<td>
											<input v-model="ln.item" type="text" class="form-control form-control-sm" />
										</td>
										<td>
											<input
												v-model.number="ln.expected_facings"
												type="number"
												inputmode="decimal"
												min="0"
												class="form-control form-control-sm"
											/>
										</td>
										<td>
											<input
												v-model.number="ln.actual_facings"
												type="number"
												inputmode="decimal"
												min="0"
												class="form-control form-control-sm"
											/>
										</td>
										<td>
											<div class="form-check form-switch">
												<input
													v-model="ln.present"
													:true-value="1"
													:false-value="0"
													class="form-check-input"
													type="checkbox"
												/>
											</div>
										</td>
										<td>
											<button
												type="button"
												class="btn btn-sm btn-link link-danger"
												:aria-label="t('Remove')"
												@click="removeLine(idx)"
											>
												<i class="ti ti-x"></i>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
						<button type="button" class="btn btn-sm btn-outline-primary" @click="addLine">
							<i class="ti ti-plus me-1"></i>{{ t("Add line") }}
						</button>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-link link-secondary"
							:disabled="submitting"
							@click="closeDrawer"
						>
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submitting || !form.outlet?.trim() || !form.company?.trim()"
							@click="submitDrawer"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>
							{{ t("Save") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
