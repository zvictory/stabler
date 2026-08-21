/**
 * Live UAT — Tender CRM full CRUD on mikas (production).
 *
 * Scenario A (handoff): Create → Read → Edit → Delete a brand-new tender deal.
 *   A freshly created deal has NO CRM Stage Event (the create payload carries no
 *   `status`), so nothing links to it and Frappe's link check lets it go. This
 *   scenario is the regression guard for the shipped feature.
 *
 * Scenario B (the real world): a deal that was moved between kanban lanes owns
 *   CRM Stage Event rows. Those rows link back to the deal, so `frappe.delete_doc`
 *   refuses the delete unless the deal drops its own history in `on_trash`.
 *   This scenario asserts the CORRECT behaviour — deleting a deal that only has
 *   its own stage history must succeed. Before the fix it FAILS, and that failure
 *   is the evidence. There is deliberately no flag that turns the red green.
 *
 * Exit code: 0 when every step passed, 1 otherwise.
 *
 * Usage: node docs/uat/scripts/live_mikas_tender_crud_uat.js
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const COMPANY = 'Mikas';
const CRM_ROUTE = `${BASE_URL}/stabler#/tender/crm`;
const OUT_DIR = path.join(__dirname, '../evidence/2026-08-15-tender-crud-uat');
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

const RUN_ID = String(Date.now());
const TITLE_A = `UAT-CRUD-${RUN_ID}`;
const TITLE_A_EDITED = `UAT-CRUD-${RUN_ID} EDITED`;
const TITLE_B = `UAT-CRUD-${RUN_ID}-HIST`;

// Drawer / board selectors — verified against TenderCrm.vue, TenderMasterDrawer.vue,
// Typeahead.vue and ConfirmHost.vue. Sections are addressed by their A/B/C/D kicker
// so the script survives translation of every visible label.
const SEL = {
	newTender: 'button.btn.btn-primary.btn-sm:has-text("New tender")',
	formDrawer: '.tgm-drawer[role="dialog"]',
	formKicker: '.tgm-drawer .tgm-kicker',
	customerInput: '.tgm-drawer .tgm-section:has(.tgm-sec-num:text-is("A")) input',
	customerClear: '.tgm-drawer button[aria-label="Clear selection"]',
	typeaheadItem: '.typeahead-menu button.stbl-menu-item',
	titleInput: '.tgm-drawer .tgm-section:has(.tgm-sec-num:text-is("B")) input.form-control',
	formSave: '.tgm-drawer-footer button.btn-primary',
	column: '.ds-col',
	card: '.ds-card',
	// NOTE: .ds-card-t and #crm-dw-title both render `_deal_label()` — the
	// CUSTOMER, not the tender title (tender.py:1895-1900). Never key identity on
	// them; use .ds-card-id / .crm-dw-src / .ds-drawer-kicker (the deal name).
	cardId: '.ds-card-id',
	dealDrawer: 'aside.ds-drawer[role="dialog"]',
	dealSource: '.crm-dw-src',
	dealEdit: '.ds-drawer-foot button.ds-btn--primary',
	dealDelete: '.ds-drawer-foot button.crm-dw-del',
	confirmModal: '.modal.show[role="dialog"]',
	confirmDanger: '.modal.show .modal-footer button.btn-danger',
};

function loadSecrets() {
	const envFile = '/Users/zafar/frappe-bench-local/.uat_secrets.env';
	if (fs.existsSync(envFile)) {
		for (const line of fs.readFileSync(envFile, 'utf8').split('\n')) {
			const trimmed = line.trim();
			if (trimmed && trimmed.includes('=')) {
				const idx = trimmed.indexOf('=');
				process.env[trimmed.substring(0, idx)] = trimmed.substring(idx + 1);
			}
		}
	}
	const adminPass = process.env.STABLER_UAT_ADMIN_PASS;
	if (!adminPass) {
		throw new Error('Missing STABLER_UAT_ADMIN_PASS secret.');
	}
	return { adminPass };
}

async function main() {
	const { adminPass } = loadSecrets();
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const results = {
		timestamp: new Date().toISOString(),
		site: BASE_URL,
		company: COMPANY,
		run_id: RUN_ID,
		titles: { scenario_a: TITLE_A, scenario_a_edited: TITLE_A_EDITED, scenario_b: TITLE_B },
		deals: {},
		delete_api_responses: [],
		steps: [],
		passed_count: 0,
		failed_count: 0,
		leftovers: [],
	};

	let shotSeq = 0;
	let customerProbe = '';
	/** Deal names this run created. Nothing outside this set may ever be deleted. */
	const createdThisRun = new Set();

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	// The exact backend error is the evidence for scenario B — capture the raw
	// delete_deal response rather than relying on the toast wording.
	page.on('response', async (resp) => {
		if (!resp.url().includes('stabler.api.crm.delete_deal')) return;
		let body = '';
		try {
			body = (await resp.text()).slice(0, 4000);
		} catch (e) {
			body = `<unreadable: ${e.message}>`;
		}
		results.delete_api_responses.push({ status: resp.status(), body });
	});

	function record(id, desc, ok, details = '') {
		const status = ok ? 'PASS' : 'FAIL';
		results.steps.push({ id, description: desc, status, details });
		if (ok) results.passed_count++;
		else results.failed_count++;
		console.log(`[${status}] ${id}: ${desc}${details ? ` — ${details}` : ''}`);
	}

	async function shot(name) {
		shotSeq += 1;
		const file = path.join(SCREENSHOT_DIR, `${String(shotSeq).padStart(2, '0')}_${name}.png`);
		await page.screenshot({ path: file, fullPage: false });
		return path.basename(file);
	}

	async function apiCount(doctype, filters) {
		const url =
			`${BASE_URL}/api/method/frappe.client.get_count` +
			`?doctype=${encodeURIComponent(doctype)}&filters=${encodeURIComponent(JSON.stringify(filters))}`;
		const resp = await page.request.get(url);
		if (resp.status() !== 200) throw new Error(`get_count ${doctype} → HTTP ${resp.status()}`);
		return (await resp.json()).message;
	}

	// POST through the page so the SPA's CSRF token rides along — same hatch the
	// other live scripts use.
	async function callSpa(method, args) {
		return page.evaluate(
			async ({ m, a }) => {
				const token = window.__STABLER__?.csrfToken || '';
				const p = new URLSearchParams();
				for (const [k, v] of Object.entries(a || {})) {
					if (v === undefined || v === null) continue;
					p.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
				}
				const res = await fetch(`/api/method/${m}`, {
					method: 'POST',
					headers: {
						'Content-Type': 'application/x-www-form-urlencoded',
						'X-Frappe-CSRF-Token': token,
					},
					body: p.toString(),
				});
				return { status: res.status, body: (await res.text()).slice(0, 2000) };
			},
			{ m: method, a: args }
		);
	}

	async function openBoard(query = '') {
		// The SPA is hash-routed, so a URL that differs only in its fragment is a
		// same-document navigation — an open drawer would survive it and then
		// intercept the next click. Bounce through about:blank to force a real
		// document load: every step starts from a clean boot, and `?deal=` is
		// exercised as a genuine deep link.
		await page.goto('about:blank', { timeout: 30000 });
		await page.goto(`${CRM_ROUTE}${query}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
		// The board renders an EmptyState when there are no deals, so wait on the
		// page chrome (the New tender button) rather than on a column.
		await page.waitForSelector(SEL.newTender, { state: 'visible', timeout: 45000 });
		await page.waitForTimeout(1500);
	}

	async function listDealNames() {
		const resp = await page.request.get(`${BASE_URL}/api/resource/CRM%20Deal?limit_page_length=0`);
		if (resp.status() !== 200) throw new Error(`CRM Deal list → HTTP ${resp.status()}`);
		return new Set(((await resp.json()).data || []).map((r) => r.name));
	}

	// The board card shows `_deal_label()` — the CUSTOMER, not the tender title
	// (tender.py:1895-1900), and `#crm-dw-title` shows the same label. The tender
	// title only ever surfaces inside the edit form. So the identity anchor for
	// every assertion below is the deal NAME, which is genuinely unique and is
	// exactly what `crm.delete_deal` receives.
	function cardFor(dealName) {
		return page.locator(`${SEL.card}:has(${SEL.cardId}:text-is("${dealName}"))`);
	}

	async function waitForCard(dealName, timeout = 20000) {
		const card = cardFor(dealName);
		try {
			await card.first().waitFor({ state: 'visible', timeout });
		} catch (e) {
			// One reload in case the board did not refresh itself after save.
			await openBoard();
			await card.first().waitFor({ state: 'visible', timeout: 20000 });
		}
		return card.first();
	}

	async function fillTenderForm(title) {
		// Customer typeahead: minChars 1, 200ms debounce, opens on input (not focus).
		const custInput = page.locator(SEL.customerInput).first();
		await custInput.click();
		await custInput.fill(customerProbe);
		await page.waitForSelector(SEL.typeaheadItem, { state: 'visible', timeout: 20000 });
		await page.locator(SEL.typeaheadItem).first().click();
		await page.waitForSelector(SEL.customerClear, { state: 'visible', timeout: 10000 });
		await page.locator(SEL.titleInput).first().fill(title);
	}

	async function saveForm() {
		await page.click(SEL.formSave);
		await page.waitForSelector(SEL.formDrawer, { state: 'detached', timeout: 45000 });
		await page.waitForTimeout(2000);
	}

	/** Create a tender and return the name of the deal it produced (set diff). */
	async function createTender(title) {
		const before = await listDealNames();
		await page.click(SEL.newTender);
		await page.waitForSelector(SEL.formDrawer, { state: 'visible', timeout: 20000 });
		await fillTenderForm(title);
		await saveForm();
		const after = await listDealNames();
		const fresh = [...after].filter((n) => !before.has(n));
		if (fresh.length !== 1) {
			throw new Error(`Expected exactly 1 new CRM Deal after save, got ${fresh.length}: ${fresh.join(', ')}`);
		}
		createdThisRun.add(fresh[0]);
		return fresh[0];
	}

	// Never click Delete unless the open drawer is showing exactly the deal this
	// run created. Unconditional gate — the board being empty today is not a reason
	// to trust it tomorrow. Both checks are on the deal NAME, which is what
	// `crm.delete_deal` actually receives.
	async function deleteOpenDeal(expectedName) {
		if (!createdThisRun.has(expectedName)) {
			throw new Error(`SAFETY GATE: ${expectedName} was not created by this run. Refusing to delete.`);
		}
		const shownSrc = (await page.locator(SEL.dealSource).innerText()).trim();
		if (!shownSrc.includes(expectedName)) {
			throw new Error(
				`SAFETY GATE: drawer source "${shownSrc}" does not carry ${expectedName}. Refusing to delete.`
			);
		}
		const shownKicker = (await page.locator(`${SEL.dealDrawer} .ds-drawer-kicker`).innerText()).trim();
		if (!shownKicker.includes(expectedName)) {
			throw new Error(
				`SAFETY GATE: drawer kicker "${shownKicker}" does not carry ${expectedName}. Refusing to delete.`
			);
		}
		await page.waitForSelector(SEL.dealDelete, { state: 'visible', timeout: 20000 });
		await page.click(SEL.dealDelete);
		await page.waitForSelector(SEL.confirmModal, { state: 'visible', timeout: 15000 });
	}

	// Open the edit form from the detail drawer and WAIT for the async intake
	// fetch. TenderMasterDrawer.vue:147 seeds `form.title` from `organization`,
	// and only :166 replaces it with the stored intake title once
	// `tender.deal_intake` resolves. Reading the input before that returns the
	// customer name — a race in the test, not a product defect.
	async function openEditFormFromDrawer() {
		await page.waitForSelector(SEL.dealEdit, { state: 'visible', timeout: 20000 });
		const intake = page
			.waitForResponse((r) => r.url().includes('stabler.api.tender.deal_intake'), { timeout: 30000 })
			.catch(() => null);
		await page.click(SEL.dealEdit);
		await page.waitForSelector(SEL.formDrawer, { state: 'visible', timeout: 20000 });
		await intake;
		await page.waitForTimeout(1500);
	}

	async function closeForm() {
		await page.click(`${SEL.formDrawer} .btn-close`);
		await page.waitForSelector(SEL.formDrawer, { state: 'detached', timeout: 15000 });
	}

	/** Re-open the edit form for a deal and read back the stored tender title. */
	async function readBackTitle(dealName) {
		await openBoard(`?deal=${encodeURIComponent(dealName)}`);
		await page.waitForSelector(SEL.dealDrawer, { state: 'visible', timeout: 30000 });
		await openEditFormFromDrawer();
		const value = await page.locator(SEL.titleInput).first().inputValue();
		await closeForm();
		return value;
	}

	async function confirmDelete() {
		await page.click(SEL.confirmDanger);
		await page.waitForTimeout(4000);
	}

	async function toastTexts() {
		const nodes = page.locator('[class*="toast"]');
		const n = await nodes.count();
		const out = [];
		for (let i = 0; i < n; i++) {
			const txt = (await nodes.nth(i).innerText().catch(() => '')).trim();
			if (txt) out.push(txt);
		}
		return out.join(' | ');
	}

	try {
		// ── 0. Login + preconditions ───────────────────────────────────────────
		const loginResp = await page.request.post(`${BASE_URL}/api/method/login`, {
			data: { usr: 'Administrator', pwd: adminPass },
		});
		record('UAT-00-LOGIN', 'Administrator login via API', loginResp.status() === 200, `HTTP ${loginResp.status()}`);
		if (loginResp.status() !== 200) throw new Error('Login failed — aborting.');

		const custResp = await page.request.get(
			`${BASE_URL}/api/resource/Customer?fields=${encodeURIComponent('["name","customer_name"]')}&limit_page_length=5`
		);
		const customers = (await custResp.json()).data || [];
		record('UAT-00-CUSTOMERS', 'Tenant has at least one Customer for the typeahead', customers.length > 0, `${customers.length} found`);
		if (!customers.length) throw new Error('No Customer on mikas — the tender form cannot be filled.');
		const firstCustomer = customers[0].customer_name || customers[0].name;
		customerProbe = firstCustomer.trim().slice(0, 3);
		results.customer_probe = customerProbe;

		await openBoard();
		record('UAT-00-BOARD', 'Tender CRM board reachable', page.url().includes('/tender/crm'), await shot('board_initial'));

		// ══ SCENARIO A — Create / Read / Edit / Delete, no stage history ═══════
		console.log('\n=== SCENARIO A: fresh deal (no stage history) ===');

		// A1 — Create
		const dealA = await createTender(TITLE_A);
		results.deals.scenario_a = dealA;
		results.leftovers.push(dealA);
		const cardA = await waitForCard(dealA);
		const colIndexA = await cardA.evaluate((el) => {
			const col = el.closest('.ds-col');
			return col ? Array.from(document.querySelectorAll('.ds-col')).indexOf(col) : -1;
		});
		record('UAT-A1-CREATE', 'New tender lands on the board', Boolean(dealA), `${dealA}, column index ${colIndexA} (0 = Intake)`);
		record('UAT-A1-LANE', 'New tender lands in the first lane (Intake)', colIndexA === 0, `column index ${colIndexA}`);
		await shot('a_card_created');

		// A2 — Read via ?deal=
		await openBoard(`?deal=${encodeURIComponent(dealA)}`);
		await page.waitForSelector(SEL.dealDrawer, { state: 'visible', timeout: 30000 });
		const readSrc = (await page.locator(SEL.dealSource).innerText()).trim();
		const readKicker = (await page.locator(`${SEL.dealDrawer} .ds-drawer-kicker`).innerText()).trim();
		record(
			'UAT-A2-READ',
			'Deep link ?deal= opens the detail drawer for that exact deal',
			readSrc.includes(dealA) && readKicker.includes(dealA),
			`src="${readSrc}", kicker="${readKicker}"`
		);
		await shot('a_read_drawer');

		// A3 — Edit. The card and `#crm-dw-title` both render the customer
		// (tender.py:1895-1900), so the stored tender title is only observable in
		// the edit form — that is where the round-trip is asserted.
		await openEditFormFromDrawer();
		const kicker = (await page.locator(SEL.formKicker).innerText()).trim();
		const restoredTitle = await page.locator(SEL.titleInput).first().inputValue();
		record('UAT-A3-EDIT-OPEN', 'Edit tender opens the form in edit mode with the intake restored', restoredTitle === TITLE_A, `kicker="${kicker}", title field="${restoredTitle}"`);
		await page.locator(SEL.titleInput).first().fill(TITLE_A_EDITED);
		await shot('a_edit_drawer');
		await saveForm();
		const persistedTitle = await readBackTitle(dealA);
		record('UAT-A3-EDIT-SAVE', 'Edited title is persisted and read back', persistedTitle === TITLE_A_EDITED, `title field after save="${persistedTitle}"`);
		await shot('a_edit_readback');
		await openBoard();
		record('UAT-A3-EDIT-CARD', 'The edited tender still holds exactly one card', (await cardFor(dealA).count()) === 1);

		// A4 — Delete
		await openBoard(`?deal=${encodeURIComponent(dealA)}`);
		await page.waitForSelector(SEL.dealDrawer, { state: 'visible', timeout: 30000 });
		await deleteOpenDeal(dealA);
		await shot('a_delete_confirm');
		await confirmDelete();
		const remainingA = await apiCount('CRM Deal', [['name', '=', dealA]]);
		record('UAT-A4-DELETE', 'Fresh tender deletes cleanly', remainingA === 0, `CRM Deal ${dealA} count=${remainingA}; toast: ${await toastTexts()}`);
		await openBoard();
		record('UAT-A4-BOARD', 'Deleted card is gone from the board', (await cardFor(dealA).count()) === 0);
		await shot('a_board_after_delete');
		if (remainingA === 0) results.leftovers = results.leftovers.filter((n) => n !== dealA);

		// ══ SCENARIO B — deal WITH its own stage history ══════════════════════
		console.log('\n=== SCENARIO B: deal with stage history ===');

		// B1 — Create
		const dealB = await createTender(TITLE_B);
		results.deals.scenario_b = dealB;
		results.leftovers.push(dealB);
		await waitForCard(dealB);
		record('UAT-B1-CREATE', 'Second tender created for the history scenario', Boolean(dealB), dealB);
		await shot('b_card_created');

		// B2 — Precondition, not the assertion: give the deal a lane move so the
		// backend writes a CRM Stage Event. HTML5 drag-and-drop is unreliable
		// headless, so the SPA's own endpoint is called directly.
		const moveResp = await callSpa('stabler.api.tender.move_deal_stage', { name: dealB, stage: 'go' });
		const eventsB = await apiCount('CRM Stage Event', [['deal', '=', dealB]]);
		record('UAT-B2-HISTORY', 'Lane move records a CRM Stage Event for the deal', moveResp.status === 200 && eventsB > 0, `move_deal_stage HTTP ${moveResp.status}, stage events=${eventsB}`);
		if (eventsB === 0) throw new Error('Precondition failed: no CRM Stage Event was written — scenario B cannot prove anything.');
		await openBoard();
		await shot('b_after_lane_move');

		// B3 — Delete through the UI. This asserts the CORRECT behaviour: a deal
		// whose only links are its own stage events must be deletable.
		await openBoard(`?deal=${encodeURIComponent(dealB)}`);
		await page.waitForSelector(SEL.dealDrawer, { state: 'visible', timeout: 30000 });
		await deleteOpenDeal(dealB);
		await shot('b_delete_confirm');
		await confirmDelete();
		const toastB = await toastTexts();
		await shot('b_after_delete_attempt');
		const remainingB = await apiCount('CRM Deal', [['name', '=', dealB]]);
		const apiErr = results.delete_api_responses.length
			? results.delete_api_responses[results.delete_api_responses.length - 1].body.slice(0, 600)
			: '<no delete_deal response captured>';
		record(
			'UAT-B3-DELETE',
			'Tender carrying only its own stage history deletes cleanly',
			remainingB === 0,
			`CRM Deal ${dealB} count=${remainingB}; toast: ${toastB}; api: ${apiErr}`
		);
		if (remainingB === 0) {
			results.leftovers = results.leftovers.filter((n) => n !== dealB);
			const orphanEvents = await apiCount('CRM Stage Event', [['deal', '=', dealB]]);
			record('UAT-B4-CLEANUP', 'Deleting the deal takes its stage history with it', orphanEvents === 0, `orphan CRM Stage Event rows=${orphanEvents}`);
		}

		await openBoard();
		await shot('final_board');
	} catch (err) {
		record('UAT-FATAL', 'Unhandled error during the run', false, err.message);
		try {
			await shot('fatal');
		} catch (e) {
			/* screenshot is best effort */
		}
	} finally {
		// Best effort teardown — never let a leftover deal hide in the log.
		const stillThere = [];
		for (const name of results.leftovers) {
			try {
				if ((await apiCount('CRM Deal', [['name', '=', name]])) > 0) stillThere.push(name);
			} catch (e) {
				stillThere.push(`${name} (state unknown: ${e.message})`);
			}
		}
		results.leftovers = stillThere;

		await browser.close();

		fs.writeFileSync(
			path.join(OUT_DIR, `tender_crud_results_${RUN_ID}.json`),
			JSON.stringify(results, null, 1)
		);

		console.log(`\n=== ${results.passed_count} passed, ${results.failed_count} failed ===`);
		if (stillThere.length) {
			console.log('\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!');
			console.log('!! LEFTOVER TEST DATA ON PRODUCTION (mikas) — CLEAN THIS UP:');
			for (const name of stillThere) console.log(`!!   ${name}`);
			console.log('!! On the server:');
			console.log(
				`!!   sudo -u frappe bench --site mikas.erpstable.com execute frappe.db.sql --args '["DELETE FROM \`tabCRM Stage Event\` WHERE deal IN (${stillThere
					.map((n) => `\\"${n}\\"`)
					.join(',')})"]'`
			);
			console.log(
				`!!   sudo -u frappe bench --site mikas.erpstable.com execute frappe.delete_doc --kwargs '{"doctype":"CRM Deal","name":"${stillThere[0]}","force":true,"ignore_permissions":true}'`
			);
			console.log('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n');
		}

		process.exit(results.failed_count === 0 ? 0 : 1);
	}
}

main().catch((e) => {
	console.error(e);
	process.exit(1);
});
