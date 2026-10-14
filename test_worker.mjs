// Collaudo del Worker in Node (>= 18), con DeepL simulato. Uso: node test_worker.mjs
import worker from './worker.js';
import { readFileSync } from 'node:fs';

let pass = 0, fail = 0;
const check = (name, cond, detail = '') => {
  if (cond) { pass++; console.log('PASS ' + name); } else { fail++; console.log('FAIL ' + name + '   -> ' + JSON.stringify(detail)); }
};

// DeepL simulato: registra le chiamate e risponde secondo la modalità
let deeplCalls = [], mode = 'ok';
globalThis.fetch = async (url, init) => {
  deeplCalls.push({ url, init, body: JSON.parse(init.body) });
  if (mode === 'quota') return new Response('', { status: 456 });
  if (mode === 'badkey') return new Response('', { status: 403 });
  if (mode === 'down') throw new TypeError('fetch failed');
  if (mode === 'empty') return new Response(JSON.stringify({ translations: [] }), { status: 200 });
  const b = JSON.parse(init.body);
  return new Response(JSON.stringify({ translations: [{ detected_source_language: b.source_lang, text: `[${b.source_lang}>${b.target_lang}] ${b.text[0]}` }] }), { status: 200 });
};

const BASE = 'https://face-translator.example.workers.dev';
const post = (body, { origin = BASE, env = { DEEPL_KEY: 'abc123:fx' }, method = 'POST', raw } = {}) =>
  worker.fetch(new Request(BASE + '/api/translate', {
    method, headers: { 'Content-Type': 'application/json', ...(origin ? { Origin: origin } : {}) },
    body: method === 'POST' ? (raw ?? JSON.stringify(body)) : undefined,
  }), env);

// 1. pagina
let r = await worker.fetch(new Request(BASE + '/'), {});
const html = await r.text();
check('1a GET / restituisce la pagina', r.status === 200 && r.headers.get('content-type').startsWith('text/html'), r.status);
check('1b la pagina è identica a index.html', html === readFileSync(new URL('./index.html', import.meta.url), 'utf8'));
for (const [path, file, type] of [['/style.css', 'style.css', 'text/css'], ['/app.js', 'app.js', 'text/javascript']]) {
  r = await worker.fetch(new Request(BASE + path), {});
  check(`1b ${path} servito identico a ${file}`, r.status === 200 && r.headers.get('content-type').startsWith(type) && (await r.text()) === readFileSync(new URL('./' + file, import.meta.url), 'utf8'), r.status);
}
check('1b la pagina collega style.css e app.js', html.includes('href="style.css"') && html.includes('src="app.js"'));
r = await worker.fetch(new Request(BASE + '/altro'), {});
check('1c percorso sconosciuto -> 404', r.status === 404, r.status);

// 2. traduzione riuscita, chiave gratuita -> api-free
deeplCalls = []; mode = 'ok';
r = await post({ text: '  ciao come stai ', source: 'it', target: 'en' });
let j = await r.json();
check('2a traduzione OK', r.status === 200 && j.text === '[IT>EN-US] ciao come stai', [r.status, j]);
check('2b chiave :fx -> api-free.deepl.com', deeplCalls[0].url === 'https://api-free.deepl.com/v2/translate', deeplCalls[0].url);
check('2c chiave nell\'intestazione, non nel corpo', deeplCalls[0].init.headers.Authorization === 'DeepL-Auth-Key abc123:fx' && !JSON.stringify(deeplCalls[0].body).includes('abc123'));
check('2d la risposta al browser non contiene la chiave', !JSON.stringify(j).includes('abc123'));

// 3. mappature lingua
deeplCalls = [];
for (const [s, t, es, et] of [['pt', 'zh-CN', 'PT', 'ZH-HANS'], ['zh-CN', 'pt', 'ZH', 'PT-PT'], ['en', 'it', 'EN', 'IT'], ['ja', 'ru', 'JA', 'RU']]) {
  await post({ text: 'x', source: s, target: t });
}
check('3 codici DeepL corretti', JSON.stringify(deeplCalls.map(c => [c.body.source_lang, c.body.target_lang])) ===
  JSON.stringify([['PT', 'ZH-HANS'], ['ZH', 'PT-PT'], ['EN', 'IT'], ['JA', 'RU']]), deeplCalls.map(c => [c.body.source_lang, c.body.target_lang]));

// 4. chiave a pagamento -> api.deepl.com
deeplCalls = [];
await post({ text: 'x', source: 'it', target: 'en' }, { env: { DEEPL_KEY: 'prokey' } });
check('4 chiave Pro -> api.deepl.com', deeplCalls[0].url === 'https://api.deepl.com/v2/translate', deeplCalls[0].url);

// 5. errori
const status = async (...a) => { const x = await post(...a); return [x.status, (await x.json()).error]; };
let s;
s = await status({ text: 'x', source: 'it', target: 'en' }, { env: {} });
check('5a senza chiave -> 503 (la pagina usa la riserva)', s[0] === 503, s);
deeplCalls = [];
s = await status({ text: 'x', source: 'it', target: 'en' }, { origin: 'https://sito-altrui.com' });
check('5b altra origine -> 403, DeepL non chiamato', s[0] === 403 && deeplCalls.length === 0, s);
s = await status({ text: 'x', source: 'xx', target: 'en' });
check('5c lingua sconosciuta -> 400', s[0] === 400, s);
s = await status({ text: '   ', source: 'it', target: 'en' });
check('5d testo vuoto -> 400', s[0] === 400, s);
s = await status({ text: 'a'.repeat(5001), source: 'it', target: 'en' });
check('5e testo oltre 5000 caratteri -> 413', s[0] === 413, s);
s = await status(null, { raw: '{non json' });
check('5f JSON rotto -> 400', s[0] === 400, s);
s = await status(null, { method: 'GET' });
check('5g GET su /api/translate -> 405', s[0] === 405, s);
mode = 'quota'; s = await status({ text: 'x', source: 'it', target: 'en' });
check('5h quota DeepL esaurita -> 429 con messaggio chiaro', s[0] === 429 && /esauriti/.test(s[1]), s);
mode = 'badkey'; s = await status({ text: 'x', source: 'it', target: 'en' });
check('5i chiave errata -> 502 "chiave DeepL non valida"', s[0] === 502 && /chiave/.test(s[1]), s);
mode = 'down'; s = await status({ text: 'x', source: 'it', target: 'en' });
check('5j DeepL irraggiungibile -> 502', s[0] === 502, s);
mode = 'empty'; s = await status({ text: 'x', source: 'it', target: 'en' });
check('5k risposta DeepL vuota -> 502', s[0] === 502, s);
mode = 'ok';
s = await status({ text: 'x', source: 'it', target: 'en' }, { origin: null });
check('5l richiesta senza Origin (stessa pagina, alcuni browser) accettata', s[0] === 200, s);

console.log(`\n${pass}/${pass + fail} test del Worker superati`);
process.exit(fail ? 1 : 0);
