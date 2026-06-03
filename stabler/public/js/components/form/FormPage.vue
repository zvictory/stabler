<script setup>
/**
 * FormPage — shared full-page document scaffold.
 *
 * Replaces the Bootstrap modal (create) + offcanvas drawer (view) pattern
 * with a routed full-page card that works for any transactional doctype.
 *
 * Props:
 *   title      — page heading (e.g. "Sales Order")
 *   docName    — document name shown below title (null when creating)
 *   status     — ERPNext status string (e.g. "To Deliver and Bill")
 *   docstatus  — numeric docstatus (0 draft, 1 submitted, 2 cancelled)
 *   loading    — show full-card spinner
 *   error      — show full-card error alert
 *
 * Slots:
 *   default   — the field grid / form body
 *   actions   — action buttons; renders in a sticky card-footer
 */
import { computed } from "vue";
import { useRouter } from "vue-router";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	title: { type: String, required: true },
	docName: { type: String, default: null },
	status: { type: String, default: null },
	docstatus: { type: Number, default: null },
	loading: { type: Boolean, default: false },
	error: { type: String, default: "" },
	backPath: { type: String, default: null },
});

const router = useRouter();

function goBack() {
	if (props.backPath) {
		router.push(props.backPath);
	} else {
		router.back();
	}
}

const STATUS_BADGE = {
	Draft: "bg-secondary-lt",
	"To Deliver and Bill": "bg-yellow-lt",
	"To Bill": "bg-orange-lt",
	"To Deliver": "bg-blue-lt",
	Completed: "bg-green-lt",
	Cancelled: "bg-red-lt",
	Closed: "bg-secondary-lt",
	"On Hold": "bg-purple-lt",
	"Partly Billed": "bg-orange-lt",
	"Return Issued": "bg-red-lt",
	"To Receive and Bill": "bg-yellow-lt",
	"To Receive": "bg-blue-lt",
	Submitted: "bg-green-lt",
	// Sales / Purchase Invoice statuses
	Paid: "bg-green-lt",
	Unpaid: "bg-yellow-lt",
	Overdue: "bg-red-lt",
	"Partly Paid": "bg-blue-lt",
	"Unpaid and Discounted": "bg-yellow-lt",
	Return: "bg-secondary-lt",
	"Credit Note Issued": "bg-purple-lt",
	"Debit Note Issued": "bg-purple-lt",
};

const badgeClass = computed(() => STATUS_BADGE[props.status] || "bg-secondary-lt");
</script>

<template>
	<div v-if="loading" class="card">
		<div class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
	</div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
	<template v-else>
		<div class="card">
			<div class="card-header">
				<div class="d-flex align-items-center gap-3 flex-wrap">
					<button
						type="button"
						class="btn btn-outline-secondary btn-sm"
						@click="goBack"
					>
						<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
					</button>
					<div>
						<h3 class="card-title mb-0">{{ title }}</h3>
						<div v-if="docName" class="text-secondary small font-monospace mt-0">
							{{ docName }}
						</div>
					</div>
					<div class="ms-auto d-flex align-items-center gap-2">
						<span v-if="status" class="badge" :class="badgeClass">
							{{ t(status) }}
						</span>
					</div>
				</div>
			</div>

			<div class="card-body">
				<slot />
			</div>

			<div
				v-if="$slots.actions"
				class="card-footer d-flex gap-2 flex-wrap align-items-center"
				style="position: sticky; bottom: 0; z-index: 10; background: var(--tblr-card-bg, #fff)"
			>
				<slot name="actions" />
			</div>
		</div>
	</template>
</template>
