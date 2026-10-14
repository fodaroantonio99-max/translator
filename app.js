'use strict';

// ---------------------------------------------------------------------------
// CONFIG
// Email opzionale per MyMemory (servizio di riserva): porta il limite gratuito
// da 5.000 a 50.000 caratteri al giorno. Non serve registrarsi.
const MYMEMORY_EMAIL = '';
const DEEPL_ENDPOINT = '/api/translate';
const API_TIMEOUT_MS = 10000;
const API_CHUNK = 450;           // MyMemory accetta max ~500 caratteri per richiesta

// Lingue: code = codice per la traduzione, stt/tts = locale per ascolto e voce
const LANGS = [
  { code:'it',    name:'Italiano',   stt:'it-IT', tts:'it-IT' },
  { code:'en',    name:'English',    stt:'en-US', tts:'en-US' },
  { code:'es',    name:'Español',    stt:'es-ES', tts:'es-ES' },
  { code:'fr',    name:'Français',   stt:'fr-FR', tts:'fr-FR' },
  { code:'de',    name:'Deutsch',    stt:'de-DE', tts:'de-DE' },
  { code:'pt',    name:'Português',  stt:'pt-PT', tts:'pt-PT' },
  { code:'ro',    name:'Română',     stt:'ro-RO', tts:'ro-RO' },
  { code:'ru',    name:'Русский',    stt:'ru-RU', tts:'ru-RU' },
  { code:'zh-CN', name:'中文',        stt:'zh-CN', tts:'zh-CN' },
  { code:'ja',    name:'日本語',      stt:'ja-JP', tts:'ja-JP' },
];
const byCode = c => LANGS.find(l => l.code === c) || LANGS[0];

// Testi dell'interfaccia nella lingua di ciascuna persona
const L10N = {
  'it':    { hint:'Tocca il microfono e parla',          caption:'Traduzione',  kb:'Tocca 🎤 sulla tastiera e parla' , talk:'PARLA' },
  'en':    { hint:'Tap the mic and speak',               caption:'Translation', kb:'Tap 🎤 on the keyboard and speak' , talk:'TALK' },
  'es':    { hint:'Toca el micrófono y habla',           caption:'Traducción',  kb:'Toca 🎤 en el teclado y habla' , talk:'HABLAR' },
  'fr':    { hint:'Touchez le micro et parlez',          caption:'Traduction',  kb:'Touchez 🎤 sur le clavier et parlez' , talk:'PARLER' },
  'de':    { hint:'Tippe auf das Mikrofon und sprich',   caption:'Übersetzung', kb:'Tippe auf 🎤 der Tastatur und sprich' , talk:'SPRECHEN' },
  'pt':    { hint:'Toque no microfone e fale',           caption:'Tradução',    kb:'Toque em 🎤 no teclado e fale' , talk:'FALAR' },
  'ro':    { hint:'Atinge microfonul și vorbește',       caption:'Traducere',   kb:'Atinge 🎤 pe tastatură și vorbește' , talk:'VORBEȘTE' },
  'ru':    { hint:'Нажмите на микрофон и говорите',      caption:'Перевод',     kb:'Нажмите 🎤 на клавиатуре и говорите' , talk:'ГОВОРИТЬ' },
  'zh-CN': { hint:'点击麦克风，开始说话',                    caption:'翻译',         kb:'点击键盘上的 🎤 开始说话' , talk:'说话' },
  'ja':    { hint:'マイクをタップして話してください',          caption:'翻訳',         kb:'キーボードの 🎤 をタップして話してください' , talk:'話す' },
};
const t = (lang, key) => (L10N[lang.code] || L10N.en)[key];

const ICON_MIC  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3.5"/></svg>';
const ICON_STOP = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2.5" fill="currentColor"/></svg>';
const ICON_SEND = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';

