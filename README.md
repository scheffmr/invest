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

1. **DNS bei all-inkl:** A-Record und AAAA-Record für `invest.scheffel.rocks` auf die IPv4 bzw. IPv6 des Servers. Kein Redirect, sondern echte DNS-Einträge.
2. **Firewall:**
   ```
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw allow 443/udp
   ```
3. **Docker installieren** (falls noch nicht vorhanden):
   ```
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER   # danach neu einloggen
   ```
4. **Repo klonen und starten:**
   ```
   git clone https://github.com/scheffmr/invest.git
   cd invest
   cp .env.example .env
   docker compose up -d --build
   ```
   Caddy holt das Zertifikat automatisch. Prüfen mit `docker compose logs -f caddy`.
5. **Account anlegen:**
   ```
   docker compose exec app python -m app.admin create-user marco
   ```
   Der ausgegebene Link ist 15 Minuten gültig. Öffne ihn auf dem Gerät, das den Passkey bekommen soll.

> Hinweis: Docker veröffentlicht Ports an ufw vorbei. Hier ist das gewollt, weil nur 80 und 443 (Caddy) veröffentlicht werden. Die App selbst ist nur intern erreichbar.

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
