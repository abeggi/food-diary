# Food Diary

Web app personale per tracciare i pasti giornalieri, ottimizzata per uso desktop e mobile.

- **Backend**: FastAPI + SQLite
- **Frontend**: HTML/CSS/JS (single page, dark theme, premium aesthetics)
- **Runtime**: `uvicorn` gestito con `systemd`
- **Porta di default**: `8080`

## Funzionalità

- **Registrazione Pasti**: Inserimento voce con data/ora, categoria, cibo e quantità.
- **AI Food Scanner 📷**: Riconoscimento automatico del cibo, della quantità e della categoria tramite foto (webcam o caricamento file). Integrato con Google Gemini Vision.
- **Categorie Quick-Select**: Colazione, Pranzo, Snack, Cena, Dopocena tramite chips interattive.
- **Navigazione Intelligente**: Selezione del giorno tramite menu a discesa compatto (ottimo per gestire molti mesi di dati).
- **Modifica e Sicurezza**: Modifica inline delle voci e conferma prima dell'eliminazione per evitare errori.
- **PWA & Mobile Ready**: Supporto completo per l'installazione su smartphone (Apple Touch Icon e Web Manifest), icona personalizzata nella home.
- **Autocomplete**: Suggerimenti intelligenti basati sullo storico sia per i **cibi** che per le **quantità** (note), con ricerca substring.
- **Area Impostazioni**: Pagina dedicata per l'esportazione dati e la manutenzione avanzata del diario:
  - **Ricerca Ottimizzata**: Database filtrabile al volo, con caricamento dei risultati solo su ricerca per prestazioni ottimali.
  - **Gestione Storico**: Modifica o eliminazione di qualunque voce direttamente in tabella.
  - **Catalogo Suggerimenti**: Gestione granulare dei nomi cibo proposti dall'autocomplete (ricerca ed eliminazione di voci errate).
  - **Export CSV (Excel Ready)**: Ottimizzato per Excel IT (delimitatore `;`, encoding UTF-8 con BOM, campi data e ora separati).
  - **Export JSON**: Dump completo dei dati in formato standard per backup o migrazioni.

## Architettura

```
food-diary/
├── main.py              # API FastAPI, logica DB, migrazioni, export, AI
├── requirements.txt     # dipendenze Python (FastAPI, uvicorn, httpx, python-dotenv)
├── .env                 # configurazione API Key (Gemini)
├── static/
│   ├── index.html       # frontend client (app principale)
│   └── settings.html    # pagina impostazioni (gestione database ed export)
├── install.sh           # installer automatico per host Linux
├── food-diary.service   # unit file per systemd
├── food-diary-ctl       # script di gestione (start/stop/logs)
└── data/                # cartella database (auto-generata)
    └── food_diary.db
```

`main.py` gestisce automaticamente l'inizializzazione del database e le migrazioni (es. aggiunta colonne come `cat`) all'avvio.

## Installazione Rapida

Vedere il file `install.sh` per i dettagli o eseguire:
```bash
sudo bash install.sh
```
L'installer configurerà il virtualenv in `/opt/food-diary/venv` e avvierà il servizio systemd.

## Gestione Servizio

Utilizzare l'helper incluso:
```bash
sudo /opt/food-diary/food-diary-ctl restart  # Riavvio
/opt/food-diary/food-diary-ctl status         # Stato
/opt/food-diary/food-diary-ctl logs           # Visualizza log
```

## Configurazione AI

L'applicazione utilizza **Google Gemini Vision** per il riconoscimento dei pasti. Per attivarla:

1. Crea o modifica il file `/opt/food-diary/.env`.
2. Inserisci la tua API Key di Google AI:
   ```env
   GEMINI_API_KEY=tua_chiave_qui
   GEMINI_MODEL=gemini-flash-latest
   ```
3. Riavvia il servizio: `sudo /opt/food-diary/food-diary-ctl restart`.

L'app invierà le foto tramite protocollo HTTPS sicuro. In caso di errori di connessione, verranno visualizzati dei toast di notifica nel frontend.

## API (Nuovi Endpoint)

### `POST /api/analyze-food-image`
Accetta un file immagine (multipart/form-data) e restituisce un JSON con l'identificazione AI:
```json
{
  "food": "Pasta al pomodoro",
  "quantity": "1 piatto fondo",
  "cat": "pranzo"
}
```

## Database (SQLite)
Tabelle principali:
- `entries`: contiene le voci del diario (`ts`, `food`, `cat`, `notes`, `created`).
- `foods`: catalogo unico cibi per l'autocomplete.

## Backup
Il database si trova in `/opt/food-diary/data/food_diary.db`. 
È sufficiente copiare questo file per un backup completo.

