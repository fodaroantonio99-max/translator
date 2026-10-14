#!/usr/bin/env python3
"""Test end-to-end nel motore WebKit (quello di Safari), tramite WebKitGTK + WebDriver.
Microfono (SpeechRecognition), voce (speechSynthesis) e servizio MyMemory sono simulati
nella pagina; si verificano logica, rendering e gestione dei tocchi in WebKit.

Uso (Linux):  sudo apt install webkit2gtk-driver xvfb && pip install selenium
              xvfb-run -a python3 test_webkit.py
"""
import functools, http.server, json, pathlib, subprocess, sys, threading, time
from selenium import webdriver
from selenium.webdriver.common.options import ArgOptions
from selenium.webdriver.support.ui import WebDriverWait

from test_e2e import STT_MOCK, TTS_MOCK

ROOT = pathlib.Path(__file__).parent
PORT, DRIVER_PORT = 8766, 4455
URL = f"http://localhost:{PORT}/index.html"
MINIBROWSER = "/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/MiniBrowser"

FETCH_MOCK = """
(() => {
  window.__mm = { mode: 'ok', requests: [] };
  const dict = { 'ciao come stai|it|en': 'hello how are you', 'where is the station|en|it': 'dov&#39;è la stazione' };
  const real = window.fetch.bind(window);
  window.fetch = async (url, opts) => {
    if (String(url).endsWith('/api/translate')) {
      window.__dl = window.__dl || { mode: 'absent', requests: [] };
      const b = JSON.parse(opts.body); window.__dl.requests.push([b.source, b.target, b.text]);
      if (window.__dl.mode !== 'ok') return new Response('Not found', {status: 404});
      const out = (b.text.toLowerCase() === 'ciao come stai' && b.source === 'it' && b.target === 'en') ? 'Hello, how are you?' : '<deepl> ' + b.text;
      return new Response(JSON.stringify({text: out}), {status: 200, headers: {'Content-Type': 'application/json'}});
    }
    if (String(url).includes('fonts.g')) throw new TypeError('offline');
    if (!String(url).includes('api.mymemory.translated.net')) return real(url, opts);
    const u = new URL(url), q = u.searchParams.get('q'), pair = u.searchParams.get('langpair');
    window.__mm.requests.push([pair, q]);
    const mode = window.__mm.mode, json = b => new Response(JSON.stringify(b), {status: 200, headers: {'Content-Type': 'application/json'}});
    if (mode === '500') return new Response('boom', {status: 500});
    if (mode === 'abort') throw new TypeError('Failed to fetch');
    if (mode === 'quota') return json({responseData: {translatedText: 'MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY.'}, responseStatus: 200});
    if (mode === 'quota429') return json({responseData: {translatedText: ''}, quotaFinished: true, responseStatus: 429,
        responseDetails: 'MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY.'});
    const key = q.toLowerCase() + '|' + pair.replace('|', '|');
    return json({responseData: {translatedText: dict[q.toLowerCase() + '|' + pair.split('|')[0] + '|' + pair.split('|')[1]] || `[${pair}] ${q}`}, responseStatus: 200});
  };
})();
"""
ERR_CAPTURE = "window.__errs = []; window.addEventListener('error', e => window.__errs.push(e.message)); window.addEventListener('unhandledrejection', e => window.__errs.push(String(e.reason)));"
MOCKS = "<script>" + ERR_CAPTURE + STT_MOCK + TTS_MOCK + FETCH_MOCK + "</script>"
MOCKS_NO_STT = "<script>" + ERR_CAPTURE + TTS_MOCK + FETCH_MOCK + "</script>"

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   -> {detail}"))

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k): pass
    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            mocks = MOCKS_NO_STT if "nostt" in self.path else MOCKS
            html = (ROOT / "index.html").read_text().replace("<head>", "<head>" + mocks, 1).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html))); self.end_headers(); self.wfile.write(html)
        else:
            super().do_GET()

