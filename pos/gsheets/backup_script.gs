// BPS backup to Google Sheets. BPS sends one table at a time; each goes to its own tab, replacing what was there.
// "PAYMENT REFERENCES" tab: each backup lists BPS's pending bills there, keeping what you typed in PAYMENT REFERENCE
// and CHANNEL (e.g. from home). BPS's Records → "Get Sheet References" puts them on the bills, then writes DONE.
// Set up: in your Google Sheet, Extensions → Apps Script, replace everything with this, Save,
// then Deploy → New deployment → Web app (Execute as: Me, Who has access: Anyone) and copy the Web app URL into BPS.
// The password below must match BPS; keep this sheet private (don't share its link).
const PASSWORD = "__PASSWORD__";

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ ok: false, error: "Not a BPS backup" });
  }
  if (body.password !== PASSWORD) return reply({ ok: false, error: "Wrong password" });

  const lock = LockService.getScriptLock();
  lock.waitLock(60000);
  try {
    const book = SpreadsheetApp.getActiveSpreadsheet();
    if (body.action === "read_references") return reply({ ok: true, references: readReferences(book) });
    if (body.action === "mark_references") return reply({ ok: true, marked: markReferences(book, body.marks || []) });
    if (body.action === "pending_references") return reply({ ok: true, rows: writePending(book, body.rows || [], body.sent_at) });
    if (body.tab === REFS_TAB) return reply({ ok: false, error: "That tab is for typing references" });
    const sheet = book.getSheetByName(body.tab) || book.insertSheet(body.tab);
    const width = body.columns.length;
    const values = [body.columns].concat(body.rows);
    sheet.clearContents();
    if (sheet.getMaxColumns() < width) sheet.insertColumnsAfter(sheet.getMaxColumns(), width - sheet.getMaxColumns());
    if (sheet.getMaxRows() < values.length) sheet.insertRowsAfter(sheet.getMaxRows(), values.length - sheet.getMaxRows());
    // Formats first, so phone numbers and references stay text (leading zeros kept).
    body.formats.forEach((format, i) => {
      if (format && body.rows.length) sheet.getRange(2, i + 1, body.rows.length, 1).setNumberFormat(format);
    });
    sheet.getRange(1, 1, values.length, width).setValues(values);
    sheet.getRange(1, 1, 1, width).setFontWeight("bold");
    sheet.setFrozenRows(1);
    note(book, body.tab, body.rows.length, body.sent_at);
    return reply({ ok: true, rows: body.rows.length });
  } finally {
    lock.releaseLock();
  }
}

// "PAYMENT REFERENCES" tab: BPS's pending bills plus the columns typed by hand. Read by column name.
const REFS_TAB = "PAYMENT REFERENCES";
const REFS_HEADER = ["TXN DATE/TIME", "ACCOUNT", "BILLER", "BILL AMT", "DUE DATE", "BPS REFERENCE",
  "PAYMENT REFERENCE", "CHANNEL", "STATUS (filled by BPS)"];
const BPS_COLUMNS = 6; // the first six come from BPS

function referencesTab(book) {
  let sheet = book.getSheetByName(REFS_TAB);
  if (!sheet) {
    sheet = book.insertSheet(REFS_TAB, 0);
    sheet.getRange(1, 1, 1, REFS_HEADER.length).setValues([REFS_HEADER]).setFontWeight("bold");
    sheet.setFrozenRows(1);
  }
  return sheet;
}

// Every row as { row, bps_reference, payment_reference, channel, status }, using the header's column names.
function referenceRows(sheet) {
  const last = sheet.getLastRow();
  if (last < 2) return [];
  const width = sheet.getLastColumn();
  const header = sheet.getRange(1, 1, 1, width).getDisplayValues()[0].map((h) => String(h).trim().toUpperCase());
  const col = (name) => header.findIndex((h) => h.indexOf(name) === 0);
  const ref = col("BPS REFERENCE"), pay = col("PAYMENT REFERENCE"), channel = col("CHANNEL"), status = col("STATUS");
  return sheet.getRange(2, 1, last - 1, width).getDisplayValues().map((r, i) => ({
    row: i + 2,
    bps_reference: ref < 0 ? "" : String(r[ref]).trim(),
    payment_reference: pay < 0 ? "" : String(r[pay]).trim(),
    channel: channel < 0 ? "" : String(r[channel]).trim(),
    status: status < 0 ? "" : String(r[status]).trim(),
    statusColumn: status + 1,
  }));
}

