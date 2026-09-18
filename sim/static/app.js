/* DoneWise simulator: live MCP receipts with an explicit offline fixture fallback.

   Every state, time, counter and spoken phrase on screen comes from the receipt JSON.

   Only Clara's utterances and the narrative titles per turn (PRD §5.1) are script copy. */

(() => {

'use strict';



const FIXTURE_URL = '../fixtures/story-3min.json';

const root = document.getElementById('dw-evening');

const get = id => root.querySelector('#de-' + id);



/* Script copy per state (PRD §5.1). Utterances only; nothing here describes a result. State 2b has no user bubble. */

const SCRIPT = {

  '1':  { user: 'Book the plumber tomorrow nine to ten and pay the sixty-dollar deposit to Ridge Plumbing.',

          title: 'Tomorrow, a little more settled.', sub: 'Clara plans her next day from the kitchen.', next: 'Clara says yes' },

  '2':  { user: 'Yes, charge it.',

          title: 'Your OK, for this task only.', sub: 'Clara confirms the amount and the payee.', next: 'A few seconds later' },

  '2b': { user: null,

          title: 'The agent checked on its own.', sub: 'The agent checked the operation on its own.', next: 'Clara changes her plan' },

  '3':  { user: "I'm running late. Move the plumber to ten.",

          title: 'Asking is not the same as done.', sub: 'The calendar answers, and the read-back decides.', next: 'Clara asks to try again' },

  '4':  { user: 'Try that again.',

          title: 'Same task, read back again.', sub: 'Same task, new attempt.', next: 'Clara asks for a recap' },

  '5':  { user: 'Recap tomorrow. And what did you charge?',

          title: 'Only what it checked, and when.', sub: 'A recap built from the receipts, not from memory.', next: 'Back to the start' }

};

const CHAPTERS = [ { state: '1', label: 'Book and pay' }, { state: '3', label: 'Change the plan' } ];



const FAULT_TEXT = {

  drop_response_after_write: 'response dropped after the write',

  ack_without_write: 'acknowledged without a write',

  read_unavailable: 'read unavailable',

  concurrent_edit: 'concurrent edit',

  registry_down: 'registry down'

};

const OUTCOME_TEXT = {

  VERIFIED: { text: 'Verified', tone: 'ok' },

  PENDING: { text: 'Checking the result', tone: 'pending' },

  NEEDS_APPROVAL: { text: 'Waiting for your OK · nothing charged', tone: 'pending' },

  NEEDS_INPUT: { text: 'Needs your answer', tone: 'pending' },

  NOT_OBSERVED: { text: 'Change not confirmed', tone: 'pending' },

  UNKNOWN: { text: 'Result not checked yet', tone: 'pending' },

  REJECTED: { text: 'Not charged', tone: 'pending' }

};

const SOURCE_TEXT = {

  fake_calendar: 'sandbox calendar', fake_payments: 'sandbox payments',

  google_calendar: 'Google Calendar', stripe_test: 'Stripe (test mode)'

};

const CONNECTED_SOURCES = new Set(['google_calendar', 'stripe_test']);



/* ---------- formatting (all times shown in the run's timezone) ---------- */

let TZ = 'America/Los_Angeles';

const fmt = (iso, opts) => iso ? new Intl.DateTimeFormat('en-US', Object.assign({ timeZone: TZ }, opts)).format(new Date(iso)) : '—';

const clock = iso => fmt(iso, { hour: 'numeric', minute: '2-digit' });

const clockSec = iso => fmt(iso, { hour: 'numeric', minute: '2-digit', second: '2-digit' });

const dayOf = iso => fmt(iso, { weekday: 'short', month: 'short', day: 'numeric' });

const range = t => t ? `${clock(t.start)}–${clock(t.end)}` : '—';

const money = t => t ? new Intl.NumberFormat('en-US', { style: 'currency', currency: t.currency, minimumFractionDigits: t.amount_minor % 100 ? 2 : 0 }).format(t.amount_minor / 100) : '—';

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

const isPayment = r => r.action === 'PAYMENT_CHARGE';

const isRecap = (tool, r) => tool === 'receipts_recap' || Array.isArray(r.items);



/* ---------- state ---------- */

let LIVE = null, LIVE_BUSY = false, LIVE_STEP = 0, LIVE_ERROR = "", eventSource = null;
let controlBusy = false, recognizing = null, speaking = false;

let STATES = [];

let index = 0;

let receiptIndex = 0;   // which receipt of the current state the card shows

let auditOpen = false;

let lastSpokenState = null;

let voiceOn = true;

try { voiceOn = localStorage.getItem('dw-voice') !== 'off'; } catch (e) { /* storage unavailable */ }



/* ---------- small DOM helpers ---------- */

const text = (id, value) => { get(id).textContent = value; };

const el = (tag, cls, content) => { const n = document.createElement(tag); if (cls) n.className = cls; if (content != null) n.textContent = content; return n; };

function fill(target, pairs) {

  target.replaceChildren();

  for (const [label, value] of pairs) target.append(el('dt', null, label), el('dd', null, value));

}



/* ---------- receipt card: pure from receipt data ---------- */

/* meta: { tool, timezone, tabs: [{label, active, onSelect}] | undefined } */

function renderReceipt(receipt, meta) {

  const r = receipt, tool = meta.tool || '';

  if (meta.timezone) TZ = meta.timezone;



  // Tabs when a turn produced more than one receipt (turn 1: calendar + approval request).

  const tabs = get('receipt-tabs'); tabs.replaceChildren(); tabs.hidden = !(meta.tabs && meta.tabs.length > 1);

  (meta.tabs || []).forEach(t => { const b = el('button', 'de-receipt-tab', t.label); b.type = 'button'; b.setAttribute('aria-pressed', String(t.active)); b.addEventListener('click', t.onSelect); tabs.append(b); });



  const facts = [], evidence = [];

  let title, sub, value, valueSub, status, tone;



  if (isRecap(tool, r)) {

    title = 'Recap of this conversation'; sub = `run ${r.run_id || '—'} · generated ${clockSec(r.generated_at)}`;

    value = plural(r.items.length, 'result', 'results'); valueSub = 'from stored receipts · no new reads, no writes';

    status = `From receipts · generated ${clock(r.generated_at)}`; tone = 'ok';

    r.items.forEach(it => facts.push([it.summary, `${it.outcome} · ${clock(it.observed_at)}`]));

    evidence.push(`Composed by template from ${r.items.map(i => i.operation_id).join(', ')}. Each item keeps its own observation time.`);

  } else {

    const o = OUTCOME_TEXT[r.outcome] || { text: r.outcome, tone: 'pending' };

    tone = o.tone;

    status = o.text + (r.evidence ? ` · read back ${clockSec(r.evidence.observed_at)}` : '');

    if (isPayment(r)) {

      title = `${r.expected.payee} · ${r.expected.concept}`;

      sub = r.approval_request ? `Approval requested · expires ${clock(r.approval_request.expires_at)}` : r.approval_id ? `Approved · ${r.approval_id}` : 'Test charge';

      value = String(r.charges_applied ?? r.writes_applied);

      valueSub = `charges applied · ${money(r.expected)} ${r.outcome === 'NEEDS_APPROVAL' ? 'waiting for your OK' : r.outcome === 'PENDING' ? 'checking the result' : 'test charge'}`;

      facts.push(['Amount', money(r.expected)], ['Payee', r.expected.payee], ['Charges applied', String(r.charges_applied ?? '—')]);

      if (r.observed) facts.push(['Observed status', r.observed.status]);

      if (r.payment_intent_id) facts.push(['Payment intent', r.payment_intent_id]);

      if (r.approval_id) facts.push(['Approval', r.approval_id]);

      if (r.approval_request) facts.push(['Approval request', r.approval_request.approval_request_id]);

    } else {

      const isMove = r.action === 'CALENDAR_RESCHEDULE';

      title = isMove ? `Move: ${r.expected.title}` : r.expected.title;

      sub = `${dayOf(r.expected.start)} · ${r.expected.calendar_id}`;

      value = String(r.writes_applied);

      valueSub = `writes applied · ${isMove ? 'requested' : 'target'} ${range(r.expected)}`;

      if (isMove) facts.push(['Before', range(r.previous || meta.previous)], ['Requested', range(r.expected)]);

      else facts.push(['Requested', range(r.expected)]);

      facts.push(['Latest read', r.observed ? range(r.observed) : 'none'], ['Writes applied', String(r.writes_applied)]);

    }

    facts.push(['Attempts', `${r.attempt_id} · ${plural(r.automatic_retries, 'automatic retry', 'automatic retries')}`]);

    if (r.evidence) facts.push(['Read back at', clockSec(r.evidence.observed_at)]);

    facts.push(['Next action', r.next_action]);



    evidence.push(`Receipt ${r.receipt_id || '(none)'} · operation ${r.operation_id} · intent ${r.intent_id}.`);

    evidence.push(r.evidence

      ? `Evidence ${r.evidence.evidence_id} from ${SOURCE_TEXT[r.evidence.source] || r.evidence.source}, observed at ${clockSec(r.evidence.observed_at)} (${dayOf(r.evidence.observed_at)}, ${TZ})${r.evidence.version ? `, version ${r.evidence.version}` : ', no version'}.`

      : `No evidence yet: nothing was read back at ${clockSec(r.observed_at)}.`);

    evidence.push(`Reason code: ${r.reason_code || 'none'} · fault injected: ${r.fault_injected || 'off'} · claims allowed: ${r.allowed_claims.join(', ') || 'none'} · may claim success: ${r.may_claim_success ? 'yes' : 'no'}.`);

  }



  text('receipt-title', title); text('receipt-sub', sub);

  text('value', value); text('value-sub', valueSub);

  text('status-text', status); get('status').dataset.tone = tone; get('status').hidden = false;

  fill(get('facts'), facts);



  const ev = get('evidence'); ev.replaceChildren(); evidence.forEach(line => ev.append(el('p', null, line)));

  const hist = get('op-history'); hist.replaceChildren(); hist.hidden = !Array.isArray(r.history);

  (r.history || []).forEach(h => { const li = el('li'); li.append(el('b', null, `${clockSec(h.at)} · ${h.kind}`), ` ${h.summary}`); hist.append(li); });



  const tag = get('fault-tag'); tag.hidden = !r.fault_injected;

  tag.textContent = r.fault_injected ? `Fault injected: ${FAULT_TEXT[r.fault_injected] || r.fault_injected}` : '';

}



/* ---------- conversation, task log, audit, demo bar ---------- */

function spokenOf(state) { return state.receipts.map(x => x.result.spoken).filter(Boolean).join(' '); }

function lastReceipt(state) { return state.receipts[state.receipts.length - 1].result; }

function timeOf(state) { const r = lastReceipt(state); return r.observed_at || r.generated_at; }



function taskLog(upto) {

  // Latest receipt per operation among the receipts seen so far.

  const ops = new Map();

  STATES.slice(0, upto + 1).forEach(s => s.receipts.forEach(x => { if (x.result.operation_id) ops.set(x.result.operation_id, x.result); }));

  return [...ops.values()].map(r => {

    const when = r.evidence ? ` · ${clock(r.evidence.observed_at)}` : '';

    if (isPayment(r)) return [`${r.expected.concept} ${money(r.expected)}`, `${plural(r.charges_applied ?? 0, 'charge', 'charges')} · ${r.outcome}${when}`];

    const shown = r.observed || r.expected;

    return [r.expected.title, `${dayOf(shown.start)} · ${range(shown)} · ${r.outcome}${when}`];

  });

}



function renderAudit(upto) {

  const box = get('audit-ops'); box.replaceChildren();

  const seen = new Map();

  STATES.slice(0, upto + 1).forEach(s => s.receipts.forEach(x => { const r = x.result; if (!r.operation_id) return; if (!seen.has(r.operation_id)) seen.set(r.operation_id, []); seen.get(r.operation_id).push(r); }));

  if (!seen.size) { box.append(el('p', 'de-small', 'No operations yet.')); return; }

  for (const [op, list] of seen) {

    const wrap = el('div', 'de-audit-op'); wrap.append(el('b', null, `${op} · ${list[0].action}`));

    const ol = el('ol', 'de-hist-list');

    list.forEach(r => {

      const li = el('li'); li.append(el('b', null, `${clockSec(r.observed_at)} · ${r.attempt_id}`), ` ${r.outcome}${r.reason_code ? ` · ${r.reason_code}` : ''}${r.fault_injected ? ` · fault ${r.fault_injected}` : ''}`); ol.append(li);

      (r.history || []).forEach(h => { const sub = el('li'); sub.append(el('b', null, `${clockSec(h.at)} · ${h.kind}`), ` ${h.summary}`); ol.append(sub); });

    });

    wrap.append(ol); box.append(wrap);

  }

}



function renderState(stateId) {

  const i = STATES.findIndex(s => s.state === stateId); if (i < 0) return;

  index = i;

  const state = STATES[index], script = SCRIPT[state.state] || {}, primary = state.receipts[receiptIndex] || state.receipts[state.receipts.length - 1];

  const spoken = spokenOf(state);



  text('title', script.title || ''); text('subtitle', script.sub || ''); text('time', clock(timeOf(state)));

  get('user-wrap').hidden = !script.user; text('user', script.user || '');

  text('answer', spoken);

  text('source', `${state.receipts.map(x => x.tool).join(' + ')} · ${state.receipts.map(x => x.result.outcome || 'recap').join(' + ')}`);



  // Fault banner: driven by fault_injected on the receipts of this state.

  const fault = state.receipts.map(x => x.result.fault_injected).find(Boolean);

  get('gap').hidden = !fault; text('gap-text', fault ? `Fault injected: ${FAULT_TEXT[fault] || fault}` : '');



  // Approve button next to the approval request (amount and payee from approval_request).

  const req = state.receipts.map(x => x.result.approval_request).find(Boolean);

  get('approve-wrap').hidden = !req;

  if (req) { text('approve', `Approve ${money(req)} for ${req.payee}`); text('approve-note', `Bound to ${req.approval_request_id} · expires ${clock(req.expires_at)}`); }



  // Receipt card.

  renderReceipt(primary.result, {

    tool: primary.tool, timezone: TZ,

    tabs: state.receipts.map((x, k) => ({ label: x.tool, active: k === (state.receipts.indexOf(primary)), onSelect: () => { receiptIndex = k; renderState(state.state); } }))

  });

  get('contrast').hidden = state.state !== '2b';



  // Task log and audit from receipts seen so far.

  const records = get('records'); records.replaceChildren();

  taskLog(index).forEach(([name, value]) => { const row = el('div', 'de-record'); row.append(el('span', null, name), el('strong', null, value)); records.append(row); });

  renderAudit(index);



  // Earlier turns.

  const past = STATES.slice(0, index).filter(s => SCRIPT[s.state] && SCRIPT[s.state].user);

  const hist = get('history'); hist.replaceChildren();

  past.forEach(s => { const row = el('div', 'de-past'); row.append(el('b', null, clock(timeOf(s))), el('p', null, 'Clara: ' + SCRIPT[s.state].user), el('p', null, 'Alexa+: ' + spokenOf(s))); hist.append(row); });

  text('history-label', past.length ? `Earlier in this conversation · ${plural(past.length, 'turn', 'turns')}` : 'The conversation starts here');



  // Demo bar.

  text('next', script.next || 'Continue'); get('prev').disabled = index === 0;

  text('count', `State ${index + 1} of ${STATES.length} · from fixture`);

  const chapterIdx = CHAPTERS.map(c => STATES.findIndex(s => s.state === c.state));

  let current = 0; chapterIdx.forEach((ci, k) => { if (ci >= 0 && index >= ci) current = k; });

  root.querySelectorAll('.de-chapter').forEach((b, k) => b.setAttribute('aria-pressed', String(k === current)));



  if (lastSpokenState !== state.state) { lastSpokenState = state.state; speak(spoken); }

}



function go(i) { receiptIndex = Number.MAX_SAFE_INTEGER; renderState(STATES[(i + STATES.length) % STATES.length].state); }



/* ---------- voice ---------- */

// Text shown on screen keeps emojis and markdown; speech drops them so TTS never reads
// symbol names or asterisks aloud.
function speakable(phrase) {
  return String(phrase)
    .replace(/[\p{Extended_Pictographic}️‍\u{1F3FB}-\u{1F3FF}]/gu, '')
    .replace(/[*_`#]+/g, '')
    .replace(/\s*-\s+/g, '. ')
    .replace(/:\.\s/g, ': ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function speak(phrase) {

  const utterance = speakable(phrase);
  if (!voiceOn || !('speechSynthesis' in window) || !utterance || recognizing) return;

  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(utterance); u.lang = 'en-US';
    speaking = true; updateControls();
    u.onend = u.onerror = () => { speaking = false; updateControls(); };
    speechSynthesis.speak(u);
  } catch (_) { speaking = false; updateControls(); }

}

function renderVoice() { get('voice').setAttribute('aria-pressed', String(voiceOn)); text('voice', voiceOn ? 'Voice on' : 'Voice off'); }

get('voice').addEventListener('click', () => {

  voiceOn = !voiceOn; renderVoice();

  try { localStorage.setItem('dw-voice', voiceOn ? 'on' : 'off'); } catch (e) { /* ignore */ }

  if (!voiceOn && 'speechSynthesis' in window) { speechSynthesis.cancel(); speaking = false; updateControls(); }

});



const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

function note(msg) { const n = get('input-note'); n.hidden = !msg; n.textContent = msg || ''; }

if (!Recognition) { get('mic').disabled = true; get('mic').title = 'Speech recognition is not supported in this browser'; }

// Listening works like a speaker, not a walkie-talkie: recognition stays open across pauses and
// closes on its own after SILENCE_MS without speech, or earlier when the mic is tapped again.
// Chrome may end a continuous session by itself; while still armed we restart it and keep the text.
const SILENCE_MS = 2000, MAX_RESTARTS = 5;

get('mic').addEventListener('click', () => {

  if (!Recognition) { note('Speech recognition is not supported in this browser. Type instead.'); return; }

  if (recognizing) { recognizing.finish(); return; }

  if (!LIVE || LIVE_BUSY || controlBusy || ttsActive()) return;

  const committed = []; // final transcripts from earlier sessions of this same listen
  let rec = null, sessionFinal = '', interim = '', silence = null, restarts = 0;
  let armed = true, failed = false, sent = false;

  const transcript = () => [...committed, sessionFinal, interim].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();

  const resetSilence = () => { clearTimeout(silence); silence = setTimeout(finish, SILENCE_MS); };

  function finish() {
    if (!armed) return;
    armed = false; clearTimeout(silence);
    try { rec && rec.stop(); } catch (_) { done(); }
  }

  function done() {
    if (sent) return;
    sent = true; clearTimeout(silence); recognizing = null;
    get('mic').setAttribute('aria-pressed', 'false'); updateControls();
    const text = transcript();
    if (!failed && text) { get('text').value = text; sendText(text); }
    else if (!failed) note('No speech detected. Nothing sent; type instead.');
  }

  function startSession() {
    rec = new Recognition(); rec.lang = 'en-US'; rec.interimResults = true; rec.continuous = true;
    sessionFinal = ''; interim = '';

    rec.onresult = e => {
      const results = Array.from(e.results);
      sessionFinal = results.filter(r => r.isFinal).map(r => r[0].transcript).join(' ').trim();
      interim = results.filter(r => !r.isFinal).map(r => r[0].transcript).join(' ').trim();
      get('text').value = transcript();
      if (armed) resetSilence();
    };

    rec.onerror = e => {
      if (e.error === 'no-speech' && transcript()) return; // a long pause, we already have words
      if (e.error === 'aborted' && !armed) return;
      failed = true; armed = false;
      note(e.error === 'not-allowed' ? 'Microphone permission denied. Allow it for this origin or type instead.' :
        e.error === 'no-speech' ? 'No speech detected. Try the microphone again or type instead.' :
        `Microphone stopped (${e.error}). Nothing sent; type instead.`);
    };

    rec.onend = () => {
      if (sessionFinal) committed.push(sessionFinal);
      sessionFinal = ''; interim = '';
      if (armed && !failed && restarts < MAX_RESTARTS) { restarts++; startSession(); return; }
      done();
    };

    try { rec.start(); } catch (_) {
      failed = true; armed = false;
      note('Could not start the microphone. Type instead.'); done();
    }
  }

  recognizing = { finish }; updateControls();
  get('mic').setAttribute('aria-pressed', 'true');
  note('Listening… sends after a short pause, or tap the mic when you are done.');
  startSession();

});

get('input').addEventListener('submit', e => {

  e.preventDefault();

  const v = get('text').value.trim();

  if (LIVE && v) sendText(v);

  else note(v ? 'Fixture mode: use Continue to browse the recorded receipts.' : '');

});

function ttsActive() {
  return speaking || ('speechSynthesis' in window && (speechSynthesis.speaking || speechSynthesis.pending));
}

async function sendText(value) {
  if (LIVE_BUSY || controlBusy || recognizing) return;
  // The server permits only a pending affirmation in scripted mode.
  if (await postLive('/turn', {text: value})) get('text').value = '';
}



/* ---------- links ---------- */

get('link-receipt').addEventListener('click', e => {

  e.preventDefault();

  const state = STATES[index]; if (!state) return;

  const blob = new Blob([JSON.stringify({ run_id: RUN_ID, state: state.state, receipts: state.receipts }, null, 2)], { type: 'application/json' });

  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `receipt-${RUN_ID}-state-${state.state}.json`; a.click();

  setTimeout(() => URL.revokeObjectURL(a.href), 1000);

});

get('link-audit').addEventListener('click', e => {

  e.preventDefault(); auditOpen = !auditOpen;

  get('audit').hidden = !auditOpen; get('link-audit').setAttribute('aria-expanded', String(auditOpen));

});



/* ---------- approve (week 1: same effect as Continue, the fixture holds the approved result) ---------- */

get('approve').addEventListener('click', () => LIVE ? postLive('/approve') : go(index + 1));



/* ---------- demo controls ---------- */

get('next').addEventListener('click', () => LIVE ? postLive('/script/next') : go(index + 1));

get('prev').addEventListener('click', () => { if (index > 0) { if (LIVE) { index--; renderLive(); } else go(index - 1); } });



/* ---------- connected sessions; receipt speech is never paraphrased ---------- */

function liveBusy(value) {

  LIVE_BUSY = value;
  updateControls();
}

function updateControls() {
  if (!LIVE) return;
  const busy = LIVE_BUSY || controlBusy || Boolean(recognizing);
  get('next').disabled = busy || LIVE_STEP >= 5 || !LIVE.admin_enabled;
  get('approve').disabled = busy;
  get('input').querySelector('[type="submit"]').disabled = busy;
  get('text').disabled = busy;
  get('mic').disabled = recognizing ? false : (busy || !Recognition || ttsActive());
  get('session-mode').disabled = busy;
  get('session-timezone').disabled = busy;
  const armed = !LIVE.fault_state || Object.keys(LIVE.fault_state.armed).length > 0;
  get('fault-drop').disabled = get('fault-ack').disabled = busy || armed || LIVE.ui_mode !== 'voice';
  get('fault-refresh').disabled = busy;
}

async function postLive(path, body) {

  if (LIVE_BUSY || controlBusy || recognizing) return false;

  LIVE_ERROR = ''; liveBusy(true); note('');

  try {

    const response = await fetch(`/session/${LIVE.session_id}${path}`, {

      method: 'POST', headers: {'Content-Type': 'application/json'},

      body: body ? JSON.stringify(body) : undefined

    });

    if (!response.ok) throw new Error((await response.json()).detail || `HTTP ${response.status}`);

    return true;
  } catch (error) { LIVE_ERROR = error.message; note(error.message); liveBusy(false); return false; }

}

function renderFaults() {
  const state = LIVE.fault_state;
  const armed = state ? Object.entries(state.armed).map(([kind, uses]) => `${FAULT_TEXT[kind]} (${uses} remaining)`) : [];
  const fired = state?.fired || [];
  const parts = [];
  if (!state) parts.push('Fault state unavailable. Refresh before arming.');
  else {
    if (armed.length) parts.push(`Fault armed: ${armed.join(', ')}`);
    if (fired.length) parts.push(`Fault injected on purpose: ${FAULT_TEXT[fired.at(-1)]} · ${fired.length} consumed in this session`);
    if (!armed.length && !fired.length) parts.push('No faults armed or injected.');
  }
  if (LIVE.ui_mode === 'scripted') parts.push('Scripted session: faults arm automatically.');
  text('fault-state', parts.join(' '));
  get('gap').hidden = !armed.length && !fired.length;
  text('gap-text', parts[0]);
  updateControls();
}

async function refreshFaults() {
  const response = await fetch(`/session/${LIVE.session_id}/state`);
  if (!response.ok) throw new Error('Unable to refresh session state.');
  const state = await response.json();
  LIVE.fault_state = state.fault_state; LIVE_BUSY = state.busy; renderFaults();
}

async function faultControl(kind, uses) {
  if (LIVE_BUSY || controlBusy || recognizing) return;
  controlBusy = true; updateControls();
  try {
    if (kind) {
      const response = await fetch(`/session/${LIVE.session_id}/faults`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({kind, uses})
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Fault could not be armed.');
    }
    note('');
  } catch (error) { note(`${error.message} No automatic retry.`); }
  finally {
    try { await refreshFaults(); } catch (_) { LIVE.fault_state = null; renderFaults(); }
    controlBusy = false; updateControls();
  }
}

get('fault-drop').addEventListener('click', () => faultControl('drop_response_after_write', 1));
get('fault-ack').addEventListener('click', () => faultControl('ack_without_write', 2));
get('fault-refresh').addEventListener('click', () => faultControl());
// Mode and timezone both restart the conversation through the same endpoint.
async function restartSession() {
  const ui_mode = get('session-mode').value, timezone = get('session-timezone').value;
  const revert = () => { get('session-mode').value = LIVE.ui_mode; get('session-timezone').value = LIVE.timezone; };
  if (LIVE_BUSY || controlBusy || recognizing) { revert(); return; }
  controlBusy = true; updateControls();
  try {
    const response = await fetch(`/session/${LIVE.session_id}/mode`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ui_mode, timezone})
    });
    if (!response.ok) throw new Error((await response.json()).detail || 'Could not restart the session.');
    eventSource?.close();
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    speaking = false;
    loadSession(await response.json());
  } catch (error) { note(error.message); revert(); }
  finally { controlBusy = false; updateControls(); }
}
get('session-mode').addEventListener('change', restartSession);
get('session-timezone').addEventListener('change', restartSession);

function renderLive() {

  const state = STATES[index];

  text('count', `Step ${LIVE_STEP} of 5 · live MCP`);

  text('next', LIVE_STEP >= 5 ? 'Demo complete' : 'Continue');

  get('prev').disabled = index <= 0;

  text('audit-session', `MCP ${LIVE.protocol_version} · session ${LIVE.mcp_session_id || '—'} · run ${RUN_ID}`);

  if (!state) return;

  get('user-wrap').hidden = !state.user; text('user', state.user || '');

  text('answer', state.answer || '');

  const primary = state.receipts[receiptIndex] || state.receipts.at(-1);

  if (primary) {

    const r = primary.result;

    text('time', clock(r.observed_at || r.generated_at));

    text('source', `${primary.tool} · ${r.outcome || 'recap'}`);

    const previous = STATES.flatMap(s => s.receipts).find(x => x.result.operation_id === r.operation_id && x.result.previous)?.result.previous;
    renderReceipt(r, {tool: primary.tool, timezone: TZ, previous, tabs: state.receipts.map((x, k) => ({

      label: `${x.tool} · ${x.result.outcome || 'recap'}`, active: x === primary,

      onSelect: () => { receiptIndex = k; renderLive(); }

    }))});

    const req = r.approval_request;

    get('approve-wrap').hidden = !req || !LIVE.admin_enabled || LIVE_BUSY;

    if (req) { text('approve', `Approve ${money(req)} for ${req.payee}`); text('approve-note', `Bound to ${req.approval_request_id} · expires ${clock(req.expires_at)}`); }

  }

  const records = get('records'); records.replaceChildren();

  taskLog(index).forEach(([name, value]) => { const row = el('div', 'de-record'); row.append(el('span', null, name), el('strong', null, value)); records.append(row); });

  renderAudit(index);

  const history = get('history'); history.replaceChildren();

  STATES.slice(0, index).forEach(s => { const row = el('div', 'de-past'); row.append(el('p', null, `Clara: ${s.user || ''}`), el('p', null, s.answer || '')); history.append(row); });

  text('history-label', `Earlier in this conversation · ${plural(index, 'turn', 'turns')}`);

}

function connectEvents() {

  eventSource = new EventSource(`/session/${LIVE.session_id}/events`);

  const replayThrough = LIVE.event_cursor || 0;
  const on = (name, fn) => eventSource.addEventListener(name, e => fn(JSON.parse(e.data), Number(e.lastEventId) <= replayThrough));

  on('user', data => {

    STATES.push({state: String(STATES.length + 1), user: data.text, receipts: [], answer: ''});

    index = STATES.length - 1; receiptIndex = Number.MAX_SAFE_INTEGER;

    get('approve-wrap').hidden = true; renderLive();

  });

  on('status', (data, replayed) => {
    if (replayed) return;

    if (data.step != null) LIVE_STEP = data.step;

    liveBusy(data.status !== 'idle');

    note(data.status === 'idle' ? LIVE_ERROR : data.status);

    renderLive();

  });

  on('receipt', data => {

    if (!STATES.length) STATES.push({state: '1', receipts: [], answer: ''});

    index = STATES.length - 1;

    STATES[index].receipts.push(data);

    STATES[index].answer = data.result.spoken;

    receiptIndex = Number.MAX_SAFE_INTEGER;

    renderLive();

  });

  on('assistant', (data, replayed) => {

    if (STATES.length) STATES.at(-1).answer = data.text;

    text('answer', data.text); if (!replayed) speak(data.text);

    if (data.source === 'model') text('source', 'Model · no operation result');

  });

  on('fault', (data, replayed) => {
    if (replayed) return;
    LIVE.fault_state = data.state; renderFaults();
  });

  eventSource.addEventListener('open', () => {
    refreshFaults().catch(() => { LIVE.fault_state = null; renderFaults(); });
  });

  eventSource.addEventListener('error', e => {

    if (e.data) { LIVE_ERROR = JSON.parse(e.data).message; note(LIVE_ERROR); }

    else note('Event stream disconnected. Reconnecting to the same session…');

  });

}

async function tryConnect() {

  let response, saved;

  try { saved = sessionStorage.getItem('donewise-session'); } catch (_) { /* no storage */ }

  if (saved) response = await fetch(`/session/${saved}/state`);

  if (!response || !response.ok) response = await fetch('/session', {method: 'POST'});

  if (!response.ok) throw new Error('Server not connected');

  loadSession(await response.json());
}

function loadSession(session) {
  LIVE = session; RUN_ID = LIVE.run_id; LIVE_STEP = LIVE.step || 0; LIVE_ERROR = '';

  try { sessionStorage.setItem('donewise-session', LIVE.session_id); } catch (_) { /* no storage */ }

  STATES = []; index = 0; receiptIndex = Number.MAX_SAFE_INTEGER;
  for (const id of ['time', 'source', 'value', 'value-sub', 'receipt-sub', 'answer', 'user', 'text']) {
    if (id === 'text') get(id).value = ''; else text(id, '');
  }
  for (const id of ['facts', 'evidence', 'op-history', 'records', 'history', 'audit-ops', 'receipt-tabs']) get(id).replaceChildren();
  for (const id of ['approve-wrap', 'fault-tag', 'status', 'receipt-tabs', 'gap']) get(id).hidden = true;
  note('');

  text('mode', LIVE.mode); get('mode').dataset.mode = LIVE.mode;

  text('preview-right', `Live MCP · run ${RUN_ID}`);

  text('title', 'An evening with Clara'); text('subtitle', 'Results checked through MCP.');

  text('answer', ''); text('receipt-title', 'No receipts yet');

  text('bottom', 'Connected to the MCP server. This build uses local sandbox adapters; no real money. Demo controls send inputs, and every receipt comes from the server.');

  get('chapters').replaceChildren(); get('contrast').hidden = true;

  root.querySelector('.de-director').hidden = !LIVE.admin_enabled || LIVE.ui_mode === 'voice';
  get('session-controls').hidden = false; get('session-mode').value = LIVE.ui_mode;
  if (LIVE.timezone) { TZ = LIVE.timezone; get('session-timezone').value = LIVE.timezone; }
  get('session-label').hidden = false;
  text('session-label', LIVE.ui_mode === 'voice' ? 'live voice session' : 'scripted session');
  text('llm-note', LIVE.llm_enabled ? 'Language model configured · connection not yet validated' : 'Language model off · input check only');
  get('fault-panel').hidden = !LIVE.admin_enabled;
  renderFaults();

  get('loading').hidden = true; get('grid').hidden = false;

  get('user-wrap').hidden = true;

  renderVoice(); liveBusy(Boolean(LIVE.busy)); renderLive(); connectEvents();

}



/* ---------- boot ---------- */

let RUN_ID = '';

async function boot() {

  try { await tryConnect(); return; }

  catch (_) { LIVE = null; text('preview-left', 'Fixture mode · server not connected'); text('bottom', 'Fixture mode · server not connected. These are recorded receipts, not operations executed now.'); }

  let data;

  try {

    const res = await fetch(FIXTURE_URL); if (!res.ok) throw new Error(`HTTP ${res.status}`);

    data = await res.json();

  } catch (err) {

    text('loading', `Could not load ${FIXTURE_URL}: ${err.message}. Serve the sim/ folder over HTTP (see README).`);

    return;

  }

  STATES = data.states; RUN_ID = data.run_id || ''; TZ = data.timezone || TZ;



  const sources = new Set(); STATES.forEach(s => s.receipts.forEach(x => x.result.evidence && sources.add(x.result.evidence.source)));

  const mode = [...sources].some(s => CONNECTED_SOURCES.has(s)) ? 'connected' : 'sandbox';

  get('mode').dataset.mode = mode; text('mode', mode);



  const turns = STATES.filter(s => SCRIPT[s.state] && SCRIPT[s.state].user).length;

  const faults = new Set(); STATES.forEach(s => s.receipts.forEach(x => x.result.fault_injected && faults.add(x.result.fault_injected)));

  text('preview-right', `${plural(turns, 'turn', 'turns')} · ${plural(faults.size, 'fault', 'faults')} injected on purpose · run ${RUN_ID}`);



  const nav = get('chapters'); nav.replaceChildren();

  CHAPTERS.forEach(c => {

    const s = STATES.find(x => x.state === c.state); if (!s) return;

    const b = el('button', 'de-chapter'); b.type = 'button'; b.setAttribute('aria-pressed', 'false');

    b.append(el('b', null, clock(timeOf(s))), c.label); b.addEventListener('click', () => { receiptIndex = Number.MAX_SAFE_INTEGER; renderState(c.state); }); nav.append(b);

  });



  get('loading').hidden = true; get('grid').hidden = false;

  renderVoice();

  go(0);

}

boot();

})();

