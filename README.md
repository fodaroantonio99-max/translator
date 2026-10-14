# Translator

Traduttore faccia a faccia nel browser. Lo schermo è diviso in due metà: ognuno sceglie la propria lingua, tocca il microfono e parla, e l'altra persona legge e sente la traduzione.

## Funzioni

- Riconoscimento vocale con la Web Speech API del browser
- Traduzione con DeepL (tramite Cloudflare Worker), Translator API di Chrome o MyMemory come riserva
- Sintesi vocale con `speechSynthesis`
- 10 lingue: italiano, inglese, spagnolo, francese, tedesco, portoghese, rumeno, russo, cinese, giapponese
- Scrittura da tastiera dove il riconoscimento vocale non è disponibile

## File

- `index.html`, `style.css`, `app.js`: l'app
- `worker_template.js`: Cloudflare Worker che serve l'app e traduce con DeepL
- `build_worker.py`: genera `worker.js` dai file dell'app
- `worker.js`: Worker generato
