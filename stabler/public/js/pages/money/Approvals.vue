<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import AuditTrail from "../../components/AuditTrail.vue";

const session = useSession();
const { activeCompany, language } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();

// "pending" = the reviewer queue; "mine" = requests this user raised.
const tab = ref("pending");
const canApprove = ref(false);
const loading = ref(false);
const error = ref("");
const search = ref("");
const rows = ref([]);
const busy = ref("");
const trail = ref({ open: false, doctype: "", name: "" });

// Tracks in-session partial-approval state keyed by request name.
// Shape: { [name]: { next_required_level: int, tier_approvals: [{level, approver}] } }
// Populated from approve() responses when fully_approved === false.
// Cleared on full load() to stay in sync with server state.
const partialState = ref({});

function showHistory(r) {
	trail.value = { open: true, doctype: r.reference_doctype, name: r.reference_name };
}

const lang = computed(() => language.value || "en");

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.title, r.party_label, r.reference_name, r.requested_by, r.reference_doctype]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

function money(r) {
	return formatMoney(r.amount || 0, r.currency || "UZS", lang.value);
}

// Returns the in-session partial state for a row, or null.
function partial(r) {
	return partialState.value[r.name] || null;
}

// True when the row is in a tiered flow and has been partially approved
// in this session (fully_approved came back false from a previous approve call).
function isPartiallyApproved(r) {
	return !!partial(r);
}

