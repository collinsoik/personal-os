// Personal OS — dashboard fetcher.
// Pulls /api/dashboard from the VM backend and patches the DOM.
// Missing fields fall through: the existing static markup acts as placeholder.

const API = 'https://personal-os-api.collinsoik.dev';
const FALLBACK_POLL_MS = 2 * 60 * 1000; // SSE is primary; this is just a safety net
const MUSIC_TICK_MS = 500;

(function unlockFromHash() {
  const m = location.hash.match(/unlock=([A-Za-z0-9]+)/);
  if (m) {
    localStorage.setItem('po_secret', m[1]);
    history.replaceState(null, '', location.pathname);
  }
})();
const PO_SECRET = () => localStorage.getItem('po_secret');

let selectedDayIndex = null;  // which day of the week strip is active (0=Mon .. 6=Sun)

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

function renderSched(events) {
  const sched = $('.card.calendar .sched');
  if (!sched) return;
  sched.innerHTML = '';
  if (!events?.length) {
    const row = document.createElement('div');
    row.className = 'ev empty';
    row.innerHTML = `<div class="t"></div><div><div class="title">No events</div></div><div class="marker"></div>`;
    sched.appendChild(row);
    return;
  }
  events.forEach(ev => {
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

function updateCalendarHeader(dateISO) {
  const d = new Date(dateISO + 'T00:00:00');
  const longDay = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][d.getDay()];
  setHTML('.calendar h2', `${longDay}, <em>${MONTHS[d.getMonth()]} ${d.getDate()}</em>`);
}

function renderCalendar(cal) {
  if (!cal?.days?.length) return;
  const daysEl = $('#days');
  if (!daysEl) return;

  if (selectedDayIndex == null) {
    const todayIdx = cal.days.findIndex(d => d.is_today);
    selectedDayIndex = todayIdx >= 0 ? todayIdx : 0;
  }

  daysEl.innerHTML = '';
  cal.days.forEach((day, i) => {
    const dNum = parseInt((day.date || '').split('-')[2], 10) || '';
    const el = document.createElement('div');
    el.className = 'day' + (i === selectedDayIndex ? ' active' : '');
    const dot = day.events?.length ? '<span class="cnt"></span>' : '';
    el.innerHTML = `<div class="wd">${day.label}</div><div class="dn">${dNum}</div>${dot}`;
    el.addEventListener('click', () => {
      selectedDayIndex = i;
      daysEl.querySelectorAll('.day').forEach(x => x.classList.remove('active'));
      el.classList.add('active');
      renderSched(day.events);
      updateCalendarHeader(day.date);
    });
    daysEl.appendChild(el);
  });

  const selected = cal.days[selectedDayIndex];
  if (selected) {
    renderSched(selected.events);
    updateCalendarHeader(selected.date);
  }
}

/* Routine digest — UI driven by static mock data for now.
   Real backend wiring lands later. */
const ROUTINE_DATA = {
  scanned: 47,
  flagged: 9,
  urgent: [
    { id: 'u1', mono: 'ML', tone: '#F0C7B5', from: 'Maya Lin',
      subject: 'Re: v2.7 assets — need your sign-off today',
      summary: 'Maya is blocked on the launch hand-off. She needs the brand pack approved before 4pm or design pushes a day.',
      action: 'Reply with go/no-go on the hero treatment.', time: '12m' },
    { id: 'u2', mono: 'AC', tone: '#E8C4B8', from: 'Arc Collective',
      subject: 'Residency contract — countersign by EOD',
      summary: 'Welcome packet attached; the host needs a countersigned PDF returned today to lock the studio dates.',
      action: 'Sign and send back the residency PDF.', time: '1h' },
  ],
  high: [
    { id: 'h1', mono: 'TH', tone: '#C8D8C2', from: 'Theo Harris',
      subject: 'Moved our sync · new calendar invite attached',
      summary: 'Pushed to Thursday 3pm — wants pre-read on the Q3 retro before the call.', time: '48m' },
    { id: 'h2', mono: 'EN', tone: '#BBD0DE', from: 'Eliza N.',
      subject: '8pm still on? Booked us a corner table',
      summary: 'Confirming dinner; will swing by the studio after if you want to walk over.', time: '2h' },
    { id: 'h3', mono: 'JR', tone: '#E0D0B8', from: 'Jules Reyes',
      subject: 'Q3 budget — three line items flagged',
      summary: 'Finance wants context on travel, contractors, and the studio sublet before Friday.', time: '3h' },
  ],
  fyi: [
    { id: 'f1', from: 'Stripe',  subject: 'Payout of $4,210 on the way',         time: '4h' },
    { id: 'f2', from: 'GitHub',  subject: '3 PRs awaiting your review',          time: '5h' },
    { id: 'f3', from: 'Figma',   subject: 'New comments on Launch / hero',       time: '7h' },
    { id: 'f4', from: 'Read.cv', subject: 'Weekly digest — 12 reads',            time: '9h' },
  ],
};

const routineState = { fyiExpanded: false, digest: null };

const ROUTINE_TONE_PALETTE = ['#F0C7B5','#E8C4B8','#C8D8C2','#BBD0DE','#E0D0B8','#D8C8E0','#C2D8D0'];
function routineMono(name) {
  return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0].toUpperCase()).join('') || '?';
}
function routineTone(id, idx) {
  const seed = String(id || idx || '');
  let h = 0; for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return ROUTINE_TONE_PALETTE[h % ROUTINE_TONE_PALETTE.length];
}

