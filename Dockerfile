FROM python:3.11-slim

# Imposta la directory di lavoro
WORKDIR /app

# Installa le dipendenze di sistema necessarie (opzionale, ma utile per sqlite/network)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copia il file dei requisiti e installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto dell'applicazione
COPY . .

# Crea la directory per il database e imposta i permessi
RUN mkdir -p /app/data && chmod 777 /app/data

# Espone la porta su cui gira l'app
EXPOSE 8080

# Variabili d'ambiente di default
ENV FOOD_DIARY_DB=/app/data/food_diary.db
ENV PYTHONUNBUFFERED=1

# Comando per avviare l'applicazione
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
