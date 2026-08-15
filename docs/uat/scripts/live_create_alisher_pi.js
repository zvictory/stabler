const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://msa.erpstable.com';
const OUT_DIR = '/Users/zafar/.gemini/antigravity/brain/56e2e62a-4fc4-46b8-a3fe-5fda74c5cfba';

async function testCreateTransportPI() {
	console.log(`\n=== 🚀 Creating Alisher Transport PI on ${BASE_URL} via Purchasing API ===`);
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
	const page = await context.newPage();

	await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');
	await page.waitForURL('**/stabler#/**', { timeout: 15000 });
	console.log('✅ Login successful!');

	// Initialize session on CI page
	await page.goto(`${BASE_URL}/stabler#/purchasing/invoices/new`);
	await page.waitForTimeout(2500);

	// Create Purchase Invoice for Alisher-FORMAK via Purchasing API
	const res = await page.evaluate(async () => {
		const boot = window.__STABLER__ || {};
		const params = new URLSearchParams();
		params.append('company', 'MSA');
		params.append('supplier', 'Alisher-FORMAK');
		params.append('currency', 'USD');
		params.append('conversion_rate', '12800.0');
		params.append('bill_no', 'ALISHER-TRK-04387');
		params.append('posting_date', '2026-08-15');
		params.append('commercial_invoice', 'CI-2026-04387');
		params.append('items', JSON.stringify([
			{
				item_code: 'Land Freight - MH/259/2026-27',
				qty: 1,
				rate: 8500.0,
				amount: 8500.0,
				uom: 'Nos',
				description: 'Road Freight Transportation to Tashkent - Alisher'
			}
		]));

		const resp = await fetch('/api/method/stabler.api.purchasing.create_purchase_invoice', {
			method: 'POST',
			headers: {
				'Accept': 'application/json',
				'Content-Type': 'application/x-www-form-urlencoded',
				'X-Frappe-CSRF-Token': boot.csrfToken || ''
			},
			body: params.toString()
		});
		return resp.json();
	});

	console.log('API Response:', JSON.stringify(res, null, 2));

	let createdPiName = res.message?.name;

	if (createdPiName) {
		console.log('✅ Created Transport PI:', createdPiName);

		// Navigate to created PI
		await page.goto(`${BASE_URL}/stabler#/purchasing/invoices/${createdPiName}`, { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(3500);
		const piScreenshot = path.join(OUT_DIR, '21_created_alisher_pi_form.png');
		await page.screenshot({ path: piScreenshot, fullPage: true });
		console.log('📸 Saved PI Screenshot:', piScreenshot);
	}

	// Navigate to CI-2026-04387
	console.log('Navigating to CI-2026-04387 to view updated Landed Cost...');
	await page.goto(`${BASE_URL}/stabler#/imports/commercial-invoices/CI-2026-04387`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3500);

	const ciScreenshot = path.join(OUT_DIR, '20_ci_4387_alisher_created.png');
	await page.screenshot({ path: ciScreenshot, fullPage: true });
	console.log('📸 Saved CI Screenshot:', ciScreenshot);

	await browser.close();
	console.log('=== Finished ===');
}

testCreateTransportPI().catch(err => {
	console.error('Error:', err);
	process.exit(1);
});
