# Depotplaner

Selbst gehostetes Tool zur Planung von Sparplänen (ETF, Fonds, Aktien, Krypto) mit Prognose in drei Szenarien, Steuer, Inflation und Chart. Login ausschließlich per Passkey, Accounts nur per SSH.

## Funktionen

- Posten mit ISIN (Krypto per Symbol), Stückzahl × Online-Kurs oder manuellem Wert, Einstandswert
- Sparrate täglich, wöchentlich oder monatlich, wahlweise nur an Xetra-Handelstagen (Ausführung rückt auf den nächsten Handelstag) oder jeden Tag
- Erwartete Rendite: historische Rendite (bis 10 Jahre p. a.) von Yahoo Finance oder manueller Wert
- Gebühr je Ausführung, TER, Steuerart mit Teilfreistellung
- Global: Horizont, Best und Worst Case als Prozentpunkte, Inflation, Sparerpauschbetrag, Kirchensteuer
- Chart: Erwartet, Best, Worst, Spread als Fläche, eingezahltes Kapital, nominal oder real

### Vereinfachungen

- Steuer wird einmalig am Ende auf den Gesamtgewinn berechnet (Verkauf am Horizontende). Keine Vorabpauschale.
- Krypto gilt als steuerfrei (Haltedauer über 1 Jahr angenommen).
- Verluste werden mit Gewinnen anderer Posten verrechnet (keine getrennten Verlusttöpfe).

## Deployment auf dem Server

Auf dem Server läuft ein zentraler Caddy (`~/proxy`) für alle Subdomains. Jedes Tool ist ein eigenes Docker-Projekt im gemeinsamen Netz `web` und veröffentlicht selbst keine Ports.

```
~/proxy/              zentraler Caddy, Ports 80 und 443
  Caddyfile
  sites/invest.caddy  eine Datei pro Subdomain
~/invest/             dieses Repo
~/<weiteres-tool>/
```

### Ersteinrichtung

1. **DNS bei all-inkl:** A- und AAAA-Record für `invest.scheffel.rocks` auf den Server.
2. **Hetzner Firewall:** eingehend TCP 80, TCP 443, UDP 443 (IPv4 und IPv6).
3. **Docker:** `curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER`, danach neu einloggen.
4. **Netz und Proxy:**
   ```
   docker network create web
   git clone https://github.com/scheffmr/invest.git ~/invest
   cp -r ~/invest/deploy/proxy ~/proxy
   cd ~/proxy && docker compose up -d
   ```
5. **Depotplaner:**
   ```
   cd ~/invest
   cp .env.example .env
   docker compose up -d --build
   docker compose exec app python -m app.admin create-user marco
   ```

### Weiteres Tool hinzufügen

1. DNS-Einträge für die neue Subdomain anlegen.
2. Im `docker-compose.yml` des Tools keine Ports veröffentlichen, sondern das Netz `web` mit einem eindeutigen Alias nutzen:
   ```yaml
   services:
     app:
       networks:
         web:
           aliases: [meintool]
   networks:
     web:
       external: true
   ```
3. `~/proxy/sites/meintool.caddy` anlegen:
   ```
   meintool.scheffel.rocks {
   	reverse_proxy meintool:8000
   }
   ```
4. Caddy neu laden: `cd ~/proxy && docker compose exec -w /etc/caddy caddy caddy reload`

### Umstieg von der alten Variante (Caddy im Invest-Projekt)

```
cd ~/invest && docker compose down
git pull
docker network create web
cp -r ~/invest/deploy/proxy ~/proxy
cd ~/proxy && docker compose up -d
cd ~/invest && docker compose up -d --build
```
Die Depotdaten bleiben erhalten, das Zertifikat wird neu ausgestellt.

## Verwaltung per SSH

```
docker compose exec app python -m app.admin list                  # Benutzer und Passkeys
docker compose exec app python -m app.admin add-passkey marco     # Link für weiteres Gerät
docker compose exec app python -m app.admin remove-passkey <id>   # Passkey entfernen
docker compose exec app python -m app.admin delete-user marco     # Benutzer samt Daten löschen
```

## Update

```
cd invest && git pull && docker compose up -d --build
```

## Backup

Die Datenbank liegt im Volume `invest_app_data` (`/data/invest.db` im Container):

```
docker compose exec app python -c "import sqlite3; s=sqlite3.connect('/data/invest.db'); s.backup(sqlite3.connect('/data/backup.db'))"
docker compose cp app:/data/backup.db ./invest-backup-$(date +%F).db
```

## Lokale Entwicklung

```
pip install -r requirements.txt pytest
DEV=1 DOMAIN=localhost DATA_DIR=./data uvicorn app.main:app --reload
DEV=1 DOMAIN=localhost DATA_DIR=./data python -m app.admin create-user test
python -m pytest
```

Passkeys funktionieren lokal unter `http://localhost:8000`.
