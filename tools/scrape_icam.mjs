/**
 * Read-only ICAM DIP scraper. Connect to an existing Edge window started with
 * remote debugging, or sign in once in a clean Edge window.
 *
 * Usage: node tools/scrape_icam.mjs --cdp http://127.0.0.1:9222
 *        node tools/scrape_icam.mjs [--limit 10] [--concurrency 3]
 * Re-running the command skips barcodes already present in icam_dips.json.
 *
 * The only ICAM requests made after sign-in are POST ScanBarcode (search) and
 * GET TaskDetails (the six display tabs). No update form is submitted.
 */
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const INPUT = path.join(ROOT, 'data', 'dips_dataset.json');
const OUTPUT = path.join(ROOT, 'data', 'icam_dips.json');
const FAILURES = path.join(ROOT, 'data', 'icam_scrape_failures.json');
const ORIGIN = 'https://copa.ifs.cloud';
const START = `${ORIGIN}/maintenix/common/ToDoList.jsp`;
const TABS = ['TaskExecution', 'FaultInformation', 'TaskInformation', 'Scheduling', 'History', 'Warranty'];

function option(name, fallback) {
  const i = process.argv.indexOf(name);
  return i < 0 ? fallback : process.argv[i + 1];
}

const limit = Number(option('--limit', Infinity));
const concurrency = Number(option('--concurrency', 3));
const cdpEndpoint = option('--cdp', null);
if (!(limit > 0) || !(concurrency >= 1 && concurrency <= 6)) {
  throw new Error('--limit must be positive and --concurrency must be 1..6');
}

const require = createRequire(import.meta.url);
function loadPlaywright() {
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    'playwright',
    path.join(os.homedir(), '.cache', 'codex-runtimes', 'codex-primary-runtime',
      'dependencies', 'node', 'node_modules', 'playwright'),
  ].filter(Boolean);
  for (const candidate of candidates) {
    try { return require(candidate); } catch { /* try the next installed location */ }
  }
  throw new Error('Playwright is missing. Install it from npm or set PLAYWRIGHT_MODULE.');
}

function sameOrigin(url) {
  const parsed = new URL(url, ORIGIN);
  if (parsed.origin !== ORIGIN) throw new Error(`Unexpected ICAM destination: ${parsed.origin}`);
  return parsed.href;
}

async function atomicJson(file, data) {
  const temporary = `${file}.tmp`;
  await fs.writeFile(temporary, JSON.stringify(data, null, 2), 'utf8');
  await fs.rename(temporary, file);
}

