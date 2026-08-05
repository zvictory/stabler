const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

async function testUiEarmarkSyncAndFooter() {
	console.log('=== STARTING LIVE BROWSER UI TEST FOR SYNC TOTALS & ITEMS FOOTER SAVE ===');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	// Step 1: Login via UI
	console.log('1. User logging in to https://msa.erpstable.com...');
	await page.goto('https://msa.erpstable.com/stabler#/login', { waitUntil: 'networkidle' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');
	await page.waitForTimeout(3000);

	// Step 2: Open Proforma PI-MSA-2026-010
	console.log('2. User navigating to Proforma /imports/proformas/PI-MSA-2026-010...');
	await page.goto('https://msa.erpstable.com/stabler#/imports/proformas/PI-MSA-2026-010', { waitUntil: 'networkidle' });
	await page.waitForTimeout(3000);

	// Step 3: Add another item line to cause a mismatch between Items Total and Bank+Cash
	console.log('3. User adding an item row to change Agreed Total...');
	const addRowBtn = page.locator('button:has-text("Add row")').first();
	await addRowBtn.click();
	await page.waitForTimeout(500);

	const lastRow = page.locator('tbody tr').last();
	const selects = lastRow.locator('select');
	if (await selects.count() >= 2) {
		await selects.nth(0).selectOption({ index: 1 }).catch(() => {});
		await selects.nth(1).selectOption({ index: 1 }).catch(() => {});
	}
	const inputs = lastRow.locator('input:not(.money-input)');
	if (await inputs.count() >= 2) {
		await inputs.nth(0).fill('170'); // 1 FCL (170 boxes)
		await inputs.nth(1).fill('16');  // 16 kg
	}
	const moneyInputs = lastRow.locator('input.money-input, input[type="text"]');
	if (await moneyInputs.count() >= 2) {
		await moneyInputs.nth(0).fill('5.00');
		await moneyInputs.nth(1).fill('4.50');
	}

	await page.waitForTimeout(1000);
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '27_ui_proforma_sync_button_warning.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 27_ui_proforma_sync_button_warning.png saved.');

	// Step 4: Click "Sync Totals" or "Sync Prepayment Totals" button in UI
	console.log('4. User clicking "Sync Totals" button in UI to automatically align Bank + Cash with Agreed Total...');
	const syncBtn = page.locator('button:has-text("Sync Totals"), button:has-text("Sync Prepayment Totals")').first();
	await syncBtn.click();
	await page.waitForTimeout(1000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '28_ui_proforma_synced_totals_active_save.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 28_ui_proforma_synced_totals_active_save.png saved.');

	// Step 5: Click "Update & Save" button located right inside the Items footer card!
	console.log('5. User clicking "Update & Save" button right inside the Items card footer...');
	const footerSaveBtn = page.locator('.card-footer button:has-text("Update & Save"), .card-footer button:has-text("Save Proforma")').first();
	await footerSaveBtn.click();
	await page.waitForTimeout(4000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '29_ui_proforma_updated_saved_footer.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 29_ui_proforma_updated_saved_footer.png saved.');

	await browser.close();
}

testUiEarmarkSyncAndFooter().catch((err) => {
	console.error('Error in live browser UI test:', err);
});
