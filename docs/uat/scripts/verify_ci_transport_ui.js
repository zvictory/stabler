const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const SCREENSHOTS_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/2026-08-05-ci-transport/screenshots';
const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

if (!fs.existsSync(SCREENSHOTS_DIR)) {
	fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

async function verifyCiTransportUI() {
	console.log('=== VERIFYING CI TRANSPORT EXPENSES & FORM REORDERING ===');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
	const page = await context.newPage();

	await page.goto('https://msa.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');

	await page.waitForURL('**/stabler#/**', { timeout: 10000 });
	await page.waitForTimeout(2000);

	await page.evaluate(() => {
		localStorage.setItem('stabler.activeCompany', 'MSA');
	});

	// Navigate to commercial invoices list
	await page.goto('https://msa.erpstable.com/stabler#/imports/commercial-invoices', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	// Get first CI link from list or navigate directly to known CI
	const ciLink = await page.evaluate(() => {
		const row = document.querySelector('table tbody tr a');
		return row ? row.getAttribute('href') : null;
	});

	console.log('Found CI link:', ciLink);

	// Open CI-2026-03774
	await page.goto('https://msa.erpstable.com/stabler#/imports/commercial-invoices/CI-2026-03774', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(4000);

	// Screenshot full page top section
	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '01_ci_form_top_and_items.png'), fullPage: false });
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '35_ci_form_top_and_items.png'), fullPage: false });
	console.log('Saved 01_ci_form_top_and_items.png');

	// Scroll down to Transport Expenses & Logistics section
	await page.evaluate(() => {
		window.scrollTo(0, document.body.scrollHeight / 2);
	});
	await page.waitForTimeout(1000);
	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '02_ci_transport_expenses_card.png'), fullPage: false });
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '36_ci_transport_expenses_card.png'), fullPage: false });
	console.log('Saved 02_ci_transport_expenses_card.png');

	// Scroll to very bottom to verify CiLogisticsOverview location
	await page.evaluate(() => {
		window.scrollTo(0, document.body.scrollHeight);
	});
	await page.waitForTimeout(1000);
	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '03_ci_form_bottom_logistics_overview.png'), fullPage: false });
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '37_ci_form_bottom_logistics_overview.png'), fullPage: false });
	console.log('Saved 03_ci_form_bottom_logistics_overview.png');

	await browser.close();
}

verifyCiTransportUI().catch(console.error);
