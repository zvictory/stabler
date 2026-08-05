const { chromium } = require('playwright');

(async () => {
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext();
	const page = await context.newPage();

	console.log('Step 1: Logging in via API request...');
	const loginResp = await page.request.post('https://mikas.erpstable.com/api/method/login', {
		data: {
			usr: 'logistics.mikas@erpstable.com',
			pwd: 'MikasUAT2026!'
		}
	});
	console.log('Login status:', loginResp.status());

	console.log('Step 2: Calling logist_board API endpoint...');
	const boardResp = await page.request.get('https://mikas.erpstable.com/api/method/stabler.api.tender.logist_board?company=Mikas');
	console.log('Board API status:', boardResp.status());
	console.log('Board API body:', await boardResp.text());

	await browser.close();
})();
