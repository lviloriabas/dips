/*
 * Read-only ICAM scraper for the Console of an already signed-in ICAM tab.
 * Generated file: data/icam_inpage_scraper.js. Paste that complete file once
 * into the Console. It uses the tab's own ICAM session; no credentials are read.
 */
(async () => {
  'use strict';
  const ORIGIN = 'https://copa.ifs.cloud';
  const TABS = ['TaskExecution', 'FaultInformation', 'TaskInformation', 'Scheduling', 'History', 'Warranty'];
  const barcodes = __BARCODES__;
  const previouslySaved = new Set(__COMPLETED__);
  const todo = barcodes.filter(code => !previouslySaved.has(code));
  const searchForm = document.querySelector('form[name="frmHeaderSearch"]');
  if (location.origin !== ORIGIN || !searchForm || !document.querySelector('#idBarcodeSearchInput')) {
    throw new Error('Open a signed-in ICAM DIP page before running this script.');
  }
  let searchUrl = searchForm.action;
  const results = [];
  const failures = [];
  const unsent = [];
  let pending = [];
  let cursor = 0;
  let stopped = false;
  let saveQueue = Promise.resolve();
  window.__icamScrape = { results, failures, unsent, startedAt: new Date().toISOString() };

  const simple = node => (node?.textContent || '').replace(/\s+/g, ' ').trim();
  function rendered(node) {
    if (!node) return '';
    const walk = part => {
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
  }
  function parse(html, tabName) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const rows = selector => Array.from(doc.querySelectorAll(`${selector} tr`), row =>
      Array.from(row.cells || [], cell => rendered(cell).replace(/\t+$/g, '').trim()));
    const output = { text: rendered(doc.querySelector(`#idTab${tabName}`)) };
    if (tabName === 'TaskExecution') {
      const execution = rows('#idTableTaskExecution');
      output.description = execution.find((row, i) =>
        i > 0 && execution[i - 1].join(' ').trim() === 'Description')?.join(' ').trim() || '';
      output.steps = rendered(doc.querySelector('#idStepBlocks'));
      output.step_items = Array.from(doc.querySelectorAll('[id^="idStepSkill"]'))
        .filter(el => /^idStepSkill\d+$/.test(el.id)).map(el => {
          const number = el.id.match(/\d+$/)[0];
          return { number: Number(number), status: simple(doc.querySelector(`#idStep${number}`)),
            description: rendered(doc.querySelector(`#idDescription${number}`)), text: rendered(el) };
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
      output.attachments = { count: attachmentArea?.querySelectorAll('input[name="aAttachment"]').length || 0,
        text: rendered(attachmentArea) };
    }
    if (tabName === 'Scheduling') output.intervals = rows('#idTableDue');
    return {
      title: doc.title,
      barcode: simple(doc.querySelector('#idBarcode')),
      aircraft: simple(doc.querySelector('#idAcft')),
      inventory: simple(doc.querySelector('#idInv')),
      header_text: rendered(doc.querySelector('#idGBox1')),
      header_fields: Object.fromEntries(['idAcft', 'idInv', 'idBarcode', 'idLogbook', 'idDue',
        'idEstimatedDuration', 'idWONumber', 'idWOLineNumber']
        .map(id => [id, simple(doc.getElementById(id))])),
      search_action: doc.querySelector('form[name="frmHeaderSearch"]')?.getAttribute('action') || null,
      tab_links: Object.fromEntries(Array.from(doc.querySelectorAll('a[id^="idTab"][id$="_link"]'))
        .map(a => [a.id.slice(5, -5), a.getAttribute('href')])),
      section: output,
    };
  }
  async function getPage(url, options = {}, expectedPath = '/maintenix/web/task/TaskDetails.jsp') {
    const resolved = new URL(url, ORIGIN);
    if (resolved.origin !== ORIGIN) throw new Error(`Unexpected destination: ${resolved.origin}`);
    let error;
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const response = await fetch(resolved, { credentials: 'same-origin', ...options });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const allowedPaths = Array.isArray(expectedPath) ? expectedPath : [expectedPath];
        if (!allowedPaths.some(path => response.url.startsWith(`${ORIGIN}${path}`))) {
          stopped = true;
          throw new Error('The ICAM session ended; sign in again and rerun the script.');
        }
        return { url: response.url, html: await response.text() };
      } catch (caught) {
        error = caught;
        if (stopped) break;
        if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 700 * attempt));
      }
    }
    throw error;
  }
  function parseInventory(html, part) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const value = id => simple(doc.getElementById(id));
    return {
      role: part.role, serial_no: part.serial_no, part_no: part.part_no || null,
      url: new URL(part.href, ORIGIN).href, title: doc.title,
      shelf_life_expiry: value('idCellShelfLifeExpiry') || null,
      release_remarks: value('idCellReleaseRemarks') || null,
      release_date: value('idCellReleaseDate') || null,
      inventory_barcode: value('idBarcode') || null,
      text: rendered(doc.querySelector('#idTabDetails')),
    };
  }
  async function capture(barcode) {
    const first = await getPage(searchUrl, { method: 'POST', body: new URLSearchParams({
      aBarcodeScan: barcode, aReturnToPage: '',
    }) }, ['/maintenix/web/task/TaskDetails.jsp', '/maintenix/servlet/ScanBarcode']);
    const parsed = parse(first.html, 'TaskExecution');
    if (parsed.search_action) searchUrl = new URL(parsed.search_action, ORIGIN).href;
    if (parsed.barcode !== barcode || !parsed.section.text) {
      throw new Error(`Barcode mismatch or empty TaskExecution for ${barcode}`);
    }
    const sections = { TaskExecution: parsed.section };
    const otherTabs = await Promise.all(TABS.slice(1).map(async tabName => {
      const href = parsed.tab_links[tabName];
      if (!href) throw new Error(`${tabName} link missing for ${barcode}`);
      const page = await getPage(href);
      const tab = parse(page.html, tabName);
      if (tab.barcode !== barcode || !tab.section.text) {
        throw new Error(`${tabName} empty or incorrect for ${barcode}`);
      }
      return [tabName, tab.section];
    }));
    for (const [name, section] of otherTabs) sections[name] = section;
    const dateSensitive = /hydro|\bht\b|fumig|shelf[ -]?life|expir|extinguisher|halon|oxygen bottle|oxygen cylinder|botella|\bfak\b|first aid kit|weight due/i
      .test(`${parsed.title}\n${sections.TaskExecution.description}\n${sections.TaskExecution.steps}`);
    const inventory_details = [];
    if (dateSensitive) {
      for (const part of sections.TaskExecution.part_inventory_links.slice(0, 4)) {
        try {
          const page = await getPage(part.href, {}, '/maintenix/web/inventory/InventoryDetails.jsp');
          const details = parseInventory(page.html, part);
          if (!details.title.includes(part.serial_no)) throw new Error('Inventory serial mismatch');
          inventory_details.push(details);
        } catch (error) {
          inventory_details.push({ role: part.role, serial_no: part.serial_no,
            url: new URL(part.href, ORIGIN).href, error: String(error.message || error) });
        }
      }
    }
    return { barcode, source: 'ICAM', captured_at_utc: new Date().toISOString(),
      page_title: parsed.title, page_url: first.url, aircraft: parsed.aircraft,
      inventory: parsed.inventory, header_text: parsed.header_text,
      header_fields: parsed.header_fields, sections, inventory_details };
  }
  function download(records) {
    if (!records.length) return;
    const blob = new Blob([JSON.stringify({ source: 'ICAM browser scrape',
      captured_at_utc: new Date().toISOString(), records, failures }, null, 2)],
      { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `icam_dips_new_${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
  }
  window.downloadIcamDips = () => download(results);
  function queueSave(force = false) {
    if (!force && pending.length < 10) return;
    const batch = pending.splice(0);
    if (!batch.length) return;
    saveQueue = saveQueue.then(async () => {
      try {
        const response = await fetch('http://127.0.0.1:8765/api/batch', {
          method: 'POST', mode: 'cors', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(batch),
        });
        if (!response.ok) throw new Error(`Local save HTTP ${response.status}`);
      } catch (error) {
        unsent.push(...batch);
        if (unsent.length === batch.length) console.warn('Local receiver unavailable; a JSON download will be offered at the end.');
      }
    });
  }
  async function worker() {
    while (!stopped && cursor < todo.length) {
      const barcode = todo[cursor++];
      try {
        const record = await capture(barcode);
        results.push(record);
        pending.push(record);
        queueSave();
        if (results.length % 10 === 0) console.log(`${results.length}/${todo.length} new DIPs read`);
      } catch (error) {
        failures.push({ barcode, error: String(error.message || error) });
        console.error(barcode, error);
      }
    }
  }
  console.log(`ICAM: reading ${todo.length} remaining DIPs with 3 workers.`);
  await Promise.all([worker(), worker(), worker()]);
  queueSave(true);
  await saveQueue;
  if (unsent.length) download(unsent);
  console.log(`Finished: ${results.length} read, ${failures.length} failed, ${unsent.length} downloaded for manual import.`);
})();
