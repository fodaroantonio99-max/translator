#!/usr/bin/env python3
"""Test end-to-end della web app in Chromium reale (Playwright).
Microfono (SpeechRecognition), voce (speechSynthesis) e API MyMemory sono simulati:
si verifica la logica dell'app, non la qualità del riconoscimento/traduzione reali.
Uso: python3 test_e2e.py"""
import functools, http.server, json, pathlib, sys, threading, urllib.parse
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).parent
PORT = 8765
URL = f"http://localhost:{PORT}/index.html"

# ---------------------------------------------------------------- mock JS ---
STT_MOCK = """
(() => {
  window.__stt = { text:'', error:null, delay:100, hold:false, calls:[] };
  class FakeSR {
    constructor(){ this.lang=''; this._ended=false; this._t=[]; this._started=false; }
    _end(){ if(this._ended) return; this._ended=true; this._t.forEach(clearTimeout); this.onend && this.onend(); }
    _res(txt, fin){ const r=[{transcript:txt}]; r.isFinal=fin; this.onresult && this.onresult({resultIndex:0, results:[r]}); }
    start(){
      const cfg = window.__stt;
      cfg.calls.push({lang:this.lang});
      this._t.push(setTimeout(() => {
        if (cfg.error) { this.onerror && this.onerror({error:cfg.error}); this._end(); return; }
        if (cfg.text) {
          this._res(cfg.text.slice(0, Math.ceil(cfg.text.length/2)), false);
          if (!cfg.hold) this._t.push(setTimeout(() => { this._res(cfg.text, true); this._end(); }, 60));
        } else if (!cfg.hold) { this._end(); }
      }, cfg.delay));
    }
    stop(){ const cfg=window.__stt; if (cfg.text) this._res(cfg.text, true); this._end(); }
    abort(){ this._end(); }
  }
  window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
})();
"""

TTS_MOCK = """
(() => {
  window.__tts = { spoken:[], cancelled:0,
    voices:[{lang:'it-IT',name:'Alice'},{lang:'en-US',name:'Samantha'},{lang:'de-DE',name:'Anna'}] };
  window.SpeechSynthesisUtterance = class { constructor(t){ this.text=t; this.lang=''; this.voice=null; this.volume=1; this.rate=1; } };
  const mock = {
    speak(u){ window.__tts.spoken.push({text:u.text, lang:u.lang, voice:u.voice&&u.voice.name||null, volume:u.volume});
              setTimeout(() => u.onend && u.onend({}), 40); },
    cancel(){ window.__tts.cancelled++; },
    getVoices(){ return window.__tts.voices; },
    addEventListener(){}, removeEventListener(){}
  };
  Object.defineProperty(window, 'speechSynthesis', { value: mock, configurable: true });
})();
"""

NATIVE_TRANSLATOR = """
window.Translator = { availability: async () => 'available',
  create: async (o) => ({ translate: async (t) => '[native ' + o.sourceLanguage + '>' + o.targetLanguage + '] ' + t }) };
"""
NO_TRANSLATOR = "try { delete window.Translator; } catch(e) {} window.Translator = undefined; delete window.Translator;"

DICT = {
    ("ciao come stai", "it|en"): "hello how are you",
    ("where is the station", "en|it"): "dov&#39;è la stazione",
}

# ---------------------------------------------------------------- harness ---
results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   -> {detail}"))

