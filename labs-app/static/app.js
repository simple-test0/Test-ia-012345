/* AI Studio Labs — standalone UI (vanilla JS, zero build step). */
'use strict';

const API = '/api/v1';
const WS_BASE = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host;

/* ── Helpers ──────────────────────────────────────────── */

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: opts.body && !(opts.body instanceof FormData)
      ? { 'Content-Type': 'application/json' } : {},
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return res.json();
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function toast(msg, isErr = false) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const t = document.createElement('div');
  t.className = 'toast' + (isErr ? ' err' : '');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), isErr ? 6000 : 3000);
}

function fmtBytes(b) {
  if (!b) return '';
  if (b > 1e9) return (b / 1e9).toFixed(1) + ' Go';
  if (b > 1e6) return (b / 1e6).toFixed(1) + ' Mo';
  return Math.round(b / 1e3) + ' Ko';
}

function fmtNum(v, digits = 4) {
  if (v === null || v === undefined) return '—';
  if (Math.abs(v) < 0.001 && v !== 0) return v.toExponential(2);
  return (+v).toFixed(digits).replace(/\.?0+$/, '') || '0';
}

/* ── Line chart (canvas): 2px lines, recessive grid, crosshair + tooltip ── */

const SERIES_COLORS = { train: '#3987e5', val: '#199e70', lr: '#9085e9' };
const CHART = {
  grid: '#2c2c2a', baseline: '#383835', tick: '#898781',
  surface: '#1a1a19', crosshair: '#52514e',
};

class LineChart {
  constructor(container, { title, series, height = 150, yDomain = null }) {
    this.series = series; // [{key, label, color}]
    this.yDomain = yDomain;
    this.data = [];
    this.hoverIdx = -1;

    this.box = document.createElement('div');
    this.box.className = 'chart-box';
    const legend = series.map((s) =>
      `<span><span class="sw" style="background:${s.color}"></span>${esc(s.label)}</span>`).join('');
    this.box.innerHTML =
      `<div class="legend"><span class="title">${esc(title)}</span>${series.length > 1 ? legend : ''}</div>`;
    this.canvas = document.createElement('canvas');
    this.canvas.style.height = height + 'px';
    this.tooltip = document.createElement('div');
    this.tooltip.className = 'chart-tooltip';
    this.box.appendChild(this.canvas);
    this.box.appendChild(this.tooltip);
    container.appendChild(this.box);

    this.height = height;
    this.canvas.addEventListener('mousemove', (e) => this._onMove(e));
    this.canvas.addEventListener('mouseleave', () => { this.hoverIdx = -1; this.tooltip.style.display = 'none'; this.render(); });
    new ResizeObserver(() => this.render()).observe(this.canvas);
  }

  setData(points) { this.data = points; this.render(); }

  _layout() {
    const w = this.canvas.clientWidth || 300;
    const h = this.height;
    return { w, h, m: { l: 42, r: 10, t: 8, b: 20 } };
  }

  _scales() {
    const { w, h, m } = this._layout();
    const xs = this.data.map((p) => p.x);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    let yMin, yMax;
    if (this.yDomain) { [yMin, yMax] = this.yDomain; }
    else {
      const vals = [];
      for (const p of this.data) for (const s of this.series) {
        if (p[s.key] !== undefined && p[s.key] !== null) vals.push(p[s.key]);
      }
      yMin = 0;
      yMax = vals.length ? Math.max(...vals) * 1.08 : 1;
      if (yMax === 0) yMax = 1;
    }
    const x = (v) => xMax === xMin
      ? m.l + (w - m.l - m.r) / 2
      : m.l + ((v - xMin) / (xMax - xMin)) * (w - m.l - m.r);
    const y = (v) => h - m.b - ((v - yMin) / (yMax - yMin)) * (h - m.t - m.b);
    return { x, y, xMin, xMax, yMin, yMax };
  }

