// BPS backup to Google Sheets. BPS sends one table at a time; each goes to its own tab, replacing what was there.
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