// The level to pass to approve() for a given row.
// For rows that returned next_required_level we use that; otherwise null (single-level).
function nextLevelFor(r) {
	const p = partial(r);
	return p ? p.next_required_level : null;
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		if (tab.value === "pending") {
			const res = await call("stabler.api.approvals.list_pending", {
				company: activeCompany.value || undefined,
				limit: 200,
			});
			rows.value = res.requests || [];
			canApprove.value = !!res.can_approve;
		} else {
			const res = await call("stabler.api.approvals.my_requests", {
				company: activeCompany.value || undefined,
				limit: 200,
			});
			rows.value = res.requests || [];
		}
		// Hydrate tier state from the server so multi-level progress shows on a
		// fresh load (not only within the session that performed an approval).
		const seeded = {};
		for (const r of rows.value) {
			if (r.multi_level && r.next_required_level != null) {
				seeded[r.name] = {
					next_required_level: r.next_required_level,
					tier_approvals: r.tier_approvals || [],
				};
			}
		}
		partialState.value = seeded;
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

async function approve(r) {
	const nextLevel = nextLevelFor(r);
	const isMultiLevel = isPartiallyApproved(r) || nextLevel !== null;

	// Confirm dialog text varies for partial (subsequent-tier) vs first approval.
	const confirmTitle = isPartiallyApproved(r)
		? t("Approve level {0}").replace("{0}", String(nextLevel))
		: t("Approve and post");
	const confirmBody = isPartiallyApproved(r)
		? t("This will record your level {0} approval for {1} {2}.").
			replace("{0}", String(nextLevel)).replace("{1}", t(r.reference_doctype)).replace("{2}", r.reference_name)
		: t("This will post {0} {1}. The action is recorded against your name.").
			replace("{0}", t(r.reference_doctype)).replace("{1}", r.reference_name);
	const confirmLabel = isPartiallyApproved(r)
		? t("Approve level {0}").replace("{0}", String(nextLevel))
		: t("Approve & post");

	const ok = await confirm({ title: confirmTitle, body: confirmBody, confirmLabel });
	if (!ok) return;
	busy.value = r.name;
	try {
		const params = { name: r.name };
		if (nextLevel !== null) params.level = nextLevel;

		const res = await call("stabler.api.approvals.approve", params);

		if (res && res.multi_level === true && res.fully_approved === false) {
			// Partial approval: keep the row in the queue and update local state.
			const nxt = res.next_required_level;
			// Record this approval tier in local state.
			const existing = partial(r);
			const prevTiers = existing ? existing.tier_approvals : [];
			if (nextLevel !== null) {
				prevTiers.push({ level: nextLevel, approver: t("You") });
			}
			partialState.value = {
				...partialState.value,
				[r.name]: { next_required_level: nxt, tier_approvals: prevTiers },
			};
			toast.success(
				t("Level {0} approved — awaiting level {1}.").
					replace("{0}", String(nextLevel ?? "")).replace("{1}", String(nxt)),
			);
		} else {
			// Fully approved (single-level or final tier): remove from queue.
			toast.success(t("Approved and posted."));
			await load();
		}
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

async function reject(r) {
	const ok = await confirm({
		title: t("Reject request"),
		body: t("Reject this request? The draft is left untouched for the maker to fix or delete."),
		danger: true,
		confirmLabel: t("Reject"),
	});
	if (!ok) return;
	busy.value = r.name;
	try {
		await call("stabler.api.approvals.reject", { name: r.name });
		toast.success(t("Request rejected."));
		await load();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}

watch(tab, load);
watch(activeCompany, load);
onMounted(load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Document, party or requester…') + '  ⌘K'"
			:count="filteredRows.length"
		>
			<template #filters>
				<div class="btn-group" role="group">
					<button
						type="button"
						class="btn btn-sm"
						:class="tab === 'pending' ? 'btn-primary' : 'btn-outline-secondary'"
						@click="tab = 'pending'"
					>
						<i class="ti ti-inbox me-1"></i>{{ t("Pending approvals") }}
					</button>
					<button
						type="button"
						class="btn btn-sm"
						:class="tab === 'mine' ? 'btn-primary' : 'btn-outline-secondary'"
						@click="tab = 'mine'"
					>
						<i class="ti ti-user-check me-1"></i>{{ t("My requests") }}
					</button>
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Document") }}</th>
						<th>{{ t("Party") }}</th>
						<th class="text-end">{{ t("Amount") }}</th>
						<th>{{ tab === "pending" ? t("Requested by") : t("Status") }}</th>
						<th>{{ tab === "pending" ? t("Requested") : t("Reviewed by") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="6" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name">
						<td>
							<div class="fw-medium">{{ r.title || r.reference_name }}</div>
							<div class="text-secondary small">
								{{ t(r.reference_doctype) }} · {{ r.reference_name }}
							</div>
							<!-- Partial-approval tier progress (only shown while in-session state exists) -->
							<template v-if="tab === 'pending' && isPartiallyApproved(r)">
								<div class="mt-1">
									<!-- Completed tiers -->
									<span
										v-for="tier in partial(r).tier_approvals"
										:key="tier.level"
										class="badge bg-success-subtle text-success me-1"
									>
										<i class="ti ti-check me-1"></i>{{ t("Level {0}").replace("{0}", String(tier.level)) }}
									</span>
									<!-- Next required tier -->
									<span class="badge bg-warning-subtle text-warning">
										<i class="ti ti-clock me-1"></i>{{ t("Awaiting level {0}").replace("{0}", String(partial(r).next_required_level)) }}
									</span>
								</div>
							</template>
						</td>
						<td>{{ r.party_label || "—" }}</td>
						<td class="text-end font-monospace">{{ money(r) }}</td>
						<td>
							<template v-if="tab === 'pending'">
								<div>{{ r.requested_by }}</div>
								<!-- Partial-approval status note -->
								<div v-if="isPartiallyApproved(r)" class="text-warning small mt-1">
									{{ t("Partially approved — awaiting level {0}").replace("{0}", String(partial(r).next_required_level)) }}
								</div>
							</template>
							<span v-else class="badge" :class="getStatusBadgeClass('Stabler Approval Request', r.status)">
								{{ t(r.status) }}
							</span>
						</td>
						<td class="text-secondary small">
							<template v-if="tab === 'pending'">{{ formatDateTime(r.requested_at) }}</template>
							<template v-else>{{ r.reviewed_by || "—" }}</template>
						</td>
						<td class="text-end">
							<div class="btn-list justify-content-end">
								<button
									class="btn btn-sm btn-ghost-secondary"
									:title="t('Audit trail')"
									@click="showHistory(r)"
								>
									<i class="ti ti-history"></i>
								</button>
								<template v-if="tab === 'pending'">
									<button
										class="btn btn-sm btn-outline-secondary"
										:disabled="busy === r.name"
										@click="reject(r)"
									>
										{{ t("Reject") }}
									</button>
									<button
										class="btn btn-sm btn-success"
										:disabled="busy === r.name || r.self_made"
										:title="r.self_made ? t('You raised this — another user must approve it.') : ''"
										@click="approve(r)"
									>
										<i class="ti ti-check me-1"></i>
										<template v-if="isPartiallyApproved(r)">
											{{ t("Approve level {0}").replace("{0}", String(partial(r).next_required_level)) }}
										</template>
										<template v-else>{{ t("Approve") }}</template>
									</button>
								</template>
								<span v-else-if="r.review_note" class="text-secondary small">{{ r.review_note }}</span>
							</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-checklist"
			:title="tab === 'pending' ? t('No payments waiting for approval') : t('You have no approval requests')"
			:subtitle="tab === 'pending'
				? t('When someone submits a payment that needs review, it appears here.')
				: t('Payments you submit that need a second approver will show here.')"
		/>

		<AuditTrail
			:open="trail.open"
			:doctype="trail.doctype"
			:name="trail.name"
			@close="trail.open = false"
		/>
	</div>
</template>
