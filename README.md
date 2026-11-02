# Gottesdienst-Aufnahme für x32-recorder

Plugin für [x32-recorder](https://github.com/tobire42/x32-recorder): nimmt den Gottesdienst ohne
Zutun auf.

- **Start nach Wochenplan**, z.B. sonntags 10:28, mit einer gewählten Vorlage (Kanäle, Gerät und
  Name wie bei einem Start in der Weboberfläche). Gestartet wird nur bis 20 Minuten nach der
  geplanten Zeit. Scheitert der Start (Pult noch aus), wird es in dieser Zeit alle 30 s erneut
  versucht. Läuft schon eine Aufnahme mit derselben Vorlage, wird sie übernommen.
- **Ende bei Stille:** Ab „normale Länge minus Spielraum“ endet die Aufnahme, sobald es einige
  Minuten durchgehend still war. Eine lange Pause mittendrin beendet sie nicht.
- **Ende bei maximaler Länge.**
- **Pult ausgeschaltet:** Dann beendet x32-recorder die Aufnahme ohnehin selbst.
- **Marker „Stille ab hier“** an der Stelle, ab der nur noch Stille kam - zum späteren
  Wegschneiden.

Überwacht werden die Master-Kanäle der Aufnahme (in der Vorlage als Master markiert), sonst alle
ihre Kanäle. Die Pegel kommen aus x32-recorder selbst, das Plugin greift kein Audio ab.

**Uhrzeit:** Ein Raspberry Pi hat keine Echtzeituhr. Ist die Uhr nicht mit dem Internet
abgeglichen, startet das Plugin nicht und zeigt eine Warnung - sonst könnte der Wochenplan zur
falschen Zeit auslösen.

## Einrichten

1. In x32-recorder unter **Einstellungen → Plugins** die GitHub-URL dieses Repos hinzufügen und
   aktivieren, Dienste neu starten.
2. In den Plugin-Einstellungen Vorlage, Wochentage, Startzeit und Längen eintragen und
   **Automatisch aufnehmen** einschalten.

## Tests

```bash
python -m unittest tests.test_schedule          # im Plugin-Ordner
uv run python x32recorder/manage.py test x32_recorder_sermon_plugin   # mit aktiviertem Plugin
```
