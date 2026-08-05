const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

async function runNormalUserProformaUITest() {
	console.log('=== STARTING NORMAL USER UI TEST: PROFORMA INVOICE CREATE & EDIT ===');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	// Step 1: Normal User Login via UI
	console.log('1. User navigating to https://msa.erpstable.com/stabler#/login');
	await page.goto('https://msa.erpstable.com/stabler#/login', { waitUntil: 'networkidle' });
	await page.waitForTimeout(1000);

	console.log('2. User entering login credentials in UI form...');
	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');
	await page.waitForTimeout(3000);

	await page.evaluate(() => {
		localStorage.setItem('stabler.activeCompany', 'MSA');
	});

	// Step 2: Navigate to Proforma list and click + New Proforma button
	console.log('3. User navigating to /imports/proformas...');
	await page.goto('https://msa.erpstable.com/stabler#/imports/proformas', { waitUntil: 'networkidle' });
	await page.waitForTimeout(2000);

	console.log('4. User clicking "+ New Proforma" button...');
	await page.click('button:has-text("New Proforma")');
	await page.waitForTimeout(2000);

	// Step 3: Fill Proforma Details via DOM UI interactions
	console.log('5. User filling Supplier in Typeahead...');
	const supplierInput = page.locator('input[placeholder*="supplier"], input[placeholder*="Tedarikçi"]').first();
	await supplierInput.click();
	await supplierInput.fill('Al Super Frozen Food Private Limited');
	await page.waitForTimeout(1000);

	const supplierOption = page.locator('.typeahead-option, .dropdown-item, div:has-text("Al Super Frozen Food Private Limited")').first();
	if (await supplierOption.isVisible()) {
		await supplierOption.click();
	} else {
		await page.keyboard.press('Enter');
	}
	await page.waitForTimeout(1000);

	console.log('6. User filling Supplier PI No...');
	const piRefInput = page.locator('input[placeholder*="FIR/25-26"], input[placeholder*="PI No"]').first();
	await piRefInput.fill('PI-MSA-2026-010');

	// Step 4: Click "+ Add row" in UI for 4 items totaling 10 FCL
	console.log('7. User adding 4 item rows totaling 10 FCL (1700 boxes)...');
	const addRowBtn = page.locator('button:has-text("Add row")').first();

	// Define 4 item specifications totaling 10 FCL (1,700 boxes)
	const itemsData = [
		{ category: 'BUFFALO COMPENSATED', product: 'BUFFALO COMPENSATED_6', boxes: '680', weight: '16', rate: '5.50', docs: '5.00' }, // 4 FCL
		{ category: 'BUFFALO COMPENSATED', product: 'BUFFALO COMPENSATED_5', boxes: '510', weight: '16', rate: '5.40', docs: '4.90' }, // 3 FCL
		{ category: 'BUFFALO COMPENSATED', product: 'BUFFALO COMPENSATED_4', boxes: '340', weight: '16', rate: '5.30', docs: '4.80' }, // 2 FCL
		{ category: 'BELLY FAT', product: 'BELLY FAT', boxes: '170', weight: '16', rate: '3.80', docs: '3.50' }                      // 1 FCL
	];

	for (let i = 0; i < itemsData.length; i++) {
		const item = itemsData[i];
		await addRowBtn.click();
		await page.waitForTimeout(400);

		const tr = page.locator('tbody tr').nth(i);
		const selects = tr.locator('select');
		if (await selects.count() >= 2) {
			await selects.nth(0).selectOption({ label: item.category }).catch(() => selects.nth(0).selectOption({ index: 1 }));
			await selects.nth(1).selectOption({ value: item.product }).catch(() => selects.nth(1).selectOption({ index: 1 }));
		}

		const inputs = tr.locator('input:not(.money-input)');
		if (await inputs.count() >= 2) {
			await inputs.nth(0).fill(item.boxes);
			await inputs.nth(1).fill(item.weight);
		}

		const moneyInputs = tr.locator('input.money-input, input[type="text"]');
		if (await moneyInputs.count() >= 2) {
			await moneyInputs.nth(0).fill(item.rate);
			await moneyInputs.nth(1).fill(item.docs);
		}
	}

	await page.waitForTimeout(1000);
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '24_ui_proforma_4items_10fcl_filled.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 24_ui_proforma_4items_10fcl_filled.png saved.');

	// Step 5: User clicks Save button in UI header
	console.log('8. User clicking "Save" button in UI header...');
	await page.click('button:has-text("Save")');
	await page.waitForTimeout(4000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '25_ui_proforma_created_saved.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 25_ui_proforma_created_saved.png saved.');

	// Step 6: User EDIT Proforma via UI (e.g. typing Remarks)
	console.log('9. User editing Remarks field in UI...');
	const remarksTextarea = page.locator('textarea').first();
	if (await remarksTextarea.isVisible()) {
		await remarksTextarea.fill('User UI Test: 10 FCL order (4 items) created and confirmed with supplier Al Super.');
	}

	console.log('10. User clicking "Save" button again to commit edit...');
	await page.click('button:has-text("Save")');
	await page.waitForTimeout(3000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '26_ui_proforma_edited_saved.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 26_ui_proforma_edited_saved.png saved.');

	await browser.close();
}

runNormalUserProformaUITest().catch((err) => {
	console.error('Error in normal user UI test:', err);
});
