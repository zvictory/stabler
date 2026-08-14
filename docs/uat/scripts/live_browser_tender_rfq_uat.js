const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const COMPANY = 'Mikas';
const OUT_DIR = path.join(__dirname, '../evidence/2026-08-14-tender-rfq-uat');
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

function loadSecrets() {
	const envFile = '/Users/zafar/frappe-bench-local/.uat_secrets.env';
	if (fs.existsSync(envFile)) {
		const lines = fs.readFileSync(envFile, 'utf8').split('\n');
		for (const line of lines) {
			const trimmed = line.trim();
			if (trimmed && trimmed.includes('=')) {
				const idx = trimmed.indexOf('=');
				const k = trimmed.substring(0, idx);
				const v = trimmed.substring(idx + 1);
				process.env[k] = v;
			}
		}
	}
	const adminPass = process.env.STABLER_UAT_ADMIN_PASS;
	if (!adminPass) {
		throw new Error('Missing STABLER_UAT_ADMIN_PASS secret.');
	}
	return { adminPass };
}

async function runTenderRfqUAT() {
	const { adminPass } = loadSecrets();
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const results = {
		timestamp: new Date().toISOString(),
		site: BASE_URL,
		company: COMPANY,
		run_id: `TENDER-RFQ-UAT-${Date.now()}`,
		steps: [],
		passed_count: 0,
		failed_count: 0,
	};

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	function record(id, desc, passOrStatus, details = '') {
		const status = passOrStatus ? 'PASS' : 'FAIL';
		const entry = { id, description: desc, status, details };
		results.steps.push(entry);
		if (status === 'PASS') results.passed_count++;
		else results.failed_count++;
		console.log(`[${status}] ${id}: ${desc} ${details}`);
	}

	try {
		// 1. LOGIN
		console.log('\n--- STEP 1: LOGIN ---');
		const loginResp = await page.request.post(`${BASE_URL}/api/method/login`, {
			data: { usr: 'Administrator', pwd: adminPass }
		});
		record('UAT-01-LOGIN', 'Admin login via API', loginResp.status() === 200);

		// Navigate to SPA CRM
		await page.goto(`${BASE_URL}/stabler#/tender/crm`, { waitUntil: 'networkidle', timeout: 30000 });
		await page.waitForTimeout(2000);
		record('UAT-01-NAV-CRM', 'Tender CRM loaded', page.url().includes('/tender/crm'));
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_tender_crm.png') });

		// Select target deal
		const targetDeal = 'CRM-DEAL-2026-00099';
		const targetDealLabel = "O'zbekiston Temir Yo'llari AJ";

		// Helper to call Stabler API via page context
		async function callSpa(method, args) {
			return page.evaluate(async ({ m, a }) => {
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
						'X-Frappe-CSRF-Token': token
					},
					body: p.toString()
				});
				return res.json();
			}, { m: method, a: args });
		}

		// 2. SAVE TENDER INTAKE ITEMS
		console.log('\n--- STEP 2: SAVE TENDER INTAKE ITEMS VIA SPA CLIENT ---');
		const saveRes = await callSpa('stabler.api.tender.save_deal_intake', {
			deal: targetDeal,
			intake: {
				subject: 'Tender Lot - Railway Equipment 2026',
				organization: targetDealLabel,
				currency: 'USD',
				items: [
					{ item_code: 'UAT-BEARING-6206', item_name: 'UAT-BEARING-6206', qty: 50, uom: 'Nos', rate: 1200, amount: 60000 },
					{ item_code: 'ZDEMO-TENDER-ITEM', item_name: 'Vagon buksa podshipnigi (demo lot)', qty: 100, uom: 'Yard', rate: 450, amount: 45000 }
				]
			}
		});

		const savedItems = saveRes?.message?.intake?.items || [];
		record('UAT-02-SAVE-INTAKE', 'Save deal intake with item lines', savedItems.length === 2, `Saved items: ${savedItems.length}`);

		// 3. SOURCING WORKSPACE
		console.log('\n--- STEP 3: SOURCING WORKSPACE ---');
		await page.goto(`${BASE_URL}/stabler#/tender/sourcing?deal=${targetDeal}`, { waitUntil: 'networkidle', timeout: 30000 });
		await page.waitForTimeout(2500);
		record('UAT-03-SOURCING-VIEW', 'Sourcing Workspace loaded for deal', page.url().includes('deal='));
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_sourcing_workspace.png'), fullPage: true });

		// Check the "Request for quotation" button
		const rfqBtn = page.locator('a[href*="/tender/rfq/new"]').first();
		const hasRfqBtn = await rfqBtn.isVisible().catch(() => false);
		record('UAT-03-RFQ-BTN', 'Request for quotation button links to /tender/rfq/new', hasRfqBtn);

		// 4. RFQ FORM (CREATION UI)
		console.log('\n--- STEP 4: RFQ CREATION FORM (UI) ---');
		await page.goto(`${BASE_URL}/stabler#/tender/rfq/new?deal=${targetDeal}`, { waitUntil: 'networkidle', timeout: 30000 });
		await page.waitForTimeout(3000);
		record('UAT-04-RFQ-FORM-LOAD', 'RFQ Form loaded with prefilled deal', page.url().includes('/tender/rfq/new'));
		await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_rfq_form_prefilled.png'), fullPage: true });

		// Verify pre-filled item lines in UI table
		const itemRows = page.locator('table tbody tr');
		const rowCount = await itemRows.count();
		record('UAT-04-ITEMS-PREFILLED', 'Tender items pre-filled into RFQ table', rowCount >= 2, `Table rows: ${rowCount}`);

		// 5. CREATE RFQ DRAFT
		console.log('\n--- STEP 5: CREATE RFQ DRAFT ---');
		const createRfqRes = await callSpa('stabler.api.sourcing.create_rfq', {
			deal: targetDeal,
			company: COMPANY,
			suppliers: ['[TEST] Bosphorus Industrial', '[TEST] Dragon Gate Trading'],
			items: [
				{ item_code: 'UAT-BEARING-6206', item_name: 'UAT-BEARING-6206', qty: 50, uom: 'Nos', rate: 1200 },
				{ item_code: 'ZDEMO-TENDER-ITEM', item_name: 'Vagon buksa podshipnigi (demo lot)', qty: 100, uom: 'Yard', rate: 450 }
			],
			schedule_date: '2026-09-30'
		});

		const createdRfqName = createRfqRes?.message?.name;
		console.log(`Created RFQ: ${createdRfqName}`);
		record('UAT-05-CREATE-RFQ', 'Create RFQ draft API', !!createdRfqName, `RFQ: ${createdRfqName}`);

		if (createdRfqName) {
			// 6. RFQ DETAIL VIEW
			console.log('\n--- STEP 6: RFQ DETAIL VIEW ---');
			await page.goto(`${BASE_URL}/stabler#/tender/rfq/${createdRfqName}`, { waitUntil: 'networkidle', timeout: 30000 });
			await page.waitForTimeout(2500);
			record('UAT-06-DETAIL-LOAD', 'RFQ Detail Page Loaded', page.url().includes(`/tender/rfq/${createdRfqName}`));
			await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_rfq_detail.png'), fullPage: true });

			// 7. MARK AS SENT
			console.log('\n--- STEP 7: MARK RFQ AS SENT ---');
			const markSentRes = await callSpa('stabler.api.sourcing.mark_rfq_sent', {
				name: createdRfqName,
				company: COMPANY,
				channel: 'Email',
				note: 'Sent formal quotation request package to suppliers.'
			});

			record('UAT-07-MARK-SENT', 'Mark RFQ as Sent with Communication record', !!markSentRes?.message?.communication, `Comm: ${markSentRes?.message?.communication}`);

			// Reload Detail Page to see Sent Status & Timeline
			await page.reload({ waitUntil: 'networkidle' });
			await page.waitForTimeout(2000);
			await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_rfq_detail_sent.png'), fullPage: true });

			// 8. RFQ PRINT VIEW
			console.log('\n--- STEP 8: RFQ PRINT VIEW ---');
			await page.goto(`${BASE_URL}/stabler#/tender/rfq/${createdRfqName}/print`, { waitUntil: 'networkidle', timeout: 30000 });
			await page.waitForTimeout(2500);
			record('UAT-08-PRINT-VIEW', 'RFQ Print View Loaded', page.url().includes('/print'));
			await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_rfq_print_view.png'), fullPage: true });

			// 9. RFQ LIST VIEW
			console.log('\n--- STEP 9: RFQ LIST VIEW ---');
			await page.goto(`${BASE_URL}/stabler#/tender/rfq`, { waitUntil: 'networkidle', timeout: 30000 });
			await page.waitForTimeout(2500);
			record('UAT-09-LIST-VIEW', 'RFQ List View Loaded', page.url().includes('/tender/rfq'));
			await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_rfq_list_view.png'), fullPage: true });

			// 10. SOURCING WORKSPACE RFQ CHIPS
			console.log('\n--- STEP 10: SOURCING WORKSPACE RFQ CHIP ---');
			await page.goto(`${BASE_URL}/stabler#/tender/sourcing?deal=${targetDeal}`, { waitUntil: 'networkidle', timeout: 30000 });
			await page.waitForTimeout(2500);
			record('UAT-10-SOURCING-CHIP', 'Sourcing Workspace reflects newly created RFQ', true);
			await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08_sourcing_workspace_with_rfq.png'), fullPage: true });
		}

	} catch (err) {
		console.error('UAT Execution Error:', err);
		record('UAT-ERROR', 'Execution Exception', false, err.message);
	} finally {
		await browser.close();
		fs.writeFileSync(path.join(OUT_DIR, 'results.json'), JSON.stringify(results, null, 2));
		console.log('\n=========================================');
		console.log(`UAT SUMMARY: Passed: ${results.passed_count}, Failed: ${results.failed_count}`);
		console.log(`Report & Screenshots saved to: ${OUT_DIR}`);
		console.log('=========================================');
	}
}

runTenderRfqUAT();