// ---------------------------------------------------------------------------
// STATO
// sides[0] = persona in basso (chi tiene il telefono), sides[1] = persona in alto
const sides = [
  { lang: LANGS[0], heard: '', received: '' },
  { lang: LANGS[1], heard: '', received: '' },
];
let state = 'idle';        // idle | listening | translating | speaking
let activeSide = null;     // chi sta parlando
let speakingSide = null;   // chi sta ascoltando la voce
let focusSide = null;      // chi deve leggere l'ultima traduzione: la sua metà si allarga
let message = '';
let rec = null;            // istanza SpeechRecognition corrente
let ttsUnlocked = false;

try {
  const saved = JSON.parse(localStorage.getItem('ft-langs') || 'null');
  if (saved) { sides[0].lang = byCode(saved[0]); sides[1].lang = byCode(saved[1]); }
} catch (_) {}
function saveLangs() {
  try { localStorage.setItem('ft-langs', JSON.stringify(sides.map(s => s.lang.code))); } catch (_) {}
}

// ---------------------------------------------------------------------------
// UI
const els = [];
function buildPanel(i) {
  const root = document.getElementById('panel-' + i);
  root.innerHTML = `
    <div class="head">
      <div class="led-window">
        <span class="ch">CH ${String(i + 1).padStart(2, '0')}</span>
        <span class="code"></span>
        <span class="name"></span>
        <span class="caret" aria-hidden="true">▾</span>
        <select aria-label="Lingua"></select>
      </div>
      <div class="plate">${i === 0 ? 'Postazione A' : 'Postazione B'}</div>
    </div>
    <div class="stage">
      <div class="caption" hidden><span class="cap-text"></span><span class="engine"></span><span class="wave" aria-hidden="true"><i></i><i></i><i></i></span></div>
      <div class="received empty" title="Tocca per riascoltare"></div>
      <div class="hint"></div>
    </div>
    <canvas class="trace" aria-hidden="true"></canvas>
    <form class="typed" hidden>
      <input type="text" enterkeyhint="send" autocomplete="off" autocorrect="on" aria-label="Frase da tradurre">
      <button type="submit" aria-label="Traduci">${ICON_SEND}</button>
    </form>
    <div class="foot">
      <div class="in"><span class="in-label">In ▸</span><div class="heard"></div></div>
      <div class="meter" aria-hidden="true">${'<i></i>'.repeat(12)}</div>
      <div class="key">
        <span class="tally" aria-hidden="true"></span>
        <button class="mic" type="button" aria-label="Parla">${ICON_MIC}</button>
        <span class="key-label"></span>
      </div>
    </div>`;
  const sel = root.querySelector('select');
  LANGS.forEach(l => sel.add(new Option(l.name, l.code)));
  sel.value = sides[i].lang.code;
  sel.addEventListener('change', () => { sides[i].lang = byCode(sel.value); saveLangs(); render(); });

  const mic = root.querySelector('.mic');
  mic.addEventListener('click', () => onMic(i));
  // tocco sul testo tradotto = riascolta
  root.querySelector('.received').addEventListener('click', () => replay(i));

  const form = root.querySelector('.typed'), input = form.querySelector('input');
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || state !== 'idle') return;
    unlockTTS();                      // il tocco su "Traduci" sblocca la voce su iPhone
    input.value = '';
    input.blur();
    form.hidden = true;
    sides[i].heard = text;
    handleText(i, text);
  });
  els[i] = { root, sel, mic, form, input,
    code: root.querySelector('.code'), caption: root.querySelector('.caption'), capText: root.querySelector('.cap-text'),
    received: root.querySelector('.received'), hint: root.querySelector('.hint'), heard: root.querySelector('.heard'),
    name: root.querySelector('.name'), keyLabel: root.querySelector('.key-label'), trace: root.querySelector('.trace'),
    meterSegs: [...root.querySelectorAll('.meter i')] };
}

