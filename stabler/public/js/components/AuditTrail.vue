<script setup>
// Reusable, read-only "who changed what, when" drawer for any document.
// Usage:
//   <AuditTrail :open="auditOpen" :doctype="'Payment Entry'" :name="row.name"
//               @close="auditOpen = false" />
import { ref, watch } from "vue";
import { call } from "../api/client.js";
import { formatDateTime } from "../composables/date.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	open: { type: Boolean, default: false },
	doctype: { type: String, default: "" },
	name: { type: String, default: "" },
});
const emit = defineEmits(["close"]);

const loading = ref(false);
const error = ref("");
const events = ref([]);

// Visual treatment per event type.
const STYLE = {
	create: { icon: "ti-plus", cls: "bg-blue-lt text-blue", label: t("Created") },
	edit: { icon: "ti-pencil", cls: "bg-secondary-lt", label: t("Edited") },
	submit: { icon: "ti-circle-check", cls: "bg-green-lt text-green", label: t("Submitted") },
	cancel: { icon: "ti-ban", cls: "bg-red-lt text-red", label: t("Cancelled") },
	comment: { icon: "ti-message-2", cls: "bg-azure-lt", label: t("Comment") },
	approval_requested: { icon: "ti-send", cls: "bg-yellow-lt text-yellow", label: t("Submitted for approval") },
	approved: { icon: "ti-checks", cls: "bg-green-lt text-green", label: t("Approved") },
	rejected: { icon: "ti-x", cls: "bg-red-lt text-red", label: t("Rejected") },
};
function style(type) {
	return STYLE[type] || STYLE.edit;
}

async function load() {
	if (!props.doctype || !props.name) return;
	loading.value = true;
	error.value = "";
	events.value = [];
	try {
		const res = await call("stabler.api.audit.document_history", {
			doctype: props.doctype,
			name: props.name,
		});
		events.value = res.events || [];
	} catch (e) {
		error.value = e?.message || String(e);
	} finally {
		loading.value = false;
	}
}

watch(
	() => [props.open, props.doctype, props.name],
	() => {
		if (props.open) load();
	},
	{ immediate: true },
);
</script>

<template>
	<div v-if="open" class="offcanvas-backdrop fade show" @click="emit('close')"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: open }"
		tabindex="-1"
		style="visibility: visible; width: 480px"
		:style="{ transform: open ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<div>
				<h5 class="offcanvas-title mb-0">{{ t("Audit trail") }}</h5>
				<div class="text-secondary small font-monospace">{{ t(doctype) }} · {{ name }}</div>
			</div>
			<button type="button" class="btn-close" :aria-label="t('Close')" @click="emit('close')"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="loading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
			<div v-else-if="events.length === 0" class="text-secondary text-center py-5">
				{{ t("No recorded history for this document.") }}
			</div>

			<ul v-else class="list-unstyled mb-0">
				<li v-for="(ev, i) in events" :key="i" class="d-flex gap-2 pb-3">
					<div class="text-center" style="width: 28px">
						<span class="avatar avatar-xs rounded" :class="style(ev.type).cls">
							<i class="ti" :class="style(ev.type).icon"></i>
						</span>
						<div v-if="i < events.length - 1" class="mx-auto" style="width: 2px; height: 100%; min-height: 16px; background: var(--tblr-border-color)"></div>
					</div>
					<div class="flex-fill">
						<div class="d-flex justify-content-between align-items-baseline">
							<strong class="small">{{ ev.summary }}</strong>
							<span class="text-secondary" style="font-size: 0.72rem">{{ formatDateTime(ev.timestamp) }}</span>
						</div>
						<div class="text-secondary small">{{ ev.user_name || ev.user }}</div>
						<table v-if="ev.changes && ev.changes.length" class="table-no-stripe mt-1" style="font-size: 0.74rem">
							<tbody>
								<tr v-for="(c, j) in ev.changes" :key="j">
									<td class="text-secondary pe-2">{{ c.label }}</td>
									<td class="text-secondary text-decoration-line-through pe-1">{{ c.from }}</td>
									<td class="pe-1"><i class="ti ti-arrow-right text-secondary"></i></td>
									<td class="fw-medium">{{ c.to }}</td>
								</tr>
							</tbody>
						</table>
						<div v-else-if="ev.child_changes" class="text-secondary small fst-italic">
							{{ t("{0} line item change(s)").replace("{0}", ev.child_changes) }}
						</div>
					</div>
				</li>
			</ul>
		</div>
	</div>
</template>