async function parseHtml(parserPage, html, tabName = 'TaskExecution') {
  return parserPage.evaluate(({ html, tabName }) => {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const simple = (node) => (node?.textContent || '').replace(/\s+/g, ' ').trim();
    const rendered = (node) => {
      if (!node) return '';
      const walk = (part) => {
        if (part.nodeType === Node.TEXT_NODE) return part.nodeValue.replace(/[\t\r\n ]+/g, ' ');
        if (part.nodeType !== Node.ELEMENT_NODE) return '';
        const tag = part.tagName.toLowerCase();
        if (['script', 'style', 'noscript', 'input', 'select', 'button', 'svg'].includes(tag)) return '';
        if (tag === 'br') return '\n';
        const content = Array.from(part.childNodes, walk).join('');
        if (tag === 'td' || tag === 'th') return `${content.trim()}\t`;
        if (['tr', 'p', 'div', 'section', 'article', 'li', 'h1', 'h2', 'h3', 'h4'].includes(tag)) return `${content.trim()}\n`;
        return content;
      };
      return walk(node).replace(/ *\t */g, '\t').replace(/[ \t]+\n/g, '\n')
        .replace(/\n[ \t]+/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    };
    const rows = (selector) => Array.from(doc.querySelectorAll(`${selector} tr`), row =>
      Array.from(row.cells || [], cell => rendered(cell).replace(/\t+$/g, '').trim()));
    const root = doc.querySelector(`#idTab${tabName}`);
    const output = { text: rendered(root) };
    if (tabName === 'TaskExecution') {
      const execution = rows('#idTableTaskExecution');
      output.description = execution.find((row, i) =>
        i > 0 && execution[i - 1].join(' ').trim() === 'Description')?.join(' ').trim() || '';
      output.steps = rendered(doc.querySelector('#idStepBlocks'));
      output.step_items = Array.from(doc.querySelectorAll('[id^="idStepSkill"]'))
        .filter(el => /^idStepSkill\d+$/.test(el.id))
        .map(el => {
          const number = el.id.match(/\d+$/)[0];
          return {
            number: Number(number),
            status: simple(doc.querySelector(`#idStep${number}`)),
            description: rendered(doc.querySelector(`#idDescription${number}`)),
            text: rendered(el),
          };
        });
      output.part_requirements = rows('#idTablePartRequirementList');
      output.tool_requirements = rows('#idTableToolRequirement');
      const partTable = doc.querySelector('#idTablePartRequirementList');
      const serialHeaders = Array.from(partTable?.querySelectorAll('tr') || [])
        .find(row => Array.from(row.cells).filter(cell => /Serial No \/ Batch No/i.test(simple(cell))).length >= 2);
      const serialColumns = serialHeaders ? Array.from(serialHeaders.cells)
        .flatMap((cell, index) => /Serial No \/ Batch No/i.test(simple(cell)) ? [index] : []) : [];
      output.part_inventory_links = Array.from(partTable?.querySelectorAll('tr') || [])
        .flatMap(row => serialColumns.flatMap((column, index) => {
          const cell = row.cells[column];
          const link = cell?.querySelector('a[href*="InventoryDetails.jsp"]');
          return link ? [{ role: index === 0 ? 'removed_part' : 'installed_part',
            serial_no: simple(link), href: link.getAttribute('href') }] : [];
        }));
    }
    if (tabName === 'FaultInformation') {
      output.selected_reference = output.text.match(/Selected Reference\s+Reference:\s*([^\n]+)/)?.[1]?.trim() || null;
    }
    if (tabName === 'TaskInformation') {
      const attachmentArea = doc.querySelector('#idGrpAttachments')?.closest('tr')?.nextElementSibling;
      output.technical_references = Array.from(
        doc.querySelectorAll('#idTabTaskInformation [id="idDocumentReference"]'), simple).filter(Boolean);
      output.attachments = {
        count: attachmentArea?.querySelectorAll('input[name="aAttachment"]').length || 0,
        text: rendered(attachmentArea),
      };
    }
    if (tabName === 'Scheduling') output.intervals = rows('#idTableDue');
    return {
      title: doc.title,
      barcode: simple(doc.querySelector('#idBarcode')),
      aircraft: simple(doc.querySelector('#idAcft')),
      inventory: simple(doc.querySelector('#idInv')),
      header_text: rendered(doc.querySelector('#idGBox1')),
      header_fields: Object.fromEntries([
        'idAcft', 'idInv', 'idBarcode', 'idLogbook', 'idDue', 'idEstimatedDuration',
        'idWONumber', 'idWOLineNumber',
      ].map(id => [id, simple(doc.getElementById(id))])),
      search_action: doc.querySelector('form[name="frmHeaderSearch"]')?.getAttribute('action') || null,
      tab_links: Object.fromEntries(Array.from(doc.querySelectorAll('a[id^="idTab"][id$="_link"]'))
        .map(a => [a.id.slice(5, -5), a.getAttribute('href')])),
      section: output,
    };
  }, { html, tabName });
}

async function readResponse(response, barcode, label) {
  const url = response.url();
  if (response.status() >= 400) throw new Error(`${label}: HTTP ${response.status()}`);
  if (!url.startsWith(`${ORIGIN}/maintenix/web/task/TaskDetails.jsp`)) {
    throw new Error(`${label}: session or redirect ended at ${new URL(url).pathname}`);
  }
  const html = await response.text();
  if (!html.includes(barcode)) throw new Error(`${label}: barcode ${barcode} absent from response`);
  return { html, url };
}

async function retry(label, operation) {
  let last;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try { return await operation(); }
    catch (error) {
      last = error;
      if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 700 * attempt));
    }
  }
  throw new Error(`${label}: ${last.message}`);
}