// Il testo tradotto prende la dimensione più grande che entra nel suo spazio (da 44 a 14 px).
const FIT_MAX = 44, FIT_MIN = 14;
function fitText(el) {
  const text = el.textContent;
  if (!text) { el.style.fontSize = ''; el.dataset.fit = ''; return; }
  const H = el.clientHeight, W = el.clientWidth;
  if (!H || !W) return;
  const key = text.length + '|' + text.slice(0, 32) + '|' + W + 'x' + H;
  if (el.dataset.fit === key) return;
  let lo = FIT_MIN, hi = FIT_MAX, best = FIT_MIN;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    el.style.fontSize = mid + 'px';
    if (el.scrollHeight <= H + 1) { best = mid; lo = mid + 1; } else hi = mid - 1;
  }
  el.style.fontSize = best + 'px';
  el.dataset.fit = key;
}
function layoutPanels() {
  // chi deve leggere ottiene circa due terzi dello schermo
  const grow = focusSide == null ? [1, 1] : (focusSide === 0 ? [1.8, 1] : [1, 1.8]);
  els.forEach((e, i) => { e.root.style.flexGrow = String(grow[i]); });
  els.forEach(e => fitText(e.received));
}

function render() {
  const statusEl = document.getElementById('status');
  statusEl.className = (state === 'translating') ? 'busy' : '';
  statusEl.innerHTML = (state === 'translating' ? '<span class="spinner"></span>' : '') + '<span></span>';
  statusEl.lastChild.textContent = message;
  document.getElementById('swap').disabled = state !== 'idle';

  sides.forEach((s, i) => {
    const e = els[i];
    e.code.textContent = s.lang.code.split('-')[0].toUpperCase();
    e.name.textContent = s.lang.name;
    e.received.textContent = s.received;
    e.received.className = 'received' + (s.received ? '' : ' empty');
    e.hint.textContent = t(s.lang, 'hint');
    e.hint.hidden = !!s.received;
    e.caption.hidden = !s.received;
    e.capText.textContent = t(s.lang, 'caption');
    e.root.querySelector('.engine').textContent = s.engine ? '· ' + s.engine : '';
    e.input.placeholder = t(s.lang, 'kb');
    e.root.classList.toggle('speaking', state === 'speaking' && speakingSide === i);
    e.heard.textContent = s.heard;
    const listening = state === 'listening' && activeSide === i;
    e.mic.classList.toggle('listening', listening);
    e.root.classList.toggle('on-air', listening);
    e.keyLabel.textContent = listening ? 'STOP' : t(s.lang, 'talk');
    if (e.mic.dataset.icon !== String(listening)) {
      e.mic.innerHTML = listening ? ICON_STOP : ICON_MIC;
      e.mic.dataset.icon = String(listening);
      e.mic.setAttribute('aria-label', listening ? 'Ferma' : 'Parla');
    }
    e.mic.disabled = (state !== 'idle') && !listening;
    e.sel.disabled = state !== 'idle';
  });
  layoutPanels();
}
function setState(s) { state = s; if (s === 'idle') { activeSide = null; speakingSide = null; } render(); }
function setMsg(m) { message = m; render(); }

// Scambia le lingue delle due persone
document.getElementById('swap').addEventListener('click', () => {
  if (state !== 'idle') return;
  [sides[0].lang, sides[1].lang] = [sides[1].lang, sides[0].lang];
  sides.forEach((s, i) => { els[i].sel.value = s.lang.code; s.heard = ''; s.received = ''; s.engine = ''; });
  focusSide = null;
  saveLangs();
  render();
});

// ---------------------------------------------------------------------------
// IDENTITÀ DEL DISPOSITIVO: un seme casuale generato una volta su questo telefono decide
// matricola e colore dei LED. Ogni installazione ha il suo aspetto.
let deviceSeed = 0;
try { deviceSeed = Number(localStorage.getItem('ft-seed')) >>> 0; } catch (_) {}
if (!deviceSeed) {
  try { const a = new Uint32Array(1); crypto.getRandomValues(a); deviceSeed = a[0] >>> 0; } catch (_) {}
  if (!deviceSeed) deviceSeed = (Math.random() * 0xffffffff) >>> 0 || 1;
  try { localStorage.setItem('ft-seed', String(deviceSeed)); } catch (_) {}
}
const LED_COLORS = ['#a8f26b', '#ffb43d', '#7fe0ff', '#f6efc9', '#ff8a5c', '#c6a6ff'];
document.documentElement.style.setProperty('--led', LED_COLORS[deviceSeed % LED_COLORS.length]);
const hex = deviceSeed.toString(16).toUpperCase().padStart(8, '0');
document.getElementById('serial').textContent = 'N° ' + hex.slice(0, 4) + '-' + hex.slice(4);

