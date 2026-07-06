<script setup>
/**
 * MultiSelectPicker — a searchable modal multi-select.
 *
 * Drop-in for MultiSelect.vue (same props/emits): the trigger is a compact
 * summary field; clicking opens a popup where the user searches by NAME or CODE,
 * ticks rows (name primary + code secondary/mono), and Applies. Selection is a
 * plain array of ids (matches the backend `_in_clause` contract).
 */
import { ref, reactive, computed, watch, nextTick, onBeforeUnmount } from "vue";
import { call } from "../api/client.js";
import { t } from "../composables/i18n.js";

const props = defineProps({
	modelValue: { type: Array, default: () => [] },
	searchApi: { type: String, required: true },
	extraParams: { type: Object, default: () => ({}) },
	idKey: { type: String, default: "name" }, // the "code" field (e.g. CUST10564)
	display: { type: Function, required: true }, // (row) => name string
	placeholder: { type: String, default: "" },
	title: { type: String, default: "" },
	size: { type: String, default: "md" },
});
const emit = defineEmits(["update:modelValue"]);

// id -> { label, code } cache so chips/selection survive across searches.
const labels = reactive({});
function cache(item) {
	const id = String(item[props.idKey]);
	labels[id] = { label: props.display(item), code: String(item[props.idKey]) };
}

const open = ref(false);
const query = ref("");
const results = ref([]);
const loading = ref(false);
const draftIds = ref([]); // working selection while the modal is open
const searchInput = ref(null);

const selectedChips = computed(() =>
	(props.modelValue || []).map((id) => ({ id, label: labels[id]?.label || String(id) }))
);
const draftChips = computed(() =>
	draftIds.value.map((id) => ({ id, label: labels[id]?.label || String(id), code: labels[id]?.code || "" }))
);
const triggerClass = computed(() => ["ms-trigger", props.size === "sm" ? "form-control-sm" : ""]);

let timer = null;
async function runSearch(q) {
	loading.value = true;
	try {
		const rows = await call(props.searchApi, { ...props.extraParams, search: q, limit: 50 });
		results.value = Array.isArray(rows) ? rows : [];
		results.value.forEach(cache);
	} catch {
		results.value = [];
	} finally {
		loading.value = false;
	}
}
function onSearch() {
	if (timer) clearTimeout(timer);
	timer = setTimeout(() => runSearch(query.value.trim()), 200);
}

function openModal() {
	draftIds.value = (props.modelValue || []).map(String);
	query.value = "";
	results.value = [];
	open.value = true;
	runSearch(""); // initial: top results
	nextTick(() => searchInput.value?.focus());
}
function isChecked(item) {
	return draftIds.value.includes(String(item[props.idKey]));
}
function toggle(item) {
	cache(item);
	const id = String(item[props.idKey]);
	draftIds.value = draftIds.value.includes(id)
		? draftIds.value.filter((x) => x !== id)
		: [...draftIds.value, id];
}
function removeDraft(id) {
	draftIds.value = draftIds.value.filter((x) => String(x) !== String(id));
}
function selectAllFiltered() {
	const add = results.value.map((r) => String(r[props.idKey]));
	draftIds.value = Array.from(new Set([...draftIds.value, ...add]));
}
function clearDraft() {
	draftIds.value = [];
}
function apply() {
	emit("update:modelValue", [...draftIds.value]);
	open.value = false;
}
function cancel() {
	open.value = false;
}
function clearTrigger() {
	emit("update:modelValue", []);
}

function onKeydown(e) {
	if (e.key === "Escape") cancel();
}
watch(open, (v) => {
	if (v) document.addEventListener("keydown", onKeydown);
	else document.removeEventListener("keydown", onKeydown);
});
onBeforeUnmount(() => {
	document.removeEventListener("keydown", onKeydown);
	if (timer) clearTimeout(timer);
});
</script>

