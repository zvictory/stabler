<template>
	<TenderPage :title="t('Document Center')">
		<div v-if="deal" class="d-flex flex-column gap-3">
			<!-- Header KPI / Readiness Summary -->
			<div class="row g-3">
				<div class="col-md-3">
					<div class="card card-sm p-3 text-center">
						<div class="text-secondary small text-uppercase fw-semibold">{{ t("Requirements") }}</div>
						<div class="h2 m-0 fw-bold">{{ summary?.total || 0 }}</div>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card card-sm p-3 text-center">
						<div class="text-secondary small text-uppercase fw-semibold">{{ t("Required") }}</div>
						<div class="h2 m-0 fw-bold text-primary">{{ summary?.required || 0 }}</div>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card card-sm p-3 text-center">
						<div class="text-secondary small text-uppercase fw-semibold">{{ t("Verified complete") }}</div>
						<div class="h2 m-0 fw-bold text-success">
							{{ summary?.done_required || 0 }} / {{ summary?.required || 0 }}
						</div>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card card-sm p-3 text-center">
						<div class="text-secondary small text-uppercase fw-semibold">{{ t("Readiness score") }}</div>
						<div class="h2 m-0 fw-bold" :class="(summary?.readiness_pct || 0) === 100 ? 'text-success' : 'text-warning'">
							{{ summary?.readiness_pct || 0 }}%
						</div>
					</div>
				</div>
			</div>

			<!-- Documents Table -->
			<div class="card">
				<div class="card-header py-2 fw-semibold d-flex justify-content-between align-items-center">
					<span><i class="ti ti-files me-1"></i>{{ t("Required & Tender Documents") }}</span>
					<div class="d-flex align-items-center gap-2">
						<span v-if="summary?.unverified" class="badge bg-warning-lt text-warning">
							<i class="ti ti-alert-circle me-1"></i>{{ summary.unverified }} {{ t("unverified legacy items") }}
						</span>
						<button v-if="deal && !editing" type="button" class="btn btn-ghost-secondary btn-sm" @click="startEditing">
							<i class="ti ti-list-check me-1"></i>{{ t("Edit checklist") }}
						</button>
						<template v-if="editing">
							<button type="button" class="btn btn-ghost-secondary btn-sm" :disabled="savingReqs" @click="cancelEditing">{{ t("Cancel") }}</button>
							<button type="button" class="btn btn-primary btn-sm" :disabled="savingReqs" @click="saveRequirements">
								<span v-if="savingReqs" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save checklist") }}
							</button>
						</template>
					</div>
				</div>
				<div v-if="editing" class="card-body p-0">
					<table class="table card-table align-middle">
						<thead>
							<tr>
								<th style="min-width: 220px">{{ t("Requirement") }}</th>
								<th style="width: 110px">{{ t("Required") }}</th>
								<th style="width: 160px">{{ t("Responsible role") }}</th>
								<th style="width: 150px">{{ t("Due date") }}</th>
								<th style="width: 120px">{{ t("Evidence") }}</th>
								<th class="text-end" style="width: 60px"></th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(d, i) in draft" :key="i">
								<td><input v-model="d.label" type="text" class="form-control form-control-sm" :placeholder="t('Document name')"></td>
								<td><label class="form-check form-switch m-0"><input v-model="d.required" type="checkbox" class="form-check-input" :true-value="1" :false-value="0"></label></td>
								<td>
									<select v-model="d.role" class="form-select form-select-sm">
										<option v-for="o in ROLE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
									</select>
								</td>
								<td><DateInput v-model="d.date" size="sm" /></td>
								<td>
									<!-- Files and waivers are server facts: this editor cannot touch them,
									     so the row says what it would keep rather than pretending to own it. -->
									<span v-if="d.waiver_reason" class="badge bg-warning-lt text-warning">{{ t("Waived") }}</span>
									<span v-else-if="d.file_count" class="badge bg-green-lt text-green">{{ d.file_count }} {{ t("file(s)") }}</span>
									<span v-else class="text-secondary small">—</span>
								</td>
								<td class="text-end">
									<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" :title="t('Remove requirement')" @click="removeRequirement(i)"><i class="ti ti-x"></i></button>
								</td>
							</tr>
						</tbody>
					</table>
					<div class="p-2 d-flex gap-2 border-top">
						<button type="button" class="btn btn-ghost-primary btn-sm" @click="addRequirement">
							<i class="ti ti-plus me-1"></i>{{ t("Add requirement") }}
						</button>
						<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addStandardSet">
							<i class="ti ti-template me-1"></i>{{ t("Add standard set") }}
						</button>
						<span class="text-secondary small ms-auto align-self-center">
							{{ t("Tender-level requirements are edited on the tender, not here.") }}
						</span>
					</div>
				</div>

				<div v-else class="card-body p-0">
					<table class="table card-table align-middle">
						<thead>
							<tr>
								<th>{{ t("Requirement") }}</th>
								<th>{{ t("Scope") }}</th>
								<th>{{ t("Status") }}</th>
								<th>{{ t("Attached files / Waiver") }}</th>
								<th class="text-end">{{ t("Actions") }}</th>
							</tr>
						</thead>
						<tbody>
							<SkeletonRows v-if="loading" :cols="5" :rows="4" />
							<tr v-for="r in requirements" :key="r.key">
								<td>
									<div class="fw-semibold">{{ r.label }}</div>
									<div class="text-secondary small">
										<span v-if="r.required" class="text-danger">* {{ t("Required") }}</span>
										<span v-else class="text-secondary">{{ t("Optional") }}</span>
									</div>
								</td>
								<td>
									<span class="badge" :class="r.scope === 'tender' ? 'bg-purple-lt text-purple' : 'bg-blue-lt text-blue'">
										{{ r.scope === 'tender' ? t("Tender Master") : t("Lot Specific") }}
									</span>
								</td>
								<td>
									<span v-if="r.done" class="badge bg-green text-white">
										<i class="ti ti-check me-1"></i>{{ t("Verified") }}
									</span>
									<span v-else-if="r.unverified" class="badge bg-warning-lt text-warning" :title="t('Legacy tick without verified file attachment')">
										<i class="ti ti-alert-triangle me-1"></i>{{ t("Unverified tick") }}
									</span>
									<span v-else-if="r.required" class="badge bg-red-lt text-red">
										<i class="ti ti-x me-1"></i>{{ t("Missing file") }}
									</span>
									<span v-else class="badge bg-secondary-lt">{{ t("Pending") }}</span>
								</td>
								<td>
									<div v-if="r.waiver_reason" class="alert alert-warning py-1 px-2 m-0 small">
										<div><i class="ti ti-shield-off me-1"></i><b>{{ t("Waived") }}:</b> {{ r.waiver_reason }}</div>
										<div class="text-secondary" style="font-size: 0.8em">{{ r.waived_by }} · {{ r.waived_at }}</div>
									</div>
									<div v-else-if="r.file_count" class="d-flex flex-column gap-1">
										<div v-for="(f, idx) in r.files" :key="idx" class="d-flex align-items-center gap-2 small">
											<i class="ti ti-paperclip text-secondary"></i>
											<a :href="getGatedDownloadUrl(r.key, f.file_url)" target="_blank" class="fw-semibold text-truncate" style="max-width: 200px">
												{{ f.file_name || f.file_url }}
											</a>
											<span class="text-secondary ms-auto" style="font-size: 0.8em">{{ f.uploaded_at ? f.uploaded_at.substring(0, 10) : '' }}</span>
										</div>
									</div>
									<span v-else class="text-secondary small">—</span>
								</td>
								<td class="text-end">
									<button type="button" class="btn btn-ghost-primary btn-sm me-1" @click="openUpload(r)">
										<i class="ti ti-upload me-1"></i>{{ t("Upload file") }}
									</button>
									<button type="button" class="btn btn-ghost-warning btn-sm" @click="openWaive(r)">
										<i class="ti ti-shield-off me-1"></i>{{ t("Waive") }}
									</button>
								</td>
							</tr>
						</tbody>
					</table>
					<EmptyState v-if="!loading && !requirements.length" icon="ti-files" :title="t('No document requirements set.')" />
				</div>
			</div>

			<!-- Upload Modal -->
			<div v-if="uploadOpen" class="modal modal-blur fade show d-block" tabindex="-1" style="background: rgba(0,0,0,0.5)">
				<div class="modal-dialog modal-dialog-centered">
					<div class="modal-content">
						<div class="modal-header py-2">
							<h5 class="modal-title">{{ t("Upload document file") }}</h5>
							<button type="button" class="btn-close" @click="uploadOpen = false"></button>
						</div>
						<div class="modal-body">
							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("Requirement") }}</label>
								<input type="text" class="form-control" :value="targetReq?.label" disabled />
							</div>
							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("File name") }} <span class="text-danger">*</span></label>
								<input v-model="uploadForm.file_name" type="text" class="form-control" :placeholder="t('e.g. GTD_Customs_Declaration.pdf')" />
							</div>
							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("File URL / Path") }} <span class="text-danger">*</span></label>
								<input v-model="uploadForm.file_url" type="text" class="form-control" :placeholder="t('/private/files/GTD_Customs_Declaration.pdf')" />
							</div>
						</div>
						<div class="modal-footer py-2">
							<button type="button" class="btn btn-outline-secondary" @click="uploadOpen = false">{{ t("Cancel") }}</button>
							<button type="button" class="btn btn-primary" :disabled="uploadSaving || !uploadForm.file_name || !uploadForm.file_url" @click="submitUpload">
								<span v-if="uploadSaving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save document") }}
							</button>
						</div>
					</div>
				</div>
			</div>

			<!-- Waive Modal -->
			<div v-if="waiveOpen" class="modal modal-blur fade show d-block" tabindex="-1" style="background: rgba(0,0,0,0.5)">
				<div class="modal-dialog modal-dialog-centered">
					<div class="modal-content">
						<div class="modal-header py-2">
							<h5 class="modal-title">{{ t("Waive document requirement") }}</h5>
							<button type="button" class="btn-close" @click="waiveOpen = false"></button>
						</div>
						<div class="modal-body">
							<div class="alert alert-warning py-2 mb-3">
								<i class="ti ti-alert-triangle me-1"></i>
								{{ t("Waiving a requirement bypasses file verification. A written justification is mandatory.") }}
							</div>
							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("Requirement") }}</label>
								<input type="text" class="form-control" :value="targetReq?.label" disabled />
							</div>
							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("Justification / Reason") }} <span class="text-danger">*</span></label>
								<textarea v-model="waiveForm.reason" class="form-control" rows="3" :placeholder="t('Enter protocol / authorization reason…')"></textarea>
							</div>
						</div>
						<div class="modal-footer py-2">
							<button type="button" class="btn btn-outline-secondary" @click="waiveOpen = false">{{ t("Cancel") }}</button>
							<button type="button" class="btn btn-warning" :disabled="waiveSaving || !waiveForm.reason.trim()" @click="submitWaive">
								<span v-if="waiveSaving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Confirm waiver") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Lot selector — when ?deal= is not present -->
	<div v-else class="card">
		<div class="card-header py-2 fw-semibold d-flex justify-content-between align-items-center">
			<span><i class="ti ti-search me-1"></i>{{ t("Select Lot — Document Center") }}</span>
			<span v-if="targets.length" class="text-muted small">{{ targets.length }} {{ t("lots") }}</span>
		</div>
		<div class="card-body p-0">
			<SkeletonRows v-if="targetsLoading" :rows="4" />
			<table v-else-if="targets.length" class="table table-sm align-middle mb-0">
				<thead>
					<tr>
						<th>{{ t("Lot / Deal") }}</th>
						<th>{{ t("Parent Tender") }}</th>
						<th>{{ t("Stage") }}</th>
						<th class="text-end">{{ t("Missing Required") }}</th>
						<th>{{ t("Readiness") }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="lot in targets" :key="lot.deal" role="button" @click="pickLot(lot.deal)">
						<td>
							<div class="fw-semibold">{{ lot.label }}</div>
							<div class="text-secondary small font-monospace">{{ lot.deal }}</div>
						</td>
						<td class="text-secondary small">{{ lot.parent_tender || "—" }}</td>
						<td><span class="badge bg-secondary-lt">{{ lot.stage }}</span></td>
						<td class="text-end">
							<span v-if="lot.missing_required" class="badge bg-red-lt text-red fw-bold">{{ lot.missing_required }}</span>
							<span v-else class="badge bg-green-lt text-green">✓</span>
						</td>
						<td>
							<div class="d-flex align-items-center gap-2">
								<div class="progress flex-grow-1" style="height: 5px; min-width: 60px">
									<div class="progress-bar" :class="(lot.readiness_pct || 0) === 100 ? 'bg-success' : 'bg-warning'"
										:style="{ width: (lot.readiness_pct || 0) + '%' }"></div>
								</div>
								<span class="font-monospace small">{{ lot.readiness_pct || 0 }}%</span>
							</div>
						</td>
						<td class="text-end">
							<button type="button" class="btn btn-ghost-primary btn-sm">{{ t("Open") }} →</button>
						</td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-else icon="ti-files-off" :title="t('No tender lots found.')" />
		</div>
	</div>
	</TenderPage>
</template>

<script setup>
import { ref, watch, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useTenderContext } from "../../composables/useTenderContext.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import DateInput from "../../components/DateInput.vue";
import TenderPage from "./TenderPage.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { documentsLocation } = useTenderContext(route);

const deal = ref(route.query.deal ? String(route.query.deal) : "");
const loading = ref(false);
const requirements = ref([]);
const summary = ref(null);

// Lot seçici — ?deal= yokken yüklenir
const targets = ref([]);
const targetsLoading = ref(false);

const uploadOpen = ref(false);
const uploadSaving = ref(false);
const targetReq = ref(null);
const uploadForm = ref({ file_name: "", file_url: "" });

// ── Requirement authoring (ADR-201/205) ─────────────────────────────────────
// Until 2026-08-28 the only screen that could create a requirement row was
// TenderIntake.vue on the PO control board — a post-win screen editing the
// checklist through the intake JSON blob. That is why ADR-201 could not retire
// its edit rights. The writer lives here now: one surface owns the checklist,
// and `set_tender_document_requirements` reconciles files/waivers server-side
// so a rename never costs an upload.
const editing = ref(false);
const savingReqs = ref(false);
const draft = ref([]);

const ROLE_OPTIONS = [
	{ value: "general", label: t("General") },
	{ value: "customs", label: t("Customs") },
	{ value: "logistics", label: t("Logistics") },
	{ value: "finance", label: t("Finance") },
];

// Mirrors the backend's default_doc_requirements() — keys and role assignments
// drive who may upload to each row.
const STD_DOCS = [
	{ key: "gtd", label: t("Customs Declaration (GTD)"), required: 1, role: "customs" },
	{ key: "origin_cert", label: t("Certificate of Origin"), required: 0, role: "customs" },
	{ key: "cmr", label: t("CMR / Waybill"), required: 1, role: "logistics" },
	{ key: "packing_list", label: t("Packing List"), required: 0, role: "logistics" },
	{ key: "invoice", label: t("Commercial Invoice"), required: 1, role: "finance" },
	{ key: "tech_spec", label: t("Technical Specification"), required: 1, role: "general" },
	{ key: "price_offer", label: t("Price Offer"), required: 1, role: "general" },
];

// Only lot rows are editable here. A tender-level requirement is shared by every
// lot under the master, so the server refuses one in this payload — the draft
// must not carry them or every save would throw.
function startEditing() {
	draft.value = requirements.value
		.filter((r) => r.scope !== "tender")
		.map((r) => ({ key: r.key, label: r.label, required: r.required ? 1 : 0, role: r.role || "general", date: r.date || "", done: !!r.done, file_count: r.file_count || 0, waiver_reason: r.waiver_reason || "" }));
	editing.value = true;
}

function cancelEditing() {
	editing.value = false;
	draft.value = [];
}

function addRequirement() {
	draft.value.push({ key: "", label: "", required: 1, role: "general", date: "", done: false, file_count: 0, waiver_reason: "" });
}

function addStandardSet() {
	const have = new Set(draft.value.map((d) => d.key || d.label));
	for (const d of STD_DOCS) {
		if (!have.has(d.key)) draft.value.push({ ...d, date: "", done: false, file_count: 0, waiver_reason: "" });
	}
}

function removeRequirement(i) {
	draft.value.splice(i, 1);
}

async function saveRequirements() {
	savingReqs.value = true;
	try {
		const res = await call("stabler.api.tender_documents.set_tender_document_requirements", {
			deal: deal.value,
			requirements: JSON.stringify(
				draft.value.map((d) => ({ key: d.key, label: d.label, required: d.required ? 1 : 0, role: d.role, date: d.date })),
			),
			company: activeCompany.value,
		});
		requirements.value = res.requirements || [];
		summary.value = res.summary || null;
		editing.value = false;
		draft.value = [];
		toast.success(t("Checklist saved"));
	} catch (err) {
		toast.error(err.message || t("Failed to save the checklist"));
	} finally {
		savingReqs.value = false;
	}
}

const waiveOpen = ref(false);
const waiveSaving = ref(false);
const waiveForm = ref({ reason: "" });

async function loadTargets() {
	if (deal.value) return;
	targetsLoading.value = true;
	try {
		const res = await call("stabler.api.tender_documents.tender_document_targets", {
			company: activeCompany.value,
		});
		targets.value = res?.targets || [];
	} catch (err) {
		toast.error(err.message || t("Failed to load lots"));
	} finally {
		targetsLoading.value = false;
	}
}

function pickLot(dealId) {
	router.push(documentsLocation(dealId));
}

async function load() {
	if (!deal.value) return;
	loading.value = true;
	try {
		const res = await call("stabler.api.tender_documents.list_tender_documents", {
			deal: deal.value,
			company: activeCompany.value,
		});
		requirements.value = res.requirements || [];
		summary.value = res.summary || null;
	} catch (err) {
		toast.error(err.message || t("Failed to load documents"));
	} finally {
		loading.value = false;
	}
}

function openUpload(r) {
	targetReq.value = r;
	uploadForm.value = { file_name: "", file_url: "" };
	uploadOpen.value = true;
}

async function submitUpload() {
	if (!targetReq.value || !uploadForm.value.file_name || !uploadForm.value.file_url) return;
	uploadSaving.value = true;
	try {
		await call("stabler.api.tender_documents.upload_tender_document", {
			deal: deal.value,
			requirement_key: targetReq.value.key,
			file_name: uploadForm.value.file_name,
			file_url: uploadForm.value.file_url,
			company: activeCompany.value,
		});
		toast.success(t("Document uploaded successfully"));
		uploadOpen.value = false;
		await load();
	} catch (err) {
		toast.error(err.message || t("Failed to upload document"));
	} finally {
		uploadSaving.value = false;
	}
}

function openWaive(r) {
	targetReq.value = r;
	waiveForm.value = { reason: "" };
	waiveOpen.value = true;
}

async function submitWaive() {
	if (!targetReq.value || !waiveForm.value.reason.trim()) return;
	waiveSaving.value = true;
	try {
		await call("stabler.api.tender_documents.waive_tender_document", {
			deal: deal.value,
			requirement_key: targetReq.value.key,
			reason: waiveForm.value.reason,
			company: activeCompany.value,
		});
		toast.success(t("Requirement waived"));
		waiveOpen.value = false;
		await load();
	} catch (err) {
		toast.error(err.message || t("Failed to waive requirement"));
	} finally {
		waiveSaving.value = false;
	}
}

function getGatedDownloadUrl(key, fileUrl) {
	return `/api/method/stabler.api.tender_documents.download_tender_document?deal=${encodeURIComponent(deal.value)}&requirement_key=${encodeURIComponent(key)}&file_url=${encodeURIComponent(fileUrl)}&company=${encodeURIComponent(activeCompany.value || '')}`;
}

// route.query.deal değişince deal ref'ini senkronize tut (lot seçicide navigasyon)
watch(() => route.query.deal, (newDeal) => {
	deal.value = newDeal ? String(newDeal) : "";
});

// deal boşken targets yükle, doluyken belgeleri yükle
watch([deal, activeCompany], () => {
	if (deal.value) {
		load();
	} else {
		loadTargets();
	}
});
onMounted(() => {
	if (deal.value) load();
	else loadTargets();
});
</script>
