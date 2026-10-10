/* Rehearsal Room — study app logic.

   Data comes from data/index.json (light: structure + question text) and
   data/<guide>.json (heavy: answer HTML, fetched the first time a guide is
   opened). Marks and last position live in state.json on disk; notes and
   recordings are ordinary files. Nothing is kept only in the browser.
*/

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const App = {
  index: null,
  content: {},        // guide key -> { id: {answer_html, figures} }
  order: [],          // every id, in reading order
  position: new Map(), // id -> index in order
  state: { marks: {}, last: null },
  current: null,
  revealed: false,
  alwaysReveal: false,
  recordings: [],
};

/* ------------------------------------------------------------ helpers */

function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 2200);
}

function debounce(fn, wait) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

function formatBytes(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return Math.round(n / 1024) + ' KB';
  return (n / 1024 / 1024).toFixed(1) + ' MB';
}

function meta(id) {
  return App.index.questions[id] || App.index.pages[id] || null;
}

function isPage(id) {
  return Boolean(App.index.pages[id]);
}

function marksFor(id) {
  return App.state.marks[id] || {};
}

/* -------------------------------------------------------------- state */

/* Saving is deliberately paranoid.

   Notes and marks are the only things in this app you cannot regenerate, so
   every pending write is flushed before anything that could lose it:
   changing question, hiding the tab, or closing the window. A plain debounce
   is not enough — it would silently drop the previous question's note when
   you move on and start typing within the debounce window.
*/

const Pending = { note: null, noteTimer: null, state: false, stateTimer: null, loadToken: 0 };

function setNoteStatus(text, problem = false) {
  const el = $('#note-status');
  if (!el) return;
  el.textContent = text;
  el.style.color = problem ? 'var(--rec)' : '';
}

function flushState(keepalive = false) {
  clearTimeout(Pending.stateTimer);
  if (!Pending.state) return Promise.resolve();
  Pending.state = false;
  return fetch('/api/state', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(App.state),
    keepalive,
  }).catch(() => toast('Could not save your progress'));
}

function saveState() {
  Pending.state = true;
  clearTimeout(Pending.stateTimer);
  Pending.stateTimer = setTimeout(flushState, 400);
}

function flushNote(keepalive = false) {
  clearTimeout(Pending.noteTimer);
  const job = Pending.note;
  if (!job) return Promise.resolve();
  Pending.note = null;
  return fetch(`/api/notes/${job.id}`, { method: 'PUT', body: job.text, keepalive })
    .then(() => { if (App.current === job.id) setNoteStatus('Saved'); })
    .catch(() => {
      if (App.current === job.id) {
        setNoteStatus('Not saved. Is the app window still open?', true);
      }
      // Put it back so the next flush retries rather than losing the text.
      Pending.note = job;
    });
}

function queueNote(id, text) {
  // Moving to another question must not cancel the previous note's save.
  if (Pending.note && Pending.note.id !== id) flushNote();
  Pending.note = { id, text };
  clearTimeout(Pending.noteTimer);
  Pending.noteTimer = setTimeout(flushNote, 600);
}

function flushEverything(keepalive = false) {
  return Promise.all([flushNote(keepalive), flushState(keepalive)]);
}

/* --------------------------------------------------- study navigation */

/* What "Next" means.

   Right now Next walks straight through in document order, which is the
   honest default: these guides are written to be read in sequence.

   Other policies are reasonable and change how the app feels to study
   with — skipping what you have marked "Got it", surfacing "Shaky" ones
   first, or shuffling within a section so you cannot coast on
   remembering the order. See chooseNext() below.
*/
function chooseNext(currentIndex, direction) {
  return currentIndex + direction;
}

function neighbour(direction) {
  if (!App.current) return null;
  const here = App.position.get(App.current);
  if (here === undefined) return null;
  const next = chooseNext(here, direction);
  if (next < 0 || next >= App.order.length) return null;
  return App.order[next];
}

/* ----------------------------------------------------------- contents */

function buildOrder() {
  App.order = [];
  App.sectionOf = new Map();
  App.index.guides.forEach(guide => {
    guide.sections.forEach(section => {
      section.ids.forEach(id => {
        App.order.push(id);
        App.sectionOf.set(id, section);
      });
    });
  });
  App.position = new Map(App.order.map((id, i) => [id, i]));
}

