'use strict';
const $ = id => document.getElementById(id);
let identities = {};
let loadSequence = 0;
function show(text, error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; }
async function api(path, method = 'GET', body) {
  const response = await fetch(path, { method, headers: { 'Content-Type': 'application/json', 'X-Lab-User': $('identity').value }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
  return data;
}
function text(tag, value, className) { const element = document.createElement(tag); element.textContent = value; if (className) element.className = className; return element; }
async function safe(action) { try { await action(); } catch (error) { show(error.message, true); } }
function action(container, label, callback, className = 'secondary') {
  const button = text('button', label, className); button.type = 'button';
  button.addEventListener('click', () => safe(async () => { button.disabled = true; try { await callback(); } finally { button.disabled = false; } })); container.append(button);
}
async function loadHistory(id) {
  const rows = await api(`/api/requests/${id}/history`);
  const table = document.createElement('table');
  const head = document.createElement('tr'); ['Time (UTC)', 'Actor', 'Change', 'Status', 'Comment'].forEach(value => head.append(text('th', value))); table.append(head);
  rows.forEach(row => { const tr = document.createElement('tr'); [row.created_at, row.actor, row.kind, `${row.from_status || 'created'} > ${row.to_status}`, row.comment].forEach(value => tr.append(text('td', value))); table.append(tr); });
  $('history').replaceChildren(table);
}
async function change(row, status) {
  let comment = '';
  if (status === 'rejected') { comment = window.prompt('Reason for rejection (at least three characters):'); if (comment === null) return; }
  const result = await api(`/api/requests/${row.id}/status`, 'PATCH', { status, version: row.version, comment });
  show(`Request changed to ${result.status}. Pending deliveries: ${result.pending_deliveries}.`); await load(); await loadHistory(row.id);
}
async function load() {
  const sequence = ++loadSequence;
  const role = identities[$('identity').value].role;
  document.querySelector('.layout').style.gridTemplateColumns = role === 'approver' ? '1fr' : '';
  $('create-panel').hidden = role !== 'requester'; $('approver-tools').hidden = role !== 'approver';
  const params = new URLSearchParams();
  if ($('status-filter').value) params.set('status', $('status-filter').value);
  if ($('department-filter').value) params.set('department', $('department-filter').value);
  const rows = await api(`/api/requests?${params}`);
  if (sequence !== loadSequence) return;
  $('list-summary').textContent = `${rows.length} visible request(s). The API returns up to 50 per page.`;
  $('requests').replaceChildren();
  if (!rows.length) $('requests').append(text('p', 'No requests match these filters.', 'hint'));
  rows.forEach(row => {
    const article = text('article', '', 'request'); article.dataset.requestId = row.id;
    const heading = text('h3', row.title); heading.append(text('span', row.status.replace('_', ' '), `badge ${row.status}`)); article.append(heading);
    article.append(text('p', `${row.department} / ${row.category} / ${row.requester} / quantity ${row.quantity} / EUR ${row.cost_eur}`));
    article.append(text('p', row.justification)); article.append(text('p', `Approval deadline: ${row.approval_deadline} / version ${row.version}`));
    const buttons = text('div', '', 'actions'); action(buttons, 'History', () => loadHistory(row.id));
    if (role === 'approver' && row.status === 'new') action(buttons, 'Start review', () => change(row, 'in_review'));
    if (role === 'approver' && row.status === 'in_review') { action(buttons, 'Approve', () => change(row, 'approved'), 'approve'); action(buttons, 'Reject', () => change(row, 'rejected'), 'reject'); }
    if (role === 'requester' && row.status === 'approved') action(buttons, 'Confirm done', () => change(row, 'done'));
    article.append(buttons); $('requests').append(article);
  });
}
$('request-form').addEventListener('submit', event => { event.preventDefault(); safe(async () => {
  const fields = Object.fromEntries(new FormData(event.target)); fields.quantity = Number(fields.quantity); fields.approval_deadline += ':00Z';
  const result = await api('/api/requests', 'POST', fields); show(`Request created. Pending deliveries: ${result.pending_deliveries}.`); event.target.reset(); setDeadline(); await load();
}); });
function setDeadline() { $('deadline').value = new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 16); }
['identity', 'status-filter', 'department-filter'].forEach(id => $(id).addEventListener('change', () => safe(load)));
$('refresh').addEventListener('click', () => safe(load));
$('remind').addEventListener('click', () => safe(async () => { const result = await api('/api/reminders', 'POST'); show(`Reminder check: ${result.queued} queued.`); }));
$('retry').addEventListener('click', () => safe(async () => { const result = await api('/api/deliveries/retry', 'POST'); show(`Deliveries sent: ${result.sent}; failed: ${result.failed}.`); }));
safe(async () => { identities = await api('/api/identities'); setDeadline(); await load(); });