async function capture(context, parserPage, barcode, searchAction) {
  const response = await retry(`search ${barcode}`, () => context.request.post(searchAction, {
    form: { aBarcodeScan: barcode, aReturnToPage: '' },
    headers: { Referer: START },
    timeout: 30000,
  }));
  const executionPage = await readResponse(response, barcode, 'search');
  const parsed = await parseHtml(parserPage, executionPage.html, 'TaskExecution');
  if (parsed.barcode !== barcode) throw new Error(`ICAM returned ${parsed.barcode || 'no barcode'} for ${barcode}`);
  if (!parsed.section.text) throw new Error(`TaskExecution is empty for ${barcode}`);
  const record = {
    barcode,
    source: 'ICAM',
    captured_at_utc: new Date().toISOString(),
    page_title: parsed.title,
    page_url: executionPage.url,
    aircraft: parsed.aircraft,
    inventory: parsed.inventory,
    header_text: parsed.header_text,
    header_fields: parsed.header_fields,
    sections: { TaskExecution: parsed.section },
  };
  for (const tabName of TABS.slice(1)) {
    const href = parsed.tab_links[tabName];
    if (!href) throw new Error(`${tabName} link is missing for ${barcode}`);
    const url = sameOrigin(href);
    const tabResponse = await retry(`${barcode} ${tabName}`, () => context.request.get(url, {
      headers: { Referer: executionPage.url }, timeout: 30000,
    }));
    const tabPage = await readResponse(tabResponse, barcode, tabName);
    const tab = await parseHtml(parserPage, tabPage.html, tabName);
    if (tab.barcode !== barcode || !tab.section.text) {
      throw new Error(`${tabName} did not contain expected DIP data for ${barcode}`);
    }
    record.sections[tabName] = tab.section;
  }
  record.inventory_details = [];
  const dateSensitive = /hydro|\bht\b|fumig|shelf[ -]?life|expir|extinguisher|halon|oxygen bottle|oxygen cylinder|botella|\bfak\b|first aid kit|weight due/i
    .test(`${parsed.title}\n${parsed.section.description}\n${parsed.section.steps}`);
  if (dateSensitive) {
    for (const part of parsed.section.part_inventory_links.slice(0, 4)) {
      const url = sameOrigin(part.href);
      try {
        const response = await retry(`${barcode} inventory ${part.serial_no}`,
          () => context.request.get(url, { timeout: 30000 }));
        if (response.status() >= 400 || !response.url().startsWith(`${ORIGIN}/maintenix/web/inventory/InventoryDetails.jsp`)) {
          throw new Error(`Inventory HTTP ${response.status()} or unexpected redirect`);
        }
        const html = await response.text();
        const details = await parserPage.evaluate(({ html, part, url }) => {
          const doc = new DOMParser().parseFromString(html, 'text/html');
          const value = id => (doc.getElementById(id)?.textContent || '').replace(/\s+/g, ' ').trim();
          return {
            role: part.role, serial_no: part.serial_no, url, title: doc.title,
            shelf_life_expiry: value('idCellShelfLifeExpiry') || null,
            release_remarks: value('idCellReleaseRemarks') || null,
            release_date: value('idCellReleaseDate') || null,
            inventory_barcode: value('idBarcode') || null,
            text: (doc.querySelector('#idTabDetails')?.textContent || '').replace(/[\t ]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim(),
          };
        }, { html, part, url });
        if (!details.title.includes(part.serial_no)) throw new Error('Inventory serial mismatch');
        record.inventory_details.push(details);
      } catch (error) {
        record.inventory_details.push({ role: part.role, serial_no: part.serial_no, url,
          error: error.message });
      }
    }
  }
  return record;
}

async function main() {
  const source = JSON.parse(await fs.readFile(INPUT, 'utf8'));
  const existing = JSON.parse(await fs.readFile(OUTPUT, 'utf8'));
  const barcodes = source.records.map(item => item.barcode);
  const saved = new Map(existing.records.map(record => [record.barcode, record]));
  const todo = barcodes.filter(barcode => !saved.has(barcode)).slice(0, limit);
  if (!todo.length) { console.log('All requested barcodes already have ICAM data.'); return; }
  const { chromium } = loadPlaywright();
  const browser = cdpEndpoint
    ? await chromium.connectOverCDP(cdpEndpoint)
    : await chromium.launch({ channel: 'msedge', headless: false });
  const context = cdpEndpoint ? browser.contexts()[0] : await browser.newContext({ acceptDownloads: false });
  if (!context) throw new Error('No Edge browser context is available.');
  const loginPage = cdpEndpoint
    ? context.pages().find(page => page.url().startsWith(`${ORIGIN}/maintenix/`))
    : await context.newPage();
  if (!loginPage) throw new Error('Open an ICAM page in the connected Edge window first.');
  const failures = [];
  let completedThisRun = 0;
  let checkpoint = Promise.resolve();
  let fatal = null;
  function saveProgress() {
    checkpoint = checkpoint.then(() => atomicJson(OUTPUT, {
      ...existing, records: barcodes.map(code => saved.get(code)).filter(Boolean),
    }));
    return checkpoint;
  }
  try {
    if (!cdpEndpoint) {
      await loginPage.goto(START, { waitUntil: 'domcontentloaded', timeout: 60000 });
      console.log('Sign in to ICAM in the Edge window. Scraping starts when Barcode Search appears.');
      await loginPage.locator('#idBarcodeSearchInput').waitFor({ state: 'visible', timeout: 10 * 60 * 1000 });
    } else if (!(await loginPage.locator('#idBarcodeSearchInput').isVisible())) {
      throw new Error('The connected ICAM tab is not signed in.');
    }
    const action = await loginPage.locator('form[name="frmHeaderSearch"]').getAttribute('action');
    if (!action) throw new Error('Barcode search form is missing after login.');
    const searchAction = sameOrigin(action);
    let cursor = 0;
    async function worker(number) {
        while (!fatal && cursor < todo.length) {
          const barcode = todo[cursor++];
          try {
            const record = await capture(context, loginPage, barcode, searchAction);
            saved.set(barcode, record);
            completedThisRun++;
            if (completedThisRun % 10 === 0) {
              await saveProgress();
              console.log(`${saved.size}/${barcodes.length} DIPs saved`);
            }
          } catch (error) {
            failures.push({ barcode, error: error.message });
            console.error(`Worker ${number} ${barcode}: ${error.message}`);
            if (/session or redirect ended/.test(error.message)) fatal = error;
          }
        }
    }
    await Promise.all(Array.from({ length: Math.min(concurrency, todo.length) }, (_, i) => worker(i + 1)));
    if (fatal) throw fatal;
  } finally {
    await checkpoint;
    await saveProgress();
    await atomicJson(FAILURES, { attempted: todo.length, succeeded: completedThisRun, failures });
    if (!cdpEndpoint) {
      await context.close();
      await browser.close();
    }
  }
  console.log(`Done: ${completedThisRun} new DIPs, ${failures.length} failures, ${saved.size}/${barcodes.length} total.`);
}

async function selfTest() {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    const html = `<!doctype html><title>Fault Details - TEST [TEST123]</title>
      <form name="frmHeaderSearch" action="/maintenix/servlet/ScanBarcode"></form>
      <div id="idBarcode">TEST123</div><div id="idAcft">Boeing test</div>
      <a id="idTabScheduling_link" href="/maintenix/web/task/TaskDetails.jsp?aTab=idTabScheduling">Scheduling</a>
      <div id="idTabTaskExecution"><table id="idTableTaskExecution">
        <tr><td>Description</td></tr><tr><td>Inspection note</td></tr></table>
        <div id="idStepBlocks"><div id="idStep1">Step 1 - Complete</div>
        <table id="idStepSkill1"><tr><td id="idDescription1">Inspect item</td></tr></table></div></div>
      <div id="idTabTaskInformation"><table><tr><td id="idGrpAttachments">Attachments</td></tr>
        <tr><td>photo.png<input name="aAttachment"></td></tr></table>
        <div id="idDocumentReference">AMM 01</div></div>
      <div id="idTabScheduling"><table id="idTableDue"><tr><td>Interval</td></tr>
        <tr><td>5</td><td>Cycles</td></tr></table></div>`;
    const execution = await parseHtml(page, html, 'TaskExecution');
    const task = await parseHtml(page, html, 'TaskInformation');
    const scheduling = await parseHtml(page, html, 'Scheduling');
    if (execution.barcode !== 'TEST123' || execution.section.description !== 'Inspection note' ||
      execution.section.step_items[0]?.description !== 'Inspect item' ||
      task.section.attachments.count !== 1 || task.section.technical_references[0] !== 'AMM 01' ||
      scheduling.section.intervals[1]?.[0] !== '5') {
      throw new Error('HTML extraction self-test failed');
    }
    console.log('HTML extraction self-test passed.');
  } finally { await browser.close(); }
}

if (process.argv.includes('--self-test')) await selfTest();
else await main();
