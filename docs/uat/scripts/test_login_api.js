const { chromium } = require('playwright');

(async () => {
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext();
	const page = await context.newPage();

	console.log('Sending login POST request...');
	const resp = await page.request.post('https://mikas.erpstable.com/api/method/login', {
		data: {
			usr: 'logistics.mikas@erpstable.com',
			pwd: 'MikasUAT2026!'
		}
	});

	console.log('Status code:', resp.status());
	console.log('Body:', await resp.text());

	await browser.close();
})();