function fmtRoutineTime(dt) {
  return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

function renderRoutineSchedule(d) {
  const ranAt = d && d.ranAt ? new Date(d.ranAt) : null;
  const nextAt = d && d.nextAt ? new Date(d.nextAt) : null;
  setText('.routine .rc-ran', ranAt ? fmtRoutineTime(ranAt) : '—');
  setText('.routine .rc-next-time', nextAt ? fmtRoutineTime(nextAt) : '—');

  const runs = document.querySelectorAll('.routine .rc-pop .run');
  if (runs.length !== 3) return;
  const labels = ['morning brief', 'midday', 'evening wrap'];
  if (!ranAt) {
    runs.forEach((el, i) => { el.textContent = `— ${labels[i]}`; el.classList.remove('current'); });
    return;
  }
  const h = ranAt.getHours();
  const slotIdx = h < 9 ? 0 : h < 15 ? 1 : 2;
  const HOUR = 3600 * 1000;
  const slots = [0, 1, 2].map((i) => new Date(ranAt.getTime() + (i - slotIdx) * 6 * HOUR));
  runs.forEach((el, i) => {
    const suffix = i === slotIdx ? ' — last run' : '';
    el.innerHTML = `${escapeHtml(fmtRoutineTime(slots[i]))} &nbsp; ${escapeHtml(labels[i] + suffix)}`;
    el.classList.toggle('current', i === slotIdx);
  });
}

function renderRoutine(digest) {
  const body = document.getElementById('rcBody');
  if (!body) return;
  if (digest !== undefined) routineState.digest = digest;
  const d = routineState.digest || ROUTINE_DATA;
  setText('.routine .rc-meta .counts', `${d.scanned ?? 0}/${d.flagged ?? 0}`);
  renderRoutineSchedule(d);

  const fyiAll = d.fyi || [];
  const fyiVisible = routineState.fyiExpanded ? fyiAll : fyiAll.slice(0, 3);
  const fyiHidden = fyiAll.length - fyiVisible.length;

  const urgentHtml = (d.urgent || []).map((it, i) => {
    if (it.dismissed) {
      return `<div class="rc-dismissed">${it.dismissed === 'done' ? '✓ marked done' : '↩ snoozed'} — ${escapeHtml(it.from)}</div>`;
    }
    const mono = it.mono || routineMono(it.from);
    const tone = it.tone || routineTone(it.id, i);
    const actHtml = it.action ? `<div class="act">↳ ${escapeHtml(it.action)}</div>` : '';
    return `
      <div class="rc-urgent-card" data-id="${it.id}">
        <div class="row1">
          <div class="rc-avatar" style="background:${tone}">${escapeHtml(mono)}</div>
          <div class="body">
            <div class="top">
              <div class="from">${escapeHtml(it.from)} <span class="rc-pill">Urgent</span></div>
              <div class="time">${escapeHtml(it.time || '')}</div>
            </div>
            <div class="subj">${escapeHtml(it.subject)}</div>
            <div class="summ">${escapeHtml(it.summary || '')}</div>
            ${actHtml}
            <div class="rc-actions">
              <button data-act="done" data-id="${it.id}">Done</button>
              <button data-act="snooze" data-id="${it.id}">Snooze</button>
            </div>
          </div>
        </div>
      </div>`;
  }).join('');

  const highHtml = (d.high || []).map((it, i) => {
    if (it.dismissed) {
      return `<div class="rc-high-row rc-dismissed">${it.dismissed === 'done' ? '✓ done' : '↩ snoozed'} — ${escapeHtml(it.from)}</div>`;
    }
    const mono = it.mono || routineMono(it.from);
    const tone = it.tone || routineTone(it.id, i);
    return `
      <div class="rc-high-row" data-id="${it.id}">
        <div class="rc-avatar" style="background:${tone}">${escapeHtml(mono)}</div>
        <div class="body">
          <div class="top">
            <div class="from">${escapeHtml(it.from)}</div>
            <div class="time">${escapeHtml(it.time || '')}</div>
          </div>
          <div class="subj">${escapeHtml(it.subject)}</div>
          <div class="summ">${escapeHtml(it.summary || '')}</div>
          <div class="rc-actions">
            <button data-act="done" data-id="${it.id}">Done</button>
            <button data-act="snooze" data-id="${it.id}">Snooze</button>
          </div>
        </div>
      </div>`;
  }).join('');

  const fyiHtml = fyiVisible.map((it) => {
    if (it.dismissed) return '';
    return `
      <div class="rc-fyi-row" data-id="${it.id}">
        <div class="body">
          <span class="from">${escapeHtml(it.from)}</span>
          <span class="subj">${escapeHtml(it.subject)}</span>
        </div>
        <span class="time">${escapeHtml(it.time || '')}</span>
      </div>`;
  }).join('');

  const moreBtn = (fyiHidden > 0 || routineState.fyiExpanded)
    ? `<button class="rc-more" data-act="toggle-fyi">${routineState.fyiExpanded ? '↑ collapse' : `+ ${fyiHidden} more`}</button>`
    : '';

  body.innerHTML = `
    <div class="rc-section urgent">
      <div class="rc-col-head">
        <div class="lbl"><span class="ix">A</span><span>Urgent</span></div>
        <div class="cnt">${(d.urgent || []).length} need reply</div>
      </div>
      ${urgentHtml}
    </div>
    <div class="rc-section high">
      <div class="rc-col-head">
        <div class="lbl"><span class="ix">B</span><span>High importance</span></div>
        <div class="cnt">${(d.high || []).length} this run</div>
      </div>
      ${highHtml}
    </div>
    <div class="rc-section fyi">
      <div class="rc-col-head">
        <div class="lbl"><span class="ix">C</span><span>FYI</span></div>
        <div class="cnt">${fyiAll.length}</div>
      </div>
      ${fyiHtml}
      ${moreBtn}
    </div>
  `;
}

function findRoutineItem(id) {
  const d = routineState.digest;
  if (!d) return null;
  for (const bucket of ['urgent', 'high', 'fyi']) {
    const list = d[bucket] || [];
    const item = list.find(x => x.id === id);
    if (item) return item;
  }
  return null;
}

async function dismissRoutineItem(id, action) {
  const secret = PO_SECRET();
  const item = findRoutineItem(id);
  if (!item) return;
  const previous = item.dismissed ?? null;
  // Optimistic update
  item.dismissed = action;
  renderRoutine();
  if (!secret) {
    console.warn('routine dismiss: not unlocked, kept local-only');
    return;
  }
  try {
    const res = await fetch(`${API}/api/routine/dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-PO-Secret': secret },
      body: JSON.stringify({ id, action }),
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    console.warn('routine dismiss failed:', err);
    item.dismissed = previous;
    renderRoutine();
  }
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.routine [data-act]');
  if (!btn) return;
  const act = btn.dataset.act;
  if (act === 'toggle-fyi') {
    routineState.fyiExpanded = !routineState.fyiExpanded;
    renderRoutine();
    return;
  }
  const id = btn.dataset.id;
  if (id && (act === 'done' || act === 'snooze')) {
    dismissRoutineItem(id, act === 'done' ? 'done' : 'snoozed');
  }
});

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
    if (m.cover_url) {
      cover.style.setProperty('--album-art', `url("${m.cover_url}")`);
    } else {
      cover.style.removeProperty('--album-art');
    }
  }
}

const PLAY_PATH  = '<path d="M8 5v14l11-7z"/>';
const PAUSE_PATH = '<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>';

function applyMusicTick() {
  const m = musicAnchor;
  if (!m) return;
  setText('.card.playing .card-head .mono:last-child', m.playing ? 'Playing' : 'Paused');
  const icon = document.getElementById('npIcon');
  if (icon) icon.innerHTML = m.playing ? PAUSE_PATH : PLAY_PATH;
  const btn = document.getElementById('npPlay');
  if (btn && !btn.disabled) btn.title = m.playing ? 'pause' : 'play';
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

/* ── music controls ────────────────────────────────────── */

let musicToastTimer = null;
function showMusicToast(msg) {
  const el = document.querySelector('.card.playing .card-head .mono:last-child');
  if (!el) return;
  el.textContent = String(msg || 'error').toUpperCase();
  clearTimeout(musicToastTimer);
  musicToastTimer = setTimeout(() => {
    if (musicAnchor) el.textContent = musicAnchor.playing ? 'Playing' : 'Paused';
  }, 3000);
}

async function spotifyControl(action) {
  const secret = PO_SECRET();
  if (!secret) return;
  if ((action === 'play' || action === 'pause') && musicAnchor) {
    musicAnchor.playing = (action === 'play');
    musicAnchor.received_at = performance.now();
    applyMusicTick();
  }
  try {
    const res = await fetch(`${API}/api/spotify/${action}`, {
      method: 'POST',
      headers: { 'X-PO-Secret': secret },
      cache: 'no-store',
    });
    if (!res.ok) {
      let err = 'control failed';
      try {
        const j = await res.json();
        err = (j && (j.detail?.error || j.error || j.detail)) || err;
      } catch {}
      showMusicToast(err);
      return;
    }
    const data = await res.json();
    if (data && data.music) renderMusic(data.music);
  } catch {
    showMusicToast('network error');
  }
}

function wireMusicControls() {
  const card = document.querySelector('.card.playing');
  if (!card) return;
  const buttons = card.querySelectorAll('.ctrls button');
  if (buttons.length < 3) return;
  const [prevBtn, playBtn, nextBtn] = buttons;
  if (!PO_SECRET()) {
    buttons.forEach(b => { b.disabled = true; b.title = 'Unlock controls to use'; });
    return;
  }
  playBtn.addEventListener('click', () => {
    spotifyControl(musicAnchor?.playing ? 'pause' : 'play');
  });
  prevBtn.addEventListener('click', () => spotifyControl('previous'));
  nextBtn.addEventListener('click', () => spotifyControl('next'));
}

function connectEvents() {
  const es = new EventSource(`${API}/api/events`);
  es.addEventListener('music', (ev) => {
    try { renderMusic(JSON.parse(ev.data)); } catch {}
  });
  es.addEventListener('routine', (ev) => {
    try { renderRoutine(JSON.parse(ev.data)); } catch {}
  });
  // EventSource auto-reconnects on transient errors; no-op on `onerror`.
  return es;
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
    // Card is now the tall half of the left stack — scale gently based on length.
    const len = q.text.length;
    const size = len <= 180 ? 19 : len <= 300 ? 17 : len <= 420 ? 15 : 14;
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

async function pingPresence() {
  try {
    await fetch(`${API}/api/presence/ping`, { method: 'POST', cache: 'no-store' });
  } catch (err) {
    console.warn('presence ping failed:', err);
  }
}

function renderPresence(p) {
  const el = document.querySelector('.card.speaker .card-head .mono:last-child');
  if (!el) return;
  const online = !!p?.online;
  el.textContent = online ? '● ONLINE' : '● OFFLINE';
  el.style.color = online ? 'var(--ok)' : 'var(--ink-3)';
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
    renderHabits(data.habits);
    renderCalendar(data.calendar);
    renderRoutine(data.routine ?? null);
    renderMusic(data.music);
    renderProject(data.project);
    renderPresence(data.presence);
  } catch (err) {
    console.warn('dashboard refresh failed:', err);
  }
}

renderStaticBoot();
renderRoutine();
loadQuotes();
wireMusicControls();
pingPresence().then(refresh);
connectEvents();
setInterval(refresh, FALLBACK_POLL_MS); // 2-min safety net for stalled SSE
setInterval(pingPresence, 30_000);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    pingPresence();
    refresh();
  }
});
