import os

DOMAIN = os.environ.get("DOMAIN", "localhost")
DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "invest.db")

# Nur für lokale Entwicklung: erlaubt http://localhost ohne TLS.
DEV = os.environ.get("DEV", "0") == "1"

RP_ID = DOMAIN
RP_NAME = "Depotplaner"
if DEV:
    ORIGIN = os.environ.get("ORIGIN", "http://localhost:8000")
else:
    ORIGIN = f"https://{DOMAIN}"

SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))
INVITE_MINUTES = int(os.environ.get("INVITE_MINUTES", "15"))
QUOTE_CACHE_HOURS = int(os.environ.get("QUOTE_CACHE_HOURS", "24"))
