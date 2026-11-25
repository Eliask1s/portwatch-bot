#!/usr/bin/env python3
"""
PortWatch VI -> Discord Notifier
================================
Beobachtet https://portwatch-vi.xyz/data/tracker.json und postet Neuigkeiten
per Discord-Webhook in deinen Kanal:

  * neue News-Artikel
  * neue Projekte (Efforts) im Tracker
  * Meilensteine (Lädt / Bootet / Menü / Welt / Spielbar)
  * Fortschritt bei Story, Grafik, FPS, Stabilität
  * Verifizierung (self-reported -> von PortWatch bestätigt)
  * Wechsel von Watchlist ins Race, Takedowns, neue Beweis-Videos
  * Sterne-Meilensteine auf GitHub
  * Status-Änderungen beim "Executable drop"

Nur Python 3.8+ Standardbibliothek – nichts zu installieren.

Start:
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    python3 portwatch_bot.py            # läuft dauerhaft, prüft jede Minute
    python3 portwatch_bot.py --once     # einmal prüfen und beenden (für cron)
    python3 portwatch_bot.py --test     # Testnachricht an Discord senden
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Einstellungen (alles auch per Umgebungsvariable änderbar)
# ---------------------------------------------------------------------------
FEED_URL = os.environ.get("PORTWATCH_FEED", "https://portwatch-vi.xyz/data/tracker.json")
SITE_URL = "https://portwatch-vi.xyz"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = Path(os.environ.get("PORTWATCH_STATE", Path(__file__).with_name("portwatch_state.json")))
INTERVAL_MIN = int(os.environ.get("PORTWATCH_INTERVAL_MIN", "1"))

# Projekte, bei denen du extra gepingt werden willst (IDs aus dem Tracker, z.B. "belobug")
FOCUS = [s.strip().lower() for s in os.environ.get("PORTWATCH_FOCUS", "belobug").split(",") if s.strip()]
# Was beim Fokus-Projekt vorangestellt wird: "@here", "<@DEINE_USER_ID>" oder "<@&ROLLEN_ID>" – leer = kein Ping
FOCUS_PING = os.environ.get("PORTWATCH_PING", "")

STAR_MILESTONES = [100, 250, 500, 1000, 2000, 3000, 5000, 10000, 25000, 50000]
USER_AGENT = "PortWatchDiscordNotifier/1.0 (+personal use)"

# Farben für die Embeds
GREEN, BLUE, ORANGE, RED, PURPLE, GREY = 0x2ECC71, 0x3498DB, 0xE67E22, 0xE74C3C, 0x9B59B6, 0x95A5A6

LADDER = [  # (Feld, Anzeigename) – Reihenfolge wie auf der Seite
    ("loads", "Lädt"),
    ("boots", "Bootet"),
    ("menu", "Menü"),
    ("world", "Welt"),
    ("playable", "Spielbar"),
]
TRACKS = [
    ("story", "Story-Fortschritt", "pct"),
    ("render", "Grafik-Korrektheit", "pct"),
    ("fps", "Performance (FPS-Stufe)", "raw"),
    ("stability", "Stabilität", "pct"),
]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def log(msg):
    if sys.stdout.isatty():
        print("\r" + " " * 70 + "\r", end="")
    print(time.strftime("[%Y-%m-%d %H:%M:%S]"), msg, flush=True)


_cache = {"etag": None, "modified": None}


def fetch_feed():
    """Lädt den Feed. Gibt None zurück, wenn er sich seit dem letzten Abruf nicht geändert hat."""
    if FEED_URL.startswith(("http://", "https://")):
        headers = {"User-Agent": USER_AGENT}
        if _cache["etag"]:
            headers["If-None-Match"] = _cache["etag"]
        if _cache["modified"]:
            headers["If-Modified-Since"] = _cache["modified"]
        req = urllib.request.Request(FEED_URL, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                _cache["etag"] = r.headers.get("ETag")
                _cache["modified"] = r.headers.get("Last-Modified")
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 304:  # unverändert – kaum Datenverkehr
                return None
            raise
    return json.loads(Path(FEED_URL).read_text(encoding="utf-8"))  # lokale Datei (zum Testen)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("Statusdatei beschädigt – starte neu.")
    return None


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_FILE)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fmt(v, kind):
    v = num(v)
    if kind == "pct":
        return f"{round(v * 100)} %"
    return f"{v:g}"


def step_label(v):
    v = num(v)
    if v >= 1:
        return "✅ erreicht"
    if v > 0:
        return "🟡 teilweise"
    return "⬜ offen"


def clip(text, n):
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def effort_url(e):
    return f"{SITE_URL}/#effort-{e.get('id', '')}"


def ladder_line(gta):
    parts = []
    for key, label in LADDER:
        v = num(gta.get(key))
        icon = "✅" if v >= 1 else ("🟡" if v > 0 else "⬜")
        parts.append(f"{icon} {label}")
    return " · ".join(parts)


def snapshot(feed):
    """Reduziert den Feed auf das, was wir vergleichen."""
    efforts = {}
    for e in feed.get("efforts") or []:
        eid = e.get("id")
        if not eid:
            continue
        stats = e.get("stats") or {}
        efforts[eid] = {
            "name": e.get("name") or eid,
            "tier": e.get("tier"),
            "verification": e.get("verification"),
            "gta": e.get("gta") or {},
            "stars": stats.get("stars") or 0,
            "archived": bool(stats.get("archived")),
            "missing": bool(stats.get("missing")),
            "nuked": bool(e.get("nuked")),
            "proof": (e.get("proof") or {}).get("url"),
        }
    return {
        "updated": feed.get("updated"),
        "news_ids": [n.get("id") for n in feed.get("news") or [] if n.get("id")],
        "exe": feed.get("exe") or {},
        "efforts": efforts,
    }


# ---------------------------------------------------------------------------
# Änderungen erkennen -> Liste von (embed, is_focus)
# ---------------------------------------------------------------------------
def diff(old, feed):
    new = snapshot(feed)
    events = []
    efforts_full = {e.get("id"): e for e in feed.get("efforts") or []}

    # --- News ---------------------------------------------------------------
    seen = set(old.get("news_ids", []))
    for n in reversed(feed.get("news") or []):  # älteste zuerst posten
        nid = n.get("id")
        if not nid or nid in seen:
            continue
        src = (n.get("sources") or [{}])[0] or {}
        embed = {
            "title": f"📰 {clip(n.get('title') or 'Neue Meldung', 240)}",
            "url": f"{SITE_URL}/news/",
            "description": clip(n.get("dek") or " ".join(n.get("body") or []), 600),
            "color": BLUE,
            "fields": [{"name": "Kategorie", "value": n.get("category") or "–", "inline": True},
                       {"name": "Datum", "value": n.get("date") or "–", "inline": True}],
        }
        if src.get("url"):
            embed["fields"].append({"name": "Quelle",
                                    "value": f"[{clip(src.get('outlet') or 'Link', 60)}]({src['url']})",
                                    "inline": True})
        img = (n.get("image") or {}).get("url") if isinstance(n.get("image"), dict) else None
        if img and img.startswith("http"):
            embed["image"] = {"url": img}
        is_focus = any(f in nid.lower() for f in FOCUS)
        events.append((embed, is_focus))

    # --- Efforts ------------------------------------------------------------
    for eid, cur in new["efforts"].items():
        full = efforts_full.get(eid, {})
        prev = old.get("efforts", {}).get(eid)
        name = cur["name"]
        is_focus = eid.lower() in FOCUS
        lines = []
        color = GREEN

        if prev is None:
            embed = {
                "title": f"🆕 Neues Projekt im Tracker: {name}",
                "url": effort_url(full),
                "description": clip(full.get("summary"), 500),
                "color": PURPLE,
                "fields": [
                    {"name": "Ansatz", "value": full.get("approach") or "–", "inline": True},
                    {"name": "Ziel", "value": full.get("target") or "–", "inline": True},
                    {"name": "Liste", "value": "Race" if cur["tier"] == "tracked" else (cur["tier"] or "–"), "inline": True},
                    {"name": "Stand", "value": ladder_line(cur["gta"]), "inline": False},
                ],
            }
            if full.get("repo"):
                embed["fields"].append({"name": "Repo", "value": f"[{full['repo']}](https://github.com/{full['repo']})", "inline": False})
            events.append((embed, is_focus))
            continue

        og, ng = prev.get("gta", {}), cur["gta"]
        for key, label in LADDER:
            a, b = num(og.get(key)), num(ng.get(key))
            if b > a:
                lines.append(f"🏁 **{label}**: {step_label(a)} → {step_label(b)}")
            elif b < a:
                lines.append(f"🔻 **{label}**: {step_label(a)} → {step_label(b)}")
                color = ORANGE
        for key, label, kind in TRACKS:
            a, b = num(og.get(key)), num(ng.get(key))
            if abs(b - a) > 1e-9:
                arrow = "📈" if b > a else "📉"
                if b < a:
                    color = ORANGE
                lines.append(f"{arrow} **{label}**: {fmt(a, kind)} → {fmt(b, kind)}")

        if prev.get("verification") != cur["verification"] and cur["verification"]:
            lines.append(f"🔍 **Verifizierung**: {prev.get('verification') or '–'} → **{cur['verification']}**")
        if prev.get("tier") != cur["tier"]:
            if cur["tier"] == "tracked":
                lines.append("🏎️ **Ist ins Race aufgestiegen!**")
            else:
                lines.append(f"↪️ **Liste**: {prev.get('tier') or '–'} → {cur['tier'] or '–'}")
        if cur["nuked"] and not prev.get("nuked"):
            lines.append("💥 **Projekt wurde offenbar entfernt / Takedown.**")
            color = RED
        if cur["missing"] and not prev.get("missing"):
            lines.append("❓ **Repo nicht mehr erreichbar.**")
            color = RED
        if cur["archived"] and not prev.get("archived"):
            lines.append("📦 **Repo wurde archiviert.**")
            color = GREY
        if cur["proof"] and cur["proof"] != prev.get("proof"):
            label = (full.get("proof") or {}).get("label") or "Neuer Beweis"
            lines.append(f"🎬 **Neuer Beweis:** [{clip(label, 80)}]({cur['proof']})")
        for m in STAR_MILESTONES:
            if prev.get("stars", 0) < m <= cur["stars"]:
                lines.append(f"⭐ **{m:,} Sterne** auf GitHub geknackt!".replace(",", "."))

        if lines:
            embed = {
                "title": f"{'⭐ ' if is_focus else ''}{name}: neuer Fortschritt",
                "url": effort_url(full),
                "description": "\n".join(lines),
                "color": color,
                "fields": [{"name": "Aktueller Stand", "value": ladder_line(ng), "inline": False}],
            }
            hl = full.get("highlights") or []
            if hl:
                embed["fields"].append({"name": "Highlight", "value": clip(str(hl[0]), 300), "inline": False})
            events.append((embed, is_focus))

    # --- Executable drop ----------------------------------------------------
    oe, ne = old.get("exe", {}), new["exe"]
    if ne and oe and (oe.get("status") != ne.get("status") or oe.get("releasedAt") != ne.get("releasedAt")):
        events.append(({
            "title": "🚨 Status-Änderung: Executable drop",
            "url": SITE_URL,
            "description": f"**{oe.get('status') or '–'} → {ne.get('status') or '–'}**\n{clip(ne.get('note'), 400)}",
            "color": RED,
        }, True))

    return events, new


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------
def post(payload, dry_run=False):
    if dry_run or not WEBHOOK_URL:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(5):
        req = urllib.request.Request(WEBHOOK_URL, data=data, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
        try:
            urllib.request.urlopen(req, timeout=30).close()
            time.sleep(1.2)  # sanft zum Rate-Limit
            return
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2.0
                try:
                    wait = float(json.loads(e.read().decode()).get("retry_after", 2))
                except Exception:
                    pass
                time.sleep(wait + 0.5)
                continue
            log(f"Discord-Fehler {e.code}: {e.read().decode(errors='ignore')[:300]}")
            return
        except urllib.error.URLError as e:
            log(f"Discord nicht erreichbar: {e}")
            time.sleep(5)
    log("Nachricht nach 5 Versuchen verworfen.")


def send_events(events, dry_run=False):
    for embed, is_focus in events:
        embed.setdefault("footer", {"text": "PortWatch VI · Fan-Tracker"})
        payload = {"username": "PortWatch VI", "embeds": [embed]}
        if is_focus and FOCUS_PING:
            payload["content"] = FOCUS_PING
            payload["allowed_mentions"] = {"parse": ["everyone", "users", "roles"]}
        post(payload, dry_run)


# ---------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------
def check(dry_run=False):
    try:
        feed = fetch_feed()
    except Exception as e:
        log(f"Feed konnte nicht geladen werden: {e}")
        return
    if feed is None:
        return  # Feed unverändert
    old = load_state()
    if old and old.get("updated") and old.get("updated") == feed.get("updated"):
        log(f"Unverändert (Stand {feed.get('updated')}).")
        return  # gleicher Stand wie zuletzt
    if old is None:
        new = snapshot(feed)
        save_state(new)
        n_eff = len(new["efforts"])
        log(f"Erster Start: {n_eff} Projekte und {len(new['news_ids'])} News gespeichert. Ab jetzt wird gemeldet.")
        focus_lines = [f"**{e['name']}** – {ladder_line(e['gta'])}"
                       for k, e in new["efforts"].items() if k.lower() in FOCUS]
        send_events([({
            "title": "👀 PortWatch-Bot ist aktiv",
            "url": SITE_URL,
            "description": f"Ich beobachte jetzt **{n_eff} Projekte** und melde neue News und Fortschritte hier."
                           + ("\n\n" + "\n".join(focus_lines) if focus_lines else ""),
            "color": GREY,
        }, False)], dry_run)
        return
    events, new = diff(old, feed)
    if events:
        log(f"{len(events)} Neuigkeit(en) gefunden.")
        send_events(events, dry_run)
    else:
        log("Nichts Neues.")
    save_state(new)


def main():
    ap = argparse.ArgumentParser(description="PortWatch VI -> Discord")
    ap.add_argument("--once", action="store_true", help="einmal prüfen und beenden")
    ap.add_argument("--dry-run", action="store_true", help="nichts senden, nur in der Konsole ausgeben")
    ap.add_argument("--test", action="store_true", help="Testnachricht an Discord schicken")
    args = ap.parse_args()

    if not WEBHOOK_URL and not args.dry_run:
        sys.exit("Bitte DISCORD_WEBHOOK_URL setzen (oder --dry-run benutzen).")

    if args.test:
        send_events([({"title": "✅ Test erfolgreich", "description": "Der PortWatch-Bot kann in diesen Kanal schreiben.",
                       "color": GREEN, "url": SITE_URL}, True)], args.dry_run)
        return
    if args.once:
        check(args.dry_run)
        return

    log(f"Läuft – prüfe alle {INTERVAL_MIN} Minuten. Fokus: {', '.join(FOCUS) or '–'}")
    checks = 0
    while True:
        check(args.dry_run)
        checks += 1
        # Statuszeile, die sich selbst überschreibt – so siehst du, dass der Bot lebt
        print(f"\r🟢 Läuft · letzte Prüfung {time.strftime('%H:%M:%S')} · {checks} Prüfungen seit Start   ",
              end="", flush=True)
        time.sleep(INTERVAL_MIN * 60)


if __name__ == "__main__":
    main()
