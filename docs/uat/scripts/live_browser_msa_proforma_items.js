const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

async function updateProformaWithItemLine() {
	console.log('--- STARTING ITEM LINE ADDITION ON PROFORMA PI-MSA-2026-001 ---');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	// Step 1: Login via API directly on context request
	console.log('Step 1: Logging in to https://msa.erpstable.com...');
	const loginResp = await page.request.post('https://msa.erpstable.com/api/method/login', {
		form: {
			usr: 'zafar@stable.uz',
			pwd: 'MsaUAT2026!'
		}
	});
	console.log('Login Status:', loginResp.status(), await loginResp.text());

	// Step 2: Call save_proforma API using authenticated session context
	console.log('Step 2: Saving 10 FCL item line with vendor category BUFFALO COMPENSATED...');
	const itemPayload = {
		name: 'PI-MSA-2026-001',
		company: 'MSA',
		supplier: 'Al Super Frozen Food Private Limited',
		supplier_name: 'Al Super Frozen Food Private Limited',
		pi_date: '2026-08-05',
		supplier_pi_ref: 'PI-MSA-2026-001',
		currency: 'USD',
		incoterm: 'CIF',
		status: 'DRAFT',
		prepayment_type: 'AGREED_TOTAL',
		agreed_total: 149600,
		advance_pct: 30,
		bank_agreed: 104720,
		cash_agreed: 44880,
		items: [
			{
				item: 'BUFFALO COMPENSATED_6',
				category: 'BUFFALO COMPENSATED',
				description: 'BUFFALO COMPENSATED 10 FCL',
				fcl: 10,
				boxes: 1700,
				box_weight_kg: 16,
				qty: 27200,
				uom: 'Kg',
				rate: 5.5,
				docs_price: 5.0
			}
		]
	};

	const saveResp = await page.request.post('https://msa.erpstable.com/api/method/stabler.api.imports.save_proforma', {
		data: { payload: itemPayload }
	});

	console.log('Save API HTTP Status:', saveResp.status());
	console.log('Save API Response:', await saveResp.text());

	// Step 3: Navigate to /imports/proformas/PI-MSA-2026-001 in browser to render updated UI
	console.log('Step 3: Navigating to /imports/proformas/PI-MSA-2026-001 in browser...');
	await page.goto('https://msa.erpstable.com/stabler#/imports/proformas/PI-MSA-2026-001', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(4000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '22_msa_proforma_item_line_added.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 22_msa_proforma_item_line_added.png saved.');

	await browser.close();
}

updateProformaWithItemLine().catch((err) => {
	console.error('Error in live MSA proforma item line update:', err);
});