class App:
    def __init__(self, d): self.d = d
    def js(self, code, *a): return self.d.execute_script(code, *a)
    def wait(self, cond, timeout=12):
        WebDriverWait(self.d, timeout, poll_frequency=0.1).until(lambda d: d.execute_script("return !!(" + cond + ")"))
    def open(self, stt=None, mm="ok"):
        self.d.get(URL); self.js("localStorage.clear()"); self.d.get(URL)
        if stt: self.js("Object.assign(window.__stt, arguments[0])", stt)
        self.js("window.__mm.mode = arguments[0]", mm)
    def click(self, sel): self.d.find_element("css selector", sel).click()
    def text(self, sel): return (self.js("return document.querySelector(arguments[0]).textContent", sel) or "").strip()
    def status(self): return self.text("#status")
    def idle(self):
        self.wait("!document.querySelector('#panel-0 .mic').disabled && !document.querySelector('#panel-1 .mic').disabled"
                  " && document.querySelector('#status .spinner')===null")
    def spoken(self): return [s for s in self.js("return window.__tts.spoken") if s["text"].strip()]
    def wait_spoken(self, n, timeout=12): self.wait("window.__tts.spoken.filter(s=>s.text.trim()).length >= %d" % n, timeout)
    def requests(self): return [tuple(r) for r in self.js("return window.__mm.requests")]
    def set_select(self, sel, value):
        self.js("const e=document.querySelector(arguments[0]); e.value=arguments[1]; e.dispatchEvent(new Event('change',{bubbles:true}))", sel, value)

