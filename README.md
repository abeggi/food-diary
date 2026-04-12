# Food Diary

Web app multi-utente per tracciare i pasti giornalieri, ottimizzata per uso desktop e mobile.

- **Backend**: FastAPI + SQLite
- **Autenticazione**: Firebase Authentication (Google Login)
- **Frontend**: HTML/CSS/JS (single page, dark theme, premium aesthetics)
- **Runtime**: `uvicorn` (systemd o Docker)
- **Porta di default**: `8080`
- **Docker Image**: `abeggi/food-diary:latest`

## Funzionalità

- **Multi-Utente**: Accesso sicuro tramite Google. Ogni utente gestisce il proprio diario privato e i propri suggerimenti personalizzati.
- **Login Wall**: Accesso ai contenuti dell'app limitato solo agli utenti registrati.
- **Registrazione Pasti**: Inserimento voce con data/ora, categoria, cibo e quantità.
- **AI Food Scanner 📷**: Riconoscimento automatico del cibo tramite Google Gemini Vision.
- **Autocomplete Personale**: Suggerimenti intelligenti basati sullo storico privato dell'utente.
- **Area Impostazioni**: 
  - Esportazione dati (CSV/JSON) filtrata per utente.
  - Ricerca ed editing globale del proprio database.
- **Gestione Amministratore**: Sezione speciale per l'amministratore per elencare ed eliminare utenti (e i relativi dati) dal sistema.
- **PWA & Mobile Ready**: Installabile su smartphone con icona personalizzata.

## Installazione e Configurazione

L'app richiede ora la configurazione di Firebase per il sistema di autenticazione.

### 1. Configurazione Firebase (Backend)
1. Crea un progetto su [Firebase Console](https://console.firebase.google.com/).
2. Vai in **Project Settings** > **Service Accounts** e genera una nuova chiave privata JSON.
3. Incolla il contenuto del JSON nel file `.env`:
   ```env
   FIREBASE_SERVICE_ACCOUNT_JSON={"type": "service_account", ...}
   ADMIN_EMAIL=tua_email@gmail.com
   ```

### 2. Configurazione Firebase (Frontend)
1. In Firebase Console, aggiungi un'app Web al progetto.
2. Copia le credenziali nel file `static/firebase-config.js` (partendo da `static/firebase-config.js.example`):
   ```javascript
   const firebaseConfig = {
     apiKey: "...",
     authDomain: "...",
     // ...
   };
   ```

### 3. Configurazione AI (Gemini)
Inserisci la tua API Key di Google AI nel file `.env`:
```env
GEMINI_API_KEY=tua_chiave_qui
```

## Architettura

```
food-diary/
├── main.py              # API FastAPI, logica DB, Autenticazione Firebase
├── requirements.txt     # dipendenze (FastAPI, firebase-admin, uvicorn, etc.)
├── .env                 # Secret keys (Gemini, Firebase Service Account)
├── static/
│   ├── index.html       # App principale
│   ├── settings.html    # Gestione dati e Admin
│   └── firebase-config.js # Configurazione client Firebase (Ignorato da Git)
├── data/                # Database SQLite (user-aware)
└── migrate_user.py      # Script per migrare dati locali a un account Google
```

## Gestione Amministratore

L'utente specificato in `ADMIN_EMAIL` nel file `.env` avrà accesso alla sezione **Gestione Utenti** nelle impostazioni. Da qui è possibile:
- Visualizzare tutti gli utenti registrati.
- Eliminare un utente e **tutti i suoi dati** permanentemente dal database.

## Sicurezza e Privacy

Tutti i dati sensibili (`.env`, `firebase-config.js`, `food_diary.db`) sono inseriti nel `.gitignore` per evitare fughe di dati su repository pubblici. 

Per lo sviluppo, è disponibile un file `static/firebase-config.js.example` come template.