function mulberry32(a) {
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
function hashStr(str) { let h = 2166136261; for (let k = 0; k < str.length; k++) { h ^= str.charCodeAt(k); h = Math.imul(h, 16777619); } return h >>> 0; }

// Indicatore di livello: si muove solo con eventi reali (parole riconosciute, parole pronunciate)
const meterLevels = [0, 0];
let meterRaf = 0;
function bump(i, v) {
  meterLevels[i] = Math.min(1, Math.max(meterLevels[i], v));
  if (!meterRaf) meterRaf = requestAnimationFrame(meterStep);
}
function meterStep() {
  let active = false;
  for (let i = 0; i < 2; i++) {
    const n = Math.round(meterLevels[i] * els[i].meterSegs.length);
    els[i].meterSegs.forEach((seg, k) => seg.classList.toggle('on', k < n));
    meterLevels[i] = Math.max(0, meterLevels[i] - 0.03);
    if (meterLevels[i] > 0) active = true;
  }
  meterRaf = active ? requestAnimationFrame(meterStep) : 0;
}

// Tracciato: ogni frase lascia un segmento d'onda generato dalle sue parole, dall'ora e dal seme
// del dispositivo. Il nastro scorre da destra a sinistra come un registratore.
const traces = [[], []];
function addTrace(i, text) {
  traces[i].push({ seed: (hashStr(text) ^ deviceSeed ^ (Date.now() >>> 0)) >>> 0,
                   w: Math.min(150, 26 + text.length * 1.5), loud: /[!?！？]/.test(text) });
  if (traces[i].length > 40) traces[i].shift();
  drawTrace(i);
}
function drawTrace(i) {
  const c = els[i].trace, W = c.clientWidth, H = c.clientHeight;
  if (!W || !H || !c.getContext) return;
  const dpr = window.devicePixelRatio || 1;
  c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  const g = c.getContext('2d'); if (!g) return;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue('--ink').trim() || '#1c201c', signal = css.getPropertyValue('--signal').trim() || '#d7341d';
  g.globalAlpha = .22; g.fillStyle = ink;
  for (let x = W - 4; x > 0; x -= 12) g.fillRect(x, H / 2, 1, 1);     // binario a puntini
  g.globalAlpha = 1;
  let x = W - 4;
  for (let k = traces[i].length - 1; k >= 0 && x > 0; k--) {
    const tr = traces[i][k], rnd = mulberry32(tr.seed), x0 = x - tr.w;
    const f1 = .07 + rnd() * .22, f2 = .35 + rnd() * .7, p1 = rnd() * 6.283, p2 = rnd() * 6.283;
    const amp = (tr.loud ? .9 : .45 + rnd() * .4) * (H / 2 - 3);
    g.strokeStyle = ink; g.lineWidth = 1.2; g.beginPath();
    for (let px = 0; px <= tr.w; px++) {
      const env = Math.sin(Math.PI * px / tr.w);
      const y = H / 2 + env * amp * (.62 * Math.sin(px * f1 + p1) + .38 * Math.sin(px * f2 + p2)) * (.75 + .25 * rnd());
      if (px === 0) g.moveTo(x0, y); else g.lineTo(x0 + px, y);
    }
    g.stroke();
    g.fillStyle = signal; g.fillRect(x0 - 3, H / 2 - 4, 1.5, 8);    // tacca di inizio frase
    x = x0 - 8;
  }
}
window.addEventListener('resize', () => { drawTrace(0); drawTrace(1); layoutPanels(); });
document.querySelectorAll('.panel').forEach(el => el.addEventListener('transitionend', (ev) => {
  if (ev.propertyName === 'flex-grow') { els.forEach(e => fitText(e.received)); drawTrace(0); drawTrace(1); }
}));

// ---------------------------------------------------------------------------
// MICROFONO (Web Speech API)
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

const ERR_MSG = {
  'not-allowed':          'Permesso microfono negato: abilitalo nelle impostazioni del browser.',
  'service-not-allowed':  'Riconoscimento vocale non consentito: su iPhone attiva Dettatura (Impostazioni > Generali > Tastiera).',
  'no-speech':            'Non ho sentito nulla, riprova.',
  'audio-capture':        'Microfono non disponibile.',
  'network':              'Il riconoscimento vocale richiede internet.',
  'language-not-supported': 'Lingua non supportata dal riconoscimento vocale di questo dispositivo.',
};

// Dove il browser non ha il riconoscimento vocale (Chrome su iPhone, Firefox…) si detta con la tastiera.
const TYPING_HINT = 'Tocca il microfono, poi 🎤 sulla tastiera: parla e invia.';
function openTyping(i) {
  if (state !== 'idle') return;
  unlockTTS();
  els.forEach((e, k) => { if (k !== i) e.form.hidden = true; });
  els[i].form.hidden = false;
  els[i].input.focus();               // dentro il tocco: su iPhone apre la tastiera
  setMsg(TYPING_HINT);
}

function onMic(i) {
  if (!SR) { openTyping(i); return; }
  if (state === 'listening' && activeSide === i) { try { rec && rec.stop(); } catch (_) {} return; }
  if (state !== 'idle') return;
  startListening(i);
}

function startListening(i) {
  unlockTTS();                       // deve avvenire dentro il gesto dell'utente (iOS)
  try { speechSynthesis.cancel(); } catch (_) {}
  keepAwake();

  sides[i].heard = '';
  message = '';
  activeSide = i;
  state = 'listening';

  const r = new SR();
  rec = r;
  r.lang = sides[i].lang.stt;
  r.interimResults = true;
  r.continuous = false;
  r.maxAlternatives = 1;

  let finalText = '', lastError = null;
  r.onresult = (e) => {
    let interim = '';
    for (let k = e.resultIndex; k < e.results.length; k++) {
      const res = e.results[k];
      if (res.isFinal) finalText += res[0].transcript; else interim += res[0].transcript;
    }
    sides[i].heard = (finalText + ' ' + interim).trim();
    bump(i, .45 + Math.random() * .5);
    render();
  };
  r.onerror = (e) => { lastError = e.error; };
  r.onend = () => {
    if (rec === r) rec = null;
    if (state !== 'listening' || activeSide !== i) return;
    const text = (finalText || sides[i].heard || '').trim();
    if (text) { handleText(i, text); return; }
    if (lastError && lastError !== 'aborted') message = ERR_MSG[lastError] || ('Errore microfono: ' + lastError);
    else message = ERR_MSG['no-speech'];
    setState('idle');
  };

  try { r.start(); } catch (err) { message = 'Impossibile avviare il microfono.'; setState('idle'); return; }
  render();
}

// Ferma l'ascolto se la pagina va in background
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    try { rec && rec.abort(); } catch (_) {}
    try { speechSynthesis.cancel(); } catch (_) {}
  }
});

