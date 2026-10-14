// Face Translator - Cloudflare Worker (piano gratuito).
// Fa due cose:
//   GET  /, /style.css, /app.js -> la pagina dell'app (pubblica, nessun login)
//   POST /api/translate  -> traduce con DeepL; la chiave resta qui, mai nel browser
//
// Impostazione: nel Worker aggiungi la variabile segreta DEEPL_KEY con la tua chiave DeepL API.
// Le chiavi del piano gratuito finiscono con ":fx" e usano api-free.deepl.com.

// Le tre parti dell'app (index.html, style.css, app.js) vengono inserite qui da build_worker.py
const HTML = __HTML__;
const CSS = __CSS__;
const JS = __JS__;

// Codici app -> codici DeepL (sorgente e destinazione differiscono per inglese, portoghese e cinese)
const SOURCE = { it: 'IT', en: 'EN', es: 'ES', fr: 'FR', de: 'DE', pt: 'PT', ro: 'RO', ru: 'RU', 'zh-CN': 'ZH', ja: 'JA' };
const TARGET = { it: 'IT', en: 'EN-US', es: 'ES', fr: 'FR', de: 'DE', pt: 'PT-PT', ro: 'RO', ru: 'RU', 'zh-CN': 'ZH-HANS', ja: 'JA' };
const MAX_CHARS = 5000;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });
}

async function translate(request, env) {
  if (request.method !== 'POST') return json({ error: 'metodo non consentito' }, 405);
  if (!env.DEEPL_KEY) return json({ error: 'DeepL non configurato: manca DEEPL_KEY' }, 503);

  // La chiave è tua: si accettano solo richieste dalla pagina servita da questo Worker.
  const url = new URL(request.url);
  const origin = request.headers.get('Origin');
  if (origin && origin !== url.origin) return json({ error: 'origine non consentita' }, 403);

  let body;
  try { body = await request.json(); } catch (_) { return json({ error: 'richiesta non valida' }, 400); }
  const text = typeof body.text === 'string' ? body.text.trim() : '';
  const source = SOURCE[body.source];
  const target = TARGET[body.target];
  if (!text || !source || !target) return json({ error: 'richiesta non valida' }, 400);
  if (text.length > MAX_CHARS) return json({ error: 'frase troppo lunga' }, 413);

  const host = env.DEEPL_KEY.trim().endsWith(':fx') ? 'https://api-free.deepl.com' : 'https://api.deepl.com';
  let resp;
  try {
    resp = await fetch(host + '/v2/translate', {
      method: 'POST',
      headers: { Authorization: 'DeepL-Auth-Key ' + env.DEEPL_KEY.trim(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: [text], source_lang: source, target_lang: target }),
    });
  } catch (_) {
    return json({ error: 'DeepL non raggiungibile' }, 502);
  }
  if (resp.status === 456) return json({ error: 'caratteri DeepL del mese esauriti' }, 429);
  if (resp.status === 403) return json({ error: 'chiave DeepL non valida' }, 502);
  if (resp.status === 429) return json({ error: 'troppe richieste a DeepL, riprova tra poco' }, 429);
  if (!resp.ok) return json({ error: 'DeepL ha risposto ' + resp.status }, 502);

  let data;
  try { data = await resp.json(); } catch (_) { return json({ error: 'risposta DeepL non valida' }, 502); }
  const out = data && Array.isArray(data.translations) && data.translations[0] && data.translations[0].text;
  if (typeof out !== 'string' || !out.trim()) return json({ error: 'risposta DeepL vuota' }, 502);
  return json({ text: out });
}

const ASSETS = {
  '/': { body: HTML, type: 'text/html; charset=utf-8' },
  '/index.html': { body: HTML, type: 'text/html; charset=utf-8' },
  '/style.css': { body: CSS, type: 'text/css; charset=utf-8' },
  '/app.js': { body: JS, type: 'text/javascript; charset=utf-8' },
};

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    if (pathname === '/api/translate') return translate(request, env);
    const asset = ASSETS[pathname];
    if (asset) {
      return new Response(asset.body, {
        headers: {
          'Content-Type': asset.type,
          'Cache-Control': 'no-cache',
          'X-Content-Type-Options': 'nosniff',
        },
      });
    }
    return new Response('Pagina non trovata', { status: 404 });
  },
};
