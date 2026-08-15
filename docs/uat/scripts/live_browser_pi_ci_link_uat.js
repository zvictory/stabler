const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://msa.erpstable.com';
const OUT_DIR = path.join(__dirname, '../evidence/2026-08-15-pi-ci-linking-uat');
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');
const ARTIFACT_DIR = '/Users/zafar/.gemini/antigravity/brain/56e2e62a-4fc4-46b8-a3fe-5fda74c5cfba';

fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

async function runPiCiLinkingUAT() {
	console.log(`\n=== 🚀 Starting Real Browser Playwright UAT for PI -> CI Linking on ${BASE_URL} ===`);

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 1200 } });
	const page = await context.newPage();

	// 1. LOGIN
	console.log('\n--- 1. Login to Stabler SPA ---');
	await page.goto(`${BASE_URL}/stabler#/login`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');

	await page.waitForURL('**/stabler#/**', { timeout: 15000 });
	await page.waitForTimeout(2000);
	console.log('✅ Login successful!');

	// 2. Open ACC-PINV-2026-01155 Purchase Invoice Form
	console.log('\n--- 2. Inspecting Purchase Invoice ACC-PINV-2026-01155 ---');
	const piUrl = `${BASE_URL}/stabler#/purchasing/invoices/ACC-PINV-2026-01155`;
	await page.goto(piUrl, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3500);

	const piScreenshotPath = path.join(SCREENSHOT_DIR, '01_acc_pinv_2026_01155_form.png');
	await page.screenshot({ path: piScreenshotPath, fullPage: true });
	fs.copyFileSync(piScreenshotPath, path.join(ARTIFACT_DIR, '01_acc_pinv_2026_01155_form.png'));
	console.log('📸 Saved PI Form screenshot to:', piScreenshotPath);

	// 3. Create a NEW Transport Purchase Invoice for Carrier ALN linked to CI-2026-04387
	console.log('\n--- 3. Creating a New Transport Purchase Invoice via Purchasing ---');
	await page.goto(`${BASE_URL}/stabler#/purchasing/invoices/new`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	const newPiScreenshotPath = path.join(SCREENSHOT_DIR, '02_new_purchase_invoice_form.png');
	await page.screenshot({ path: newPiScreenshotPath, fullPage: true });
	fs.copyFileSync(newPiScreenshotPath, path.join(ARTIFACT_DIR, '02_new_purchase_invoice_form.png'));
	console.log('📸 Saved New PI Form screenshot to:', newPiScreenshotPath);

	// Fill Supplier: ALN
	const supplierInput = page.locator('input[placeholder*="supplier"], input[placeholder*="Supplier"]').first();
	if (await supplierInput.isVisible().catch(() => false)) {
		console.log('Filling supplier: ALN...');
		await supplierInput.fill('ALN');
		await page.waitForTimeout(1000);
		const firstOption = page.locator('.dropdown-menu .dropdown-item, .typeahead-item').first();
		if (await firstOption.isVisible().catch(() => false)) {
			await firstOption.click();
		}
	}

	// 4. Inspect Commercial Invoice CI-2026-04387
	console.log('\n--- 4. Inspecting Commercial Invoice CI-2026-04387 Form ---');
	await page.goto(`${BASE_URL}/stabler#/imports/commercial-invoices/CI-2026-04387`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3500);

	const ciFullScreenshot = path.join(SCREENSHOT_DIR, '03_ci_2026_04387_full_page.png');
	await page.screenshot({ path: ciFullScreenshot, fullPage: true });
	fs.copyFileSync(ciFullScreenshot, path.join(ARTIFACT_DIR, '03_ci_2026_04387_full_page.png'));
	console.log('📸 Saved CI Form screenshot to:', ciFullScreenshot);

	// Scroll to Landed Cost card
	const lcCard = page.locator('h3:has-text("Landed cost (UZS)")').first();
	if (await lcCard.isVisible().catch(() => false)) {
		await lcCard.scrollIntoViewIfNeeded();
		await page.waitForTimeout(1000);
		const lcScreenshot = path.join(SCREENSHOT_DIR, '04_ci_landed_cost_table.png');
		await page.screenshot({ path: lcScreenshot });
		fs.copyFileSync(lcScreenshot, path.join(ARTIFACT_DIR, '04_ci_landed_cost_table.png'));
		console.log('📸 Saved Landed Cost table screenshot to:', lcScreenshot);
	}

	await browser.close();
	console.log('\n=== ✅ Playwright UAT Finished ===\n');
}

runPiCiLinkingUAT().catch(err => {
	console.error('Fatal error in Playwright UAT:', err);
	process.exit(1);
});
