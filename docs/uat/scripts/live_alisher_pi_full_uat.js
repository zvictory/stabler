const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://msa.erpstable.com';
const OUT_DIR = '/Users/zafar/.gemini/antigravity/brain/56e2e62a-4fc4-46b8-a3fe-5fda74c5cfba';
const EVIDENCE_DIR = path.join(__dirname, '../evidence/2026-08-15-alisher-pi-uat/screenshots');

async function testCompleteAlisherFlow() {
	console.log(`\n=== 🚀 Complete Flow: Create Alisher Transport PI & Link to CI-2026-04387 ===`);
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
	const page = await context.newPage();

	// 1. Login
	await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');
	await page.waitForURL('**/stabler#/**', { timeout: 15000 });
	console.log('✅ Login successful!');

	// 2. Open New Purchase Invoice Form
	console.log('Navigating to /purchasing/invoices/new ...');
	await page.goto(`${BASE_URL}/stabler#/purchasing/invoices/new`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	// 3. Fill Supplier: Alisher-FORMAK
	const suppInput = page.locator('input[placeholder*="supplier"], input[placeholder*="Supplier"]').first();
	await suppInput.fill('Alisher');
	await page.waitForTimeout(1000);
	const suppOption = page.locator('text="Alisher-FORMAK"').first();
	if (await suppOption.isVisible().catch(() => false)) {
		await suppOption.click();
		await page.waitForTimeout(500);
	}

	// 4. Fill Commercial Invoice: CI-2026-04387
	const ciInput = page.locator('input[placeholder*="Search commercial invoice"]').first();
	if (await ciInput.isVisible().catch(() => false)) {
		await ciInput.fill('CI-2026-04387');
		await page.waitForTimeout(1500);
		const ciOption = page.locator('.dropdown-menu .dropdown-item, .typeahead-item').first();
		if (await ciOption.isVisible().catch(() => false)) {
			await ciOption.click();
			await page.waitForTimeout(500);
		}
	}

	// 5. Fill Bill No & Currency
	const billNoInput = page.locator('input#billNo, label:has-text("Bill No.") + input').first();
	if (await billNoInput.isVisible().catch(() => false)) {
		await billNoInput.fill('ALISHER-TRK-04387');
	}

	const currencySelect = page.locator('select').filter({ hasText: 'UZS' }).first();
	if (await currencySelect.isVisible().catch(() => false)) {
		await currencySelect.selectOption({ label: 'USD ($)' }).catch(() => {});
	}

	// Uncheck update stock
	const updateStockToggle = page.locator('#piUpdateStock, input[type="checkbox"]').first();
	if (await updateStockToggle.isChecked().catch(() => false)) {
		await updateStockToggle.uncheck().catch(() => {});
	}

	// 6. Fill Item Code: 105/106
	console.log('Filling Item 105/106...');
	const itemSearch = page.locator('input[placeholder*="Search..."]').first();
	if (await itemSearch.isVisible().catch(() => false)) {
		await itemSearch.fill('105');
		await page.waitForTimeout(1500);
		const itemOption = page.locator('.dropdown-menu .dropdown-item, .typeahead-item').first();
		if (await itemOption.isVisible().catch(() => false)) {
			await itemOption.click();
			await page.waitForTimeout(500);
		}
	}

	// Fill Rate
	const rateInput = page.locator('input.font-monospace, input[placeholder*="0"]').last();
	if (await rateInput.isVisible().catch(() => false)) {
		await rateInput.fill('8500');
	}

	await page.waitForTimeout(1000);

	// Screenshot: Form Filled
	const formScreenshot = path.join(EVIDENCE_DIR, '01_alisher_transport_pi_form_filled.png');
	await page.screenshot({ path: formScreenshot, fullPage: true });
	fs.copyFileSync(formScreenshot, path.join(OUT_DIR, '01_alisher_transport_pi_form_filled.png'));
	console.log('📸 Saved Form Screenshot:', formScreenshot);

	// Click Save as draft
	console.log('Clicking Save as draft...');
	const saveBtn = page.locator('button:has-text("Save as draft")').first();
	if (await saveBtn.isVisible().catch(() => false)) {
		await saveBtn.click();
		await page.waitForTimeout(4000);
		const savedScreenshot = path.join(EVIDENCE_DIR, '03_alisher_pi_saved.png');
		await page.screenshot({ path: savedScreenshot, fullPage: true });
		fs.copyFileSync(savedScreenshot, path.join(OUT_DIR, '03_alisher_pi_saved.png'));
		console.log('📸 Saved PI saved Screenshot:', savedScreenshot);
	}

	await browser.close();
	console.log('=== Finished ===\n');
}

testCompleteAlisherFlow().catch(err => {
	console.error('Fatal Error:', err);
	process.exit(1);
});
