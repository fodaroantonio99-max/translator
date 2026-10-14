# Face Translator (web app)

Traduttore faccia a faccia a costo zero. File: `index.html` (struttura), `style.css` (grafica), `app.js` (logica); `worker.js` è generato da questi tre da `build_worker.py` e serve per Cloudflare. Schermo diviso: la metà superiore è capovolta, così le due persone si leggono dai lati opposti del telefono. Ognuna tocca il proprio microfono, parla, e l'altra legge e sente la traduzione.

| Funzione | Tecnologia | Costo |
|---|---|---|
| Ascolto | Web Speech API del browser (Safari / Chrome) | gratis |
| Traduzione | Translator API on-device di Chrome se disponibile, altrimenti MyMemory | gratis, nessuna chiave |
| Voce | `speechSynthesis` del browser | gratis |

## Metterla online gratis (serve HTTPS per il microfono)

Scegli una opzione, tutte gratuite e senza carta di credito:

1. **Netlify Drop**: vai su https://app.netlify.com/drop e trascina la cartella con `index.html`, `style.css` e `app.js` (tutti e tre, nella stessa cartella). Ottieni subito un indirizzo https. Senza account il sito resta online solo per un tempo limitato: con un account gratuito diventa permanente.
2. **GitHub Pages**: crea un repository, carica `index.html`, `style.css` e `app.js`, poi *Settings > Pages > Deploy from branch*.
3. **Cloudflare Pages**: *Workers & Pages > Create > Pages > Upload assets*.

Apri l'indirizzo sul telefono.

## Traduzione con DeepL e link pubblico

Vedi `PUBBLICA_CON_DEEPL.md`: `worker.js` (generato da `index.html`, `style.css` e `app.js` con `python3 build_worker.py`) va incollato in un Worker Cloudflare gratuito con la variabile segreta `DEEPL_KEY`.

## Uso

- **iPhone**: apri l'indirizzo in **Safari** e usalo da lì. Non aggiungerlo alla schermata Home: iOS blocca il riconoscimento vocale nelle web app installate. Attiva *Impostazioni > Generali > Tastiera > Dettatura*.
- **Android**: apri in **Chrome**.
- Imposta la lingua di ciascuno dal menu del proprio lato, tocca il microfono, parla. Si ferma da solo al silenzio, oppure tocca di nuovo. Tocca il testo tradotto per riascoltarlo.
- Le lingue scelte vengono ricordate; lo schermo resta acceso durante l'uso.

## Limiti

- Serve internet: Safari e Chrome inviano l'audio ai server Apple/Google per il riconoscimento, e la traduzione passa da MyMemory (tranne con la Translator API on-device di Chrome).
- MyMemory gratuito: 5.000 caratteri al giorno per indirizzo IP. Scrivi la tua email in `MYMEMORY_EMAIL` in cima allo script per salire a 50.000.
- Dialogo a turni (premi e parla), non traduzione continua.
- Le voci devono essere installate sul telefono (iOS: Impostazioni > Accessibilità > Contenuto letto > Voci).

## Test

- `node test_worker.mjs`: 24 verifiche sul Worker (pagina, DeepL simulato, errori, protezione della chiave).

- `python3 test_e2e.py`: 92 verifiche in Chromium (richiede `pip install playwright` e `playwright install chromium`).
- `xvfb-run -a python3 test_webkit.py`: 50 verifiche nel motore WebKit di Safari (Linux: `sudo apt install webkit2gtk-driver xvfb` e `pip install selenium`).

Microfono, voce e servizio di traduzione sono simulati. Non verificano il riconoscimento vocale, le voci e la traduzione reali su un telefono.