class Env:
    def __init__(self, browser, stt=None, native=False, mm=None, viewport=(390, 844), no_stt=False, deepl=None):
        self.requests = []
        self.drequests = []
        self.errors = []
        self.ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                                       device_scale_factor=2, has_touch=True, is_mobile=True,
                                       user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
        self.page = self.ctx.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.ctx.add_init_script(STT_MOCK)
        self.ctx.add_init_script(TTS_MOCK)
        self.ctx.add_init_script(NATIVE_TRANSLATOR if native else NO_TRANSLATOR)
        if no_stt:   # browser senza riconoscimento vocale (es. Chrome su iPhone)
            self.ctx.add_init_script("delete window.SpeechRecognition; delete window.webkitSpeechRecognition;")
        if stt:
            self.ctx.add_init_script("Object.assign(window.__stt, %s)" % json.dumps(stt))
        mm = mm or self.default_mm
        def handler(route):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query)
            self.requests.append((q["langpair"][0], q["q"][0]))
            mm(route, q["q"][0], q["langpair"][0])
        self.ctx.route("https://api.mymemory.translated.net/**", handler)
        deepl = deepl or self.deepl_absent
        def dhandler(route):
            body = json.loads(route.request.post_data or "{}")
            self.drequests.append((body.get("source"), body.get("target"), body.get("text")))
            deepl(route, body.get("text"), body.get("source"), body.get("target"))
        self.ctx.route("**/api/translate", dhandler)
        self.ctx.route("https://fonts.googleapis.com/**", lambda r: r.abort())
        self.ctx.route("https://fonts.gstatic.com/**", lambda r: r.abort())
        self.page.goto(URL)

    @staticmethod
    def deepl_absent(route, text, src, tgt):      # pagina non servita dal Worker (es. Netlify)
        route.fulfill(status=404, body="Not found")

    @staticmethod
    def deepl_ok(route, text, src, tgt):
        out = {("ciao come stai", "it", "en"): "Hello, how are you?"}.get((text.lower(), src, tgt), f"<deepl {src}>{tgt}> {text}")
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"text": out}))

    @staticmethod
    def default_mm(route, q, pair):
        out = DICT.get((q.lower(), pair), f"[{pair}] {q}")
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"responseData": {"translatedText": out}, "responseStatus": 200}))

    def idle(self):
        self.page.wait_for_function(
            "!document.querySelector('#panel-0 .mic').disabled && !document.querySelector('#panel-1 .mic').disabled"
            " && document.querySelector('#status .spinner')===null")
    def spoken(self):
        return [s for s in self.page.evaluate("window.__tts.spoken") if s["text"].strip()]
    def wait_spoken(self, n):
        self.page.wait_for_function("window.__tts.spoken.filter(s=>s.text.trim()).length >= %d" % n)
    def txt(self, sel):
        return self.page.inner_text(sel)
    def status(self):
        return self.page.inner_text("#status")
    def close(self):
        self.ctx.close()