// ---------------------------------------------------------------------------
// FLUSSO: testo riconosciuto -> traduzione -> voce
async function handleText(from, text) {
  const to = 1 - from;
  setState('translating');
  message = 'Traduzione…';
  render();
  let out;
  try {
    out = await translate(text, sides[from].lang, sides[to].lang);
  } catch (err) {
    message = 'Traduzione non riuscita: ' + (err && err.message ? err.message : err);
    setState('idle');
    return;
  }
  sides[to].received = out;
  sides[to].engine = lastEngine;
  focusSide = to;
  addTrace(from, text);
  addTrace(to, out);
  message = '';
  speakingSide = to;
  setState('speaking');
  await speak(out, sides[to].lang, to);
  setState('idle');
}

function replay(i) {
  if (state !== 'idle' || !sides[i].received) return;
  speakingSide = i;
  setState('speaking');
  speak(sides[i].received, sides[i].lang, i).then(() => setState('idle'));
}

// ---------------------------------------------------------------------------
// TRADUZIONE, dal migliore al più semplice:
//  1) DeepL, tramite il Worker che pubblica questa pagina (la chiave resta segreta sul server)
//  2) Translator API di Chrome (on-device) se già disponibile
//  3) MyMemory (gratis, senza chiave) solo come riserva
function splitForApi(text, max) {
  if (text.length <= max) return [text];
  const parts = text.match(/[^.!?。！？]+[.!?。！？]*\s*/g) || [text];
  const chunks = []; let cur = '';
  for (const p of parts) {
    if ((cur + p).length > max && cur) { chunks.push(cur); cur = ''; }
    if (p.length > max) { for (let k = 0; k < p.length; k += max) chunks.push(p.slice(k, k + max)); }
    else cur += p;
  }
  if (cur) chunks.push(cur);
  return chunks;
}
async function byChunks(text, max, fn) {
  const out = [];
  for (const c of splitForApi(text, max)) out.push(await fn(c.trim()));
  return out.join(' ');
}

