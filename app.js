// Personal OS — dashboard fetcher.
// Pulls /api/dashboard from the VM backend and patches the DOM.
// Missing fields fall through: the existing static markup acts as placeholder.

const API = 'https://personal-os-api.collinsoik.dev';
const POLL_MS = 30_000;
const MUSIC_TICK_MS = 500;

const USER = {
  fullNameHtml: 'Collin <em>Soik</em>',
  subtitle: 'Student · Raleigh',
  topBar: '◎ Personal OS',
  location: { label: 'Raleigh, NC', lat: 35.7796, lon: -78.6382 },
};

const DAY_LABELS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const MONTHS_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return [...root.querySelectorAll(sel)]; }

function setText(sel, value) {
  if (value == null || value === '') return;
  const el = $(sel); if (el) el.textContent = value;
}
function setHTML(sel, html) {
  if (html == null || html === '') return;
  const el = $(sel); if (el) el.innerHTML = html;
}

function ordinalSuffix(n) {
  const v = n % 100; if (v >= 11 && v <= 13) return 'th';
  switch (n % 10) { case 1: return 'st'; case 2: return 'nd'; case 3: return 'rd'; default: return 'th'; }
}

function greeting(date) {
  const h = date.getHours();
  if (h < 5) return 'Good <em>night,</em>';
  if (h < 12) return 'Good <em>morning,</em>';
  if (h < 17) return 'Good <em>afternoon,</em>';
  if (h < 21) return 'Good <em>evening,</em>';
  return 'Good <em>night,</em>';
}

function dayOfYear(date) {
  const start = new Date(date.getFullYear(), 0, 0);
  const diff = date - start;
  return Math.floor(diff / 86_400_000);
}

function renderStaticBoot() {
  setHTML('.card.speaker .name', USER.fullNameHtml);
  setText('.card.speaker .body .mono', USER.subtitle);
  setText('.topbar .left span', USER.topBar);

  const now = new Date();
  const firstName = USER.fullNameHtml.replace(/<[^>]+>/g, '').split(' ')[0];
  setHTML('.hero-l h1', `${greeting(now)} ${firstName}.`);
  const longDay = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][now.getDay()];
  setText('.hero-l .sub', `${longDay} · ${MONTHS[now.getMonth()]} ${now.getDate()}, ${now.getFullYear()} · Day ${dayOfYear(now)} of 365`);
  setHTML('.calendar h2', `${longDay}, <em>${MONTHS[now.getMonth()]} ${now.getDate()}</em>`);
  setText('.card.calendar .card-head .mono:last-child', `${MONTHS_SHORT[now.getMonth()]} ${now.getFullYear()}`);
  buildWeekStrip(now);
}

function buildWeekStrip(today) {
  const days = $('#days');
  if (!days) return;
  days.innerHTML = '';
  const mondayOffset = (today.getDay() + 6) % 7;
  const monday = new Date(today); monday.setDate(today.getDate() - mondayOffset);
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday); d.setDate(monday.getDate() + i);
    const el = document.createElement('div');
    el.className = 'day' + (d.toDateString() === today.toDateString() ? ' active' : '');
    el.innerHTML = `<div class="wd">${DAY_LABELS[d.getDay()]}</div><div class="dn">${d.getDate()}</div>`;
    el.addEventListener('click', () => {
      days.querySelectorAll('.day').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
    });
    days.appendChild(el);
  }
}

/* ── renderers ────────────────────────────────────────── */

function renderVitals(v) {
  if (!v) return;
  if (v.steps != null) setText('.card.vitals .steps b', v.steps.toLocaleString());
  const bioMap = ['heart_bpm','sleep_hours','hrv_ms','water_l'];
  $$('.card.vitals .bios .bio').forEach((el, i) => {
    const key = bioMap[i]; const raw = v[key]; if (raw == null) return;
    const units = { heart_bpm: 'bpm', sleep_hours: 'hrs', hrv_ms: 'ms', water_l: 'L' }[key];
    el.querySelector('.v').innerHTML = `${raw}<small>${units}</small>`;
  });
  if (v.rings) {
    const ringOrder = ['move','exercise','stand'];
    $$('.card.vitals .rings .ring').forEach((el, i) => {
      const r = v.rings[ringOrder[i]]; if (!r) return;
      const pct = Math.round((r.value / r.goal) * 100);
      const arc = el.querySelectorAll('circle')[1];
      if (arc) arc.setAttribute('stroke-dasharray', `${pct} 100`);
      const n = el.querySelector('.n'); if (n) n.textContent = `${r.value}/${r.goal}`;
    });
  }
}

