/* Rehearsal Room — the online half, in the browser.

   Loaded by both editions (the laptop page and the on-phone page), which
   have drifted apart in every other respect: different data shapes,
   different storage, different function names. So this file knows nothing
   about either. It is handed a question id, a take name and a DOM node, and
   it does the rest. Each page glues it in with a dozen lines.

   Everything here needs the internet. Nothing else in the app does, so
   every entry point checks `enabled` first and simply does not appear when
   there is no key — the offline app must look exactly as it did before.
*/

(function () {
  'use strict';

  const AI = {
    info: null,
    enabled: false,
    ready: null,
    turns: {},          // question id -> [{q, a}], the last few, for context
  };

  /* ------------------------------------------------------------- status */

  AI.ready = (async () => {
    try {
      const res = await fetch('/api/ai/status', { cache: 'no-store' });
      AI.info = await res.json();
    } catch (err) {
      AI.info = { enabled: false };   // no server, or no network: same thing
    }
    AI.enabled = !!(AI.info && AI.info.enabled);
    return AI.enabled;
  })();

  async function post(action, payload) {
    const res = await fetch('/api/ai/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    let body = {};
    try { body = await res.json(); } catch (err) { /* fall through */ }
    if (body && body.error) {
      const problem = new Error(body.error);
      problem.kind = body.kind || 'error';
      throw problem;
    }
    if (!res.ok) throw new Error('The app could not reach its own server.');
    return body;
  }

  /* ------------------------------------------------- the audio sibling

     The video of a take is far too big to transcribe (25 MB cap, and a
     three-minute phone video is already past it). So a second recorder
     reads the same live microphone track and writes a few hundred KB of
     Opus beside it. Verified: Chromium allows two recorders on one track.
  */

  function pickAudioMime() {
    return ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4',
            'audio/ogg;codecs=opus']
      .find(t => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || '';
  }

  AI.recordAudio = function (stream) {
    const mime = pickAudioMime();
    const tracks = stream && stream.getAudioTracks ? stream.getAudioTracks() : [];
    if (!mime || !tracks.length) return null;

    let recorder;
    try {
      recorder = new MediaRecorder(new MediaStream(tracks),
                                   { mimeType: mime, audioBitsPerSecond: 64000 });
    } catch (err) {
      return null;            // the take still records; only grading is lost
    }

    const chunks = [];
    recorder.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
    const finished = new Promise(resolve => { recorder.onstop = resolve; });
    try {
      recorder.start(1000);
    } catch (err) {
      return null;
    }

    return {
      // Stop, and wait for the last chunk. Without the wait the final
      // second of every answer is silently lost.
      async stop() {
        if (recorder.state !== 'inactive') recorder.stop();
        await Promise.race([finished, new Promise(r => setTimeout(r, 4000))]);
        const blob = new Blob(chunks, { type: mime });
        return blob.size > 500 ? { blob, ext: 'webm' } : null;
      },
    };
  };

  /* A fallback for the day the dual recorder yields nothing: pull the audio
     out of the recorded video and write a small 16 kHz mono WAV. Pure
     browser, no ffmpeg to install on a phone. If this fails too, the server
     falls back to transcribing the video itself when it is small enough. */

  AI.wavFromVideo = async function (videoBlob) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx || !window.OfflineAudioContext) return null;
      const decoded = await new Ctx().decodeAudioData(await videoBlob.arrayBuffer());
      const rate = 16000;
      const frames = Math.floor(decoded.duration * rate);
      if (!frames) return null;
      const off = new OfflineAudioContext(1, frames, rate);
      const src = off.createBufferSource();
      src.buffer = decoded;
      src.connect(off.destination);
      src.start();
      const mono = (await off.startRendering()).getChannelData(0);

      const view = new DataView(new ArrayBuffer(44 + mono.length * 2));
      const ascii = (at, text) => { for (let i = 0; i < text.length; i++) view.setUint8(at + i, text.charCodeAt(i)); };
      ascii(0, 'RIFF'); view.setUint32(4, 36 + mono.length * 2, true);
      ascii(8, 'WAVEfmt '); view.setUint32(16, 16, true);
      view.setUint16(20, 1, true); view.setUint16(22, 1, true);
      view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
      view.setUint16(32, 2, true); view.setUint16(34, 16, true);
      ascii(36, 'data'); view.setUint32(40, mono.length * 2, true);
      for (let i = 0; i < mono.length; i++) {
        const s = Math.max(-1, Math.min(1, mono[i]));
        view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
      return { blob: new Blob([view], { type: 'audio/wav' }), ext: 'wav' };
    } catch (err) {
      return null;
    }
  };

  /* Upload the sibling under the SAME timestamp as its video — that pairing
     is the only thing connecting the two files on disk. */
  AI.uploadAudio = async function (questionId, stamp, audio) {
    if (!audio || !audio.blob) return false;
    try {
      const res = await fetch('/api/recordings/' + questionId, {
        method: 'POST',
        headers: {
          'Content-Type': audio.ext === 'wav' ? 'audio/wav' : 'audio/webm',
          'X-Recorded-At': String(stamp),
          'X-Audio': audio.ext,
        },
        body: audio.blob,
      });
      return res.ok;
    } catch (err) {
      return false;
    }
  };

  /* ---------------------------------------------------------- rendering */

  const VERDICT_TONE = {
    'WOULD PASS': 'pass',
    'BORDERLINE': 'edge',
    'WOULD NOT PASS': 'fail',
    'NO ANSWER': 'none',
  };

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function renderGrade(host, grade, transcript) {
    host.innerHTML = '';
    const tone = VERDICT_TONE[grade.verdict] || 'edge';
    const panel = el('div', 'ai-grade tone-' + tone);

    panel.appendChild(el('div', 'ai-verdict', grade.verdict || ''));
    if (grade.verdict_note) panel.appendChild(el('p', 'ai-note', grade.verdict_note));

    if (grade.missed && grade.missed.length) {
      panel.appendChild(el('h4', null, 'Missed from the answer'));
      const list = el('ul', 'ai-missed');
      grade.missed.forEach(m => list.appendChild(el('li', null, m)));
      panel.appendChild(list);
    }

    if (grade.wrong && grade.wrong.length) {
      panel.appendChild(el('h4', null, 'Said wrong'));
      const list = el('ul', 'ai-wrong');
      grade.wrong.forEach(w => {
        const li = el('li');
        li.appendChild(el('span', 'ai-said', '“' + w.said + '”'));
        if (w.why) li.appendChild(el('span', 'ai-why', ' — ' + w.why));
        list.appendChild(li);
      });
      panel.appendChild(list);
    }

    const s = grade.scores || {};
    if (s.correctness || s.depth || s.articulation) {
      const row = el('div', 'ai-scores');
      [['correctness', s.correctness], ['depth', s.depth],
       ['articulation', s.articulation]].forEach(([name, value]) => {
        const chip = el('span', 'ai-score' + (value <= 2 ? ' low' : ''));
        chip.appendChild(el('b', null, (value == null ? '-' : value) + '/5'));
        chip.appendChild(el('i', null, name));
        row.appendChild(chip);
      });
      panel.appendChild(row);
    }

    if (grade.delivery) {
      const line = el('p', 'ai-delivery');
      line.appendChild(el('b', null, 'Delivery: '));
      line.appendChild(document.createTextNode(grade.delivery));
      panel.appendChild(line);
    }

    if (transcript) {
      const details = el('details', 'ai-transcript');
      details.appendChild(el('summary', null, 'What it heard you say'));
      details.appendChild(el('p', null, transcript));
      panel.appendChild(details);
    }

    host.appendChild(panel);
  }

  /* ------------------------------------------------- the grade, per take */

  /** Mount a "Grade this take" control for one recording.
   *  opts: { base, questionId, transcript, grade, hasAudio }
   */
  AI.mountTake = function (host, opts) {
    if (!AI.enabled || !host) return;
    const wrap = el('div', 'ai-take');
    const button = el('button', 'ai-button');
    const message = el('p', 'ai-message');
    const panel = el('div');
    wrap.appendChild(button);
    wrap.appendChild(message);
    wrap.appendChild(panel);
    host.appendChild(wrap);

    let transcript = opts.transcript || null;
    let grade = opts.grade || null;

    const label = () => {
      button.textContent = grade ? 'Grade again' : 'Grade this take';
      button.disabled = false;
    };
    if (grade) renderGrade(panel, grade, transcript);
    label();

    button.addEventListener('click', async () => {
      const force = !!grade;
      button.disabled = true;
      message.className = 'ai-message';
      try {
        if (!transcript || force) {
          button.textContent = 'Transcribing…';
          transcript = (await post('transcribe', { base: opts.base, force })).text;
        }
        button.textContent = 'Grading…';
        grade = await post('grade', {
          base: opts.base, question: opts.questionId, transcript, force,
        });
        renderGrade(panel, grade, transcript);
        message.textContent = '';
        if (opts.onGraded) opts.onGraded(grade, transcript);
      } catch (err) {
        message.className = 'ai-message problem';
        message.textContent = err.message;
      }
      label();
    });
  };

  /* -------------------------------------------- the cross-question box */

  /** Mount the concept explainer under the answer on screen.
   *  opts: { questionId }
   */
  AI.mountExplain = function (host, opts) {
    if (!AI.enabled || !host) return;
    const wrap = el('div', 'ai-ask');
    wrap.appendChild(el('h4', 'ai-ask-title',
                        "Don't follow something above?"));
    const row = el('div', 'ai-ask-row');
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Name it — pseudo-labelling, the cluster assumption…';
    input.className = 'ai-ask-input';
    const send = el('button', 'ai-ask-send', 'Explain');
    row.appendChild(input);
    row.appendChild(send);
    const thread = el('div', 'ai-thread');
    wrap.appendChild(row);
    wrap.appendChild(thread);
    host.appendChild(wrap);

    const ask = async () => {
      const question = input.value.trim();
      if (!question) return;
      input.value = '';
      send.disabled = true;
      const block = el('div', 'ai-turn');
      block.appendChild(el('p', 'ai-asked', question));
      const answer = el('p', 'ai-answer', 'working it out…');
      block.appendChild(answer);
      thread.insertBefore(block, thread.firstChild);
      try {
        const reply = await post('explain', {
          question: opts.questionId,
          ask: question,
          turns: AI.turns[opts.questionId] || [],
        });
        answer.textContent = reply.text;
        const turns = AI.turns[opts.questionId] || (AI.turns[opts.questionId] = []);
        turns.push({ q: question, a: reply.text });
        if (turns.length > 3) turns.shift();
      } catch (err) {
        answer.className = 'ai-answer problem';
        answer.textContent = err.message;
      }
      send.disabled = false;
      input.focus();
    };

    send.addEventListener('click', ask);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });
  };

  /* ------------------------------------------------------------- styles

     Carried here rather than in either stylesheet, so one file is the whole
     feature and neither edition's CSS has to be edited twice.
  */

  const CSS = `
.ai-take { margin-top: 10px; }
/* The takes list is a flex <ul>; the grade panel needs a plain block row of
   its own, or it is squeezed in beside the play and delete buttons. */
li.ai-take-row {
  display: block; list-style: none; padding: 0; margin: 0 0 4px;
  border: 0; background: none;
}
.ai-button, .ai-ask-send {
  font: inherit; font-size: 13px; padding: 7px 13px; cursor: pointer;
  border-radius: 7px; border: 1px solid var(--line, #cfd6d6);
  background: var(--card, #fff); color: var(--ink, #1b2222);
}
.ai-button:hover:not(:disabled), .ai-ask-send:hover:not(:disabled) {
  border-color: var(--accent, #0f5f69); color: var(--accent, #0f5f69);
}
.ai-button:disabled, .ai-ask-send:disabled { opacity: .6; cursor: default; }
.ai-message { font-size: 12.5px; margin: 6px 0 0; color: var(--soft, #667); }
.ai-message.problem, .ai-answer.problem { color: #b4442e; }

.ai-grade {
  margin-top: 10px; padding: 11px 13px; border-radius: 9px;
  border: 1px solid var(--line, #cfd6d6);
  border-left: 4px solid var(--soft, #889);
  background: var(--card, #fff); font-size: 13.5px; line-height: 1.5;
}
.ai-grade.tone-pass { border-left-color: #2f7d58; }
.ai-grade.tone-edge { border-left-color: #b8860b; }
.ai-grade.tone-fail { border-left-color: #b4442e; }
.ai-grade.tone-none { border-left-color: var(--soft, #889); }
.ai-verdict {
  font-weight: 700; font-size: 12px; letter-spacing: .09em;
  text-transform: uppercase;
}
.tone-pass .ai-verdict { color: #2f7d58; }
.tone-edge .ai-verdict { color: #946a00; }
.tone-fail .ai-verdict { color: #b4442e; }
.ai-grade h4 {
  margin: 11px 0 4px; font-size: 11.5px; letter-spacing: .07em;
  text-transform: uppercase; color: var(--soft, #667); font-weight: 600;
}
.ai-grade p { margin: 5px 0; }
.ai-grade ul { margin: 0; padding: 0; list-style: none; }
.ai-grade li { position: relative; padding-left: 17px; margin: 4px 0; }
.ai-missed li::before {
  content: '✗'; position: absolute; left: 0; color: #b4442e; font-weight: 700;
}
.ai-wrong li::before {
  content: '•'; position: absolute; left: 3px; color: #b4442e; font-weight: 700;
}
.ai-said { font-style: italic; }
.ai-why { color: var(--soft, #667); }
.ai-scores { display: flex; flex-wrap: wrap; gap: 7px; margin: 11px 0 3px; }
.ai-score {
  display: inline-flex; align-items: baseline; gap: 4px; padding: 3px 8px;
  border-radius: 20px; background: var(--chip, rgba(0,0,0,.05)); font-size: 12px;
}
.ai-score b { font-weight: 700; }
.ai-score.low b { color: #b4442e; }
.ai-score i { font-style: normal; color: var(--soft, #667); }
.ai-delivery { margin-top: 9px !important; }
.ai-transcript { margin-top: 9px; font-size: 12.5px; }
.ai-transcript summary { cursor: pointer; color: var(--soft, #667); }
.ai-transcript p { color: var(--soft, #667); margin-top: 5px; }

.ai-ask {
  margin: 26px 0 8px; padding-top: 18px;
  border-top: 1px solid var(--line, #cfd6d6);
}
.ai-ask-title {
  margin: 0 0 8px; font-size: 12px; letter-spacing: .07em;
  text-transform: uppercase; color: var(--soft, #667); font-weight: 600;
}
.ai-asked { font-weight: 600; }
.ai-ask-row { display: flex; gap: 6px; }
.ai-ask-input {
  flex: 1; min-width: 0; font: inherit; font-size: 13px; padding: 7px 10px;
  border-radius: 7px; border: 1px solid var(--line, #cfd6d6);
  background: var(--card, #fff); color: var(--ink, #1b2222);
}
.ai-ask-input:focus { outline: 2px solid var(--accent, #0f5f69); outline-offset: -1px; }
.ai-turn {
  margin-top: 10px; padding-left: 10px;
  border-left: 2px solid var(--line, #cfd6d6);
}
.ai-asked { margin: 0; font-size: 12.5px; color: var(--soft, #667); }
.ai-answer { margin: 3px 0 0; font-size: 13.5px; line-height: 1.55; white-space: pre-line; }
@media (prefers-color-scheme: dark) {
  .ai-score { background: var(--chip, rgba(255,255,255,.08)); }
}
`;

  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  window.RehearsalAI = AI;
})();
