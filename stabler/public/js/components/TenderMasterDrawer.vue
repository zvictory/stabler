<script setup>
import { reactive, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../stores/session.js";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";
import { useToast } from "../composables/useToast.js";
import MoneyInput from "./MoneyInput.vue";
import DateInput from "./DateInput.vue";

const props = defineProps({
	open: { type: Boolean, default: false },
	tender: { type: Object, default: null },
	initialLot: { type: Object, default: null },
});
const emit = defineEmits(["update:open", "saved", "close"]);

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const saving = ref(false);
const form = reactive({
	name: "",
	title: "",
	tender_number: "",
	buyer_name: "",
	source: "UZEX",
	publication_date: "",
	submission_deadline: "",
	currency: "USD",
	estimated_total: 0,
});

watch(
	() => props.tender,
	(val) => {
		if (val) {
			form.name = val.name || "";
			form.title = val.title || "";
			form.tender_number = val.tender_number || "";
			form.buyer_name = val.buyer_name || "";
			form.source = val.source || "UZEX";
			form.publication_date = val.publication_date || "";
			form.submission_deadline = val.submission_deadline || "";
			form.currency = val.currency || "USD";
			form.estimated_total = val.estimated_total || 0;
		} else {
			reset();
		}
	},
	{ immediate: true }
);

function reset() {
	form.name = "";
	form.title = props.initialLot ? `${props.initialLot.organization || props.initialLot.name}` : "";
	form.tender_number = "";
	form.buyer_name = props.initialLot?.organization || "";
	form.source = "UZEX";
	form.publication_date = "";
	form.submission_deadline = "";
	form.currency = "USD";
	form.estimated_total = props.initialLot?.deal_value || 0;
}

function close() {
	emit("update:open", false);
	emit("close");
}

async function save() {
	if (!form.title) {
		toast.error(t("Title is required"));
		return;
	}
	saving.value = true;
	try {
		const res = await call("stabler.api.tender_master.save_tender_master", {
			data: {
				name: form.name || undefined,
				title: form.title,
				tender_number: form.tender_number,
				buyer_name: form.buyer_name,
				source: form.source,
				publication_date: form.publication_date,
				submission_deadline: form.submission_deadline,
				currency: form.currency,
				estimated_total: form.estimated_total,
			},
			company: activeCompany.value,
		});

		// If initialLot is provided, bind the lot to the created tender master
		if (props.initialLot?.name && res?.name) {
			await call("stabler.api.tender.save_deal_intake", {
				deal: props.initialLot.name,
				data: { custom_parent_tender: res.name },
				company: activeCompany.value,
			});
		}

		toast.success(form.name ? t("Tender updated") : t("Tender created"));
		emit("saved", res);
		close();
	} catch (err) {
		toast.error(err?.message || t("Could not save tender"));
	} finally {
		saving.value = false;
	}
}
</script>

<template>
	<div v-if="open" class="modal-backdrop fade show" @click="close"></div>
	<div v-if="open" class="ds-drawer fade show d-block" tabindex="-1" role="dialog">
		<div class="ds-drawer-dialog">
			<div class="ds-drawer-content">
				<div class="ds-drawer-header">
					<h3 class="ds-drawer-title">
						{{ form.name ? t("Edit Tender Master") : t("Create Tender Master") }}
					</h3>
					<button type="button" class="btn-close" @click="close"></button>
				</div>
				<div class="ds-drawer-body">
					<form @submit.prevent="save">
						<div class="mb-3">
							<label class="form-label required">{{ t("Tender Title") }}</label>
							<input v-model="form.title" type="text" class="form-control" placeholder="e.g. UZEX Supply Tender 2026" required />
						</div>

						<div class="row g-2 mb-3">
							<div class="col-6">
								<label class="form-label">{{ t("Tender / Lot No") }}</label>
								<input v-model="form.tender_number" type="text" class="form-control" placeholder="TND-1001" />
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Buyer / Customer") }}</label>
								<input v-model="form.buyer_name" type="text" class="form-control" placeholder="Navoi Mining..." />
							</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-6">
								<label class="form-label">{{ t("Source / Portal") }}</label>
								<select v-model="form.source" class="form-select">
									<option value="UZEX">UZEX</option>
									<option value="Direct">Direct</option>
									<option value="Other">Other</option>
								</select>
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Currency") }}</label>
								<input v-model="form.currency" type="text" class="form-control text-uppercase" placeholder="USD" />
							</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-6">
								<label class="form-label">{{ t("Publication Date") }}</label>
								<DateInput v-model="form.publication_date" />
							</div>
							<div class="col-6">
								<label class="form-label">{{ t("Submission Deadline") }}</label>
								<DateInput v-model="form.submission_deadline" />
							</div>
						</div>

						<div class="mb-3">
							<label class="form-label">{{ t("Estimated Total Value") }}</label>
							<MoneyInput v-model="form.estimated_total" :currency="form.currency" :language="user.language" />
						</div>

						<div v-if="initialLot" class="alert alert-info py-2 px-3 small mb-3">
							<i class="ti ti-link me-1"></i>
							{{ t("Unlinked lot {0} will be attached to this tender upon creation.", { 0: initialLot.name }) }}
						</div>

						<div class="d-flex justify-content-end gap-2 mt-4">
							<button type="button" class="btn btn-ghost-secondary" :disabled="saving" @click="close">
								{{ t("Cancel") }}
							</button>
							<button type="submit" class="btn btn-primary" :disabled="saving">
								<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
								{{ t("Save Tender") }}
							</button>
						</div>
					</form>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.modal-backdrop { opacity: 0.5; z-index: 1040; }
.ds-drawer { position: fixed; top: 0; right: 0; bottom: 0; z-index: 1050; width: 480px; max-width: 100vw; background: var(--stbl-surface, #fff); box-shadow: -4px 0 24px rgba(0,0,0,0.15); display: flex; flex-direction: column; }
.ds-drawer-dialog { height: 100%; display: flex; flex-direction: column; }
.ds-drawer-content { height: 100%; display: flex; flex-direction: column; }
.ds-drawer-header { padding: 16px 20px; border-bottom: 1px solid var(--stbl-border, #dbe1ea); display: flex; align-items: center; justify-content: space-between; }
.ds-drawer-title { font-size: 16px; font-weight: 700; margin: 0; }
.ds-drawer-body { padding: 20px; overflow-y: auto; flex: 1; }
</style>