function sectionProgress(section) {
  let known = 0, shaky = 0;
  section.ids.forEach(id => {
    const m = marksFor(id);
    if (m.known) known++;
    if (m.unsure) shaky++;
  });
  return { known, shaky, total: section.ids.length };
}

function renderContents() {
  const host = $('#contents-scroll');
  host.innerHTML = '';
  const openGuide = App.current ? (meta(App.current) || {}).guide : null;

  App.index.guides.forEach(guide => {
    const head = document.createElement('button');
    head.className = 'guide-head';
    head.setAttribute('aria-expanded', String(guide.key === openGuide));
    head.innerHTML = `${guide.title}<span class="guide-count">${guide.count}</span>`;
    head.addEventListener('click', () => {
      const open = head.getAttribute('aria-expanded') === 'true';
      head.setAttribute('aria-expanded', String(!open));
      body.hidden = open;
    });
    host.appendChild(head);

    const body = document.createElement('div');
    body.hidden = guide.key !== openGuide;
    host.appendChild(body);

    let lastPart = null;
    guide.sections.forEach(section => {
      if (!section.ids.length) return;
      if (section.part && section.part !== lastPart) {
        const label = document.createElement('div');
        label.className = 'part-label';
        label.textContent = section.part;
        body.appendChild(label);
        lastPart = section.part;
      }

      const progress = sectionProgress(section);
      const link = document.createElement('button');
      link.className = 'section-link';
      if (section.kind === 'page') link.classList.add('is-page');
      if (progress.known === progress.total) link.classList.add('complete');
      if (App.current && section.ids.includes(App.current)) {
        link.classList.add('current');
      }
      link.innerHTML =
        `<span class="sec-name">${section.section_title}</span>` +
        (section.kind === 'page'
          ? ''
          : `<span class="sec-done">${progress.known}/${progress.total}</span>`);
      link.addEventListener('click', () => show(section.ids[0]));
      body.appendChild(link);
    });
  });

  const totals = App.index.totals;
  const known = Object.values(App.state.marks).filter(m => m.known).length;
  $('#contents-foot').textContent =
    `${known} of ${totals.questions} marked`;
}

/* -------------------------------------------------------------- views */

async function loadGuide(key) {
  if (App.content[key]) return App.content[key];
  const res = await fetch(`data/${key}.json`);
  App.content[key] = await res.json();
  return App.content[key];
}

function enhance(root) {
  // Wide comparison tables are common here; let them scroll on their own
  // rather than forcing the whole page sideways.
  $$('table', root).forEach(table => {
    if (table.parentElement.classList.contains('table-wrap')) return;
    const wrap = document.createElement('div');
    wrap.className = 'table-wrap';
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
  });
}

async function show(id, options = {}) {
  const info = meta(id);
  if (!info) return;

  flushNote();   // never leave a half-typed note behind
  App.current = id;
  App.revealed = App.alwaysReveal || isPage(id);
  App.state.last = id;
  saveState();

  const store = await loadGuide(info.guide);
  const body = store[id];
  const sheet = $('#sheet');

  if (isPage(id)) {
    sheet.innerHTML = `
      <div class="crumb">
        <span class="crumb-section">${info.section_title}</span>
        <span class="crumb-pos">reference</span>
      </div>
      <div class="answer is-page">${body.answer_html}</div>`;
  } else {
    // Position within the section, which is what you actually feel while
    // studying. The global count lives in the sidebar.
    const section = App.sectionOf.get(id);
    const here = section.ids.indexOf(id) + 1;
    sheet.innerHTML = `
      <div class="crumb">
        <span class="qnum">${info.qnum}</span>
        <span class="crumb-section">${info.section_title}</span>
        <span class="crumb-pos">${here} of ${section.ids.length} in this section</span>
      </div>
      <h1 class="question">${info.question_html}</h1>
      <p class="q-meta">${info.words} words${info.is_long
        ? ' <span class="long-flag">· a long one, read it rather than drill it</span>'
        : ''}${info.has_figure ? ' · has a diagram' : ''}</p>
      <div class="reveal-bar" id="reveal-bar">
        <button class="reveal-button" id="reveal-button">
          <span>Show the answer</span>
        </button>
        <span class="reveal-hint">or press Space</span>
        <label class="reveal-hint" style="margin-left:auto">
          <input type="checkbox" id="always-reveal"> Always show
        </label>
      </div>
      <div class="answer-wrap" id="answer-wrap">
        <div><div class="answer">${body.answer_html}</div></div>
      </div>`;

    const checkbox = $('#always-reveal');
    checkbox.checked = App.alwaysReveal;
    checkbox.addEventListener('change', () => {
      App.alwaysReveal = checkbox.checked;
      localStorage.setItem('alwaysReveal', String(App.alwaysReveal));
      setRevealed(App.alwaysReveal);
    });
    $('#reveal-button').addEventListener('click', () => setRevealed(!App.revealed));
    setRevealed(App.revealed);
  }

  mountExplainer();

  enhance(sheet);
  renderPager();
  renderMargin();
  renderContents();

  if (!options.keepScroll) $('#reading').scrollTop = 0;
}

