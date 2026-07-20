<script setup>
/**
 * StatusBadge — the single status-badge renderer for the SPA (WP-103).
 *
 * Global rule (project CLAUDE.md, "Centralized status codes"): every status
 * badge/label is resolved centrally via `getStatusBadgeClass` /
 * `getDocstatusLabel` from composables/status.js. Per-page status→color maps
 * are FORBIDDEN. This component is the shared wrapper that enforces that.
 *
 * Contract:
 *   - String status:  <StatusBadge doctype="EHF Status" :status="row.status" />
 *       cls   = getStatusBadgeClass(doctype, status)  (STATUS_MAP[doctype][status])
 *       label = t(status)
 *   - Numeric docstatus: <StatusBadge doctype="Sales Invoice" :docstatus="d.docstatus" />
 *       cls   = getStatusBadgeClass(doctype, docstatus)  (STATUS_MAP.docstatus[n])
 *       label = getDocstatusLabel(docstatus)  ("Draft" / "Submitted" / "Cancelled")
 *   - Unknown status falls back to "bg-secondary-lt"; in DEV a console.warn
 *     flags the missing STATUS_MAP entry so gaps surface during development
 *     without leaking logs into the production bundle.
 */
import { computed } from "vue";
import { t } from "../composables/i18n.js";
import {
	STATUS_MAP,
	getStatusBadgeClass,
	getDocstatusLabel,
} from "../composables/status.js";

const props = defineProps({
	doctype: { type: String, required: true },
	status: { type: String, default: "" },
	docstatus: { type: Number, default: null },
});

const cls = computed(() => {
	if (props.status) {
		if (import.meta.env?.DEV) {
			const map = STATUS_MAP[props.doctype];
			if (!map || !(props.status in map)) {
				console.warn("STATUS_MAP missing:", props.doctype, props.status);
			}
		}
		return getStatusBadgeClass(props.doctype, props.status);
	}
	return getStatusBadgeClass(props.doctype, props.docstatus);
});

const label = computed(() =>
	props.status ? t(props.status) : getDocstatusLabel(props.docstatus)
);
</script>

<template>
	<span class="badge" :class="cls">{{ label }}</span>
</template>