<template>
	<div class="ms-picker">
		<!-- Trigger -->
		<button type="button" :class="triggerClass" @click="openModal">
			<template v-if="selectedChips.length">
				<span class="badge bg-blue-lt text-truncate" style="max-width: 9rem">{{ selectedChips[0].label }}</span>
				<span v-if="selectedChips.length > 1" class="badge bg-secondary-lt">+{{ selectedChips.length - 1 }}</span>
			</template>
			<span v-else class="text-secondary text-truncate">{{ placeholder }}</span>
			<span class="ms-trigger-actions">
				<i v-if="selectedChips.length" class="ti ti-x ms-clear" :title="t('Clear')" @click.stop="clearTrigger"></i>
				<i class="ti ti-selector text-secondary"></i>
			</span>
		</button>

		<!-- Modal -->
		<Teleport to="body">
			<div v-if="open" class="modal fade show d-block" tabindex="-1" style="background: rgba(15,23,42,.5)" @click.self="cancel">
				<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable" style="max-width: 560px">
					<div class="modal-content">
						<div class="modal-header py-2 px-3">
							<h3 class="modal-title d-flex align-items-center gap-2">
								{{ title || t("Select") }}
								<span v-if="draftIds.length" class="badge bg-blue-lt">{{ draftIds.length }}</span>
							</h3>
							<button type="button" class="btn-close" @click="cancel"></button>
						</div>

						<div class="px-3 pt-2">
							<div class="input-group input-group-sm">
								<span class="input-group-text"><i class="ti ti-search"></i></span>
								<input
									ref="searchInput"
									v-model="query"
									type="text"
									class="form-control"
									:placeholder="t('Search by name or code…')"
									@input="onSearch"
								/>
							</div>
							<!-- Selected chips (persist across searches) -->
							<div v-if="draftChips.length" class="d-flex flex-wrap gap-1 mt-2">
								<span v-for="c in draftChips" :key="c.id" class="badge bg-blue-lt d-inline-flex align-items-center gap-1">
									<span class="text-truncate" style="max-width: 12rem">{{ c.label }}</span>
									<button type="button" class="btn-close btn-close-sm" style="font-size: .5rem" @click="removeDraft(c.id)"></button>
								</span>
							</div>
							<div class="d-flex align-items-center justify-content-between mt-2 small">
								<button type="button" class="btn btn-link btn-sm p-0" :disabled="!results.length" @click="selectAllFiltered">
									<i class="ti ti-checks me-1"></i>{{ t("Select all") }}
								</button>
								<button type="button" class="btn btn-link btn-sm p-0 text-secondary" :disabled="!draftIds.length" @click="clearDraft">
									{{ t("Clear") }}
								</button>
							</div>
						</div>

						<div class="modal-body pt-2">
							<div v-if="loading" class="text-center text-secondary py-4">
								<span class="spinner-border spinner-border-sm me-1"></span>{{ t("Searching…") }}
							</div>
							<div v-else-if="!results.length" class="text-center text-secondary py-4">{{ t("No matches found") }}</div>
							<div v-else class="ms-list">
								<button
									v-for="item in results"
									:key="item[idKey]"
									type="button"
									class="ms-row"
									:class="{ selected: isChecked(item) }"
									@click="toggle(item)"
								>
									<span class="ms-check"><i v-if="isChecked(item)" class="ti ti-check"></i></span>
									<span class="ms-text">
										<span class="ms-name text-truncate">{{ display(item) }}</span>
										<span class="ms-code font-monospace text-secondary">{{ item[idKey] }}</span>
									</span>
								</button>
							</div>
						</div>

						<div class="modal-footer py-2 px-3">
							<button type="button" class="btn btn-outline-secondary btn-sm" @click="cancel">{{ t("Cancel") }}</button>
							<button type="button" class="btn btn-primary btn-sm" @click="apply">
								{{ t("Apply") }}<span v-if="draftIds.length"> ({{ draftIds.length }})</span>
							</button>
						</div>
					</div>
				</div>
			</div>
		</Teleport>
	</div>
</template>

<style scoped>
.ms-trigger {
	display: flex;
	align-items: center;
	gap: 0.25rem;
	width: 100%;
	min-height: 2rem;
	padding: 0.25rem 0.5rem;
	background: var(--stbl-surface, #fff);
	border: 1px solid var(--stbl-border, #dbe1ea);
	border-radius: 6px;
	text-align: left;
	cursor: pointer;
	font-size: 0.875rem;
}
.ms-trigger:hover { border-color: var(--stbl-primary, #2f6df6); }
.ms-trigger-actions { margin-left: auto; display: inline-flex; align-items: center; gap: 0.25rem; }
.ms-clear { color: var(--stbl-text-secondary, #6a7690); cursor: pointer; border-radius: 4px; }
.ms-clear:hover { color: var(--stbl-danger, #d3453f); background: rgba(211,69,63,.1); }
.ms-list { display: flex; flex-direction: column; }
.ms-row {
	display: flex;
	align-items: center;
	gap: 0.6rem;
	width: 100%;
	padding: 0.45rem 0.5rem;
	border: 0;
	border-radius: 8px;
	background: transparent;
	text-align: left;
	cursor: pointer;
}
.ms-row:hover { background: var(--stbl-surface-2, #f6f8fb); }
.ms-row.selected { background: rgba(47,109,246,.08); }
.ms-check {
	flex: none;
	width: 20px; height: 20px;
	border: 1.5px solid var(--stbl-border, #cdd5e1);
	border-radius: 6px;
	display: grid; place-items: center;
	font-size: 13px; color: #fff;
}
.ms-row.selected .ms-check { background: var(--stbl-primary, #2f6df6); border-color: var(--stbl-primary, #2f6df6); }
.ms-text { display: flex; flex-direction: column; min-width: 0; line-height: 1.25; }
.ms-name { font-weight: 500; }
.ms-code { font-size: 0.72rem; }
</style>