def run(a: App):
    print("UA :", a.js("return navigator.userAgent"))
    a.open(stt={"text": "ciao come stai"})
    print("view:", a.js("return [innerWidth, innerHeight, devicePixelRatio]"))
    check("0 motore WebKit (non Chromium)", "AppleWebKit" in a.js("return navigator.userAgent") and not a.js("return !!window.chrome"))

    # 1. basso (it) -> alto (en): click reale sul pulsante
    a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle()
    check("1a richiesta it|en", a.requests() == [("it|en", "ciao come stai")], a.requests())
    check("1b traduzione nel pannello opposto", a.text("#panel-1 .received") == "hello how are you", a.text("#panel-1 .received"))
    check("1c testo detto nel proprio pannello", a.text("#panel-0 .heard") == "ciao come stai", a.text("#panel-0 .heard"))
    sp = a.spoken()
    check("1d voce en-US (Samantha)", sp and sp[0]["lang"] == "en-US" and sp[0]["voice"] == "Samantha" and sp[0]["text"] == "hello how are you", sp)
    check("1e STT con locale it-IT", a.js("return window.__stt.calls[0].lang") == "it-IT")
    check("1f torna idle senza messaggi", a.status() == "", a.status())
    a.click("#panel-1 .received"); a.wait_spoken(2); a.idle()
    check("6 tocco sul testo = riascolta", len(a.spoken()) == 2, a.spoken())

    # 2. alto (pannello ruotato) -> basso: il click deve centrare il pulsante capovolto
    a.open(stt={"text": "where is the station"})
    a.click("#panel-1 .mic"); a.wait_spoken(1); a.idle()
    check("2a click sul pulsante capovolto funziona", a.requests() == [("en|it", "where is the station")], a.requests())
    check("2b entità HTML decodificate", a.text("#panel-0 .received") == "dov'è la stazione", a.text("#panel-0 .received"))
    check("2c voce it-IT", a.spoken()[0]["lang"] == "it-IT" and a.spoken()[0]["voice"] == "Alice", a.spoken())

    # 3. ascolto in corso: altro microfono e menu bloccati, stop manuale traduce
    a.open(stt={"text": "ciao come stai", "hold": True})
    a.click("#panel-0 .mic"); a.wait("document.querySelector('#panel-0 .mic.listening')")
    check("3a altro microfono disabilitato", a.js("return document.querySelector('#panel-1 .mic').disabled"))
    check("3b menu lingua bloccato", a.js("return document.querySelector('#panel-0 select').disabled"))
    a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle()
    check("3c stop manuale traduce comunque", a.text("#panel-1 .received") == "hello how are you", a.text("#panel-1 .received"))

    # 4/5. errori microfono e silenzio
    for err, frag in [("not-allowed", "Permesso microfono"), ("service-not-allowed", "Dettatura"),
                      ("language-not-supported", "Lingua non supportata"), ("network", "internet")]:
        a.open(stt={"error": err}); a.click("#panel-0 .mic"); a.idle()
        check(f"4 errore {err}", frag in a.status(), a.status())
    a.open(stt={"text": ""}); a.click("#panel-0 .mic"); a.idle()
    check("5 silenzio -> messaggio, nessuna richiesta", "Non ho sentito" in a.status() and not a.requests(), (a.status(), a.requests()))

    # 7. errori di traduzione
    for mode, frag, label in [("500", "Traduzione non riuscita", "HTTP 500"), ("quota", "limite giornaliero", "quota (testo)"),
                              ("quota429", "limite giornaliero", "quota (stato 429)"), ("abort", "nessuna connessione", "rete assente")]:
        a.open(stt={"text": "ciao come stai"}, mm=mode); a.click("#panel-0 .mic"); a.idle()
        check(f"7 {label}", frag in a.status() and not a.spoken(), (a.status(), a.spoken()))
    a.open(stt={"text": "ciao come stai"}, mm="500"); a.click("#panel-0 .mic"); a.idle()
    a.js("window.__mm.mode = 'ok'"); a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle()
    check("7d dopo un errore il secondo tentativo funziona", a.text("#panel-1 .received") == "hello how are you", a.text("#panel-1 .received"))

    # 8. testo lungo
    long_text = " ".join(f"Questa è la frase numero {i} del discorso." for i in range(1, 31))
    a.open(stt={"text": long_text}); a.click("#panel-0 .mic"); a.wait_spoken(30, 25); a.idle()
    reqs = a.requests()
    check("8a testo lungo in più richieste <= 450 caratteri", len(reqs) > 1 and all(len(q) <= 450 for _, q in reqs), [len(q) for _, q in reqs])
    check("8b nessuna parte persa", " ".join(q.strip() for _, q in reqs).replace("  ", " ") == long_text)
    check("8c voce spezzata in frasi", len(a.spoken()) >= 30, len(a.spoken()))

    # 9. stessa lingua
    a.open(stt={"text": "ciao come stai"}); a.set_select("#panel-1 select", "it")
    a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle()
    check("9 stessa lingua -> niente richieste di rete", not a.requests() and a.text("#panel-1 .received") == "ciao come stai", (a.requests(), a.text("#panel-1 .received")))

    # 11. persistenza (localStorage di WebKit)
    a.open(); a.set_select("#panel-1 select", "es"); a.set_select("#panel-0 select", "de"); a.d.get(URL)
    check("11 lingue salvate dopo il ricaricamento", a.js("return [document.querySelector('#panel-1 select').value, document.querySelector('#panel-0 select').value]") == ["es", "de"],
          a.js("return [document.querySelector('#panel-1 select').value, document.querySelector('#panel-0 select').value]"))

    # 12. layout nel motore WebKit
    a.open(stt={"text": "ciao come stai"})
    tr = a.js("return getComputedStyle(document.getElementById('panel-1')).transform")
    top = a.js("const r=document.getElementById('panel-1').getBoundingClientRect(); return [r.top, r.height]")
    bot = a.js("const r=document.getElementById('panel-0').getBoundingClientRect(); return [r.top, r.height]")
    check("12a pannello superiore ruotato di 180°", tr.startswith("matrix(-1,") and tr.rstrip(")").endswith("-1, 0, 0"), tr)
    check("12b superiore sopra, inferiore sotto, altezze uguali", top[0] < bot[0] and abs(top[1] - bot[1]) < 4, (top, bot))
    check("12c nessuno scroll della pagina", a.js("return document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight"))
    check("12d #app occupa tutta l'altezza (100dvh supportato)", abs(a.js("return document.getElementById('app').getBoundingClientRect().height") - a.js("return innerHeight")) < 2)
    check("12e testo ruotato resta dentro lo schermo", a.js("""const r=document.querySelector('#panel-1 .mic').getBoundingClientRect();
        return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth"""))
    contrast = a.js("""
      const lum = c => { const m = c.match(/[\\d.]+/g).map(Number).slice(0,3).map(v => { v/=255; return v<=.03928 ? v/12.92 : Math.pow((v+.055)/1.055,2.4); }); return .2126*m[0]+.7152*m[1]+.0722*m[2]; };
      return [...document.querySelectorAll('select')].map(e => { const cs = getComputedStyle(e); const a = lum(cs.color), b = lum(cs.backgroundColor);
        return (Math.max(a,b)+.05)/(Math.min(a,b)+.05); });""")
    check("12f testo dei menu lingua leggibile (contrasto >= 4.5)", contrast and all(c >= 4.5 for c in contrast), contrast)
    a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle(); time.sleep(0.5)
    a.d.save_screenshot(str(ROOT / "screenshot_webkit.png"))

    # 13. Browser senza riconoscimento vocale (Chrome su iPhone usa WebKit così): dettatura da tastiera
    from selenium.webdriver.common.keys import Keys
    for side, other, text, expected in [(0, 1, "ciao come stai", "hello how are you"), (1, 0, "where is the station", "dov'è la stazione")]:
        a.d.get(URL + "?nostt"); a.js("localStorage.clear()"); a.d.get(URL + "?nostt")
        check(f"13a[{side}] nessun SpeechRecognition, suggerimento tastiera",
              "tastiera" in a.status() and a.js("return typeof webkitSpeechRecognition === 'undefined'"), a.status())
        a.click(f"#panel-{side} .mic")
        check(f"13b[{side}] il microfono apre il campo e lo mette a fuoco",
              a.js(f"const f=document.querySelector('#panel-{side} .typed'); return !f.hidden && document.activeElement === f.querySelector('input')"))
        inp = a.d.find_element("css selector", f"#panel-{side} .typed input")
        inp.send_keys(text); inp.send_keys(Keys.ENTER)
        a.wait_spoken(1); a.idle()
        check(f"13c[{side}] dettato -> tradotto e letto", a.text(f"#panel-{other} .received") == expected and len(a.spoken()) == 1,
              (a.text(f"#panel-{other} .received"), a.spoken()))
        check(f"13d[{side}] campo richiuso, nessun errore JS",
              a.js(f"return document.querySelector('#panel-{side} .typed').hidden") and a.js("return window.__errs.length") == 0, a.js("return window.__errs"))

    # 15. DeepL tramite il Worker
    a.open(stt={"text": "ciao come stai"}); a.js("window.__dl = { mode: 'ok', requests: [] }")
    a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle()
    check("15a DeepL usato, nessuna riserva", a.js("return window.__dl.requests") == [["it", "en", "ciao come stai"]] and not a.requests(), (a.js("return window.__dl.requests"), a.requests()))
    check("15b traduzione DeepL mostrata e letta", a.text("#panel-1 .received") == "Hello, how are you?" and a.spoken()[0]["text"] == "Hello, how are you?")
    check("15c etichetta DeepL", a.js("return document.querySelector('#panel-1 .engine').textContent") == "· DeepL")

    # 17. frase lunga in WebKit: entra senza scorrere, chi legge ha più spazio
    medium = ("Scusi, sa dirmi dove si trova la stazione dei treni più vicina? Devo prendere il treno delle sei per Milano "
              "e non vorrei perderlo perché ho un appuntamento importante domattina.")
    a.open(stt={"text": medium}); a.js("window.__dl = { mode: 'ok', requests: [] }")
    a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle(); time.sleep(0.5)
    fit = a.js("const r=document.querySelector('#panel-1 .received'); return [parseFloat(getComputedStyle(r).fontSize), r.scrollHeight, r.clientHeight]")
    hts = a.js("return [document.getElementById('panel-0').getBoundingClientRect().height, document.getElementById('panel-1').getBoundingClientRect().height]")
    check("17a frase lunga entra senza scorrere (WebKit)", fit[1] <= fit[2] + 1 and fit[0] >= 18, fit)
    check("17b chi legge ha più spazio (WebKit)", hts[1] > hts[0] * 1.5, hts)
    a.d.save_screenshot(str(ROOT / "screenshot_webkit_long.png"))

    # 16. scambio lingue
    a.open(); a.click("#swap")
    check("16 scambio lingue", a.js("return [document.querySelector('#panel-0 select').value, document.querySelector('#panel-1 select').value]") == ["en", "it"])

    # 14. nessun errore JavaScript durante un intero flusso normale
    a.open(stt={"text": "ciao come stai"}); a.click("#panel-0 .mic"); a.wait_spoken(1); a.idle()
    check("14 nessun errore JS nel flusso normale", a.js("return window.__errs.length") == 0, a.js("return window.__errs"))

def main():
    class Quiet(Handler): pass
    srv = http.server.ThreadingHTTPServer(("localhost", PORT), functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    drv = subprocess.Popen(["/usr/bin/WebKitWebDriver", f"--port={DRIVER_PORT}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    o = ArgOptions()
    o.set_capability("browserName", "MiniBrowser")
    o.set_capability("webkitgtk:browserOptions", {"binary": MINIBROWSER, "args": ["--automation"]})
    d = webdriver.Remote(command_executor=f"http://localhost:{DRIVER_PORT}", options=o)
    try:
        try: d.set_window_rect(width=390, height=844)
        except Exception as e: print("window rect non impostabile:", e)
        run(App(d))
    finally:
        d.quit(); drv.terminate(); srv.shutdown()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} test superati in WebKit")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
