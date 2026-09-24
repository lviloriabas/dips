/**
 * Batch extractor for the Codex Computer Use browser session.
 * Run tools/icam_json_receiver.py locally, sign in to ICAM in Edge, then call
 * extractIcamBatch({ icamTab, receiverTab, limit: 120 }).
 * Only the barcode search, page tabs, and Show All Step Content are used in ICAM.
 */

const TABS = ["TaskExecution", "FaultInformation", "TaskInformation", "Scheduling", "History", "Warranty"];
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function readTab(tab, key) {
  return tab.playwright.evaluate((name) => {
    const query = (selector) => document.querySelector(selector);
    const value = (selector) => query(selector)?.innerText?.trim() || "";
    const rows = (selector) => [...(query(selector)?.querySelectorAll("tr") || [])]
      .map((row) => [...row.cells].map((cell) => cell.innerText.trim()));
    const output = { text: value("#idTab" + name) };
    if (name === "TaskExecution") {
      const execution = rows("#idTableTaskExecution");
      output.description = execution.find((row, i) => i > 0 && execution[i - 1].join(" ").trim() === "Description")?.join(" ").trim() || "";
      output.steps = value("#idStepBlocks");
      output.part_requirements = rows("#idTablePartRequirementList");
      output.tool_requirements = rows("#idTableToolRequirement");
    }
    if (name === "FaultInformation") {
      output.selected_reference = output.text.match(/Selected Reference\s+Reference:\s*([^\n]+)/)?.[1]?.trim() || null;
    }
    if (name === "TaskInformation") {
      const area = query("#idGrpAttachments")?.closest("tr")?.nextElementSibling;
      output.technical_references = [...document.querySelectorAll('#idTabTaskInformation [id="idDocumentReference"]')]
        .map((element) => element.innerText.trim()).filter(Boolean);
      output.attachments = {
        count: area?.querySelectorAll('input[name="aAttachment"]').length || 0,
        text: area?.innerText?.trim() || "",
      };
    }
    if (name === "Scheduling") output.intervals = rows("#idTableDue");
    return output;
  }, key);
}

async function waitForTab(tab, key) {
  for (let i = 0; i < 30; i++) {
    const data = await readTab(tab, key);
    if (data.text) return data;
    await pause(400);
  }
  throw new Error(`ICAM did not load ${key}`);
}

async function captureDip(tab, barcode) {
  let shown = await tab.playwright.evaluate(() => document.querySelector("#idBarcode")?.innerText.trim());
  if (shown !== barcode) {
    const search = tab.playwright.locator("#idBarcodeSearchInput");
    await search.fill(barcode);
    await search.press("Enter");
    for (let i = 0; i < 30; i++) {
      shown = await tab.playwright.evaluate(() => document.querySelector("#idBarcode")?.innerText.trim());
      if (shown === barcode) break;
      await pause(400);
    }
    if (shown !== barcode) throw new Error(`ICAM returned ${shown || "no barcode"} for ${barcode}`);
  }

  const record = {
    barcode,
    source: "ICAM",
    captured_at_utc: new Date().toISOString(),
    page_title: null,
    page_url: null,
    aircraft: null,
    inventory: null,
    sections: {},
  };
  for (const key of TABS) {
    const link = tab.playwright.locator("#idTab" + key + "_link");
    if (await link.count()) await link.click();
    let data = await waitForTab(tab, key);
    if (key === "TaskExecution") {
      if (/Step \d+/.test(data.steps) && !data.steps.includes("Description:")) {
        const originalLength = data.steps.length;
        await tab.playwright.getByRole("link", { name: "Show All Step Content" }).click();
        for (let i = 0; i < 30; i++) {
          data = await readTab(tab, key);
          if (data.steps.length > originalLength + 30) break;
          await pause(400);
        }
        if (data.steps.length <= originalLength + 30) throw new Error(`Step content did not expand for ${barcode}`);
      }
      record.page_title = await tab.title();
      record.page_url = await tab.url();
      record.aircraft = await tab.playwright.evaluate(() => document.querySelector("#idAcft")?.innerText.trim() || null);
      record.inventory = await tab.playwright.evaluate(() => document.querySelector("#idInv")?.innerText.trim() || null);
    }
    record.sections[key] = data;
  }
  return record;
}

async function saveBatch(receiverTab, batch) {
  await receiverTab.goto("http://127.0.0.1:8765/");
  await receiverTab.playwright.getByRole("textbox", { name: "records" }).fill(JSON.stringify(batch));
  await receiverTab.playwright.getByRole("button", { name: "Save locally" }).click();
  await receiverTab.goto("http://127.0.0.1:8765/");
  const completed = await receiverTab.playwright.evaluate(() => JSON.parse(document.querySelector("#completed").textContent));
  for (const { barcode } of batch) {
    if (!completed.includes(barcode)) throw new Error(`Local save failed for ${barcode}`);
  }
}

export async function extractIcamBatch({ icamTab, receiverTab, limit = 120, batchSize = 6 }) {
  await receiverTab.goto("http://127.0.0.1:8765/");
  const input = await receiverTab.playwright.evaluate(() => ({
    barcodes: JSON.parse(document.querySelector("#barcodes").textContent),
    completed: JSON.parse(document.querySelector("#completed").textContent),
  }));
  const completed = new Set(input.completed);
  const selected = input.barcodes.filter((barcode) => !completed.has(barcode)).slice(0, limit);
  const failures = [];
  let batch = [];
  for (const barcode of selected) {
    try {
      batch.push(await captureDip(icamTab, barcode));
    } catch (error) {
      failures.push({ barcode, error: String(error) });
    }
    if (batch.length >= batchSize) {
      await saveBatch(receiverTab, batch);
      batch = [];
    }
  }
  if (batch.length) await saveBatch(receiverTab, batch);
  return { attempted: selected.length, failed: failures };
}
