'use strict';

const IDENT = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
const SIG = /^[A-Za-z][A-Za-z0-9_]*\([A-Za-z0-9_,()\[\]]*\)$/;
const HEX64 = /^[0-9a-f]{64}$/;
const VERSION = 'transaction-attack-v1';

const el = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const textOf = (v, label) => (typeof v === 'string' && v.trim().length > 0 && v.length <= 100000) ? null : 'Invalid or oversized ' + label;

function canon(v) {
  if (Array.isArray(v)) return v.map(canon);
  if (v !== null && typeof v === 'object') {
    const out = {};
    for (const k of Object.keys(v).sort()) out[k] = canon(v[k]);
    return out;
  }
  return v;
}

async function digestOf(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(canon(value)));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function checkArgs(values, errors, label) {
  if (!Array.isArray(values) || values.length > 20) { errors.push('Invalid ' + label + ' arguments'); return; }
  for (const v of values) {
    if (typeof v !== 'string' || v.length > 4096 || v.startsWith('-')) { errors.push('Invalid ABI argument in ' + label); return; }
  }
}

function checkExpression(expr, labels, errors, depth = 0, budget = [128]) {
  budget[0] -= 1;
  if (depth > 8 || budget[0] < 0) { errors.push('Predicate exceeds bounded expression budget'); return; }
  if (typeof expr === 'number') {
    if (!Number.isInteger(expr) || Math.abs(expr) >= 2 ** 256) errors.push('Oversized predicate integer');
    return;
  }
  if (typeof expr === 'boolean') return;
  if (typeof expr === 'string') {
    if (expr.length > 200) errors.push('Oversized predicate string');
    return;
  }
  if (expr === null || typeof expr !== 'object') { errors.push('Invalid predicate expression'); return; }
  const keys = Object.keys(expr);
  if (keys.length === 1 && keys[0] === 'ref') {
    if (!labels.includes(expr.ref)) errors.push('Unknown probe reference: ' + expr.ref);
    return;
  }
  if (keys.length !== 2 || !('op' in expr) || !('args' in expr)) { errors.push('Invalid predicate expression'); return; }
  const ops = ['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'add', 'sub', 'mul', 'and', 'or', 'not'];
  if (!ops.includes(expr.op)) { errors.push('Unknown predicate operator: ' + expr.op); return; }
  if (!Array.isArray(expr.args) || expr.args.length !== (expr.op === 'not' ? 1 : 2)) { errors.push('Invalid predicate arity'); return; }
  for (const a of expr.args) checkExpression(a, labels, errors, depth + 1, budget);
}

function checkPolicy(policy, expectedSnapshot, intent) {
  const errors = [], warnings = [];
  if (policy === null || typeof policy !== 'object' || Array.isArray(policy)) return { errors: ['Policy is not a JSON object'], warnings };
  const keys = Object.keys(policy);
  const want = ['version', 'snapshot_digest', 'contract_name', 'probes', 'requirements'];
  keys.sort(); want.sort();
  if (keys.join() !== want.join()) { errors.push('Invalid attack policy fields'); return { errors, warnings }; }
  if (policy.version !== VERSION) errors.push('Unknown policy version');
  if (!HEX64.test(policy.snapshot_digest || '')) errors.push('Invalid snapshot digest');
  else if (expectedSnapshot && policy.snapshot_digest !== expectedSnapshot) errors.push('Policy addresses a different snapshot than the selected challenge version');
  if (!IDENT.test(policy.contract_name || '')) errors.push('Invalid contract name');
  const probes = policy.probes;
  if (!Array.isArray(probes) || probes.length < 1 || probes.length > 20) errors.push('Need 1-20 trusted probes');
  const labels = [];
  if (Array.isArray(probes)) for (const p of probes) {
    if (p === null || typeof p !== 'object') { errors.push('Invalid probe'); continue; }
    const k = Object.keys(p).sort().join();
    if (p.kind === 'balance' && k === 'kind,label') {
    } else if (p.kind === 'view' && k === 'arguments,function,kind,label') {
      if (!SIG.test(p.function || '')) errors.push('Invalid probe ABI signature');
      checkArgs(p.arguments, errors, 'probe');
    } else { errors.push('Invalid probe kind or fields'); continue; }
    if (!IDENT.test(p.label || '')) errors.push('Invalid probe label');
    else labels.push(p.label);
  }
  if (new Set(labels).size !== labels.length) errors.push('Duplicate trusted probe label');
  const reqs = policy.requirements;
  if (!Array.isArray(reqs) || reqs.length < 1 || reqs.length > 20) errors.push('Need 1-20 operational requirements');
  const ids = [];
  if (Array.isArray(reqs)) for (const r of reqs) {
    if (r === null || typeof r !== 'object') { errors.push('Invalid requirement'); continue; }
    const rk = Object.keys(r).sort().join();
    const wantR = 'id,intent_quote,predicate,property_id,requirement,review_status,scope,step_scope';
    if (rk !== wantR) { errors.push('Invalid requirement fields'); continue; }
    if (!IDENT.test(r.id || '')) errors.push('Invalid requirement id'); else ids.push(r.id);
    const t = textOf(r.requirement, 'English requirement'); if (t) errors.push(t);
    const q = textOf(r.intent_quote, 'intent quotation'); if (q) errors.push(q);
    if (!['spec', 'intent'].includes(r.scope)) errors.push('Invalid requirement scope');
    if (!['pending', 'approved'].includes(r.review_status)) errors.push('Invalid requirement review status');
    const scope = r.step_scope;
    if (scope === 'each' || scope === 'final') {
    } else if (typeof scope === 'string' && scope.startsWith('after:')) {
      if (!SIG.test(scope.slice(6)) || scope.length === 6) errors.push('Invalid predicate step scope');
    } else errors.push('Invalid predicate step scope');
    if (r.scope === 'spec') { if (!IDENT.test(r.property_id || '')) errors.push('A spec requirement needs a Lean property id'); }
    else if (r.property_id !== '') errors.push('An intent requirement must not claim a Lean target');
    if (typeof intent === 'string' && typeof r.intent_quote === 'string' && !intent.includes(r.intent_quote))
      errors.push('Requirement quotation is absent from creator intent: "' + r.intent_quote + '"');
    if (r.review_status === 'pending') warnings.push('Requirement ' + r.id + ' is pending review: a demonstrated violation is reported as proposed, and acceptance stays blocked until a creator decision');
    if (r.scope === 'spec') warnings.push('The CLI additionally verifies that ' + r.id + ' maps to property ' + r.property_id + ' in the frozen snapshot');
    checkExpression(r.predicate, labels, errors);
  }
  if (new Set(ids).size !== ids.length) errors.push('Duplicate requirement id');
  return { errors, warnings };
}

function checkSubmission(sub, policy, policyDigest) {
  const errors = [], warnings = [];
  if (sub === null || typeof sub !== 'object') return { errors: ['Submission is not an object'], warnings };
  const keys = Object.keys(sub).sort().join();
  const want = 'contributor,policy_digest,reasoning,requirement_id,snapshot_digest,trace,version';
  if (keys !== want) { errors.push('Invalid attack submission fields'); return { errors, warnings }; }
  if (sub.version !== VERSION) errors.push('Unknown submission version');
  if (!HEX64.test(sub.snapshot_digest || '')) errors.push('Invalid snapshot digest');
  if (policy && sub.snapshot_digest !== policy.snapshot_digest) errors.push('Submission addresses a different snapshot');
  if (!HEX64.test(sub.policy_digest || '')) errors.push('Invalid policy digest');
  else if (policyDigest && sub.policy_digest !== policyDigest) errors.push('Submission addresses a different policy');
  const t = textOf(sub.contributor, 'contributor attribution'); if (t) errors.push(t);
  const t2 = textOf(sub.reasoning, 'attack reasoning'); if (t2) errors.push(t2);
  if (policy && !policy.requirements.some(r => r.id === sub.requirement_id)) errors.push('Unknown attacked requirement');
  const tr = sub.trace;
  if (tr === null || typeof tr !== 'object') { errors.push('Invalid transaction trace'); return { errors, warnings }; }
  const tk = Object.keys(tr).sort().join();
  if (tk !== 'actions,constructor_arguments,contract_name,observations') { errors.push('Invalid transaction trace fields'); return { errors, warnings }; }
  if (!IDENT.test(tr.contract_name || '')) errors.push('Invalid contract name');
  else if (policy && tr.contract_name !== policy.contract_name) errors.push('Attack selects a different contract');
  checkArgs(tr.constructor_arguments, errors, 'constructor');
  if (!Array.isArray(tr.actions) || tr.actions.length < 1 || tr.actions.length > 30) errors.push('Need 1-30 replay actions');
  if (Array.isArray(tr.actions)) for (const a of tr.actions) {
    if (a === null || typeof a !== 'object' || Object.keys(a).sort().join() !== 'account,arguments,function,value_wei') { errors.push('Invalid action fields'); continue; }
    if (!Number.isInteger(a.account) || a.account < 0 || a.account > 9) errors.push('Invalid local account index');
    if (typeof a.function !== 'string' || (a.function && !SIG.test(a.function))) errors.push('Invalid ABI signature');
    checkArgs(a.arguments, errors, 'action');
    if (a.function === '' && a.arguments && a.arguments.length) errors.push('Empty calldata takes no arguments');
    if (typeof a.value_wei !== 'string' || !/^[0-9]{1,78}$/.test(a.value_wei) || Number(a.value_wei) >= 2 ** 256) errors.push('Invalid wei amount');
  }
  if (!Array.isArray(tr.observations) || tr.observations.length > 30) errors.push('Trace exceeds bounded replay budget');
  if (Array.isArray(tr.observations)) for (const o of tr.observations) {
    if (o === null || typeof o !== 'object' || Object.keys(o).sort().join() !== 'arguments,function,label') { errors.push('Invalid observation fields'); continue; }
    if (typeof o.label !== 'string' || o.label.length > 200) errors.push('Invalid observation label');
    if (typeof o.function !== 'string' || !SIG.test(o.function)) errors.push('Invalid observation ABI signature');
    checkArgs(o.arguments, errors, 'observation');
  }
  return { errors, warnings };
}

/* ---------- markdown (minimal, escaped) ---------- */

function renderMd(md) {
  const lines = esc(md).split('\n');
  let html = '', inCode = false, inTable = false, para = [];
  const flushPara = () => { if (para.length) { html += '<p>' + para.join('<br>') + '</p>'; para = []; } };
  const inline = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  for (const line of lines) {
    if (line.startsWith('```')) {
      flushPara();
      if (inTable) { html += '</table>'; inTable = false; }
      html += inCode ? '</code></pre>' : '<pre><code>';
      inCode = !inCode;
      continue;
    }
    if (inCode) { html += line + '\n'; continue; }
    if (/^\|/.test(line)) {
      flushPara();
      if (!inTable) { html += '<table class="plain">'; inTable = true; }
      const cells = line.split('|').slice(1, -1);
      if (cells.every(c => /^ *-+ *$/.test(c) || c === undefined || /^ *-+:? *$/.test(c))) continue;
      html += '<tr>' + cells.map(c => '<td>' + inline(c.trim()) + '</td>').join('') + '</tr>';
      continue;
    }
    if (inTable) { html += '</table>'; inTable = false; }
    if (/^### /.test(line)) { flushPara(); html += '<h3>' + inline(line.slice(4)) + '</h3>'; continue; }
    if (/^## /.test(line)) { flushPara(); html += '<h2>' + inline(line.slice(3)) + '</h2>'; continue; }
    if (/^# /.test(line)) { flushPara(); html += '<h1>' + inline(line.slice(2)) + '</h1>'; continue; }
    if (/^---+$/.test(line.trim())) { flushPara(); html += '<hr>'; continue; }
    if (/^[-*] /.test(line)) { flushPara(); html += '<li>' + inline(line.slice(2)) + '</li>'; continue; }
    if (!line.trim()) { flushPara(); continue; }
    para.push(inline(line));
  }
  if (inCode) html += '</code></pre>';
  if (inTable) html += '</table>';
  flushPara();
  return html;
}

/* ---------- charts ---------- */

function lineChart(series, xCount) {
  const W = 520, H = 190, padL = 44, padB = 26, padT = 12, padR = 12;
  const yMax = Math.max(10, ...series.flatMap(s => s.points.map(p => p[1]))) * 1.1;
  const x = (i) => padL + (xCount <= 1 ? 0 : i * (W - padL - padR) / (xCount - 1));
  const y = (v) => padT + (1 - v / yMax) * (H - padT - padB);
  let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">';
  svg += '<defs><pattern id="grid" width="' + (W - padL - padR) / 4 + '" height="' + (H - padT - padB) / 4 + '" patternUnits="userSpaceOnUse"><path d="M ' + (W - padL - padR) / 4 + ' 0 L 0 0 0 ' + (H - padT - padB) / 4 + '" fill="none" stroke="#e9eff5" stroke-width="1"/></pattern></defs>';
  svg += '<rect x="' + padL + '" y="' + padT + '" width="' + (W - padL - padR) + '" height="' + (H - padT - padB) + '" fill="url(#grid)"/>';
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const value = Math.round(yMax * t / ticks);
    svg += '<line x1="' + padL + '" y1="' + y(value) + '" x2="' + (W - padR) + '" y2="' + y(value) + '" stroke="#e9eff5"/>';
    svg += '<text x="' + (padL - 7) + '" y="' + (y(value) + 4) + '" text-anchor="end" font-size="10" fill="#5b7085" font-family="IBM Plex Mono, monospace">' + value + '</text>';
  }
  for (let i = 0; i < xCount; i++)
    svg += '<text x="' + x(i) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="10" fill="#5b7085" font-family="IBM Plex Mono, monospace">' + i + '</text>';
  for (const s of series) {
    const pts = s.points.map((p, i) => x(p[0]) + ',' + y(p[1])).join(' ');
    if (s.area) svg += '<polygon points="' + padL + ',' + y(0) + ' ' + pts + ' ' + x(s.points[s.points.length - 1][0]) + ',' + y(0) + '" fill="' + s.color + '11"/>';
    svg += '<polyline points="' + pts + '" fill="none" stroke="' + s.color + '" stroke-width="2"' + (s.dashed ? ' stroke-dasharray="5 4"' : '') + '/>';
    for (const p of s.points)
      svg += '<circle cx="' + x(p[0]) + '" cy="' + y(p[1]) + '" r="3" fill="' + s.color + '"/>';
  }
  svg += '</svg>';
  return svg;
}

/* ---------- static sections ---------- */

let DATA = null;

function kv(label, value) { return '<div class="kv"><b>' + esc(label) + '</b><code>' + esc(value) + '</code></div>'; }

function kindBadge(kind) {
  const cls = /refutation/.test(kind) ? 'refutation' : /observation/.test(kind) ? 'observation' : /bug/.test(kind) ? 'bug' : '';
  return '<span class="kind ' + cls + '">' + esc(kind) + '</span>';
}

function resultClass(result) {
  return /supported|accepted|replayed|proved|demonstrated/.test(result) ? 'good' : /pending|proposed|inconclusive|not_demonstrated/.test(result) ? '' : 'bad';
}

function cmdRow(text) {
  return '<div class="cmd-row"><span>' + esc(text) + '</span><button class="copy" data-copy="' + esc(text) + '">copy</button></div>';
}

function renderStatic() {
  const d = DATA, c = d.challenge;
  el('nav-chips').innerHTML = '<span class="chip dim">staged</span><span class="chip">internal pilot</span>';
  el('hero-fullname').textContent = c.name;
  el('hero-stats').innerHTML =
    '<span class="statchip"><b>5</b> kernel-checked targets</span>' +
    '<span class="statchip"><b>7/7</b> verifier gates</span>' +
    '<span class="statchip"><b>8/8</b> live replay stages</span>' +
    '<span class="statchip"><b>2</b> contract families</span>';
  el('hero-tagline').textContent = 'Ground contract security requirements in transactions: agents propose specifications, contributors challenge them with replayable transaction sequences, and accepted findings persist as regression cases.';
  el('hero-score').innerHTML = '<b style="font-weight:600">How the score works.</b> ' + esc(c.score_composition);
  el('hero-invariants').innerHTML = '<span><b>Every result, everywhere on this page:</b> contract accepted: <b>false</b> · creator approval: <b>pending</b> · model/EVM correspondence: <b>not_proved</b>. A transaction makes behavior reproducible; it does not prove interpretation, equivalence or security.</span>';
  el('hero-meta').innerHTML = 'Evidence bundle ' + esc(d.meta.generated) + ' from <b>' + esc(d.meta.repo) + '@' + esc(d.meta.branch) + '</b> (' + esc(d.meta.commit) + ') · runtimes: ' + esc(Object.values(d.meta.tools).join(' · ')) + '. ' + esc(d.meta.scope_note);

  el('records-cards').innerHTML = d.records.cards.map(r =>
    '<div class="record-card"><div class="label">' + esc(r.label) + '</div><div class="value">' + esc(r.value) + '</div><div class="detail">' + esc(r.detail) + '</div></div>').join('');
  el('records-latest').innerHTML = '<span>' + esc(d.records.latest) + '</span><span>Recorded frontier: <b>' + esc(d.records.frontier) + '</b></span>';

  el('ledger-stats').innerHTML =
    '<span>' + d.ledger.rows.length + ' recorded rows</span><span>2 accepted registry cases</span><span>2 contract families</span><span>1 repaired revision under mapping review</span>';
  const lf = d.ledger.lending_frames, ef = d.ledger.escrow_frames;
  el('chart-lending').innerHTML = lineChart([
    { points: lf.original.map(f => [f.step, f.values.Collateral]), color: '#2868b2', area: true },
    { points: lf.original.map(f => [f.step, 2 * f.values.Debt]), color: '#c13c36' },
    { points: lf.repaired.map(f => [f.step, 2 * f.values.Debt]), color: '#0e8754', dashed: true },
  ], 5);
  el('legend-lending').innerHTML =
    '<span><span class="legend-dot" style="background:#2868b2"></span>collateral (original)</span>' +
    '<span><span class="legend-dot" style="background:#c13c36"></span>2·debt (original: violated at step 4)</span>' +
    '<span><span class="legend-dot" style="background:#0e8754"></span>2·debt (repaired source)</span>';
  el('chart-escrow').innerHTML = lineChart([
    { points: ef.attack.map(f => [f.step, f.values.Deposited]), color: '#2868b2', area: true },
    { points: ef.attack.map(f => [f.step, f.values.Released]), color: '#c13c36' },
    { points: ef.safe.map(f => [f.step, f.values.Released]), color: '#0e8754', dashed: true },
  ], 5);
  el('legend-escrow').innerHTML =
    '<span><span class="legend-dot" style="background:#2868b2"></span>deposited(payer)</span>' +
    '<span><span class="legend-dot" style="background:#c13c36"></span>released(payer) (double release)</span>' +
    '<span><span class="legend-dot" style="background:#0e8754"></span>released(payer) (safe trace)</span>';
  el('ledger-caption').innerHTML = '<b>Fig. 2 —</b> Trusted state observations by replay step, linear scale (wei), recorded per step on a disposable local Anvil. The LendingPool guard requires 2·debt ≤ collateral at every step: the original source crosses it at step 4; the repaired source reverts the withdrawal and stays below. The escrow guard requires released ≤ deposited: the double release releases 200 against a 100 deposit.';
  el('ledger-rows').innerHTML = d.ledger.rows.map(r =>
    '<tr><td><span class="author">' + esc(r.author) + '</span><div class="authorship">' + esc(r.authorship) + '</div></td>' +
    '<td>' + esc(r.evidence) + '</td><td>' + kindBadge(r.kind) + '</td>' +
    '<td><span class="result ' + resultClass(r.result) + '">' + esc(r.result) + '</span></td>' +
    '<td class="mono">' + esc(r.kernels) + '</td><td class="mono">' + esc(r.digest) + '</td><td class="mono">' + esc(r.recorded) + '</td></tr>').join('');
  el('ledger-note').textContent = d.ledger.note;
  el('report-body').innerHTML = renderMd(d.verification.report_md);

  el('challenge-objective').textContent = c.objective;
  el('challenge-loop').innerHTML = c.loop.map(s => '<li>' + esc(s) + '</li>').join('');
  el('challenge-editable').innerHTML = c.editable_paths.map(p => '<div class="kv"><b>editable</b><code>' + esc(p) + '</code></div>').join('') +
    '<div class="kv"><b>protected</b><code>schemas · orchestration · frozen targets · checker · rubric</code></div>';
  el('challenge-rubric').innerHTML = '<table class="plain"><tr><th>Input</th><th>Criterion</th><th>What the assessor looks for</th></tr>' +
    c.rubric_cases.map(cs => cs.criteria.map(cr =>
      '<tr><td><code>' + esc(cs.input.split('/').pop()) + '</code></td><td><b>' + esc(cr.id) + '</b></td><td>' + esc(cr.text) + '</td></tr>'
    ).join('')).join('') + '</table>';

  el('rewards-classes').innerHTML = '<table class="plain"><tr><th>Credit</th><th>Earned by</th></tr>' +
    c.rewards.credit_classes.map(x => '<tr><td><b>' + esc(x.class) + '</b></td><td>' + esc(x.rule) + '</td></tr>').join('') + '</table>' +
    '<p class="subtle" style="margin-top:8px">' + esc(c.rewards.note) + '</p>';
  el('rewards-never').innerHTML = c.rewards.never_earn.map(s => '<li class="subtle">' + esc(s) + '</li>').join('');
  el('rewards-budget').textContent = c.rewards.budget;

  el('participate-blockers').textContent = c.blockers;
  el('participate-terminal').innerHTML =
    '<div class="c"># 1 · clone the internal repository on the general-intent-pipeline branch</div>' +
    '<div class="cmd">git clone -b general-intent-pipeline &lt;internal-repo&gt; &amp;&amp; cd auto-prove</div>' +
    '<div class="c"># 2 · run the eight-stage live loop on a disposable local Anvil</div>' +
    '<div class="cmd">bash scripts/verify_attacks.sh</div>' +
    '<div><span class="ok">✓</span> 54 unit tests pass</div>' +
    '<div><span class="ok">✓</span> requirement violations replayed with receipts</div>' +
    '<div><span class="ok">✓</span> acceptance, deduplication and regressions asserted</div>' +
    '<div><span class="ok">✓</span> runtime failures stay inconclusive</div>' +
    '<div class="c"># 3 · recheck the protected Lean verifier gates (Docker)</div>' +
    '<div class="cmd">python3 -m general.regressions --output runs/my-gates</div>' +
    '<div><span class="ok">✓</span> all seven gates pass — sorry, target swaps and custom axioms rejected</div>' +
    '<div class="c"># 4 · import on Yukon once authenticated: solvers improve the editable prompts</div>' +
    '<div class="hl">$ yukon setup &amp;&amp; yukon run</div>';
  el('participate-cards').innerHTML = c.participation.map((p, i) =>
    '<div class="card"><div class="num">' + (i + 1) + '</div><h3>' + esc(p.step) + '</h3><p class="subtle">' + esc(p.body) + '</p></div>').join('');
  el('participate-commands').innerHTML =
    cmdRow(d.commands.attack) +
    cmdRow(d.commands.propose) +
    cmdRow(d.commands.review_policy) +
    cmdRow(d.commands.accept) +
    cmdRow(d.commands.regress) +
    cmdRow(d.commands.verify_loop);

  el('footer-note').innerHTML = esc(c.name) + ' — internal pilot, staged for Yukon. This page hosts no checking and accepts no submissions; every artifact references the frozen digests it was produced against, and every result leaves creator approval pending and contract correspondence not proved.';
}

document.addEventListener('click', (event) => {
  const btn = event.target.closest('button.copy');
  if (btn) navigator.clipboard.writeText(btn.dataset.copy).then(() => { btn.textContent = 'copied'; setTimeout(() => btn.textContent = 'copy', 1200); });
});

/* ---------- composer (unchanged logic) ---------- */

const state = { demo: null, policy: null, intent: null, snapshot: null, policyRaw: '', policyEdited: false,
  contributor: '', requirement_id: '', reasoning: '', constructor: '', actions: [], observations: [] };

function csvParse(v) { if (!v.trim()) return []; return v.split(',').map(s => s.trim()); }
function csvJoin(list) { return (list || []).join(', '); }

function renderTraceTable() {
  el('t-contract').textContent = state.policy ? state.policy.contract_name : '—';
  el('t-actions').innerHTML = state.actions.map((a, i) =>
    '<tr>' +
    '<td><input data-i="' + i + '" data-k="account" type="number" min="0" max="9" value="' + esc(a.account) + '"></td>' +
    '<td><input data-i="' + i + '" data-k="function" value="' + esc(a.function) + '" placeholder="deposit()"></td>' +
    '<td><input data-i="' + i + '" data-k="arguments" value="' + esc(csvJoin(a.arguments)) + '" placeholder="50"></td>' +
    '<td><input data-i="' + i + '" data-k="value_wei" value="' + esc(a.value_wei) + '"></td>' +
    '<td><button class="mini" data-del="' + i + '">&times;</button></td></tr>').join('');
  el('t-observations').innerHTML = state.observations.map((o, i) =>
    '<tr>' +
    '<td><input data-oi="' + i + '" data-ok="label" value="' + esc(o.label) + '"></td>' +
    '<td><input data-oi="' + i + '" data-ok="function" value="' + esc(o.function) + '"></td>' +
    '<td><input data-oi="' + i + '" data-ok="arguments" value="' + esc(csvJoin(o.arguments)) + '"></td>' +
    '<td><button class="mini" data-odel="' + i + '">&times;</button></td></tr>').join('');
}

function buildSubmission() {
  return {
    version: VERSION, snapshot_digest: state.policy ? state.policy.snapshot_digest : '',
    policy_digest: '', contributor: state.contributor, requirement_id: state.requirement_id,
    reasoning: state.reasoning,
    trace: { contract_name: state.policy ? state.policy.contract_name : '',
      constructor_arguments: csvParse(state.constructor),
      actions: state.actions.map(a => ({ account: Number(a.account), function: a.function, arguments: csvParse(a.arguments), value_wei: a.value_wei })),
      observations: state.observations.map(o => ({ label: o.label, function: o.function, arguments: csvParse(o.arguments) })) },
  };
}

let policyDigest = '';

async function refreshComposer() {
  const policyErrors = el('composer-policy-errors'), subErrors = el('composer-submission-errors');
  const policyWarn = el('composer-policy-warnings'), subWarn = el('composer-submission-warnings');
  policyErrors.innerHTML = ''; policyWarn.innerHTML = ''; subErrors.innerHTML = ''; subWarn.innerHTML = '';

  let policy = null;
  try { policy = JSON.parse(state.policyRaw); } catch (e) { policyErrors.innerHTML = '<li>Policy is not valid JSON: ' + esc(e.message) + '</li>'; }
  state.policy = policy;
  el('composer-snapshot-digest').textContent = state.snapshot || '—';

  if (policy) {
    const check = checkPolicy(policy, state.snapshot, state.intent);
    policyErrors.innerHTML = check.errors.map(e => '<li>' + esc(e) + '</li>').join('');
    policyWarn.innerHTML = check.warnings.map(e => '<li>' + esc(e) + '</li>').join('');
    policyDigest = await digestOf(policy);
    el('composer-policy-digest').textContent = policyDigest;
    const sel = el('f-requirement');
    const previous = state.requirement_id;
    sel.innerHTML = (policy.requirements || []).map(r => '<option value="' + esc(r.id) + '">' + esc(r.id) + (r.review_status === 'pending' ? ' (pending review)' : '') + '</option>').join('');
    if ((policy.requirements || []).some(r => r.id === previous)) sel.value = previous;
    else if (policy.requirements && policy.requirements.length) { state.requirement_id = policy.requirements[0].id; sel.value = state.requirement_id; }
  } else {
    el('composer-policy-digest').textContent = '—';
    policyDigest = '';
  }

  const sub = buildSubmission();
  sub.policy_digest = policyDigest;
  const check = checkSubmission(sub, policy, policyDigest);
  subErrors.innerHTML = check.errors.map(e => '<li>' + esc(e) + '</li>').join('');
  subWarn.innerHTML = check.warnings.map(e => '<li>' + esc(e) + '</li>').join('');

  const valid = policy && check.errors.length === 0 && checkPolicy(policy, state.snapshot, state.intent).errors.length === 0;
  el('composer-verdict').innerHTML = valid
    ? '<span class="ok">Schema-valid submission.</span> Download it and run the command below against the trusted CLI.'
    : '<span class="bad">Not yet valid.</span> Fix the listed issues; the browser mirrors the CLI validators but the runner is authoritative.';

  el('composer-output').value = JSON.stringify(sub, null, 2);
  el('composer-submission-digest').textContent = valid ? await digestOf(sub) : '—';

  let command;
  if (valid) {
    const snapshotPath = state.demo ? (state.demo === 'escrow' ? 'general/fixtures/escrow/snapshot.json' : 'general/fixtures/attacks/snapshot.json') : 'your-snapshot.json';
    const policyPath = state.demo && !state.policyEdited
      ? (state.demo === 'escrow' ? 'general/fixtures/escrow/draft-policy.json' : 'general/fixtures/attacks/policy.json')
      : 'my-policy.json';
    command = 'python3 -m general attack ' + snapshotPath + ' ' + policyPath + ' my-attack.json --output runs/my-attack';
    el('composer-download-policy').style.display = state.policyEdited || !state.demo ? '' : 'none';
  } else {
    command = '# fix the validation issues above';
    el('composer-download-policy').style.display = 'none';
  }
  el('composer-command').innerHTML = '<span>' + esc(command) + '</span><button class="copy" data-copy="' + esc(command) + '">copy</button>';

  state.lastSub = sub;
}

function loadDemo(name) {
  state.demo = name;
  document.querySelectorAll('#composer-demo-select .chip').forEach(b => {
    b.style.background = b.dataset.demo === name ? 'var(--accent-soft)' : '#f5f5f7';
    b.style.color = b.dataset.demo === name ? 'var(--accent)' : 'var(--ink-faint)';
  });
  if (name === 'custom') {
    state.intent = null; state.snapshot = null;
    state.policyRaw = JSON.stringify({ version: VERSION, snapshot_digest: '', contract_name: '', probes: [], requirements: [] }, null, 2);
    state.contributor = ''; state.requirement_id = ''; state.reasoning = '';
    state.constructor = ''; state.actions = [{ account: 0, function: '', arguments: [], value_wei: '0' }]; state.observations = [];
    state.policyEdited = true;
  } else {
    const demo = DATA.demos[name];
    state.intent = demo.intent; state.snapshot = demo.snapshot_digest;
    state.policyRaw = JSON.stringify(demo.policy, null, 2);
    state.policyEdited = false;
    const s = demo.submission;
    state.contributor = s.contributor + '-edit-me'; state.requirement_id = s.requirement_id; state.reasoning = s.reasoning;
    state.constructor = csvJoin(s.trace.constructor_arguments);
    state.actions = s.trace.actions.map(a => ({ ...a, arguments: [...a.arguments] }));
    state.observations = s.trace.observations.map(o => ({ ...o, arguments: [...o.arguments] }));
  }
  el('composer-policy').value = state.policyRaw;
  el('f-contributor').value = state.contributor;
  el('f-reasoning').value = state.reasoning;
  el('t-constructor').value = state.constructor;
  el('composer-policy').readOnly = false;
  el('composer-policy-note').textContent = name === 'custom'
    ? 'Paste a maintainer-provided policy. Without the snapshot text the intent-quote check runs only in the CLI.'
    : 'Loaded from the repo fixtures. Edits are allowed (try flipping a review_status to pending); download the edited policy and use it in the command.';
  renderTraceTable();
  refreshComposer();
}

function bindComposer() {
  el('composer-demo-select').innerHTML =
    '<button class="chip" data-demo="escrow" style="cursor:pointer">MilestoneEscrow demo</button>' +
    '<button class="chip" data-demo="lending" style="cursor:pointer">LendingPool demo</button>' +
    '<button class="chip" data-demo="custom" style="cursor:pointer">Custom policy</button>';
  document.querySelectorAll('#composer-demo-select .chip').forEach(b => b.addEventListener('click', () => loadDemo(b.dataset.demo)));

  el('composer-policy').addEventListener('input', (e) => {
    state.policyRaw = e.target.value;
    if (state.demo) state.policyEdited = state.policyRaw !== JSON.stringify(DATA.demos[state.demo].policy, null, 2);
    refreshComposer();
  });
  el('f-contributor').addEventListener('input', (e) => { state.contributor = e.target.value; refreshComposer(); });
  el('f-requirement').addEventListener('change', (e) => { state.requirement_id = e.target.value; refreshComposer(); });
  el('f-reasoning').addEventListener('input', (e) => { state.reasoning = e.target.value; refreshComposer(); });
  el('t-constructor').addEventListener('input', (e) => { state.constructor = e.target.value; refreshComposer(); });
  el('t-add-action').addEventListener('click', () => { state.actions.push({ account: 0, function: '', arguments: [], value_wei: '0' }); renderTraceTable(); refreshComposer(); });
  el('t-add-observation').addEventListener('click', () => { state.observations.push({ label: '', function: '', arguments: [] }); renderTraceTable(); refreshComposer(); });

  document.addEventListener('input', (e) => {
    const t = e.target;
    if (t.dataset.i !== undefined && t.dataset.k) {
      const a = state.actions[Number(t.dataset.i)];
      if (t.dataset.k === 'account') a.account = t.value === '' ? '' : Number(t.value);
      else if (t.dataset.k === 'arguments') a.arguments = csvParse(t.value);
      else a[t.dataset.k] = t.value;
      refreshComposer();
    }
    if (t.dataset.oi !== undefined && t.dataset.ok) {
      const o = state.observations[Number(t.dataset.oi)];
      if (t.dataset.ok === 'arguments') o.arguments = csvParse(t.value);
      else o[t.dataset.ok] = t.value;
      refreshComposer();
    }
  });
  document.addEventListener('click', (e) => {
    const del = e.target.closest('button[data-del]'), odel = e.target.closest('button[data-odel]');
    if (del) { state.actions.splice(Number(del.dataset.del), 1); renderTraceTable(); refreshComposer(); }
    if (odel) { state.observations.splice(Number(odel.dataset.odel), 1); renderTraceTable(); refreshComposer(); }
  });

  el('composer-download').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(state.lastSub, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'my-attack.json'; a.click(); URL.revokeObjectURL(a.href);
  });
  el('composer-download-policy').addEventListener('click', () => {
    const blob = new Blob([state.policyRaw], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'my-policy.json'; a.click(); URL.revokeObjectURL(a.href);
  });
}

fetch('data/site.json').then(r => r.json()).then((data) => {
  DATA = data;
  renderStatic();
  bindComposer();
  loadDemo('escrow');
});
