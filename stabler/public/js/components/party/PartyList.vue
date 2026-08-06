<script setup>
/**
 * Party Center — sol panel (master list).
 *
 * Bilerek `ListToolbar.vue` KULLANILMIYOR: bu panel ~22rem genişliğinde ve
 * ListToolbar geniş sayfa başlıkları için tasarlandı; burada satır satır
 * sarılıyor. Onun yerine dar panel varyantı: tek `ds-input` arama + segment
 * toggle'lar.
 *
 * Bileşen tamamen sunumsaldır: satırlar PartyCenter tarafından zenginleştirilmiş
 * (`balance`, `balanceCurrency`, `tooltip`, `title`, `code` …) olarak gelir.
 */
import SkeletonRows from "../SkeletonRows.vue";
import EmptyState from "../EmptyState.vue";
import PartyAvatar from "../PartyAvatar.vue";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	rows: { type: Array, default: () => [] },
	loading: { type: Boolean, default: false },
	error: { type: String, default: "" },
	selectedName: { type: String, default: "" },
	search: { type: String, default: "" },
	onlyWithBalance: { type: Boolean, default: false },
	onlyOverdue: { type: Boolean, default: false },
	filterGroup: { type: String, default: "" },
	filterTerritory: { type: String, default: "" },
	groupOptions: { type: Array, default: () => [] },
	territoryOptions: { type: Array, default: () => [] },
	sortField: { type: String, default: "name" },
	sortAsc: { type: Boolean, default: true },
	hierarchyEnabled: { type: Boolean, default: false },
	treeMode: { type: Boolean, default: false },
	expandedMap: { type: Object, default: () => ({}) },
	// Alt bilgi (footer)
	filteredCount: { type: Number, default: 0 },
	loadedCount: { type: Number, default: 0 },
	totalCount: { type: Number, default: 0 },
	truncated: { type: Boolean, default: false },
	visibleTotals: { type: Array, default: () => [] },
	grandTotals: { type: Array, default: () => [] },
	showGrandTotals: { type: Boolean, default: false },
	language: { type: String, default: "" },
	labels: { type: Object, default: () => ({}) },
});

const emit = defineEmits([
	"update:search",
	"update:onlyWithBalance",
	"update:onlyOverdue",
	"update:filterGroup",
	"update:filterTerritory",
	"search-input",
	"sort",
	"toggle-view",
	"toggle-expand",
	"select",
	"create",
]);

function balanceTone(v) {
	if (Number(v) > 0) return "pc-pos";
	if (Number(v) < 0) return "pc-neg";
	return "pc-zero";
}
</script>