function renderThought(t) {
  if (!t?.text) return;
  setText('.card.thought blockquote', t.text);
  setText('.card.thought .attr b', t.author ? `— ${t.author}` : '');
  const source = t.source ? t.source : formatTopDate(new Date());
  setText('.card.thought .attr span', source);
}
function formatTopDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getMonth()+1)}·${pad(d.getDate())}·${String(d.getFullYear()).slice(2)}`;
}

function renderReading(r) {
  if (!r) return;
  setText('.card.reading .btitle', r.title);
  setText('.card.reading .bauthor', r.author);
  setText('.card.reading .pg span:first-child', `pg ${r.page} / ${r.total_pages}`);
  const pbar = $('.card.reading .pbar i');
  if (pbar) pbar.style.width = `${r.progress}%`;
  setText('.card.reading .card-head .mono:last-child', `${r.progress}% · pg ${r.page}`);
  if (r.up_next) setText('.card.reading .next .tl', r.up_next);
}

function renderHabits(habits) {
  if (!habits?.length) return;
  const todayStr = new Date().toISOString().slice(0, 10);
  const headRight = $('.card.habits .card-head .mono:last-child');
  const rows = $$('.card.habits .row');
  habits.slice(0, rows.length).forEach((h, idx) => {
    const row = rows[idx];
    if (!row) return;
    row.querySelector('.hlbl').textContent = h.label;
    const dots = row.querySelector('.dots');
    if (!dots) return;
    dots.innerHTML = '';
    const today = new Date();
    for (let i = 13; i >= 0; i--) {
      const d = new Date(today); d.setDate(today.getDate() - i);
      const ds = d.toISOString().slice(0, 10);
      const tick = h.ticks.find(t => t.day === ds);
      const i1 = document.createElement('i');
      if (!tick) i1.className = 'miss';
      else if (tick.level === 1) i1.className = 'l1';
      else if (tick.level === 2) i1.className = 'l2';
      else if (tick.level >= 3) i1.className = 'l3';
      dots.appendChild(i1);
    }
    // streak = consecutive days from today backwards with level > 0
    let streak = 0;
    for (let i = 0; i < 365; i++) {
      const d = new Date(today); d.setDate(today.getDate() - i);
      const ds = d.toISOString().slice(0, 10);
      const tick = h.ticks.find(t => t.day === ds);
      if (tick && tick.level > 0) streak++; else break;
    }
    const s = row.querySelector('.streak');
    if (s) s.innerHTML = `${streak}<small>d</small>`;
  });
  // today count: any habit hit today
  const hits = habits.filter(h => h.ticks.some(t => t.day === todayStr && t.level > 0)).length;
  if (headRight) headRight.textContent = `${hits} of ${habits.length} today`;
}

function renderCalendar(cal) {
  if (!cal?.events?.length) return;
  const sched = $('.card.calendar .sched');
  if (!sched) return;
  sched.innerHTML = '';
  cal.events.forEach(ev => {
    const row = document.createElement('div');
    row.className = 'ev' + (ev.now ? ' now' : '');
    row.innerHTML = `
      <div class="t"><b>${ev.now ? 'NOW' : ev.time_head || ''}</b>${ev.time_tail || ''}</div>
      <div>
        <div class="title">${escapeHtml(ev.title || '')}</div>
        <div class="desc">${escapeHtml(ev.desc || '')}</div>
      </div>
      <div class="marker"></div>`;
    sched.appendChild(row);
  });
}

function renderInbox(email) {
  if (!email) return;
  if (typeof email.unread === 'number') {
    setText('.card.inbox .card-head .mono:last-child', `${email.unread} unread`);
  }
  if (!email.items?.length) return;
  const list = $('.card.inbox .list');
  if (!list) return;
  list.innerHTML = '';
  const palette = ['a','b','c','d'];
  email.items.slice(0, 5).forEach((m, i) => {
    const initials = (m.from || '??').split(/\s+/).map(s => s[0]).slice(0, 2).join('').toUpperCase();
    const row = document.createElement('div');
    row.className = 'row';
    const tag = m.urgent ? `<span class="tag">Urgent</span>` : '';
    row.innerHTML = `
      <div class="ava ${palette[i % palette.length]}">${escapeHtml(initials)}</div>
      <div>
        <div class="name">${escapeHtml(m.from || '')} ${tag}</div>
        <div class="prev">${escapeHtml(m.preview || m.subject || '')}</div>
      </div>
      <div class="time">${escapeHtml(m.time_rel || '')}</div>`;
    list.appendChild(row);
  });
}

let musicAnchor = null; // { ...payload, received_at: performance.now() }
let musicLastTrack = null;
let musicTimer = null;
let musicLastSplit = -1;

function renderMusic(m) {
  if (!m) return;
  musicAnchor = { ...m, received_at: performance.now() };
  const trackKey = `${m.title}|${m.artist}|${m.album || ''}`;
  if (trackKey !== musicLastTrack) {
    musicLastTrack = trackKey;
    paintMusicStatic();
    musicLastSplit = -1; // force bar repaint on track change
  }
  applyMusicTick();
  if (musicTimer == null) {
    musicTimer = setInterval(applyMusicTick, MUSIC_TICK_MS);
  }
}

function paintMusicStatic() {
  const m = musicAnchor;
  if (!m) return;
  const hasTrack = m.title && m.title !== '—';
  if (hasTrack) {
    setHTML('.card.playing .np-meta .title', escapeHtml(m.title));
    setText('.card.playing .np-meta .sub', [m.artist, m.album].filter(Boolean).join(' · '));
  }
  const cover = document.querySelector('.card.playing .cover');
  if (cover) {
    cover.style.setProperty(
      '--album-art',
      m.cover_url ? `url("${m.cover_url}")` : 'none',
    );
  }
}

function applyMusicTick() {
  const m = musicAnchor;
  if (!m) return;
  setText('.card.playing .card-head .mono:last-child', m.playing ? 'Playing' : 'Paused');
  if (!m.duration_ms || m.progress_ms == null) return;
  let progress = m.progress_ms;
  if (m.playing) {
    progress = Math.min(
      m.duration_ms,
      m.progress_ms + (performance.now() - m.received_at),
    );
  }
  const pct = Math.min(1, progress / m.duration_ms);
  const bars = $$('#wave i');
  const split = Math.round(bars.length * pct);
  if (split !== musicLastSplit) {
    bars.forEach((b, i) => {
      const played = i < split;
      b.classList.toggle('played', played);
      b.classList.toggle('future', !played);
    });
    musicLastSplit = split;
  }
  setText('#npTime', msToMS(Math.round(progress)));
  setText('.card.playing .np-ctrl > span:last-child', msToMS(m.duration_ms));
}

function msToMS(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function renderProject(p) {
  if (!p) return;
  setHTML('.card.project h3', escapeHtml(p.title));
  setText('.card.project .bc', p.subtitle || '');
  if (p.due) setText('.card.project .card-head .mono:last-child', `Due ${p.due}`);
  setText('#pct', `${p.progress}%`);
  const bar = $('#bar'); if (bar) bar.style.width = `${p.progress}%`;
  const tasks = $('#tasks');
  if (tasks && p.tasks?.length) {
    tasks.innerHTML = '';
    p.tasks.forEach(t => {
      const el = document.createElement('div');
      el.className = 'task' + (t.done ? ' done' : '');
      el.dataset.t = t.id;
      el.innerHTML = `
        <div class="box"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5"><path d="M5 12l5 5 9-11"/></svg></div>
        <div class="label">${escapeHtml(t.label)}</div>`;
      el.addEventListener('click', () => el.classList.toggle('done')); // TODO: POST to API in task #8
      tasks.appendChild(el);
    });
  }
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

/* ── daily quote (local, static) ──────────────────────── */

let LOCAL_QUOTES = [];

async function loadQuotes() {
  try {
    const res = await fetch('/quotes.json', { cache: 'force-cache' });
    if (!res.ok) return;
    LOCAL_QUOTES = await res.json();
    renderDailyQuote();
  } catch (err) {
    console.warn('quotes load failed:', err);
  }
}

function renderDailyQuote() {
  if (!LOCAL_QUOTES.length) return;
  // Deterministic by absolute day — a given date always maps to the same quote.
  const now = new Date();
  const daysSinceEpoch = Math.floor(now.getTime() / 86_400_000);
  const q = LOCAL_QUOTES[daysSinceEpoch % LOCAL_QUOTES.length];
  const bq = $('.card.thought blockquote');
  if (bq) {
    bq.textContent = q.text;
    // Shrink font to keep long quotes inside the card without clipping.
    const len = q.text.length;
    const size = len <= 120 ? 17 : len <= 180 ? 15 : len <= 240 ? 14 : 13;
    bq.style.fontSize = `${size}px`;
  }
  setText('.card.thought .attr b', q.author ? `— ${q.author}` : '');
  setText('.card.thought .attr span', q.source || formatTopDate(now));
}

async function renderWeather() {
  const { label, lat, lon } = USER.location;
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m&temperature_unit=fahrenheit`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    const temp = data?.current?.temperature_2m;
    if (temp == null) return;
    setText('#loc', `${label} · ${Math.round(temp)}°F`);
  } catch (err) {
    console.warn('weather fetch failed:', err);
  }
}

/* ── fetch loop ───────────────────────────────────────── */

async function refresh() {
  renderWeather();
  try {
    const res = await fetch(`${API}/api/dashboard`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderVitals(data.vitals);
    renderThought(data.thought);
    renderReading(data.reading);
    renderHabits(data.habits);
    renderCalendar(data.calendar);
    renderInbox(data.email);
    renderMusic(data.music);
    renderProject(data.project);
  } catch (err) {
    console.warn('dashboard refresh failed:', err);
  }
}

renderStaticBoot();
loadQuotes();
refresh();
setInterval(refresh, POLL_MS);