async function fetchWithTimeout(url, ms, opts) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    return await fetch(url, Object.assign({ signal: ctl.signal }, opts || {}));
  } catch (err) {
    if (err && err.name === 'AbortError') throw new Error('timeout, controlla la connessione');
    if (err instanceof TypeError) throw new Error('nessuna connessione internet');
    throw err;
  } finally { clearTimeout(timer); }
}

// Diventa false se la pagina non è servita dal Worker (es. caricata su Netlify): niente altri tentativi.
let deeplAvailable = true;
async function deeplTranslate(text, from, to) {
  const resp = await fetchWithTimeout(DEEPL_ENDPOINT, API_TIMEOUT_MS, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, source: from.code, target: to.code }),
  });
  if ([404, 405, 501, 503].includes(resp.status)) { deeplAvailable = false; throw new Error('DeepL non configurato'); }
  let data = null;
  try { data = await resp.json(); } catch (_) {}
  if (!resp.ok || !data || typeof data.text !== 'string' || !data.text.trim()) {
    throw new Error((data && data.error) || ('DeepL non disponibile (' + resp.status + ')'));
  }
  return data.text.trim();
}

const nativeCache = new Map();
async function nativeTranslate(text, from, to) {
  if (!('Translator' in self)) return null;
  const opts = { sourceLanguage: from.code.split('-')[0], targetLanguage: to.code.split('-')[0] };
  const key = opts.sourceLanguage + '>' + opts.targetLanguage;
  try {
    let tr = nativeCache.get(key);
    if (!tr) {
      if ((await self.Translator.availability(opts)) !== 'available') return null;
      tr = await self.Translator.create(opts);
      nativeCache.set(key, tr);
    }
    return await tr.translate(text);
  } catch (_) { return null; }
}

async function myMemory(text, from, to) {
  const url = 'https://api.mymemory.translated.net/get?q=' + encodeURIComponent(text) +
    '&langpair=' + encodeURIComponent(from.code + '|' + to.code) +
    (MYMEMORY_EMAIL ? '&de=' + encodeURIComponent(MYMEMORY_EMAIL) : '');
  const resp = await fetchWithTimeout(url, API_TIMEOUT_MS);
  if (!resp.ok) throw new Error('servizio non raggiungibile (' + resp.status + ')');
  const data = await resp.json();
  const out = (data && data.responseData && data.responseData.translatedText) || '';
  const details = (data && data.responseDetails) || '';
  // Quota finita: l'API può rispondere 200 o 429, con l'avviso nel testo o nei dettagli
  if (data && (data.quotaFinished === true || /MYMEMORY WARNING/i.test(out) || /MYMEMORY WARNING/i.test(details))) {
    throw new Error('limite giornaliero gratuito raggiunto (riprova domani o imposta MYMEMORY_EMAIL)');
  }
  if (/QUERY LENGTH LIMIT/i.test(out) || /QUERY LENGTH LIMIT/i.test(details)) throw new Error('frase troppo lunga');
  if (!out || Number(data.responseStatus) !== 200) throw new Error(details || 'risposta non valida');
  return decodeEntities(out);
}