function setRevealed(on) {
  App.revealed = on;
  const wrap = $('#answer-wrap');
  if (!wrap) return;
  wrap.classList.toggle('open', on);
  const label = $('#reveal-button span');
  if (label) label.textContent = on ? 'Hide the answer' : 'Show the answer';
}

function renderPager() {
  $('#pager')?.remove();
  const prevId = neighbour(-1);
  const nextId = neighbour(1);

  const pager = document.createElement('nav');
  pager.className = 'pager';
  pager.id = 'pager';

  const button = (id, role, cls) => {
    const b = document.createElement('button');
    b.className = `pager-button ${cls}`;
    if (!id) {
      b.disabled = true;
      b.innerHTML = `<span class="pager-role">${role}</span><span class="pager-q">—</span>`;
    } else {
      const info = meta(id);
      const text = isPage(id) ? info.section_title : info.question_text;
      b.innerHTML = `<span class="pager-role">${role}</span>` +
                    `<span class="pager-q">${text}</span>`;
      b.addEventListener('click', () => show(id));
    }
    return b;
  };

  pager.appendChild(button(prevId, 'Previous', 'prev'));
  pager.appendChild(button(nextId, 'Next', 'next'));
  $('#reading').appendChild(pager);
}

/* ------------------------------------------------------------- margin */

function renderMargin() {
  const host = $('#margin-inner');
  host.innerHTML = '';
  if (!App.current || isPage(App.current)) {
    host.innerHTML = '<p class="camera-note">Notes and recording attach to a question. Open one to start.</p>';
    return;
  }

  host.appendChild($('#tpl-margin').content.cloneNode(true));

  const marks = marksFor(App.current);
  $$('.mark', host).forEach(button => {
    const kind = button.dataset.mark;
    button.classList.toggle('on', Boolean(marks[kind]));
    button.addEventListener('click', () => toggleMark(kind));
  });

  const id = App.current;
  const input = $('#note-input');
  input.value = '';
  setNoteStatus('');

  // If the note arrives after you have started typing, the typing wins.
  // Otherwise a slow read could wipe words you had already written.
  const token = ++Pending.loadToken;
  let touched = false;
  fetch(`/api/notes/${id}`)
    .then(r => r.text())
    .then(text => {
      if (token !== Pending.loadToken || touched) return;
      input.value = text;
    })
    .catch(() => setNoteStatus('Could not read your saved note', true));

  input.addEventListener('input', () => {
    touched = true;
    setNoteStatus('Saving…');
    queueNote(id, input.value);
  });
  input.addEventListener('blur', () => flushNote());

  setupCamera();
  renderTakes();
}

function toggleMark(kind) {
  const id = App.current;
  const marks = { ...marksFor(id) };
  marks[kind] = !marks[kind];
  // "Got it" and "Shaky" are two answers to the same question.
  if (kind === 'known' && marks.known) marks.unsure = false;
  if (kind === 'unsure' && marks.unsure) marks.known = false;
  App.state.marks[id] = marks;
  saveState();
  renderMargin();
  renderContents();
}

/* ------------------------------------------------------------- camera */

const Camera = { stream: null, recorder: null, chunks: [], started: 0,
                 timer: null, audio: null };

function pickMimeType() {
  const options = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm'];
  return options.find(t => MediaRecorder.isTypeSupported(t)) || '';
}

function releaseCamera() {
  if (Camera.stream) {
    Camera.stream.getTracks().forEach(t => t.stop());
    Camera.stream = null;
  }
  clearInterval(Camera.timer);
  const stage = $('#camera-stage');
  if (stage) stage.classList.remove('live');
}