# ------------------------------------------------------------------ tests ---
def run(browser):
    # 1. Basso (it) -> alto (en): richiesta, testo mostrato, voce nella lingua giusta
    e = Env(browser, stt={"text": "ciao come stai"})
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("1a richiesta traduzione it|en", e.requests == [("it|en", "ciao come stai")], e.requests)
    check("1b traduzione mostrata nel pannello opposto", e.txt("#panel-1 .received") == "hello how are you", e.txt("#panel-1 .received"))
    check("1c testo detto mostrato nel proprio pannello", e.txt("#panel-0 .heard") == "ciao come stai", e.txt("#panel-0 .heard"))
    sp = e.spoken()
    check("1d voce letta in en-US con voce inglese", sp and sp[0]["text"] == "hello how are you" and sp[0]["lang"] == "en-US" and sp[0]["voice"] == "Samantha", sp)
    check("1e STT avviato con locale it-IT", e.page.evaluate("window.__stt.calls")[0]["lang"] == "it-IT")
    check("1f stato torna idle senza errori", e.status() == "" and not e.errors, (e.status(), e.errors))
    # 6. riascolto con tocco sul testo tradotto
    e.page.click("#panel-1 .received"); e.wait_spoken(2); e.idle()
    check("6 tocco sul testo = riascolta", len(e.spoken()) == 2 and e.spoken()[1]["text"] == "hello how are you", e.spoken())
    e.close()

    # 2. Alto (en, pannello ruotato) -> basso (it); entità HTML decodificate
    e = Env(browser, stt={"text": "where is the station"})
    e.page.click("#panel-1 .mic"); e.wait_spoken(1); e.idle()
    check("2a richiesta en|it dal pannello ruotato", e.requests == [("en|it", "where is the station")], e.requests)
    check("2b entità HTML decodificate", e.txt("#panel-0 .received") == "dov'è la stazione", e.txt("#panel-0 .received"))
    check("2c voce in it-IT", e.spoken()[0]["lang"] == "it-IT" and e.spoken()[0]["voice"] == "Alice", e.spoken())
    e.close()

    # 3. Durante l'ascolto l'altro microfono è disattivato; secondo tocco ferma e traduce
    e = Env(browser, stt={"text": "ciao come stai", "hold": True})
    e.page.click("#panel-0 .mic")
    e.page.wait_for_selector("#panel-0 .mic.listening")
    check("3a altro microfono disabilitato mentre si ascolta", e.page.is_disabled("#panel-1 .mic"))
    check("3b selettore lingua bloccato", e.page.is_disabled("#panel-0 select"))
    e.page.click("#panel-0 .mic")   # stop
    e.wait_spoken(1); e.idle()
    check("3c stop manuale -> traduce comunque", e.txt("#panel-1 .received") == "hello how are you", e.txt("#panel-1 .received"))
    e.close()

    # 3d. Microfoni bloccati durante la lettura della voce (anti-eco)
    e = Env(browser, stt={"text": "ciao come stai"})
    e.page.evaluate("""() => { const orig = window.speechSynthesis.speak;
        window.speechSynthesis.speak = (u) => { window.__tts.spoken.push({text:u.text,lang:u.lang,voice:null});
          if (!u.text.trim()) return;   // ignora l'utterance vuota di "sblocco" iOS
          window.__during = [document.querySelector('#panel-0 .mic').disabled, document.querySelector('#panel-1 .mic').disabled];
          setTimeout(() => u.onend && u.onend({}), 300); }; }""")
    e.page.click("#panel-0 .mic"); e.page.wait_for_function("window.__during !== undefined")
    check("3d microfoni disabilitati mentre parla la voce", e.page.evaluate("window.__during") == [True, True], e.page.evaluate("window.__during"))
    e.idle(); e.close()

    # 4. Errori microfono
    for err, frag in [("not-allowed", "Permesso microfono"), ("service-not-allowed", "Dettatura"),
                      ("language-not-supported", "Lingua non supportata"), ("network", "internet")]:
        e = Env(browser, stt={"error": err})
        e.page.click("#panel-0 .mic"); e.idle()
        check(f"4 errore {err} mostrato e mic riabilitato", frag in e.status(), e.status()); e.close()
    e = Env(browser, stt={"text": ""})
    e.page.click("#panel-0 .mic"); e.idle()
    check("5 silenzio senza testo -> messaggio, nessuna richiesta", "Non ho sentito" in e.status() and not e.requests, (e.status(), e.requests))
    e.close()

    # 7. Errori traduzione: 500, quota, JSON rotto, timeout di rete
    def mm500(route, q, pair): route.fulfill(status=500, body="boom")
    e = Env(browser, stt={"text": "ciao come stai"}, mm=mm500)
    e.page.click("#panel-0 .mic"); e.idle()
    check("7a HTTP 500 -> errore, mic riabilitato, nessuna voce", "Traduzione non riuscita" in e.status() and not e.spoken(), (e.status(), e.spoken()))
    e.close()
    def mmquota(route, q, pair):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"responseData": {"translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."}, "responseStatus": 200}))
    e = Env(browser, stt={"text": "ciao come stai"}, mm=mmquota)
    e.page.click("#panel-0 .mic"); e.idle()
    check("7b quota giornaliera segnalata", "limite giornaliero" in e.status() and not e.spoken(), e.status())
    e.close()
    def mmquota429(route, q, pair):   # forma reale: stato 429 nel JSON, avviso nei dettagli
        route.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"responseData": {"translatedText": ""}, "quotaFinished": True, "responseStatus": 429,
             "responseDetails": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."}))
    e = Env(browser, stt={"text": "ciao come stai"}, mm=mmquota429)
    e.page.click("#panel-0 .mic"); e.idle()
    check("7e quota finita (stato 429) segnalata chiaramente", "limite giornaliero" in e.status() and not e.spoken(), e.status())
    e.close()
    def mmabort(route, q, pair): route.abort()
    e = Env(browser, stt={"text": "ciao come stai"}, mm=mmabort)
    e.page.click("#panel-0 .mic"); e.idle()
    check("7c rete assente -> messaggio chiaro", "nessuna connessione" in e.status(), e.status())
    e.close()
    # dopo un errore si può riprovare
    e = Env(browser, stt={"text": "ciao come stai"}, mm=mm500)
    e.page.click("#panel-0 .mic"); e.idle()
    e.ctx.unroute("https://api.mymemory.translated.net/**")
    e.ctx.route("https://api.mymemory.translated.net/**", lambda r: Env.default_mm(r, "ciao come stai", "it|en"))
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("7d dopo errore il secondo tentativo funziona", e.txt("#panel-1 .received") == "hello how are you", e.txt("#panel-1 .received"))
    e.close()

    # 8. Testo lungo: spezzato in richieste <= 450 caratteri, voce a frasi
    long_text = " ".join(f"Questa è la frase numero {i} del discorso." for i in range(1, 31))
    e = Env(browser, stt={"text": long_text})
    e.page.click("#panel-0 .mic"); e.page.wait_for_function("window.__tts.spoken.filter(s=>s.text.trim()).length >= 30", timeout=15000); e.idle()
    check("8a testo lungo in più richieste", len(e.requests) > 1, len(e.requests))
    check("8b ogni richiesta <= 450 caratteri", all(len(q) <= 450 for _, q in e.requests), [len(q) for _, q in e.requests])
    check("8c nessuna parte del testo persa", " ".join(q.strip() for _, q in e.requests).replace("  ", " ") == long_text, "")
    check("8d voce spezzata in frasi", len(e.spoken()) >= 30, len(e.spoken()))
    e.close()

    # 9. Stessa lingua: nessuna chiamata API
    e = Env(browser, stt={"text": "ciao come stai"})
    e.page.select_option("#panel-1 select", "it")
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("9 stessa lingua -> niente API, testo ripetuto", not e.requests and e.txt("#panel-1 .received") == "ciao come stai", (e.requests, e.txt("#panel-1 .received")))
    e.close()

    # 10. Translator API nativa (Chrome on-device): nessuna chiamata di rete
    e = Env(browser, stt={"text": "ciao come stai"}, native=True)
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("10 Translator on-device usato, zero richieste di rete", not e.requests and e.txt("#panel-1 .received") == "[native it>en] ciao come stai", (e.requests, e.txt("#panel-1 .received")))
    e.close()

    # 11. Persistenza lingue
    e = Env(browser, stt={"text": "ciao come stai"})
    e.page.select_option("#panel-1 select", "es"); e.page.select_option("#panel-0 select", "de")
    e.page.reload(); e.page.wait_for_selector("#panel-1 select")
    check("11 lingue salvate dopo reload", e.page.input_value("#panel-1 select") == "es" and e.page.input_value("#panel-0 select") == "de",
          (e.page.input_value("#panel-1 select"), e.page.input_value("#panel-0 select")))
    e.close()

    # 12. Layout a specchio
    e = Env(browser, stt={"text": "ciao come stai"})
    tr = e.page.evaluate("getComputedStyle(document.querySelector('#panel-1')).transform")
    tb = e.page.locator("#panel-1").bounding_box(); bb = e.page.locator("#panel-0").bounding_box()
    check("12a pannello superiore ruotato di 180°", tr.startswith("matrix(-1,") and tr.endswith("-1, 0, 0)"), tr)
    check("12b pannello superiore sta sopra, inferiore sotto", tb["y"] < bb["y"] and abs(tb["height"] - bb["height"]) < 4, (tb, bb))
    check("12c nessuno scroll orizzontale/verticale della pagina", e.page.evaluate("document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight"))
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    e.page.screenshot(path=str(ROOT / "screenshot.png"))
    e.close()

    # 13. Browser senza riconoscimento vocale (Chrome su iPhone): dettatura da tastiera
    for side, other, text, expected, voice in [(0, 1, "ciao come stai", "hello how are you", "en-US"),
                                                (1, 0, "where is the station", "dov'è la stazione", "it-IT")]:
        e = Env(browser, no_stt=True)
        check(f"13a[{side}] nessun SpeechRecognition, suggerimento tastiera", "tastiera" in e.status() and
              e.page.evaluate("typeof webkitSpeechRecognition === 'undefined'"), e.status())
        check(f"13b[{side}] campo nascosto prima del tocco", e.page.is_hidden(f"#panel-{side} .typed"))
        e.page.click(f"#panel-{side} .mic")
        check(f"13c[{side}] il microfono apre il campo e lo mette a fuoco", e.page.is_visible(f"#panel-{side} .typed") and
              e.page.evaluate(f"document.activeElement === document.querySelector('#panel-{side} .typed input')"))
        check(f"13d[{side}] l'altro campo resta chiuso", e.page.is_hidden(f"#panel-{other} .typed"))
        e.page.fill(f"#panel-{side} .typed input", text)
        e.page.press(f"#panel-{side} .typed input", "Enter")
        e.wait_spoken(1); e.idle()
        check(f"13e[{side}] dettato -> tradotto nel pannello opposto", e.txt(f"#panel-{other} .received") == expected, e.txt(f"#panel-{other} .received"))
        check(f"13f[{side}] voce nella lingua dell'altro", e.spoken()[0]["lang"] == voice, e.spoken())
        check(f"13g[{side}] campo richiuso e svuotato", e.page.is_hidden(f"#panel-{side} .typed") and
              e.page.input_value(f"#panel-{side} .typed input") == "")
        check(f"13h[{side}] nessun errore JS", not e.errors, e.errors)
        e.close()
    e = Env(browser, no_stt=True)
    e.page.click("#panel-0 .mic"); e.page.press("#panel-0 .typed input", "Enter")
    check("13i invio a vuoto non fa nulla", not e.requests and not e.spoken(), (e.requests, e.spoken()))
    e.page.click("#panel-0 .mic"); e.page.fill("#panel-0 .typed input", "ciao come stai"); e.page.click("#panel-0 .typed button")
    e.wait_spoken(1); e.idle()
    check("13j anche il pulsante Traduci funziona", e.txt("#panel-1 .received") == "hello how are you", e.txt("#panel-1 .received"))
    e.close()

