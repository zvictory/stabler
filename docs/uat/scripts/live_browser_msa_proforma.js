const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

async function runLiveMsaProformaTest() {
	console.log('--- STARTING LIVE PROFORMA INVOICE CREATION TEST ON MSA ---');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	// Step 1: Login
	console.log('Step 1: Logging in to https://msa.erpstable.com...');
	await page.goto('https://msa.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');
	await page.waitForTimeout(2000);

	await page.evaluate(() => {
		localStorage.setItem('stabler.activeCompany', 'MSA');
	});

	// Step 2: Navigate to New Proforma page directly
	console.log('Step 2: Navigating to /imports/proformas/new...');
	await page.goto('https://msa.erpstable.com/stabler#/imports/proformas/new', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	// Step 3: Fill Supplier Typeahead
	console.log('Step 3: Filling Supplier field...');
	const supplierInput = await page.waitForSelector('input[placeholder*="supplier"], input[placeholder*="Tedarikçi"]', { timeout: 5000 }).catch(() => null);
	if (supplierInput) {
		await supplierInput.click();
		await supplierInput.fill('Al Super Frozen Food Private Limited');
		await page.waitForTimeout(1000);
		// Select first dropdown option if available
		const option = await page.waitForSelector('.typeahead-option, .dropdown-item, li:has-text("Al Super")', { timeout: 3000 }).catch(() => null);
		if (option) {
			await option.click();
		} else {
			await page.keyboard.press('Enter');
		}
	}

	// Step 4: Fill Supplier PI Ref
	console.log('Step 4: Filling Supplier PI No...');
	const piRefInput = await page.waitForSelector('input[placeholder*="FIR/25-26"], input[placeholder*="PI No"], input[placeholder*="ref"]', { timeout: 5000 }).catch(() => null);
	if (piRefInput) {
		await piRefInput.fill('PI-MSA-2026-001');
	}

	await page.waitForTimeout(1000);
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '19_msa_proforma_modal_filled.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 19_msa_proforma_modal_filled.png saved.');

	// Step 5: Click Save button
	console.log('Step 5: Clicking Save button...');
	const saveBtn = await page.waitForSelector('button:has-text("Save"), button:has-text("Kaydet")', { timeout: 5000 }).catch(() => null);
	if (saveBtn) {
		await saveBtn.click();
		await page.waitForTimeout(4000);
	}

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '20_msa_proforma_saved.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 20_msa_proforma_saved.png saved.');

	await browser.close();
}

runLiveMsaProformaTest().catch((err) => {
	console.error('Error in live MSA proforma test:', err);
});
