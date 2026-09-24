/** Offline integration check for the page-context scraper; no ICAM traffic. */
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(path.join(os.homedir(), '.cache', 'codex-runtimes',
  'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright'));
const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const template = await fs.readFile(path.join(root, 'tools', 'icam_inpage_scraper.template.js'), 'utf8');
const script = template.replace('__BARCODES__', '["TEST123"]')
  .replace('__COMPLETED__', '[]');
const mainUrl = 'https://copa.ifs.cloud/maintenix/web/task/TaskDetails.jsp';
const tabs = ['TaskExecution', 'FaultInformation', 'TaskInformation', 'Scheduling', 'History', 'Warranty'];
function taskHtml(tab) {
  return `<!doctype html><title>Fault Details - HALON EXPIRY [TEST123]</title>
    <form name="frmHeaderSearch" action="/maintenix/servlet/ScanBarcode"><input id="idBarcodeSearchInput"></form>
    <div id="idBarcode">TEST123</div><div id="idAcft">Boeing test</div><div id="idInv">Halon</div>
    ${tabs.map(name => `<a id="idTab${name}_link" href="${mainUrl}?aTab=idTab${name}">${name}</a>`).join('')}
    <div id="idTab${tab}">${tab === 'TaskExecution' ? `
      <table id="idTableTaskExecution"><tr><td>Description</td></tr><tr><td>Halon expiry due 22-OCT-2026</td></tr></table>
      <div id="idStepBlocks"><div id="idStep1">Step 1</div><table id="idStepSkill1"><tr><td id="idDescription1">Inspect bottle</td></tr></table></div>
      <table id="idTablePartRequirementList"><tr><td>Part</td></tr>
      <tr><td>Part</td><td>Part No</td><td>Serial No / Batch No</td><td>Part No</td><td>Serial No / Batch No</td></tr>
      <tr><td>x</td><td>898052</td><td><a href="/maintenix/web/inventory/InventoryDetails.jsp?aInventory=1">SERIAL1</a></td><td>898052</td><td></td></tr></table>` : 'Tab content'}
      ${tab === 'Scheduling' ? '<table id="idTableDue"><tr><td>Interval</td></tr><tr><td>22-OCT-2026</td></tr></table>' : ''}
    </div>`;
}
const inventoryHtml = `<!doctype html><title>Inventory Details - (SN: SERIAL1)</title>
  <div id="idCellShelfLifeExpiry">22-OCT-2026 00:00 UTC</div>
  <div id="idCellReleaseRemarks">NEXT HT DUE 31-MAY-2036</div>
  <div id="idTabDetails">Shelf-Life Expiry: 22-OCT-2026. NEXT HT DUE 31-MAY-2036</div>`;
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ acceptDownloads: true });
  await page.route('**/*', route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.hostname === '127.0.0.1') {
      return route.fulfill({ status: request.method() === 'OPTIONS' ? 204 : 200,
        headers: { 'Access-Control-Allow-Origin': 'https://copa.ifs.cloud',
          'Access-Control-Allow-Methods': 'POST, OPTIONS',
          'Access-Control-Allow-Headers': 'content-type',
          'Access-Control-Allow-Private-Network': 'true' }, body: '' });
    }
    if (url.pathname.endsWith('/InventoryDetails.jsp')) {
      return route.fulfill({ status: 200, contentType: 'text/html', body: inventoryHtml });
    }
    if (url.pathname.endsWith('/ScanBarcode')) {
      return route.fulfill({ status: 200, contentType: 'text/html', body: taskHtml('TaskExecution') });
    }
    const tab = url.searchParams.get('aTab')?.replace('idTab', '') || 'TaskExecution';
    return route.fulfill({ status: 200, contentType: 'text/html', body: taskHtml(tab) });
  });
  await page.goto(mainUrl);
  await page.evaluate(script);
  const result = await page.evaluate(() => window.__icamScrape);
  const record = result.results[0];
  if (result.failures.length || record?.barcode !== 'TEST123' ||
    Object.keys(record.sections).length !== 6 ||
    record.inventory_details[0]?.shelf_life_expiry !== '22-OCT-2026 00:00 UTC') {
    throw new Error(`In-page scraper check failed: ${JSON.stringify(result.failures)}`);
  }
  console.log('In-page scraper integration check passed.');
} finally { await browser.close(); }