# ------------------------------------------------------------------- main ---
def run_extra(browser):
    # 15. DeepL tramite il Worker
    e = Env(browser, stt={"text": "ciao come stai"}, deepl=Env.deepl_ok)
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("15a usa DeepL: una richiesta it>en, nessun servizio di riserva", e.drequests == [("it", "en", "ciao come stai")] and not e.requests, (e.drequests, e.requests))
    check("15b traduzione DeepL mostrata e letta", e.txt("#panel-1 .received") == "Hello, how are you?" and e.spoken()[0]["text"] == "Hello, how are you?", (e.txt("#panel-1 .received"), e.spoken()))
    check("15c motore indicato accanto alla didascalia", e.page.evaluate("document.querySelector('#panel-1 .engine').textContent") == "· DeepL")
    check("15d nessun messaggio di errore", e.status() == "", e.status())
    e.close()
    e = Env(browser, stt={"text": "ciao come stai"})          # pagina non servita dal Worker: 404
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    e.page.click("#panel-0 .mic"); e.wait_spoken(2); e.idle()
    check("15e senza Worker: riserva MyMemory, DeepL provato una sola volta", len(e.drequests) == 1 and len(e.requests) == 2
          and e.txt("#panel-1 .received") == "hello how are you" and e.status() == "", (e.drequests, e.requests, e.status()))
    check("15f con la riserva nessuna etichetta DeepL", e.page.evaluate("document.querySelector('#panel-1 .engine').textContent") == "")
    e.close()
    def deepl_quota(route, text, src, tgt):
        route.fulfill(status=429, content_type="application/json", body=json.dumps({"error": "caratteri DeepL del mese esauriti"}))
    e = Env(browser, stt={"text": "ciao come stai"}, deepl=deepl_quota)
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    e.page.click("#panel-0 .mic"); e.wait_spoken(2); e.idle()
    check("15g quota DeepL esaurita: riserva, e DeepL riprovato al turno dopo", len(e.drequests) == 2 and len(e.requests) == 2
          and e.txt("#panel-1 .received") == "hello how are you", (e.drequests, e.requests))
    e.close()
    def deepl_abort(route, text, src, tgt): route.abort()
    e = Env(browser, stt={"text": "ciao come stai"}, deepl=deepl_abort, native=True)
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("15h Worker irraggiungibile -> traduttore on-device di Chrome", not e.requests and e.txt("#panel-1 .received") == "[native it>en] ciao come stai", (e.requests, e.txt("#panel-1 .received")))
    e.close()
    long_text = " ".join(f"Questa è la frase numero {i} del discorso." for i in range(1, 51))
    e = Env(browser, stt={"text": long_text}, deepl=Env.deepl_ok)
    e.page.click("#panel-0 .mic"); e.page.wait_for_function("window.__tts.spoken.filter(s=>s.text.trim()).length >= 1", timeout=15000); e.idle()
    check("15i testo lungo: una sola richiesta DeepL con tutto il testo", len(e.drequests) == 1 and e.drequests[0][2] == long_text and not e.requests, len(e.drequests))
    e.close()
    e = Env(browser, stt={"text": "ciao come stai"}, deepl=Env.deepl_ok)
    e.page.select_option("#panel-1 select", "it")
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("15j stessa lingua: nessuna richiesta a DeepL", not e.drequests, e.drequests)
    e.close()

    # 16. Scambio lingue
    e = Env(browser, stt={"text": "ciao come stai", "hold": True})
    e.page.click("#swap")
    check("16a scambio: in basso English, in alto Italiano", e.page.input_value("#panel-0 select") == "en" and e.page.input_value("#panel-1 select") == "it",
          (e.page.input_value("#panel-0 select"), e.page.input_value("#panel-1 select")))
    e.page.reload(); e.page.wait_for_selector("#panel-0 select")
    check("16b scambio salvato", e.page.input_value("#panel-0 select") == "en")
    e.page.click("#panel-0 .mic"); e.page.wait_for_selector("#panel-0 .mic.listening")
    check("16c scambio bloccato durante l'ascolto", e.page.is_disabled("#swap"))
    e.page.click("#panel-0 .mic"); e.idle()
    e.close()

    # 17. Testi nella lingua di ciascuno
    e = Env(browser, stt={"text": "ciao come stai"})
    check("17a suggerimento in inglese per chi è in alto", e.txt("#panel-1 .hint") == "Tap the mic and speak", e.txt("#panel-1 .hint"))
    check("17b suggerimento in italiano per chi è in basso", e.txt("#panel-0 .hint") == "Tocca il microfono e parla", e.txt("#panel-0 .hint"))
    e.page.select_option("#panel-1 select", "es")
    check("17c cambia con la lingua scelta", e.txt("#panel-1 .hint") == "Toca el micrófono y habla", e.txt("#panel-1 .hint"))
    check("17d codice lingua aggiornato", e.txt("#panel-1 .code") == "ES", e.txt("#panel-1 .code"))
    e.page.select_option("#panel-1 select", "en")
    e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle()
    check("17e dopo la traduzione: didascalia in inglese, suggerimento nascosto",
          e.page.evaluate("document.querySelector('#panel-1 .cap-text').textContent") == "Translation" and e.page.is_hidden("#panel-1 .hint"),
          (e.page.evaluate("document.querySelector('#panel-1 .cap-text').textContent"), e.page.is_hidden("#panel-1 .hint")))
    check("17f nessun errore JS", not e.errors, e.errors)
    e.page.screenshot(path=str(ROOT / "screenshot.png"))
    e.close()