// Rows with a payment reference typed and no STATUS yet.
function readReferences(book) {
  return referenceRows(referencesTab(book))
    .filter((r) => r.payment_reference && !r.status)
    .map((r) => ({ row: r.row, bps_reference: r.bps_reference, payment_reference: r.payment_reference, channel: r.channel, status: "" }));
}

// marks: [{ row, bps_reference, status }] → STATUS, only where the row still has that BPS reference
// (rows may have moved since BPS read them).
function markReferences(book, marks) {
  const sheet = referencesTab(book);
  const rows = referenceRows(sheet);
  let marked = 0;
  marks.forEach((m) => {
    const r = rows[m.row - 2];
    if (!r || r.statusColumn < 1 || r.bps_reference.toUpperCase() !== String(m.bps_reference).trim().toUpperCase()) return;
    sheet.getRange(m.row, r.statusColumn).setValue(m.status);
    marked++;
  });
  return marked;
}

// pending: [[txn, account, biller, amount, due, bps_reference], ...] from BPS. Rewrites the tab with them, carrying
// over what was typed for each BPS reference. Typed rows whose bill isn't pending any more (and aren't DONE) stay
// at the bottom marked NOT PENDING IN BPS, so nothing typed is lost; delete them once checked.
function writePending(book, pending, sentAt) {
  const sheet = referencesTab(book);
  const typed = {};
  const leftovers = [];
  const pendingKeys = {};
  pending.forEach((p) => { pendingKeys[String(p[5]).trim().toUpperCase()] = true; });
  referenceRows(sheet).forEach((r) => {
    if (!r.payment_reference && !r.channel) return;
    const key = r.bps_reference.toUpperCase();
    if (pendingKeys[key] && !/^DONE|^ALREADY/i.test(r.status)) typed[key] = r;
    else if (!pendingKeys[key] && !/^DONE|^ALREADY/i.test(r.status)) leftovers.push(r);
  });
  const old = sheet.getLastRow() > 1 ? sheet.getRange(2, 1, sheet.getLastRow() - 1, BPS_COLUMNS).getDisplayValues() : [];
  const oldByKey = {};
  old.forEach((r) => { oldByKey[String(r[5]).trim().toUpperCase()] = r; });

  const values = [REFS_HEADER].concat(
    pending.map((p) => {
      const t = typed[String(p[5]).trim().toUpperCase()];
      return p.concat([t ? t.payment_reference : "", t ? t.channel : "", ""]);
    }),
    leftovers.map((r) => (oldByKey[r.bps_reference.toUpperCase()] || ["", "", "", "", "", r.bps_reference])
      .slice(0, BPS_COLUMNS).concat([r.payment_reference, r.channel, "NOT PENDING IN BPS"]))
  );
  const width = REFS_HEADER.length;
  sheet.clearContents();
  if (sheet.getMaxColumns() < width) sheet.insertColumnsAfter(sheet.getMaxColumns(), width - sheet.getMaxColumns());
  if (sheet.getMaxRows() < values.length) sheet.insertRowsAfter(sheet.getMaxRows(), values.length - sheet.getMaxRows());
  sheet.getRange(1, 1, Math.max(sheet.getMaxRows(), values.length), width).setNumberFormat("@"); // text: keeps leading zeros
  if (values.length > 1) sheet.getRange(2, 4, values.length - 1, 1).setNumberFormat("#,##0.00");
  sheet.getRange(1, 1, values.length, width).setValues(values);
  sheet.getRange(1, 1, 1, width).setFontWeight("bold");
  sheet.setFrozenRows(1);
  note(book, REFS_TAB, pending.length, sentAt);
  return pending.length;
}

// "BACKUP INFO" tab: when each tab was last updated.
function note(book, tab, rows, sentAt) {
  const info = book.getSheetByName("BACKUP INFO") || book.insertSheet("BACKUP INFO", 0);
  if (info.getLastRow() === 0) info.appendRow(["TAB", "ROWS", "UPDATED"]);
  const tabs = info.getRange(1, 1, info.getLastRow(), 1).getValues().map((r) => r[0]);
  const at = tabs.indexOf(tab);
  const row = [tab, rows, sentAt];
  if (at === -1) info.appendRow(row);
  else info.getRange(at + 1, 1, 1, 3).setValues([row]);
}

function reply(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}