<template>
	<div class="pc-list">
		<div class="pc-list-head">
			<div class="pc-search">
				<i class="ti ti-search pc-search-icon"></i>
				<input
					:value="props.search"
					type="search"
					class="ds-input pc-search-input"
					:placeholder="props.labels.searchPlaceholder || t('Search… ⌘K')"
					@input="emit('update:search', $event.target.value); emit('search-input')"
				/>
			</div>
			<button
				v-if="props.hierarchyEnabled"
				type="button"
				class="ds-btn pc-icon-btn"
				:title="props.treeMode ? t('Flat view') : t('Tree view')"
				@click="emit('toggle-view')"
			>
				<i class="ti" :class="props.treeMode ? 'ti-list' : 'ti-sitemap'"></i>
			</button>
			<button type="button" class="ds-btn ds-btn--primary pc-new-btn" @click="emit('create')">
				<i class="ti ti-plus"></i><span class="pc-new-txt">{{ t("New") }}</span>
			</button>
		</div>

		<div class="pc-filters">
			<select
				v-if="props.groupOptions.length"
				class="ds-input pc-select"
				:value="props.filterGroup"
				:aria-label="props.labels.groupLabel || t('Group')"
				@change="emit('update:filterGroup', $event.target.value)"
			>
				<option value="">{{ props.labels.allGroups || t("All groups") }}</option>
				<option v-for="g in props.groupOptions" :key="g" :value="g">{{ g }}</option>
			</select>
			<select
				v-if="props.territoryOptions.length"
				class="ds-input pc-select"
				:value="props.filterTerritory"
				:aria-label="t('Territory')"
				@change="emit('update:filterTerritory', $event.target.value)"
			>
				<option value="">{{ props.labels.allTerritories || t("All territories") }}</option>
				<option v-for="tr in props.territoryOptions" :key="tr" :value="tr">{{ tr }}</option>
			</select>
			<div class="ds-seg pc-seg">
				<button
					type="button"
					:aria-pressed="props.onlyWithBalance ? 'true' : 'false'"
					@click="emit('update:onlyWithBalance', !props.onlyWithBalance)"
				>
					{{ t("Only with balance") }}
				</button>
				<button
					type="button"
					:aria-pressed="props.onlyOverdue ? 'true' : 'false'"
					@click="emit('update:onlyOverdue', !props.onlyOverdue)"
				>
					{{ t("Overdue only") }}
				</button>
			</div>
		</div>

		<div class="pc-list-scroll">
			<table v-if="props.loading" class="ds-table pc-table">
				<SkeletonRows :rows="8" :cols="2" />
			</table>
			<div v-else-if="props.error" class="pc-error">{{ props.error }}</div>
			<EmptyState
				v-else-if="!props.rows.length"
				icon="ti-users"
				accentIcon="ti-user-plus"
				tone="purple"
				:title="props.labels.emptyTitle || t('No records')"
				:subtitle="props.labels.emptySubtitle || ''"
			>
				<template #actions>
					<button type="button" class="ds-btn" @click="emit('create')">
						<i class="ti ti-plus"></i>{{ props.labels.emptyAction || t("New") }}
					</button>
				</template>
			</EmptyState>
			<table v-else class="ds-table pc-table">
				<thead>
					<tr>
						<th class="pc-sortable" @click="emit('sort', 'name')">
							{{ t("Name") }}
							<i v-if="props.sortField === 'name'" :class="props.sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
						</th>
						<th class="ds-td-num pc-sortable" @click="emit('sort', 'balance')">
							{{ t("Balance") }}
							<i v-if="props.sortField === 'balance'" :class="props.sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
						</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="row in props.rows"
						:key="row.key"
						class="pc-row"
						:class="{ 'pc-row-active': props.selectedName === row.name, 'pc-row-child': row.level === 1 }"
						@click="emit('select', row.raw)"
					>
						<td>
							<div class="pc-name" :class="{ 'pc-name-indent': row.level === 1 }">
								<button
									v-if="row.isParent"
									type="button"
									class="pc-chevron"
									:title="props.expandedMap[row.name] ? t('Collapse') : t('Expand')"
									@click.stop="emit('toggle-expand', row.name)"
								>
									<i class="ti" :class="props.expandedMap[row.name] ? 'ti-chevron-down' : 'ti-chevron-right'"></i>
								</button>
								<span v-else-if="row.level === 1" class="pc-tree-line"></span>
								<PartyAvatar :name="row.title" size="sm" class="flex-shrink-0" />
								<div class="pc-name-text">
									<div class="pc-title" :class="{ 'pc-title-parent': row.isParent }">
										{{ row.title }}
										<span v-if="row.isParent" class="pc-count">{{ row.childCount }}</span>
									</div>
									<div v-if="row.parentLabel" class="pc-sub">
										<i class="ti ti-corner-down-right"></i> {{ row.parentLabel }}
									</div>
									<div v-else class="pc-sub pc-sub-mono">{{ row.code }}</div>
								</div>
							</div>
						</td>
						<td class="ds-td-num font-monospace">
							<span :class="balanceTone(row.balance)" :title="row.tooltip">
								{{ formatMoney(row.balance, row.balanceCurrency, props.language) }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<div v-if="props.rows.length" class="pc-list-foot">
			<div class="pc-foot-line">
				<span class="pc-label">{{ t("Visible") }} · {{ props.filteredCount }}</span>
				<span
					v-if="props.truncated"
					class="ds-chip"
					data-tone="soon"
					:title="t('The server returned a capped page; this total covers the rows loaded, not the whole book.')"
				>
					<i class="ti ti-alert-triangle"></i>{{ props.loadedCount }} / {{ props.totalCount }}
				</span>
			</div>
			<div v-for="b in props.visibleTotals" :key="b.currency" class="pc-foot-total">
				<span class="pc-cur">{{ b.currency }}</span>
				<span class="font-monospace pc-foot-amount">{{ formatMoney(b.amount, b.currency, props.language) }}</span>
			</div>
			<div v-if="!props.visibleTotals.length" class="pc-foot-empty">{{ t("No outstanding balance.") }}</div>
			<div v-if="props.showGrandTotals" class="pc-foot-grand">
				<div class="pc-label pc-foot-grand-head">
					{{ props.labels.grandTotalLabel || t("All records") }} · {{ props.totalCount }}
				</div>
				<div v-for="b in props.grandTotals" :key="'gt-' + b.currency" class="pc-foot-total">
					<span class="pc-cur">{{ b.currency }}</span>
					<span class="font-monospace pc-foot-amount">{{ formatMoney(b.amount, b.currency, props.language) }}</span>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.pc-list {
	display: flex;
	flex-direction: column;
	min-height: 0;
	height: 100%;
	background: #fff;
}

.pc-list-head {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 10px 12px;
	border-bottom: 1px solid #e3e5e8;
}
.pc-search {
	position: relative;
	flex: 1 1 auto;
	min-width: 0;
}
.pc-search-icon {
	position: absolute;
	left: 10px;
	top: 50%;
	transform: translateY(-50%);
	color: var(--tblr-gray-600, #667382);
	pointer-events: none;
}
.pc-search-input {
	padding-left: 30px;
}
.pc-icon-btn {
	flex: 0 0 auto;
	padding: 9px 11px;
}
.pc-new-btn {
	flex: 0 0 auto;
	display: inline-flex;
	align-items: center;
	gap: 6px;
}

.pc-filters {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	padding: 10px 12px;
	border-bottom: 1px solid #e3e5e8;
	background: #f6f8fb;
}
.pc-select {
	flex: 1 1 8rem;
	min-width: 0;
	min-height: 36px;
	padding: 6px 8px;
	font-size: 13px;
}
.pc-seg {
	flex: 1 1 100%;
}
.pc-seg button {
	flex: 1 1 0;
}

.pc-list-scroll {
	flex: 1 1 auto;
	min-height: 0;
	overflow-y: auto;
	overflow-x: hidden;
}
.pc-table {
	font-size: 13px;
}
.pc-table th,
.pc-table td {
	padding-left: 12px;
	padding-right: 12px;
}
/* Ad sütunu panele uyar, bakiye sütunu içeriği kadar yer alır. `max-width: 0`
   tam genişlikli bir tabloda hücreyi büzülebilir yapar — ancak o zaman
   içerideki `.pc-title` / `.pc-sub` ellipsis'i devreye girer, aksi halde uzun
   müşteri adları paneli yatayda taşırır. */
.pc-table th:first-child,
.pc-table td:first-child {
	width: 100%;
	max-width: 0;
}
.pc-table th:last-child,
.pc-table td:last-child {
	width: 1%;
	white-space: nowrap;
}
.pc-table td:last-child {
	font-size: 12px;
}
.pc-table th {
	position: sticky;
	top: 0;
	z-index: 1;
	background: #fff;
}
.pc-sortable {
	cursor: pointer;
	user-select: none;
}
.pc-row {
	cursor: pointer;
}
.pc-row-active {
	background: #eef4ff;
	box-shadow: inset 3px 0 0 #206bc4;
}
.pc-row-child {
	background: #fcfcfd;
}
.pc-name {
	display: flex;
	align-items: center;
	gap: 6px;
	min-width: 0;
}
.pc-name-indent {
	padding-left: 1.25rem;
}
.pc-name-text {
	min-width: 0;
}
.pc-title {
	font-weight: 600;
	color: #1d273b;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.pc-title-parent {
	font-weight: 700;
}
.pc-count {
	display: inline-block;
	margin-left: 4px;
	padding: 0 5px;
	font-family: var(--ds-mono, monospace);
	font-size: 11px;
	font-weight: 600;
	color: var(--tblr-gray-600, #667382);
	background: #eef0f3;
}
.pc-sub {
	font-size: 11.5px;
	color: var(--tblr-gray-600, #667382);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.pc-sub-mono {
	font-family: var(--ds-mono, monospace);
}
.pc-chevron {
	flex: 0 0 auto;
	width: 20px;
	height: 20px;
	line-height: 1;
	padding: 0;
	border: 0;
	background: transparent;
	color: var(--tblr-gray-600, #667382);
	cursor: pointer;
}
.pc-tree-line {
	display: inline-block;
	flex: 0 0 auto;
	width: 1.1rem;
	height: 0.85rem;
	margin-right: 0.1rem;
	border-left: 2px solid #e3e5e8;
	border-bottom: 2px solid #e3e5e8;
}
.pc-pos {
	color: #1c7a3a;
}
.pc-neg {
	color: #b32424;
}
.pc-zero {
	color: var(--tblr-gray-600, #667382);
}

.pc-error {
	margin: 12px;
	padding: 10px 12px;
	border: 1px solid #d63939;
	color: #b32424;
	font-size: 13px;
}

.pc-list-foot {
	flex: 0 0 auto;
	padding: 12px;
	border-top: 2px solid rgba(29, 39, 59, 0.32);
	background: #f6f8fb;
}
.pc-foot-line {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 8px;
	margin-bottom: 6px;
}
.pc-foot-total {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 8px;
	padding: 2px 0;
}
.pc-cur {
	font-family: var(--ds-mono, monospace);
	font-size: 11px;
	letter-spacing: 0.08em;
	color: var(--tblr-gray-600, #667382);
}
.pc-foot-amount {
	font-weight: 700;
	font-variant-numeric: tabular-nums;
	color: #1d273b;
}
.pc-foot-empty {
	font-size: 12.5px;
	color: var(--tblr-gray-600, #667382);
}
.pc-foot-grand {
	margin-top: 8px;
	padding-top: 8px;
	border-top: 1px solid #e3e5e8;
}
.pc-foot-grand-head {
	margin-bottom: 4px;
}

/* Mikro etiket. `.ds-label` modernist katmanda ÇEVRİLMEYEN teknik kimlikler
   (para birimi kodu, doctype adı) için ayrılmıştır; kullanıcıya dönük çevrili
   etiketler aynı tipografiyi buradan alır, tonu AA'ya çekilir (#9099a6 değil).
   Global sayfa DEĞİŞTİRİLMİYOR. */
.pc-label {
	font-family: var(--ds-mono);
	font-size: 10px;
	letter-spacing: 0.14em;
	text-transform: uppercase;
	color: var(--tblr-gray-600, #667382);
}
</style>
