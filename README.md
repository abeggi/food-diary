# Food Diary

Web app personale per tracciare i pasti giornalieri, ottimizzata per uso desktop e mobile.

- **Backend**: FastAPI + SQLite
- **Frontend**: HTML/CSS/JS (single page, dark theme, premium aesthetics)
- **Runtime**: `uvicorn` gestito con `systemd`
- **Porta di default**: `8080`

## Funzionalità

- **Registrazione Pasti**: Inserimento voce con data/ora, categoria, cibo e quantità.
- **Categorie Quick-Select**: Colazione, Pranzo, Snack, Cena, Dopocena tramite chips interattive.
- **Navigazione Intelligente**: Selezione del giorno tramite menu a discesa compatto (ottimo per gestire molti mesi di dati).
- **Modifica e Sicurezza**: Modifica inline delle voci e conferma prima dell'eliminazione per evitare errori.
- **PWA & Mobile Ready**: Supporto completo per l'installazione su smartphone (Apple Touch Icon e Web Manifest), icona personalizzata nella home.
- **Autocomplete**: Suggerimenti cibi basati sullo storico con ricerca substring.
- **Export Avanzato**: 
  - **CSV (Excel Ready)**: Ottimizzato per Excel IT (delimitatore `;`, encoding UTF-8 con BOM per le accentate, campi data e ora separati).
  - **JSON**: Dump completo dei dati in formato standard.

## Architettura

```
food-diary/
├── main.py              # API FastAPI, logica DB, migrazioni, export
├── requirements.txt     # dipendenze Python (FastAPI, uvicorn, pydantic, etc.)
├── static/
│   └── index.html       # frontend SPA (markup, stile, logica client)
├── install.sh           # installer automatico per host Linux
├── food-diary.service   # unit file per systemd
└── food-diary-ctl       # script di gestione (start/stop/logs)
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

## API

### `GET /api/entries`
Lista passi con filtri opzionali.
- Query params: `date`, `limit` (max 1000).

### `POST /api/entries`
Nuovo inserimento. JSON Body:
```json
{
  "ts": "2026-04-04T12:30",
  "food": "Pasta al pesto",
  "cat": "pranzo",
  "notes": "100gr"
}
```

### `PUT /api/entries/{id}`
Aggiornamento parziale della voce.

### `DELETE /api/entries/{id}`
Rimozione definitiva.

## Database (SQLite)
Tabelle principali:
- `entries`: contiene le voci del diario (`ts`, `food`, `cat`, `notes`, `created`).
- `foods`: catalogo unico cibi per l'autocomplete.

## Backup
Il database si trova in `/opt/food-diary/data/food_diary.db`. 
È sufficiente copiare questo file per un backup completo.