  render() {
    const { w, h, m } = this._layout();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = w * dpr;
    this.canvas.height = h * dpr;
    const ctx = this.canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    ctx.font = '10px system-ui, sans-serif';

    if (!this.data.length) {
      ctx.fillStyle = CHART.tick;
      ctx.fillText('En attente de métriques…', m.l, h / 2);
      return;
    }

    const { x, y, xMin, xMax, yMin, yMax } = this._scales();

    // Grid: 4 hairline rows + labels in muted ink
    ctx.strokeStyle = CHART.grid;
    ctx.fillStyle = CHART.tick;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const v = yMin + ((yMax - yMin) * i) / 3;
      const yy = Math.round(y(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(m.l, yy); ctx.lineTo(w - m.r, yy); ctx.stroke();
      ctx.textAlign = 'right';
      ctx.fillText(fmtNum(v, v < 10 ? 2 : 0), m.l - 6, yy + 3);
    }
    // Baseline + x ticks (first / last epoch)
    ctx.strokeStyle = CHART.baseline;
    ctx.beginPath();
    ctx.moveTo(m.l, h - m.b + 0.5); ctx.lineTo(w - m.r, h - m.b + 0.5); ctx.stroke();
    ctx.textAlign = 'center';
    ctx.fillText(String(xMin), x(xMin), h - 6);
    if (xMax !== xMin) ctx.fillText(String(xMax), x(xMax), h - 6);

    // Crosshair under the marks
    if (this.hoverIdx >= 0 && this.data[this.hoverIdx]) {
      const hx = Math.round(x(this.data[this.hoverIdx].x)) + 0.5;
      ctx.strokeStyle = CHART.crosshair;
      ctx.beginPath(); ctx.moveTo(hx, m.t); ctx.lineTo(hx, h - m.b); ctx.stroke();
    }

    // Series: 2px lines, round joins
    for (const s of this.series) {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      let started = false;
      for (const p of this.data) {
        if (p[s.key] === undefined || p[s.key] === null) continue;
        const px = x(p.x), py = y(p[s.key]);
        if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
      }
      ctx.stroke();
      // Single point: draw a marker so it's visible
      const pts = this.data.filter((p) => p[s.key] !== undefined && p[s.key] !== null);
      if (pts.length === 1) {
        ctx.fillStyle = s.color;
        ctx.beginPath(); ctx.arc(x(pts[0].x), y(pts[0][s.key]), 3, 0, Math.PI * 2); ctx.fill();
      }
    }

    // Hover markers: 8px dots with a 2px surface ring
    if (this.hoverIdx >= 0 && this.data[this.hoverIdx]) {
      const p = this.data[this.hoverIdx];
      for (const s of this.series) {
        if (p[s.key] === undefined || p[s.key] === null) continue;
        ctx.beginPath();
        ctx.arc(x(p.x), y(p[s.key]), 4, 0, Math.PI * 2);
        ctx.fillStyle = s.color;
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = CHART.surface;
        ctx.stroke();
      }
    }
  }

  _onMove(e) {
    if (!this.data.length) return;
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const { x } = this._scales();
    let best = 0, bestD = Infinity;
    this.data.forEach((p, i) => {
      const d = Math.abs(x(p.x) - mx);
      if (d < bestD) { bestD = d; best = i; }
    });
    this.hoverIdx = best;
    const p = this.data[best];
    const rows = this.series
      .filter((s) => p[s.key] !== undefined && p[s.key] !== null)
      .map((s) => `<span class="sw" style="background:${s.color}"></span>${esc(s.label)} : <b>${fmtNum(p[s.key])}</b>`)
      .join('<br/>');
    this.tooltip.innerHTML = `<b>epoch ${p.x}</b><br/>${rows}`;
    this.tooltip.style.display = 'block';
    const tw = this.tooltip.offsetWidth;
    const left = Math.min(mx + 14, rect.width - tw - 4);
    this.tooltip.style.left = Math.max(left, 0) + 'px';
    this.tooltip.style.top = '30px';
    this.render();
  }
}

/* ── Global state ─────────────────────────────────────── */

const state = {
  archs: [], options: null, datasets: [], tokenizers: [], runs: [],
  selectedArch: null, selectedAlgo: 'bpe',
  runWatchers: new Map(),   // run_id → {ws, charts, history}
  pollTimer: null, consoleWs: null,
};

/* ── Router ───────────────────────────────────────────── */

const VIEWS = ['runs', 'new', 'datasets', 'tokenizers', 'archs', 'hardware', 'console'];

function route() {
  const name = (location.hash.replace('#/', '') || 'runs').split('?')[0];
  const view = VIEWS.includes(name) ? name : 'runs';
  document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  document.querySelectorAll('nav a').forEach((a) =>
    a.classList.toggle('active', a.dataset.view === view));
  if (view === 'runs') refreshRuns();
  if (view === 'new') renderNewRun();
  if (view === 'datasets') refreshDatasets();
  if (view === 'tokenizers') { refreshDatasets(); refreshTokenizers(); }
  if (view === 'archs') renderArchsCatalog();
  if (view === 'hardware') renderHardware();
  if (view === 'console') openConsole();
}
window.addEventListener('hashchange', route);

/* ── Runs ─────────────────────────────────────────────── */

async function refreshRuns() {
  try { state.runs = await api('/labs/runs'); } catch (e) { toast(e.message, true); return; }
  renderRuns();
  const active = state.runs.some((r) => ['running', 'pending', 'paused'].includes(r.status));
  clearTimeout(state.pollTimer);
  if (active && location.hash.includes('runs')) {
    state.pollTimer = setTimeout(refreshRuns, 4000);
  }
}

function renderRuns() {
  const root = document.getElementById('runs-list');
  const keep = new Set();

  if (!state.runs.length) {
    root.innerHTML = '<div class="card empty">Aucun run — lancez un entraînement depuis « Nouveau run ».</div>';
    return;
  }

  for (const run of state.runs) {
    keep.add(run.id);
    let card = document.getElementById('run-' + run.id);
    if (!card) {
      card = document.createElement('div');
      card.className = 'card';
      card.id = 'run-' + run.id;
      card.innerHTML = `
        <div class="run-head">
          <div><div class="name"></div><div class="meta"></div></div>
          <span class="chip"></span>
        </div>
        <div class="progress"><div></div></div>
        <div class="progress-label"></div>
        <div class="banners"></div>
        <div class="charts"></div>
        <div class="stats-row"></div>
        <details class="tbl"><summary>Tableau des métriques</summary>
          <div class="table-scroll"></div></details>
        <div class="run-actions"></div>`;
      root.appendChild(card);
    }
    card.querySelector('.name').textContent = run.name;
    card.querySelector('.meta').textContent =
      `${run.architecture} · ${new Date(run.created_at).toLocaleString('fr-FR')}` +
      (run.tokenizer_id ? ' · tokenizer ✓' : '');
    const chip = card.querySelector('.chip');
    chip.className = 'chip ' + run.status;
    chip.textContent = run.status;

    const pct = run.total_epochs ? Math.round(((run.current_epoch || 0) / run.total_epochs) * 100) : 0;
    card.querySelector('.progress > div').style.width = pct + '%';
    card.querySelector('.progress-label').textContent =
      `epoch ${run.current_epoch || 0} / ${run.total_epochs || '?'}`;

    const banners = card.querySelector('.banners');
    banners.innerHTML = run.error_message
      ? `<div class="error-banner">${esc(run.error_message)}</div>` : '';

    ensureRunCharts(run, card);
    renderRunActions(run, card);
  }

  // Drop cards (and watchers) of deleted runs
  root.querySelectorAll('.card[id^="run-"]').forEach((c) => {
    const id = c.id.slice(4);
    if (!keep.has(id)) { stopWatcher(id); c.remove(); }
  });
}

function historyToPoints(history) {
  return (history || [])
    .filter((e) => e.type === 'epoch_metric' || e.epoch !== undefined)
    .map((e) => ({
      x: e.epoch, train: e.train_loss, val: e.val_loss,
      train_acc: e.train_acc, val_acc: e.val_acc, lr: e.lr,
    }));
}

function ensureRunCharts(run, card) {
  let w = state.runWatchers.get(run.id);
  if (!w) {
    const chartsBox = card.querySelector('.charts');
    const loss = new LineChart(chartsBox, {
      title: 'Loss',
      series: [
        { key: 'train', label: 'train', color: SERIES_COLORS.train },
        { key: 'val', label: 'validation', color: SERIES_COLORS.val },
      ],
    });
    const acc = new LineChart(chartsBox, {
      title: 'Accuracy',
      yDomain: [0, 1],
      series: [
        { key: 'train_acc', label: 'train', color: SERIES_COLORS.train },
        { key: 'val_acc', label: 'validation', color: SERIES_COLORS.val },
      ],
    });
    w = { ws: null, loss, acc, points: historyToPoints(run.metrics_history), batchLoss: null };
    state.runWatchers.set(run.id, w);
    w.loss.setData(w.points);
    w.acc.setData(w.points);
  }

  updateRunStats(run, card, w);
  renderMetricsTable(card, w.points);

  const live = ['running', 'paused', 'pending'].includes(run.status);
  if (live && !w.ws) {
    const ws = new WebSocket(`${WS_BASE}/ws/training/${run.id}`);
    w.ws = ws;
    ws.onmessage = (msg) => {
      const evt = JSON.parse(msg.data);
      if (evt.type === 'epoch_metric') {
        const pt = {
          x: evt.epoch, train: evt.train_loss, val: evt.val_loss,
          train_acc: evt.train_acc, val_acc: evt.val_acc, lr: evt.lr,
        };
        const i = w.points.findIndex((p) => p.x === pt.x);
        if (i >= 0) w.points[i] = pt; else w.points.push(pt);
        w.loss.setData(w.points);
        w.acc.setData(w.points);
        updateRunStats(run, card, w);
        renderMetricsTable(card, w.points);
      } else if (evt.type === 'batch_metric') {
        w.batchLoss = evt.loss;
        updateRunStats(run, card, w);
      } else if (evt.type === 'warning') {
        const b = card.querySelector('.banners');
        b.innerHTML += `<div class="warn-banner">⚠ ${esc(evt.message)}</div>`;
      } else if (evt.type === 'completed' || evt.type === 'error') {
        refreshRuns();
      }
    };
    ws.onclose = () => { if (state.runWatchers.get(run.id)) state.runWatchers.get(run.id).ws = null; };
  } else if (!live && w.ws) {
    w.ws.close();
    w.ws = null;
  }
}

function stopWatcher(id) {
  const w = state.runWatchers.get(id);
  if (w && w.ws) w.ws.close();
  state.runWatchers.delete(id);
}

function updateRunStats(run, card, w) {
  const last = w.points[w.points.length - 1];
  const bestVal = w.points.reduce((b, p) => (p.val !== undefined && p.val < b ? p.val : b), Infinity);
  const tiles = [];
  if (w.batchLoss !== null && ['running', 'paused'].includes(run.status)) {
    tiles.push(['batch loss', fmtNum(w.batchLoss)]);
  }
  if (last) {
    if (last.val !== undefined) tiles.push(['val loss', fmtNum(last.val)]);
    if (bestVal !== Infinity) tiles.push(['meilleure val loss', fmtNum(bestVal)]);
    if (last.val_acc !== undefined) tiles.push(['val accuracy', (last.val_acc * 100).toFixed(1) + ' %']);
    if (last.lr !== undefined) tiles.push(['learning rate', fmtNum(last.lr, 6)]);
  }
  card.querySelector('.stats-row').innerHTML = tiles
    .map(([l, v]) => `<div class="stat-tile"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`)
    .join('');
}

function renderMetricsTable(card, points) {
  const box = card.querySelector('.tbl .table-scroll');
  if (!points.length) { box.innerHTML = '<p class="empty">Pas encore de métriques.</p>'; return; }
  const rows = points.map((p) => `
    <tr><td>${p.x}</td><td>${fmtNum(p.train)}</td><td>${fmtNum(p.val)}</td>
    <td>${p.train_acc !== undefined ? (p.train_acc * 100).toFixed(1) + ' %' : '—'}</td>
    <td>${p.val_acc !== undefined ? (p.val_acc * 100).toFixed(1) + ' %' : '—'}</td>
    <td>${fmtNum(p.lr, 6)}</td></tr>`).join('');
  box.innerHTML = `<table class="metrics">
    <tr><th>epoch</th><th>train loss</th><th>val loss</th><th>train acc</th><th>val acc</th><th>lr</th></tr>
    ${rows}</table>`;
}

function renderRunActions(run, card) {
  const box = card.querySelector('.run-actions');
  const b = [];
  if (['running', 'pending'].includes(run.status)) b.push(`<button class="ghost small" data-act="pause">⏸ Pause</button>`);
  if (run.status === 'paused') b.push(`<button class="ghost small" data-act="resume">▶ Reprendre</button>`);
  if (['running', 'paused', 'pending'].includes(run.status)) b.push(`<button class="danger small" data-act="stop">⏹ Stop</button>`);
  if (run.status === 'completed' && run.best_checkpoint_path) {
    b.push(`<button class="ghost small" data-act="onnx">⬇ Export ONNX</button>`);
    b.push(`<button class="ghost small" data-act="safetensors">⬇ Export safetensors</button>`);
  }
  if (!['running', 'pending'].includes(run.status)) b.push(`<button class="danger small" data-act="delete">🗑 Supprimer</button>`);
  box.innerHTML = b.join('');
  box.querySelectorAll('button').forEach((btn) => {
    btn.onclick = () => runAction(run.id, btn.dataset.act, btn);
  });
}

async function runAction(id, act, btn) {
  try {
    if (act === 'pause') await api(`/labs/runs/${id}/pause`, { method: 'POST' });
    else if (act === 'resume') await api(`/labs/runs/${id}/resume`, { method: 'POST' });
    else if (act === 'stop') await api(`/labs/runs/${id}/stop`, { method: 'POST' });
    else if (act === 'delete') {
      if (!confirm('Supprimer ce run et ses checkpoints ?')) return;
      stopWatcher(id);
      await api(`/labs/runs/${id}`, { method: 'DELETE' });
    } else if (act === 'onnx' || act === 'safetensors') {
      btn.disabled = true;
      btn.textContent = 'Export…';
      await api(`/labs/runs/${id}/export`, { method: 'POST', body: JSON.stringify({ format: act }) });
      window.location.href = `${API}/labs/runs/${id}/export/download`;
      btn.disabled = false;
      btn.textContent = act === 'onnx' ? '⬇ Export ONNX' : '⬇ Export safetensors';
      return;
    }
    refreshRuns();
  } catch (e) { toast(e.message, true); if (btn) btn.disabled = false; }
}

/* ── New run ──────────────────────────────────────────── */

async function loadStatics() {
  if (!state.archs.length) state.archs = await api('/labs/architectures');
  if (!state.options) state.options = await api('/labs/training-options');
}

async function renderNewRun() {
  try {
    await loadStatics();
    state.datasets = await api('/labs/datasets');
    state.tokenizers = await api('/labs/tokenizers');
  } catch (e) { toast(e.message, true); return; }

  if (!state.selectedArch) state.selectedArch = state.archs[0]?.id;

  const cards = document.getElementById('arch-cards');
  cards.innerHTML = state.archs.map((a) => `
    <div class="opt-card ${a.id === state.selectedArch ? 'selected' : ''}" data-id="${a.id}">
      <div class="t">${esc(a.name)}</div>
      <div class="d">${esc(a.description)}</div>
      <div class="tags">${(a.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}
        <span class="chip">≥ ${a.min_vram_mb} Mo VRAM</span></div>
    </div>`).join('');
  cards.querySelectorAll('.opt-card').forEach((c) => {
    c.onclick = () => { state.selectedArch = c.dataset.id; renderNewRun(); };
  });

  const arch = state.archs.find((a) => a.id === state.selectedArch);
  renderArchParams(arch);

  const dsSel = document.getElementById('run-dataset');
  dsSel.innerHTML = '<option value="">— Données aléatoires (démo) —</option>' +
    state.datasets.filter((d) => d.status === 'ready')
      .map((d) => `<option value="${d.id}">${esc(d.name)} (${d.num_samples || '?'} ex.)</option>`).join('');

  const isNlp = (arch?.tags || []).includes('nlp') || (arch?.task_types || []).includes('nlp');
  document.getElementById('run-tokenizer-wrap').style.display = isNlp ? '' : 'none';
  const tokSel = document.getElementById('run-tokenizer');
  tokSel.innerHTML = '<option value="">— Aucun (hash de démo) —</option>' +
    state.tokenizers.filter((t) => t.status === 'ready')
      .map((t) => `<option value="${t.id}">${esc(t.name)} (${t.algorithm}, vocab ${t.actual_vocab_size})</option>`).join('');

  renderTrainingOptions();
}

function renderArchParams(arch) {
  const box = document.getElementById('arch-params');
  if (!arch || !arch.param_schema) { box.innerHTML = ''; return; }
  const fields = Object.entries(arch.param_schema).map(([key, sch]) => {
    const def = arch.default_config[key];
    if (sch.type === 'boolean') {
      return `<div class="check-row"><input type="checkbox" id="ap-${key}" ${def ? 'checked' : ''}/>
        <label for="ap-${key}">${esc(sch.label || key)}</label></div>`;
    }
    const step = sch.type === 'float' ? '0.05' : '1';
    return `<div><label>${esc(sch.label || key)}</label>
      <input type="number" id="ap-${key}" value="${def ?? ''}" min="${sch.min ?? ''}" max="${sch.max ?? ''}" step="${step}"/></div>`;
  });
  box.innerHTML = `<details open><summary>Paramètres de l'architecture</summary>
    <div class="grid3" style="margin-top:8px">${fields.join('')}</div></details>`;
}

function renderTrainingOptions() {
  const { options, groups } = state.options;
  const box = document.getElementById('training-options');
  const byGroup = {};
  for (const [key, o] of Object.entries(options)) (byGroup[o.group] ||= []).push([key, o]);

  box.innerHTML = Object.entries(groups).map(([gid, gname]) => {
    const fields = (byGroup[gid] || []).map(([key, o]) => {
      if (o.type === 'boolean') {
        return `<div class="check-row"><input type="checkbox" id="to-${key}" ${o.default ? 'checked' : ''}/>
          <label for="to-${key}" title="${esc(o.help)}">${esc(o.label)}</label></div>`;
      }
      if (o.type === 'enum') {
        return `<div><label title="${esc(o.help)}">${esc(o.label)}</label>
          <select id="to-${key}">${o.choices.map((c) =>
            `<option ${c === o.default ? 'selected' : ''}>${c}</option>`).join('')}</select></div>`;
      }
      return `<div><label title="${esc(o.help)}">${esc(o.label)}</label>
        <input type="number" id="to-${key}" value="${o.default}" min="${o.min}" max="${o.max}" step="${o.step ?? (o.type === 'float' ? 0.0001 : 1)}"/></div>`;
    }).join('');
    const open = gid === 'base' ? 'open' : '';
    return `<details ${open}><summary>${esc(gname)}</summary>
      <div class="grid3" style="margin-top:8px">${fields}</div></details>`;
  }).join('');
}

async function createRun() {
  const name = document.getElementById('run-name').value.trim();
  if (!name) { toast('Donnez un nom au run', true); return; }
  const arch = state.archs.find((a) => a.id === state.selectedArch);

  const archConfig = { ...arch.default_config };
  for (const [key, sch] of Object.entries(arch.param_schema || {})) {
    const el = document.getElementById('ap-' + key);
    if (!el) continue;
    if (sch.type === 'boolean') archConfig[key] = el.checked;
    else if (sch.type === 'float') archConfig[key] = parseFloat(el.value);
    else archConfig[key] = parseInt(el.value, 10);
  }

  const trainingConfig = {};
  for (const [key, o] of Object.entries(state.options.options)) {
    const el = document.getElementById('to-' + key);
    if (!el) continue;
    if (o.type === 'boolean') trainingConfig[key] = el.checked;
    else if (o.type === 'enum') trainingConfig[key] = el.value;
    else if (o.type === 'float') trainingConfig[key] = parseFloat(el.value);
    else trainingConfig[key] = parseInt(el.value, 10);
  }

  const body = {
    name,
    architecture: state.selectedArch,
    arch_config: archConfig,
    training_config: trainingConfig,
    dataset_id: document.getElementById('run-dataset').value || null,
    tokenizer_id: document.getElementById('run-tokenizer').value || null,
  };

  const btn = document.getElementById('btn-create-run');
  btn.disabled = true;
  try {
    await api('/labs/runs', { method: 'POST', body: JSON.stringify(body) });
    toast('Entraînement lancé !');
    location.hash = '#/runs';
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
}

/* ── Datasets ─────────────────────────────────────────── */

async function refreshDatasets() {
  try { state.datasets = await api('/labs/datasets'); } catch (e) { toast(e.message, true); return; }
  const root = document.getElementById('datasets-list');
  if (!state.datasets.length) { root.innerHTML = '<p class="empty">Aucun dataset.</p>'; }
  else {
    root.innerHTML = state.datasets.map((d) => `
      <div class="item-row">
        <div><span class="t">${esc(d.name)}</span>
          <div class="m">${esc(d.source)}${d.source_identifier ? ' · ' + esc(d.source_identifier) : ''}
            ${d.num_samples ? ' · ' + d.num_samples + ' exemples' : ''}
            ${d.size_bytes ? ' · ' + fmtBytes(d.size_bytes) : ''}</div>
          ${d.error_message ? `<div class="m" style="color:var(--critical)">${esc(d.error_message)}</div>` : ''}</div>
        <div class="right"><span class="chip ${d.status}">${d.status}</span>
          <button class="danger small" data-id="${d.id}">🗑</button></div>
      </div>`).join('');
    root.querySelectorAll('button').forEach((b) => {
      b.onclick = async () => {
        if (!confirm('Supprimer ce dataset ?')) return;
        try { await api('/labs/datasets/' + b.dataset.id, { method: 'DELETE' }); refreshDatasets(); }
        catch (e) { toast(e.message, true); }
      };
    });
  }
  // Sync the tokenizer-form dataset selector
  const tokDs = document.getElementById('tok-dataset');
  tokDs.innerHTML = state.datasets.filter((d) => d.status === 'ready')
    .map((d) => `<option value="${d.id}">${esc(d.name)}</option>`).join('')
    || '<option value="">— Importez d\'abord un dataset —</option>';

  if (state.datasets.some((d) => d.status === 'downloading') &&
      (location.hash.includes('datasets') || location.hash.includes('tokenizers'))) {
    setTimeout(refreshDatasets, 3000);
  }
}

async function downloadHF() {
  const name = document.getElementById('ds-name').value.trim();
  const hfId = document.getElementById('ds-hfid').value.trim();
  if (!name || !hfId) { toast('Nom et identifiant HF requis', true); return; }
  try {
    await api('/labs/datasets/huggingface', {
      method: 'POST',
      body: JSON.stringify({ name, hf_id: hfId, task_type: document.getElementById('ds-task').value }),
    });
    toast('Téléchargement lancé');
    document.getElementById('ds-name').value = '';
    document.getElementById('ds-hfid').value = '';
    refreshDatasets();
  } catch (e) { toast(e.message, true); }
}

async function uploadDataset() {
  const name = document.getElementById('up-name').value.trim();
  const files = document.getElementById('up-files').files;
  if (!name || !files.length) { toast('Nom et fichiers requis', true); return; }
  const fd = new FormData();
  fd.append('name', name);
  fd.append('task_type', document.getElementById('up-task').value);
  for (const f of files) fd.append('files', f);
  try {
    await api('/labs/datasets/upload', { method: 'POST', body: fd });
    toast('Import lancé');
    document.getElementById('up-name').value = '';
    document.getElementById('up-files').value = '';
    refreshDatasets();
  } catch (e) { toast(e.message, true); }
}

/* ── Tokenizers ───────────────────────────────────────── */

async function refreshTokenizers() {
  try {
    state.tokenizers = await api('/labs/tokenizers');
    if (!state.algos) state.algos = (await api('/labs/tokenizers/algorithms')).algorithms;
  } catch (e) { toast(e.message, true); return; }

  const cards = document.getElementById('tok-algo-cards');
  cards.innerHTML = state.algos.map((a) => `
    <div class="opt-card ${a.id === state.selectedAlgo ? 'selected' : ''}" data-id="${a.id}">
      <div class="t">${esc(a.name)}</div><div class="d">${esc(a.description)}</div>
    </div>`).join('');
  cards.querySelectorAll('.opt-card').forEach((c) => {
    c.onclick = () => { state.selectedAlgo = c.dataset.id; refreshTokenizers(); };
  });
  document.getElementById('tok-byte').parentElement.style.display =
    state.selectedAlgo === 'bpe' ? '' : 'none';

  const root = document.getElementById('tokenizers-list');
  if (!state.tokenizers.length) { root.innerHTML = '<p class="empty">Aucun tokenizer entraîné.</p>'; }
  else {
    root.innerHTML = state.tokenizers.map((t) => `
      <div class="item-row">
        <div><span class="t">${esc(t.name)}</span>
          <div class="m">${esc(t.algorithm)} · vocab ${t.actual_vocab_size || t.vocab_size}
            ${t.stats?.num_texts ? ' · entraîné sur ' + t.stats.num_texts + ' textes' : ''}</div>
          ${t.error_message ? `<div class="m" style="color:var(--critical)">${esc(t.error_message)}</div>` : ''}</div>
        <div class="right"><span class="chip ${t.status}">${t.status}</span>
          <button class="danger small" data-id="${t.id}">🗑</button></div>
      </div>`).join('');
    root.querySelectorAll('button').forEach((b) => {
      b.onclick = async () => {
        if (!confirm('Supprimer ce tokenizer ?')) return;
        try { await api('/labs/tokenizers/' + b.dataset.id, { method: 'DELETE' }); refreshTokenizers(); }
        catch (e) { toast(e.message, true); }
      };
    });
  }

  const play = document.getElementById('play-tokenizer');
  const ready = state.tokenizers.filter((t) => t.status === 'ready');
  play.innerHTML = ready.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('')
    || '<option value="">— Aucun tokenizer prêt —</option>';

  if (state.tokenizers.some((t) => t.status === 'training') && location.hash.includes('tokenizers')) {
    setTimeout(refreshTokenizers, 3000);
  }
}

async function trainTokenizer() {
  const name = document.getElementById('tok-name').value.trim();
  const datasetId = document.getElementById('tok-dataset').value;
  if (!name || !datasetId) { toast('Nom et dataset requis', true); return; }
  const special = document.getElementById('tok-special').value
    .split(',').map((s) => s.trim()).filter(Boolean);
  try {
    await api('/labs/tokenizers', {
      method: 'POST',
      body: JSON.stringify({
        name,
        dataset_id: datasetId,
        algorithm: state.selectedAlgo,
        vocab_size: parseInt(document.getElementById('tok-vocab').value, 10),
        min_frequency: parseInt(document.getElementById('tok-minfreq').value, 10),
        lowercase: document.getElementById('tok-lower').checked,
        byte_level: document.getElementById('tok-byte').checked,
        special_tokens: special.length ? special : null,
      }),
    });
    toast('Entraînement du tokenizer lancé');
    document.getElementById('tok-name').value = '';
    refreshTokenizers();
  } catch (e) { toast(e.message, true); }
}

let playTimer = null;
async function playEncode() {
  clearTimeout(playTimer);
  playTimer = setTimeout(async () => {
    const tokId = document.getElementById('play-tokenizer').value;
    const text = document.getElementById('play-text').value;
    const box = document.getElementById('play-tokens');
    const stats = document.getElementById('play-stats');
    if (!tokId || !text.trim()) { box.innerHTML = ''; stats.innerHTML = ''; return; }
    try {
      const r = await api(`/labs/tokenizers/${tokId}/encode`, {
        method: 'POST', body: JSON.stringify({ text }),
      });
      box.innerHTML = r.tokens.map((t, i) =>
        `<span class="token-chip">${esc(t)}<small>${r.ids[i]}</small></span>`).join('');
      stats.innerHTML =
        `<div class="stat-tile"><div class="v">${r.num_tokens}</div><div class="l">tokens</div></div>` +
        `<div class="stat-tile"><div class="v">${r.vocab_size}</div><div class="l">vocabulaire</div></div>`;
    } catch (e) { toast(e.message, true); }
  }, 300);
}

/* ── Architectures catalog ────────────────────────────── */

async function renderArchsCatalog() {
  try { await loadStatics(); } catch (e) { toast(e.message, true); return; }
  document.getElementById('archs-list').innerHTML = state.archs.map((a) => `
    <div class="card">
      <div class="run-head"><div>
        <div class="name">${esc(a.name)}</div>
        <div class="meta">${esc(a.description)}</div></div>
        <span class="chip">≥ ${a.min_vram_mb} Mo VRAM</span></div>
      <div class="tags" style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap">
        ${(a.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}
        ${(a.task_types || []).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}</div>
      <details><summary>Paramètres (${Object.keys(a.param_schema || {}).length})</summary>
        <div class="table-scroll"><table class="metrics">
          <tr><th>paramètre</th><th>type</th><th>min</th><th>max</th><th>défaut</th></tr>
          ${Object.entries(a.param_schema || {}).map(([k, s]) => `
            <tr><td>${esc(s.label || k)}</td><td>${esc(s.type)}</td>
            <td>${s.min ?? '—'}</td><td>${s.max ?? '—'}</td>
            <td>${esc(JSON.stringify(a.default_config[k] ?? '—'))}</td></tr>`).join('')}
        </table></div></details>
    </div>`).join('');
}

/* ── Hardware ─────────────────────────────────────────── */

async function renderHardware() {
  const root = document.getElementById('hardware-info');
  try {
    const [info, rec] = await Promise.all([
      api('/hardware/info'), api('/hardware/recommendations'),
    ]);
    const gpus = info.gpus.map((g) => `
      <div class="stat-tile"><div class="v">${esc(g.name)}</div>
        <div class="l">${g.vram_free_mb} / ${g.vram_total_mb} Mo VRAM libres · CUDA ${esc(g.cuda_version || '?')}</div></div>`).join('')
      || '<div class="stat-tile"><div class="v">Aucun GPU</div><div class="l">entraînement sur CPU</div></div>';
    root.innerHTML = `
      <div class="card"><h2 style="margin-top:0">Machine — ${esc(rec.tier_label)}</h2>
        <div class="stats-row">${gpus}
          <div class="stat-tile"><div class="v">${Math.round(info.ram_total_mb / 1024)} Go</div><div class="l">RAM (${Math.round(info.ram_free_mb / 1024)} Go libres)</div></div>
          <div class="stat-tile"><div class="v">${info.cpu ? esc(String(info.cpu.logical_cores)) : '?'} threads</div><div class="l">${esc(info.cpu?.name || 'CPU')}</div></div>
        </div></div>
      <div class="card"><h2 style="margin-top:0">Recommandations d'entraînement</h2>
        <div class="stats-row">
          <div class="stat-tile"><div class="v">${rec.training.recommended_batch_size}</div><div class="l">batch size conseillé</div></div>
          <div class="stat-tile"><div class="v">${rec.training.recommended_learning_rate}</div><div class="l">learning rate conseillé</div></div>
          <div class="stat-tile"><div class="v">${rec.training.use_mixed_precision ? 'fp16' : 'fp32'}</div><div class="l">précision</div></div>
          <div class="stat-tile"><div class="v">${(rec.training.max_recommended_params / 1e6).toFixed(0)} M</div><div class="l">paramètres max conseillés</div></div>
        </div>
        <p class="subtitle" style="margin:10px 0 0">${(rec.training.notes || []).map(esc).join(' · ')}</p>
        <p class="subtitle" style="margin:4px 0 0">Architectures conseillées : ${(rec.training.recommended_architectures || []).map(esc).join(', ')}</p>
      </div>`;
  } catch (e) { root.innerHTML = `<div class="card empty">Impossible de lire le matériel : ${esc(e.message)}</div>`; }
}

/* ── Console ──────────────────────────────────────────── */

function openConsole() {
  if (state.consoleWs && state.consoleWs.readyState <= 1) return;
  const box = document.getElementById('console-log');
  box.innerHTML = '';
  const ws = new WebSocket(`${WS_BASE}/ws/logs`);
  state.consoleWs = ws;
  ws.onmessage = (msg) => {
    const e = JSON.parse(msg.data);
    const line = document.createElement('div');
    line.className = 'lvl-' + e.level;
    const ts = new Date(e.ts * 1000).toLocaleTimeString('fr-FR');
    line.innerHTML = `<span class="lg">${ts} ${esc(e.logger)}</span> ${esc(e.message)}`;
    box.appendChild(line);
    while (box.childNodes.length > 1500) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  };
}

/* ── Shutdown ─────────────────────────────────────────── */

async function shutdown() {
  if (!confirm("Arrêter le serveur Labs ?")) return;
  try { await api('/system/shutdown', { method: 'POST' }); } catch { /* server exits */ }
  document.body.innerHTML =
    '<div style="display:flex;height:100vh;align-items:center;justify-content:center;color:#898781;font-size:15px">⏻ Serveur Labs arrêté. Vous pouvez fermer cet onglet.</div>';
}

/* ── Boot ─────────────────────────────────────────────── */

document.getElementById('btn-create-run').onclick = createRun;
document.getElementById('btn-ds-hf').onclick = downloadHF;
document.getElementById('btn-ds-upload').onclick = uploadDataset;
document.getElementById('btn-tok-train').onclick = trainTokenizer;
document.getElementById('btn-shutdown').onclick = shutdown;
document.getElementById('play-text').addEventListener('input', playEncode);
document.getElementById('play-tokenizer').addEventListener('change', playEncode);

route();
