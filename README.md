# PortWatch VI → Discord-Bot

Postet automatisch in deinen Discord-Kanal, wenn sich auf portwatch-vi.xyz etwas tut.

## 1. Webhook in Discord anlegen (1 Minute)
1. Kanal-Einstellungen (Zahnrad am Kanal) → **Integrationen** → **Webhooks** → **Neuer Webhook**
2. Name z. B. „PortWatch VI“ → **Webhook-URL kopieren**

## 2. Python
Python 3.8 oder neuer reicht, zusätzliche Pakete brauchst du nicht.
Windows: https://www.python.org/downloads/ (bei der Installation „Add to PATH“ anhaken).

## 3. Starten
**Windows (PowerShell):**
```powershell
$env:DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/DEINE/URL"
python portwatch_bot.py --test   # Testnachricht
python portwatch_bot.py          # läuft dauerhaft, prüft jede Minute
```
**macOS / Linux:**
```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/DEINE/URL"
python3 portwatch_bot.py --test
python3 portwatch_bot.py
```

Beim ersten Lauf merkt sich der Bot den aktuellen Stand und schickt eine Startnachricht.
Ab da wird nur noch gemeldet, was **neu** ist (Datei `portwatch_state.json`).

## Optionen (Umgebungsvariablen)
| Variable | Standard | Bedeutung |
|---|---|---|
| `PORTWATCH_FOCUS` | `belobug` | Projekte, bei denen du gepingt wirst (kommagetrennt, z. B. `belobug,zettrox`) |
| `PORTWATCH_PING` | leer | Ping für Fokus-Projekte, z. B. `<@DEINE_USER_ID>` oder `@here` |
| `PORTWATCH_INTERVAL_MIN` | `1` | Prüfintervall in Minuten. Ungeänderter Feed wird nicht neu geladen (ETag), daher sehr sparsam. Die Seite selbst aktualisiert ca. alle 3 h. |

Deine User-ID: Discord → Einstellungen → Erweitert → Entwicklermodus an → Rechtsklick auf dich → „ID kopieren“.

## Was gemeldet wird
- 📰 neue News-Artikel
- 🆕 neue Projekte im Tracker
- 🏁 Meilensteine: Lädt → Bootet → Menü → Welt → Spielbar
- 📈 Story, Grafik, FPS-Stufe, Stabilität
- 🔍 Verifizierung durch PortWatch, 🏎️ Aufstieg ins Race
- 🎬 neue Beweis-Videos, ⭐ Sterne-Meilensteine
- 💥 Takedowns / gelöschte oder archivierte Repos
- 🚨 Statusänderung beim „Executable drop“

## Ohne laufenden PC
Mit `--once` prüft der Bot einmal und beendet sich – ideal für die Windows-Aufgabenplanung,
cron oder einen kleinen Server/Raspberry Pi.