function setupCamera() {
  const button = $('#record-button');
  if (!button) return;
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    button.disabled = true;
    $('#camera-note').textContent = 'This browser cannot record video.';
    return;
  }
  button.addEventListener('click', () => {
    if (Camera.recorder && Camera.recorder.state === 'recording') stopRecording();
    else startRecording();
  });
}

async function startRecording() {
  const note = $('#camera-note');
  const questionId = App.current;
  note.classList.remove('problem');
  note.textContent = 'Asking for the camera…';

  try {
    Camera.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: true,
    });
  } catch (err) {
    note.classList.add('problem');
    note.textContent = err.name === 'NotAllowedError'
      ? 'Camera blocked. Allow it in the address bar, then try again.'
      : 'No camera available: ' + err.name;
    return;
  }

  const stage = $('#camera-stage');
  const preview = $('#preview');
  preview.controls = false;
  preview.muted = true;
  preview.srcObject = Camera.stream;
  preview.play();
  stage.classList.add('live');
  stage.classList.remove('playing');

  Camera.chunks = [];
  // A second recorder on the same live microphone track writes a small
  // Opus file beside the video. The video is far too big to transcribe.
  Camera.audio = window.RehearsalAI ? RehearsalAI.recordAudio(Camera.stream) : null;
  Camera.recorder = new MediaRecorder(Camera.stream, { mimeType: pickMimeType() });
  Camera.recorder.ondataavailable = e => { if (e.data.size) Camera.chunks.push(e.data); };
  Camera.recorder.onstop = () => uploadTake(questionId);
  Camera.recorder.start();

  Camera.started = Date.now();
  $('#rec-dot').hidden = false;
  $('#rec-time').hidden = false;
  Camera.timer = setInterval(() => {
    const s = Math.floor((Date.now() - Camera.started) / 1000);
    $('#rec-time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }, 250);

  $('#record-button').classList.add('recording');
  $('#record-label').textContent = 'Stop and save';
  note.textContent = 'Recording. Answer it the way you would out loud.';
}

function stopRecording() {
  if (Camera.recorder && Camera.recorder.state === 'recording') Camera.recorder.stop();
  $('#record-button').classList.remove('recording');
  $('#record-label').textContent = 'Start recording';
  $('#rec-dot').hidden = true;
  $('#rec-time').hidden = true;
  clearInterval(Camera.timer);
}

async function uploadTake(questionId) {
  const blob = new Blob(Camera.chunks, { type: 'video/webm' });
  Camera.chunks = [];
  // One timestamp for the video and its audio: that pairing is the only
  // thing joining the two files on disk. And the audio recorder must be
  // drained before the camera is released, or the last words are lost.
  const stamp = Date.now();
  let audio = Camera.audio ? await Camera.audio.stop() : null;
  Camera.audio = null;
  releaseCamera();

  const note = $('#camera-note');
  const say = text => { if (App.current === questionId && note) note.textContent = text; };
  say(`Saving ${formatBytes(blob.size)}…`);

  // Two attempts, then hand the file to the browser rather than lose a take
  // you have already performed.
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const res = await fetch(`/api/recordings/${questionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'video/webm', 'X-Recorded-At': String(stamp) },
        body: blob,
      });
      if (!res.ok) throw new Error('server said ' + res.status);
      const saved = await res.json();
      if (window.RehearsalAI && RehearsalAI.enabled) {
        // No sibling? Pull the audio out of the video instead. If that
        // fails too the server transcribes the video, when it is small
        // enough. Grading is never the reason a take is lost.
        if (!audio) audio = await RehearsalAI.wavFromVideo(blob);
        await RehearsalAI.uploadAudio(questionId, stamp, audio);
      }
      await refreshRecordings();
      if (App.current === questionId) {
        note.classList.remove('problem');
        say(`Saved ${formatBytes(saved.bytes)} into the recordings folder.`);
        renderTakes();
      }
      return;
    } catch (err) {
      if (attempt === 2) offerManualSave(blob, questionId, err);
    }
  }
}

function offerManualSave(blob, questionId, err) {
  const note = $('#camera-note');
  if (!note || App.current !== questionId) return;
  note.classList.add('problem');
  note.textContent = `Could not save it to disk (${err.message}). Download it here so the take is not lost: `;
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${questionId}--${Date.now()}.webm`;
  link.textContent = 'Save the video';
  link.style.color = 'var(--accent)';
  note.appendChild(link);
}

async function refreshRecordings() {
  const res = await fetch('/api/recordings');
  App.recordings = (await res.json()).recordings;
}

function renderTakes() {
  const host = $('#takes');
  if (!host) return;
  const mine = App.recordings.filter(r => r.question === App.current);
  host.innerHTML = '';

  mine.forEach(rec => {
    const when = new Date(rec.modified * 1000);
    const li = document.createElement('li');
    li.className = 'take';
    li.innerHTML =
      `<span class="take-name">${when.toLocaleDateString()} ${when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>` +
      `<span class="take-size">${formatBytes(rec.bytes)}</span>`;

    const play = document.createElement('button');
    play.title = 'Watch this take';
    play.innerHTML = '<svg viewBox="0 0 20 20"><path d="M6 4l10 6-10 6z"/></svg>';
    play.addEventListener('click', () => playTake(rec));
    li.appendChild(play);

    const del = document.createElement('button');
    del.className = 'delete';
    del.title = 'Delete this take';
    del.innerHTML = '<svg viewBox="0 0 20 20"><path d="M4 6h12M8 6V4h4v2M6.5 6l.7 10h5.6l.7-10"/></svg>';
    let armed = false;
    del.addEventListener('click', () => {
      if (!armed) {
        armed = true;
        del.innerHTML = '<span style="font-size:11px">Sure?</span>';
        setTimeout(() => {
          armed = false;
          del.innerHTML = '<svg viewBox="0 0 20 20"><path d="M4 6h12M8 6V4h4v2M6.5 6l.7 10h5.6l.7-10"/></svg>';
        }, 3000);
        return;
      }
      deleteTake(rec.name);
    });
    li.appendChild(del);

    host.appendChild(li);

    // The grade for this take gets a plain row of its own under it.
    if (window.RehearsalAI && RehearsalAI.enabled) {
      const row = document.createElement('li');
      row.className = 'ai-take-row';
      host.appendChild(row);
      RehearsalAI.mountTake(row, {
        base: rec.base,
        questionId: rec.question,
        transcript: rec.transcript,
        grade: rec.grade,
        onGraded: (grade, transcript) => {
          rec.grade = grade;
          rec.transcript = transcript;
        },
      });
    }
  });
}

/* The concept explainer sits in the reading column, after the answer and
   INSIDE the collapsing wrapper -- so it appears when you reveal the
   answer and is hidden while you are still trying to recall it. Asking
   about a concept before you have seen the answer would spoil the drill.
   It belongs to the question on screen, so it is rebuilt, not reused. */
function mountExplainer() {
  if (!window.RehearsalAI || !RehearsalAI.enabled || !App.current) return;
  const wrap = $('#answer-wrap');
  // Reference sheets have no reveal wrapper; their answer is always open.
  const host = wrap ? wrap.firstElementChild : $('.answer.is-page');
  if (!host) return;
  const old = host.querySelector('.ai-ask');
  if (old) old.remove();
  RehearsalAI.mountExplain(host, { questionId: App.current });
}

function playTake(rec) {
  const stage = $('#camera-stage');
  const preview = $('#preview');
  releaseCamera();
  preview.srcObject = null;
  preview.src = `recordings/${rec.name}`;
  preview.muted = false;
  preview.controls = true;
  stage.classList.add('playing');
  preview.play();
}

async function deleteTake(name) {
  await fetch(`/api/recordings/${name}`, { method: 'DELETE' });
  await refreshRecordings();
  renderTakes();
  toast('Take deleted');
}

/* --------------------------------------------------------------- home */

function showHome() {
  App.current = null;
  releaseCamera();
  const totals = App.index.totals;
  const marked = Object.values(App.state.marks).filter(m => m.known).length;
  const last = App.state.last && meta(App.state.last) ? App.state.last : null;

  const sheet = $('#sheet');
  sheet.innerHTML = `
    <h1 class="home-lede">Somewhere quiet to practise saying it out loud.</h1>
    <p class="home-sub">${totals.questions.toLocaleString()} questions and
      ${totals.pages} reference sheets, taken straight from your guides.
      Mark what you know, write what you keep forgetting, and record yourself
      answering until it sounds like you.</p>
    <div id="home-resume"></div>
    <div class="guide-list" id="home-guides"></div>`;

  if (last) {
    const info = meta(last);
    const button = document.createElement('button');
    button.className = 'resume';
    button.innerHTML =
      `<div class="resume-role">Where you left off</div>` +
      `<div class="resume-q">${isPage(last) ? info.section_title : info.question_text}</div>`;
    button.addEventListener('click', () => show(last));
    $('#home-resume').appendChild(button);
  }

  const list = $('#home-guides');
  App.index.guides.forEach(guide => {
    const row = document.createElement('button');
    row.className = 'guide-row';

    const strip = guide.sections
      .filter(s => s.ids.length && s.kind !== 'page')
      .map(section => {
        const p = sectionProgress(section);
        const cls = p.known === p.total ? 'done' : (p.shaky ? 'shaky' : '');
        return `<span class="${cls}" title="${section.section_title}: ${p.known}/${p.total}"></span>`;
      }).join('');

    const knownHere = guide.sections.reduce(
      (sum, s) => sum + sectionProgress(s).known, 0);

    row.innerHTML =
      `<div class="guide-row-title">${guide.title}</div>` +
      `<div class="guide-row-blurb">${guide.blurb}</div>` +
      `<div class="progress-strip">${strip}</div>` +
      `<div class="guide-row-stats">${guide.count} questions · ` +
      `${knownHere} marked as yours</div>`;
    row.addEventListener('click', () => {
      const first = guide.sections.find(s => s.ids.length);
      if (first) show(first.ids[0]);
    });
    list.appendChild(row);
  });

  $('#pager')?.remove();
  renderMargin();
  renderContents();
  $('#reading').scrollTop = 0;
}

/* --------------------------------------------------------- recordings */

async function showRecordings() {
  await refreshRecordings();
  App.current = null;
  releaseCamera();

  const total = App.recordings.reduce((sum, r) => sum + r.bytes, 0);
  const sheet = $('#sheet');
  sheet.innerHTML = `
    <h1 class="home-lede">Your recordings</h1>
    <p class="rec-total">${App.recordings.length} take${App.recordings.length === 1 ? '' : 's'},
      ${formatBytes(total)} on disk. They live in the recordings folder —
      delete them here or in File Explorer, whichever you prefer.</p>
    <div id="rec-list"></div>`;

  const list = $('#rec-list');
  if (!App.recordings.length) {
    list.innerHTML = '<p class="camera-note">Nothing recorded yet. Open a question and say your answer out loud.</p>';
  }

  App.recordings.slice().reverse().forEach(rec => {
    const info = meta(rec.question);
    const when = new Date(rec.modified * 1000);
    const item = document.createElement('div');
    item.className = 'rec-item';
    item.innerHTML =
      `<div class="rec-item-main">` +
      `<div class="rec-item-q">${info ? info.question_text : rec.question}</div>` +
      `<div class="rec-item-meta">${when.toLocaleString()} · ${formatBytes(rec.bytes)}</div>` +
      `</div>`;

    const open = document.createElement('button');
    open.className = 'icon-button';
    open.textContent = 'Open question';
    open.addEventListener('click', () => show(rec.question));
    item.appendChild(open);

    const del = document.createElement('button');
    del.className = 'icon-button';
    del.textContent = 'Delete';
    let armed = false;
    del.addEventListener('click', async () => {
      if (!armed) { armed = true; del.textContent = 'Sure?'; setTimeout(() => { armed = false; del.textContent = 'Delete'; }, 3000); return; }
      await deleteTake(rec.name);
      showRecordings();
    });
    item.appendChild(del);

    list.appendChild(item);
  });

  $('#pager')?.remove();
  renderMargin();
}

/* ------------------------------------------------------------- search */

function runSearch(term) {
  const panel = $('#search-results');
  const query = term.trim().toLowerCase();
  if (query.length < 2) { panel.hidden = true; return; }

  const hits = [];
  for (const id of App.order) {
    const info = meta(id);
    if (!info) continue;
    const haystack = (info.question_text || info.section_title || '').toLowerCase();
    const at = haystack.indexOf(query);
    if (at !== -1) hits.push({ id, info, at });
    if (hits.length >= 60) break;
  }

  panel.innerHTML = '';
  if (!hits.length) {
    const empty = document.createElement('p');
    empty.className = 'search-empty';
    empty.textContent = `Nothing matches “${term}”.`;
    panel.appendChild(empty);
    panel.hidden = false;
    return;
  }

  hits.sort((a, b) => a.at - b.at).slice(0, 40).forEach(hit => {
    const text = hit.info.question_text || hit.info.section_title;
    const at = text.toLowerCase().indexOf(query);
    const marked = at === -1 ? text
      : text.slice(0, at) + '<mark>' + text.slice(at, at + query.length) + '</mark>' + text.slice(at + query.length);
    const button = document.createElement('button');
    button.className = 'result';
    button.innerHTML =
      `<div class="result-q">${marked}</div>` +
      `<div class="result-where">${hit.info.qnum ? hit.info.qnum + ' · ' : ''}${hit.info.section_title}</div>`;
    button.addEventListener('click', () => {
      panel.hidden = true;
      $('#search').value = '';
      show(hit.id);
    });
    panel.appendChild(button);
  });
  panel.hidden = false;
}

/* ---------------------------------------------------------- behaviour */

function setTypeSize(px) {
  const size = Math.min(26, Math.max(15, px));
  document.documentElement.style.setProperty('--read-size', size + 'px');
  localStorage.setItem('readSize', String(size));
}

function currentTypeSize() {
  return parseInt(getComputedStyle(document.documentElement)
    .getPropertyValue('--read-size'), 10) || 19;
}

function setTheme(name) {
  document.documentElement.dataset.theme = name;
  localStorage.setItem('theme', name);
}

function wireUp() {
  $('#go-home').addEventListener('click', e => { e.preventDefault(); showHome(); });
  $('#open-recordings').addEventListener('click', showRecordings);
  $('#toggle-theme').addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  $('#toggle-contents').addEventListener('click', () => {
    $('.shell').classList.toggle('no-contents');
  });
  $('#type-up').addEventListener('click', () => setTypeSize(currentTypeSize() + 1));
  $('#type-down').addEventListener('click', () => setTypeSize(currentTypeSize() - 1));

  const search = $('#search');
  search.addEventListener('input', () => runSearch(search.value));
  search.addEventListener('keydown', e => {
    if (e.key === 'Escape') { search.value = ''; $('#search-results').hidden = true; search.blur(); }
  });
  document.addEventListener('click', e => {
    if (!e.target.closest('.search-field') && !e.target.closest('.search-results')) {
      $('#search-results').hidden = true;
    }
  });

  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA)$/.test(e.target.tagName);
    if (e.key === '/' && !typing) { e.preventDefault(); search.focus(); return; }
    if (typing) return;

    if (e.key === 'ArrowRight' || e.key === 'n') {
      const id = neighbour(1); if (id) show(id);
    } else if (e.key === 'ArrowLeft' || e.key === 'p') {
      const id = neighbour(-1); if (id) show(id);
    } else if (e.key === ' ' && App.current && !isPage(App.current)) {
      e.preventDefault(); setRevealed(!App.revealed);
    } else if (e.key === 'c') {
      $('.shell').classList.toggle('no-contents');
    } else if (App.current && !isPage(App.current)) {
      if (e.key === '1') toggleMark('known');
      if (e.key === '2') toggleMark('unsure');
      if (e.key === '3') toggleMark('starred');
    }
  });

  // Anything unsaved goes to disk before the page can go away. keepalive
  // lets the request outlive the page being closed.
  window.addEventListener('beforeunload', event => {
    flushEverything(true);
    releaseCamera();
    if (Camera.recorder && Camera.recorder.state === 'recording') {
      event.preventDefault();
      event.returnValue = '';   // "you are still recording" prompt
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushEverything(true);
  });
}

/* --------------------------------------------------------------- boot */

async function start() {
  setTheme(localStorage.getItem('theme') || 'light');
  setTypeSize(parseInt(localStorage.getItem('readSize'), 10) || 19);
  App.alwaysReveal = localStorage.getItem('alwaysReveal') === 'true';

  App.index = await (await fetch('data/index.json')).json();
  buildOrder();

  try { App.state = { marks: {}, last: null, ...(await (await fetch('/api/state')).json()) }; }
  catch { /* first run */ }
  if (!App.state.marks) App.state.marks = {};

  try { await refreshRecordings(); } catch { App.recordings = []; }

  // Whether grading exists at all. It needs a key and the internet;
  // without either, none of its controls are rendered.
  if (window.RehearsalAI) { try { await RehearsalAI.ready; } catch { /* off */ } }

  $('#search').placeholder =
    `Search ${App.index.totals.questions.toLocaleString()} questions`;

  wireUp();
  showHome();
}

start();