def run_unique(browser):
    # 18. Unicità: seme del dispositivo, matricola, colore LED, tracciato non ripetibile
    trace_px = "(() => { const c = document.querySelector('#panel-1 .trace'); const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data; let n=0, h=0; for (let k=3;k<d.length;k+=4) if (d[k]>0) { n++; h = (h*31 + k) >>> 0; } return [n, h]; })()"
    a = Env(browser, stt={"text": "ciao come stai"}, deepl=Env.deepl_ok)
    b = Env(browser, stt={"text": "ciao come stai"}, deepl=Env.deepl_ok)
    sa, sb = a.page.evaluate("localStorage.getItem('ft-seed')"), b.page.evaluate("localStorage.getItem('ft-seed')")
    check("18a ogni dispositivo genera il proprio seme", sa and sb and sa != sb, (sa, sb))
    ser = a.page.evaluate("document.getElementById('serial').textContent")
    check("18b matricola nel formato N° XXXX-XXXX", __import__('re').fullmatch(r"N° [0-9A-F]{4}-[0-9A-F]{4}", ser) is not None, ser)
    a.page.reload(); a.page.wait_for_selector("#serial")
    check("18c matricola stabile sullo stesso dispositivo", a.page.evaluate("document.getElementById('serial').textContent") == ser)
    led = a.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--led').trim()")
    check("18d colore LED scelto dal seme", led in ['#a8f26b', '#ffb43d', '#7fe0ff', '#f6efc9', '#ff8a5c', '#c6a6ff'], led)
    a.page.evaluate("window.__stt.text = 'ciao come stai'")
    for env in (a, b):
        env.page.click("#panel-0 .mic"); env.wait_spoken(1); env.idle()
    ta, tb = a.page.evaluate(trace_px), b.page.evaluate(trace_px)
    check("18e il tracciato viene disegnato dopo una frase", ta[0] > 50 and tb[0] > 50, (ta, tb))
    check("18f stessa frase su due dispositivi -> tracciati diversi", ta[1] != tb[1], (ta, tb))
    a.page.wait_for_timeout(20)
    a.page.click("#panel-0 .mic"); a.wait_spoken(2); a.idle()
    ta2 = a.page.evaluate(trace_px)
    check("18g la stessa frase ripetuta aggiunge un segmento nuovo", ta2[0] > ta[0] and ta2[1] != ta[1], (ta, ta2))
    check("18h nessun errore JS", not a.errors and not b.errors, (a.errors, b.errors))
    a.page.screenshot(path=str(ROOT / "screenshot.png"))
    # stato "in onda" per l'anteprima
    c = Env(browser, stt={"text": "dove si trova la stazione dei treni", "hold": True}, deepl=Env.deepl_ok)
    c.page.click("#panel-0 .mic"); c.page.wait_for_selector("#panel-0.on-air")
    check("18i spia in onda ed etichetta STOP durante l'ascolto", c.page.evaluate("document.querySelector('#panel-0 .key-label').textContent") == "STOP")
    c.page.wait_for_timeout(250)
    c.page.screenshot(path=str(ROOT / "screenshot_on_air.png"))
    c.page.click("#panel-0 .mic"); c.idle()
    for env in (a, b, c): env.close()

