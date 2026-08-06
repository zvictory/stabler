<script setup>
/**
 * TenderDocumentsPanel — the "Documents" tab of the tender workspace.
 *
 * Pulls the merged two-level document requirements (tender master + lot) via
 * stabler.api.tender_documents.list_tender_documents, renders a readiness
 * summary, an optional role filter (customs / logistics / finance / general),
 * and one FileSlot per requirement plus an inline waiver box for required-but-
 * missing documents. Upload/waive flow through the dedicated endpoints so the
 * server remains the single source of truth for files + derived completion.
 *
 * This is the "file manager feel" surface for a single tender — scoped to this
 * lot's requirement set, not a generic filesystem explorer.
 */
import { computed, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import FileSlot from "../../components/files/FileSlot.vue";

const props = defineProps({ deal: { type: String, required: true } });
const toast = useToast();

const loading = ref(false);
const busyKey = ref("");
const roleFilter = ref(""); // "" = all
const data = ref({ requirements: [], summary: {}, tender_master: null });

const ROLE_LABEL = { customs: t("Customs"), logistics: t("Logistics"), finance: t("Finance"), general: t("General") };
const ROLE_ICON = { customs: "ti-building-bridge-2", logistics: "ti-truck", finance: "ti-report-money", general: "ti-file-description" };

const roles = computed(() => {
	const set = new Set(data.value.requirements.map((r) => r.role || "general"));
	return [...set];
});
const filtered = computed(() => {
	const rf = roleFilter.value;
	if (!rf) return data.value.requirements;
	return data.value.requirements.filter((r) => (r.role || "general") === rf);
});
const summary = computed(() => data.value.summary || {});

async function load() {
	if (!props.deal) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender_documents.list_tender_documents", { deal: props.deal });
	} catch (e) {
		toast.error(e?.message || t("Could not load documents."));
	} finally {
		loading.value = false;
	}
}

async function attach(req, file) {
	busyKey.value = req.key;
	try {
		data.value = await call("stabler.api.tender_documents.upload_tender_document", {
			deal: props.deal, requirement_key: req.key, file_name: file.file_name, file_url: file.file_url,
		});
		toast.success(t("Document attached."));
	} catch (e) {
		toast.error(e?.message || t("Could not attach document."));
	} finally {
		busyKey.value = "";
	}
}

async function waive(req) {
	const reason = (req._waiverDraft || "").trim();
	if (!reason) { toast.error(t("Waiver reason is mandatory.")); return; }
	busyKey.value = req.key;
	try {
		data.value = await call("stabler.api.tender_documents.waive_tender_document", {
			deal: props.deal, requirement_key: req.key, reason,
		});
		toast.success(t("Document waived."));
	} catch (e) {
		toast.error(e?.message || t("Could not waive document."));
	} finally {
		busyKey.value = "";
	}
}

async function remove(req) {
	if (!req.latest_file) return;
	busyKey.value = req.key;
	try {
		data.value = await call("stabler.api.tender_documents.remove_tender_document", {
			deal: props.deal, requirement_key: req.key, file_url: req.latest_file.file_url,
		});
		toast.success(t("Document removed."));
	} catch (e) {
		toast.error(e?.message || t("Could not remove document."));
	} finally {
		busyKey.value = "";
	}
}

watch(() => props.deal, load, { immediate: true });
</script>

