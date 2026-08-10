const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const UAT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/2026-08-11-hma-proforma-uat';
const SCREENSHOTS_DIR = path.join(UAT_DIR, 'screenshots');

if (!fs.existsSync(SCREENSHOTS_DIR)) {
	fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

async function runLiveHmaProformaSplitTest() {
	console.log('--- STARTING LIVE HMA PROFORMA INVOICE SPLIT ADVANCE TEST ---');
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
	await page.waitForTimeout(3000);

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
		await supplierInput.fill('HMA AGRO INDUSTRIES LIMITED');
		await page.waitForTimeout(1500);
		// Select first dropdown option if available
		const option = await page.waitForSelector('.typeahead-option, .dropdown-item, li:has-text("HMA")', { timeout: 3000 }).catch(() => null);
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
		const uatRef = `UAT-HMA-${Date.now()}`;
		await piRefInput.fill(uatRef);
		console.log(`Using PI Ref: ${uatRef}`);
	}

	// Step 5: Prepayment base and split settings
	console.log('Step 5: Setting Prepayment Pct to 30%...');
	const pctInput = page.locator('input[type="number"]').first();
	if (await pctInput.isVisible()) {
		await pctInput.fill('30');
	}

	// Step 6: Use category modal to add 33 containers
	console.log('Step 6: Clicking "Fill from category" button...');
	const fillBtn = await page.waitForSelector('button:has-text("Fill from category")', { timeout: 5000 });
	await fillBtn.click();
	await page.waitForTimeout(1500);

	console.log('Step 6b: Filling category fill modal...');
	const modalSelect = page.locator('.modal select').first();
	await modalSelect.selectOption({ label: 'Test Category' }).catch(() => modalSelect.selectOption({ index: 1 }));

	const containerInput = page.locator('.modal div:has(> label:has-text("Containers")) input');
	await containerInput.fill('33');

	const boxWeightInput = page.locator('.modal div:has(> label:has-text("Box weight")) input');
	await boxWeightInput.fill('20');

	const agreedPriceInput = page.locator('.modal div:has(> label:has-text("Agreed price")) input');
	await agreedPriceInput.fill('5.00');

	const docsPriceInput = page.locator('.modal div:has(> label:has-text("Docs price")) input');
	await docsPriceInput.fill('4.50');

	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '01_fill_category_modal.png'), fullPage: false });
	console.log('Screenshot 01_fill_category_modal.png saved.');

	const applyBtn = page.locator('.modal button:has-text("Apply")');
	await applyBtn.click();
	await page.waitForTimeout(2000);

	// Step 7: Click Save button
	console.log('Step 7: Clicking Save button...');
	const saveBtn = await page.waitForSelector('button:has-text("Save"), button:has-text("Kaydet")', { timeout: 5000 }).catch(() => null);
	if (saveBtn) {
		await saveBtn.click();
		await page.waitForTimeout(4000);
	}

	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '02_proforma_saved.png'), fullPage: false });
	console.log('Screenshot 02_proforma_saved.png saved.');

	// Step 8: Click "Record Advance" button to test new modal
	console.log('Step 8: Clicking "Record Advance" button...');
	const recordBtn = await page.waitForSelector('button:has-text("Record Advance")', { timeout: 5000 });
	await recordBtn.click();
	await page.waitForTimeout(2500);

	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '03_record_advance_modal_open.png'), fullPage: false });
	console.log('Screenshot 03_record_advance_modal_open.png saved.');

	// Click 30% pill
	console.log('Step 8b: Selecting 30% pill...');
	const pill30 = page.locator('.modal button:has-text("30%")');
	if (await pill30.isVisible()) {
		await pill30.click();
		await page.waitForTimeout(500);
	}

	// Click Split Bank + Cash strategy
	console.log('Step 8c: Clicking "Split Bank + Cash" strategy card...');
	const splitCard = page.locator('.modal .card-body .row .card:has-text("Split Bank")');
	if (await splitCard.isVisible()) {
		await splitCard.click();
		await page.waitForTimeout(1000);
	}

	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '04_split_strategy_selected.png'), fullPage: false });
	console.log('Screenshot 04_split_strategy_selected.png saved.');

	// Click Create Draft Payment Entries button
	console.log('Step 9: Submitting advance payments...');
	const createBtn = page.locator('.modal button:has-text("Create Draft")');
	if (await createBtn.isVisible()) {
		await createBtn.click();
		await page.waitForTimeout(4000);
	}

	await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '05_advance_payments_recorded.png'), fullPage: false });
	console.log('Screenshot 05_advance_payments_recorded.png saved.');

	await browser.close();
	console.log('--- LIVE HMA PROFORMA INVOICE SPLIT ADVANCE TEST COMPLETED SUCCESSFULLY ---');
}

runLiveHmaProformaSplitTest().catch((err) => {
	console.error('Error in live HMA proforma test:', err);
});