def run_fit(browser):
    # 19. Frasi lunghe: il testo si adatta allo spazio, chi legge ottiene più spazio
    fit = "(() => { const r = document.querySelector('#panel-1 .received'); return {size: parseFloat(getComputedStyle(r).fontSize), sh: r.scrollHeight, ch: r.clientHeight}; })()"
    heights = "[document.getElementById('panel-0').getBoundingClientRect().height, document.getElementById('panel-1').getBoundingClientRect().height]"
    def deepl_echo(route, text, src, tgt):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"text": text}))
    short = "Buongiorno, come sta?"
    medium = ("Scusi, sa dirmi dove si trova la stazione dei treni più vicina? Devo prendere il treno delle sei per Milano "
              "e non vorrei perderlo perché ho un appuntamento importante domattina.")
    long_ = " ".join([medium] * 3)
    results_fit = {}
    for label, text in [("corta", short), ("media", medium), ("lunga", long_)]:
        e = Env(browser, stt={"text": text}, deepl=deepl_echo)
        e.page.click("#panel-0 .mic"); e.wait_spoken(1); e.idle(); e.page.wait_for_timeout(400)
        results_fit[label] = (e.page.evaluate(fit), e.page.evaluate(heights))
        if label == "media":
            e.page.screenshot(path=str(ROOT / "screenshot_long.png"))
        if label == "lunga":
            # il lettore cambia al turno successivo
            e.page.evaluate("window.__stt.text = 'Thank you very much'")
            e.page.click("#panel-1 .mic"); e.wait_spoken(2); e.idle(); e.page.wait_for_timeout(400)
            results_fit["inverso"] = e.page.evaluate(heights)
            e.page.click("#swap"); e.page.wait_for_timeout(400)
            results_fit["scambio"] = e.page.evaluate(heights)
        check(f"19 nessun errore JS ({label})", not e.errors, e.errors)
        e.close()
    (fs, hs), (fm, hm), (fl, hl) = results_fit["corta"], results_fit["media"], results_fit["lunga"]
    check("19a frase corta: carattere grande (>= 40 px)", fs["size"] >= 40, fs)
    check("19b frase media: entra tutta senza scorrere", fm["sh"] <= fm["ch"] + 1, fm)
    check("19c frase media: carattere ancora grande (>= 22 px)", fm["size"] >= 22, fm)
    check("19d frase lunga: entra tutta senza scorrere", fl["sh"] <= fl["ch"] + 1, fl)
    check("19e frase lunga: carattere leggibile (>= 14 px)", fl["size"] >= 14, fl)
    check("19f il carattere scende con la lunghezza", fs["size"] > fm["size"] > fl["size"], (fs["size"], fm["size"], fl["size"]))
    check("19g chi legge (in alto) ha più spazio", hl[1] > hl[0] * 1.5, hl)
    inv = results_fit["inverso"]
    check("19h al turno dopo lo spazio passa a chi legge in basso", inv[0] > inv[1] * 1.5, inv)
    sw = results_fit["scambio"]
    check("19i lo scambio lingue riporta le metà uguali", abs(sw[0] - sw[1]) < 4, sw)

def main():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k): pass
    handler = functools.partial(Quiet, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("localhost", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            run(browser)
            run_extra(browser)
            run_unique(browser)
            run_fit(browser)
        finally:
            browser.close(); srv.shutdown()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} test superati")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
