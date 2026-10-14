# Pubblicare Face Translator con DeepL (gratis, link pubblico senza login)

Un solo file, `worker.js` (contiene già `index.html`, `style.css` e `app.js`), fa tutto: pubblica la pagina e traduce con DeepL tenendo la tua chiave segreta. Lo ospita Cloudflare Workers, gratis fino a 100.000 richieste al giorno. Chi riceve il link apre l'app e basta: niente account, niente password.

Ti servono due account gratuiti: DeepL (per la traduzione) e Cloudflare (per l'hosting). Una volta sola, circa 10 minuti.

## 1. Chiave DeepL (gratuita, 500.000 caratteri al mese)

1. Vai su https://www.deepl.com/pro-api e scegli il piano **DeepL API Free**.
2. Crea l'account. DeepL può chiedere una carta solo per verificare l'identità: il piano Free non addebita nulla.
3. Nel tuo account apri **API Keys** e copia la chiave. Quella gratuita finisce con `:fx`.

## 2. Worker su Cloudflare

1. Crea un account gratuito su https://dash.cloudflare.com/sign-up.
2. Nel menu apri **Workers & Pages** > **Create** > crea un Worker partendo da **Hello World**.
3. Dagli un nome, per esempio `face-translator`, e premi **Deploy**.
4. Premi **Edit code**, cancella tutto il codice di esempio, incolla l'intero contenuto di `worker.js` e premi **Deploy**.
5. Torna al Worker > **Settings** > **Variables and Secrets** > **Add**:
   - tipo: **Secret**
   - nome: `DEEPL_KEY`
   - valore: la chiave DeepL copiata prima
   
   e salva con **Deploy**.

## 3. Usala e condividila

L'indirizzo del Worker è del tipo `https://face-translator.TUONOME.workers.dev` (lo vedi nella pagina del Worker). Aprilo sul telefono e manda lo stesso link a chi vuoi: funziona subito per chiunque.

Quando la traduzione arriva da DeepL, accanto alla didascalia compare **· DeepL**. Se manca, la chiave non è impostata o è sbagliata e l'app sta usando il traduttore di riserva (MyMemory).

## Da sapere

- Le traduzioni di tutti quelli che usano il tuo link consumano i tuoi 500.000 caratteri mensili (una conversazione media ne usa poche migliaia). A fine quota l'app passa da sola al traduttore di riserva fino al mese successivo.
- La chiave non arriva mai al telefono di nessuno: resta nel Worker. Il Worker accetta solo richieste dalla propria pagina, non da altri siti.
- Per aggiornare l'app in futuro: incolla il nuovo `worker.js` (rigenerato con `python3 build_worker.py` se hai modificato uno dei tre file) in **Edit code** e premi **Deploy**. La chiave resta.
- Il vecchio link Netlify chiedeva il login perché Netlify protegge con password i siti caricati con Drop senza account, finché non vengono rivendicati. Con il Worker il problema non c'è più.

## Su iPhone

- In **Safari** il microfono dell'app ascolta direttamente.
- In **Chrome** il microfono dell'app apre un campo: tocca il 🎤 della tastiera, parla e invia (Apple non permette a Chrome il riconoscimento vocale diretto).
- Attiva la dettatura: *Impostazioni > Generali > Tastiera > Abilita Dettatura*.
