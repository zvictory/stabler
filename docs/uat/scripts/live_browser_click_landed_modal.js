const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

(async () => {
	console.log('Launching browser for Interactive Landed Charges Modal Entry...');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	try {
		console.log('Step 1: Logging in as sourcing.mikas@erpstable.com...');
		await page.goto('https://mikas.erpstable.com/stabler#/', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		const emailInput = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
		if (await emailInput.count() > 0 && await emailInput.isVisible()) {
			await emailInput.fill('sourcing.mikas@erpstable.com');
			await page.fill('input[type="password"]', 'MikasUAT2026!');
			await page.click('button[type="submit"]');
			await page.waitForTimeout(3000);
		}

		console.log('Step 2: Navigating to Sourcing Workspace for CRM-DEAL-2026-00098...');
		await page.goto('https://mikas.erpstable.com/stabler#/tender/sourcing?deal=CRM-DEAL-2026-00098', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(5000); // Allow complete workspace data fetch

		console.log('Step 3: Clicking Landed Cost button on first quotation row...');
		const landedBtn = page.locator('button:has-text("Landed cost")').first();
		await landedBtn.waitFor({ state: 'visible', timeout: 15000 });
		await landedBtn.click();
		await page.waitForTimeout(3000);

		console.log('Step 4: Verifying Landed Charges Editor Modal in Browser UI...');
		const modal = page.locator('.modal-dialog, .modal-content').first();
		await modal.waitFor({ state: 'visible', timeout: 10000 });

		await page.screenshot({ path: path.join(ARTIFACTS_DIR, '08_landed_charges_editor_modal.png'), fullPage: true });
		console.log('Screenshot saved: 08_landed_charges_editor_modal.png');

		console.log('\n--- INTERACTIVE LANDED CHARGES MODAL TEST PASSED ---');
	} catch (err) {
		console.error('Error testing Landed Charges modal:', err);
	} finally {
		await browser.close();
	}
})();