function decodeEntities(s) {
  const ta = document.createElement('textarea');
  ta.innerHTML = s;
  return ta.value;
}

let lastEngine = '';
async function translate(text, from, to) {
  lastEngine = '';
  if (from.code === to.code) return text;
  if (deeplAvailable) {
    try { const out = await deeplTranslate(text, from, to); lastEngine = 'DeepL'; return out; }
    catch (_) { /* quota esaurita o rete: si passa ai servizi di riserva */ }
  }
  const native = await nativeTranslate(text, from, to);
  if (native) return native;
  return byChunks(text, API_CHUNK, c => myMemory(c, from, to));
}

// ---------------------------------------------------------------------------
// VOCE (speechSynthesis)
let voices = [];
function loadVoices() { try { voices = speechSynthesis.getVoices() || []; } catch (_) { voices = []; } }
loadVoices();
try { speechSynthesis.addEventListener('voiceschanged', loadVoices); } catch (_) {}

function pickVoice(lang) {
  const full = lang.tts.toLowerCase().replace('_', '-');
  const short = full.split('-')[0];
  const norm = v => (v.lang || '').toLowerCase().replace('_', '-');
  return voices.find(v => norm(v) === full) || voices.find(v => norm(v).split('-')[0] === short) || null;
}

// iOS consente speak() solo dopo un gesto dell'utente: "sblocchiamo" al primo tocco
function unlockTTS() {
  if (ttsUnlocked) return;
  try {
    const u = new SpeechSynthesisUtterance(' ');   // uno spazio: iOS ignora le frasi vuote
    u.volume = 0;
    speechSynthesis.speak(u);
    ttsUnlocked = true;
  } catch (_) {}
}

function speak(text, lang, side) {
  return new Promise((resolve) => {
    if (!('speechSynthesis' in window)) { message = 'Voce non supportata da questo browser.'; render(); return resolve(); }
    try { speechSynthesis.cancel(); } catch (_) {}
    loadVoices();
    const voice = pickVoice(lang);
    if (!voice && voices.length) { message = 'Voce per ' + lang.name + ' non installata sul dispositivo.'; render(); }

    // frasi separate: evita lo stop silenzioso di Chrome sui testi lunghi
    const parts = (text.match(/[^.!?。！？]+[.!?。！？]*/g) || [text]).map(s => s.trim()).filter(Boolean);
    let remaining = parts.length, done = false;
    const finish = () => { if (done) return; done = true; clearTimeout(guard); resolve(); };
    const guard = setTimeout(finish, 8000 + text.length * 120);   // paracadute

    parts.forEach((p) => {
      const u = new SpeechSynthesisUtterance(p);
      u.lang = lang.tts;
      if (voice) u.voice = voice;
      u.rate = 1;
      u.onend = u.onerror = () => { if (--remaining <= 0) finish(); };
      // l'indicatore di livello segue le parole pronunciate
      if (side != null) { u.onstart = () => bump(side, .7); u.onboundary = () => bump(side, .5 + Math.random() * .45); }
      speechSynthesis.speak(u);
    });
  });
}

// Tiene lo schermo acceso durante la conversazione
let wakeLock = null;
async function keepAwake() {
  try { if ('wakeLock' in navigator && !wakeLock) {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener('release', () => { wakeLock = null; });
  } } catch (_) {}
}

// ---------------------------------------------------------------------------
buildPanel(0);
buildPanel(1);
render();
if (!SR) setMsg(TYPING_HINT);