<template>
	<div>
		<!-- Summary strip -->
		<div class="card mb-3">
			<div class="card-body py-2 px-3 d-flex align-items-center flex-wrap gap-2">
				<span class="fw-semibold me-2"><i class="ti ti-files me-1"></i>{{ t("Tender documents") }}</span>
				<span v-if="summary.required" class="badge" :class="summary.done_required >= summary.required ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'">
					{{ summary.done_required }}/{{ summary.required }} {{ t("required") }}
				</span>
				<span v-if="summary.unverified" class="badge bg-yellow-lt text-yellow" :title="t('Marked done but no file')">
					<i class="ti ti-alert-triangle me-1"></i>{{ summary.unverified }} {{ t("unverified") }}
				</span>
				<span v-if="summary.required" class="badge bg-secondary-lt text-secondary font-monospace">{{ summary.readiness_pct }}%</span>
				<div v-if="roles.length > 1" class="btn-group btn-group-sm ms-auto">
					<button type="button" class="btn" :class="roleFilter === '' ? 'btn-primary' : 'btn-outline-secondary'" @click="roleFilter = ''">{{ t("All") }}</button>
					<button v-for="r in roles" :key="r" type="button" class="btn" :class="roleFilter === r ? 'btn-primary' : 'btn-outline-secondary'" @click="roleFilter = r">
						<i class="ti me-1" :class="ROLE_ICON[r] || 'ti-tag'"></i>{{ ROLE_LABEL[r] || r }}
					</button>
				</div>
			</div>
		</div>

		<div v-if="loading" class="text-center py-4"><span class="spinner-border spinner-border-sm text-primary"></span></div>

		<div v-else-if="!filtered.length" class="card"><div class="card-body text-center text-secondary small">
			{{ t("No document requirements yet. Add them in Tender details.") }}
		</div></div>

		<div v-else class="row g-2">
			<div v-for="req in filtered" :key="req.key" class="col-12 col-md-6 col-xl-4">
				<div class="card h-100" :class="{ 'border-warning': req.unverified, 'border-danger': req.required && !req.done && !req.unverified }">
					<div class="card-body p-2">
						<div class="d-flex align-items-start gap-2 mb-2">
							<i class="ti mt-1" :class="ROLE_ICON[req.role] || 'ti-file'"></i>
							<div class="flex-fill">
								<div class="fw-semibold small">{{ req.label }}</div>
								<div class="d-flex align-items-center gap-1 flex-wrap mt-1">
									<span v-if="req.scope === 'tender'" class="badge bg-purple-lt text-purple" :title="t('Shared across all lots of this tender')">{{ t("Tender") }}</span>
									<span v-else class="badge bg-secondary-lt text-secondary">{{ t("Lot") }}</span>
									<span class="badge bg-secondary-lt text-secondary">{{ ROLE_LABEL[req.role] || t("General") }}</span>
									<span v-if="req.required" class="badge bg-red-lt text-red">{{ t("Required") }}</span>
									<span v-if="req.done" class="badge bg-green-lt text-green">
										<i class="ti" :class="req.waiver_reason ? 'ti-shield-check' : 'ti-check'"></i>
									</span>
									<span v-else-if="req.unverified" class="badge bg-yellow-lt text-yellow" :title="t('Marked done but no file')"><i class="ti ti-alert-triangle"></i></span>
								</div>
							</div>
						</div>

						<!-- Latest file attach control -->
						<FileSlot
							:attached-to="'CRM Deal'"
							:attached-name="deal"
							:existing="req.latest_file"
							:disabled="!!busyKey"
							:download-endpoint="'stabler.api.tender_documents.download_tender_document'"
							:download-params="{ deal, requirement_key: req.key }"
							@uploaded="(f) => attach(req, f)"
							@remove="remove(req)"
						/>

						<!-- File history (if more than one) -->
						<div v-if="req.file_count > 1" class="mt-1 small text-secondary">
							<i class="ti ti-history me-1"></i>{{ req.file_count }} {{ t("files") }}
						</div>

						<!-- Waiver box for required-but-missing -->
						<div v-if="req.waiver_reason" class="mt-2 small fst-italic text-secondary border-top pt-1">
							<i class="ti ti-shield-check me-1"></i>{{ req.waiver_reason }}
							<div class="text-end" style="font-size:10px">{{ req.waived_by }}</div>
						</div>
						<div v-else-if="req.required && !req.done" class="input-group input-group-sm mt-2">
							<input v-model="req._waiverDraft" type="text" class="form-control form-control-sm" :placeholder="t('Waive with reason…')" :disabled="!!busyKey">
							<button type="button" class="btn btn-outline-warning btn-sm" :disabled="!!busyKey || busyKey === req.key" @click="waive(req)">
								<span v-if="busyKey === req.key" class="spinner-border spinner-border-sm"></span>
								<span v-else><i class="ti ti-shield-check"></i></span>
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
