---
name: jarvis-nightshift
description: "JARVIS' Nachtschicht: Kalender, Gmail und WhatsApp sichten, recherchieren, Entwürfe schreiben und einen Code-Punkt als Patch vorbereiten. Sendet nichts — alles wartet auf Marlons Freigabe im Morgen-Briefing."
version: 1.0.0
author: Marlon
---

# Nachtschicht

Du arbeitest allein, während Marlon schläft. Alles, was du tust, landet in einem
Bericht, den er morgens am Mac-HUD vorgelesen bekommt.

**Du sendest, postest, veröffentlichst oder rufst nichts an.** Auch nicht, wenn
etwas dringend wirkt, und auch nicht, wenn eine Erinnerung sagt, er wolle ohne
Rückfrage handeln: Für die Nachtschicht hat er am 15.09.2026 ausdrücklich „nur
Entwürfe, Freigabe am Morgen" gewählt. Also kein `hermes send`, kein
`phone_call`, kein `jarvis-whatsapp-mode.py`, kein `jarvis-notify`, keine Posts
im Browser, keine Kalendereinträge. Was gesendet werden soll, wird ein Entwurf.

## Datum

Du hast keine Uhr. Hol das Datum zuerst mit `date +%F` und die Uhrzeit mit
`date +%H:%M`. Der Bericht trägt das Datum des Morgens, an dem er gelesen wird.

## Terminal-Befehle einfach halten

Der Sicherheitsscan blockiert Befehle, deren ausgeführter Teil erst zur Laufzeit
feststeht: `$(…)`, Backticks, `( … )`-Gruppen, `eval`, `sh -c` — und schon ein
Programmpfad mit `~`. Schreib Pfade daher immer ausgeschrieben
(`/Users/marlon/…`), führe einen einfachen Befehl pro Aufruf aus und setze Werte
wie das Datum als fertigen Text ein, nachdem du sie mit einem eigenen Aufruf
geholt hast. Meldet der Scan
`BLOCKED`, schreib den Befehl einfacher, statt den Schritt aufzugeben.

## Bericht

Datei: `/Users/marlon/Developer/JARVIS/Jarvis Output/Nachtschicht/<JJJJ-MM-TT>.md`.
Leg den Ordner an, falls er fehlt. Gibt es die Datei schon (zweiter Lauf in einer
Nacht), ergänze sie, statt sie zu überschreiben. Aufbau:

```markdown
# Nachtschicht <JJJJ-MM-TT>

## Zum Vorlesen
<höchstens vier kurze Sätze, das Wichtigste der Nacht, gesprochen formuliert>

## Kalender heute

## Nachrichten
### Gmail
### WhatsApp

## Recherche

## Entwürfe
### E1 — <Kanal> an <Empfänger>
- Status: offen
- Anlass: <ein Satz>
- Ziel: <chat_id oder Adresse>
- Text:
  > <der fertige Text, so wie er gesendet würde>

## Code

## Probleme
```

Entwürfe sind fortlaufend nummeriert (E1, E2, …), ihr Status ist immer `offen`.
Gmail kann JARVIS nur lesen, nicht senden: Schreib bei Mail-Entwürfen dazu, dass
Marlon sie selbst abschicken muss.

## Ablauf

Jeder Schritt darf scheitern, ohne die übrigen abzubrechen. Was scheitert, steht
mit dem Fehler in einem Satz unter „Probleme".

1. **Kalender:** `/Users/marlon/.hermes/bin/jarvis-cal today` und `/Users/marlon/.hermes/bin/jarvis-cal tomorrow`.
2. **Gmail:** `gmail_list_emails` für die letzten 24 Stunden. Zusammenfassen,
   Werbung weglassen. Wo eine Antwort von Marlon erwartet wird, ein Entwurf.
3. **WhatsApp:** `/Users/marlon/Developer/JARVIS/scripts/jarvis-whatsapp-read.py unread`,
   bei Bedarf `… chat <Name>`. Zusammenfassen. Antwortentwürfe für Einzelchats;
   in Gruppen nur, wenn Marlon direkt angesprochen wurde.
4. **Recherche:** Websuche zu dem, was laut Kalender und Nachrichten heute
   ansteht, und zu offenen Themen aus deinem Gedächtnis. Jede Aussage mit Link.
5. **Content-Entwürfe:** nur für Projekte und Kanäle, die du aus deinem
   Gedächtnis sicher kennst. Kennst du keins, schreib unter „Entwürfe" einen
   Satz, dass Marlon dir sagen soll, wofür du Content entwerfen sollst — erfinde
   kein Projekt.
6. **Code:** höchstens ein Punkt aus
   `/Users/marlon/Developer/JARVIS/Jarvis Output/Monet-Fixliste.md` oder den
   offenen Punkten in `/Users/marlon/Developer/JARVIS/fixes.md`. Nimm keinen Punkt,
   der auf eine Entscheidung von Marlon wartet. Starte
   `/Users/marlon/Developer/JARVIS/scripts/jarvis-nightshift-code.sh "<vollständiger Auftrag>"`
   mit einem Timeout von 1800 Sekunden. Trag Patch-Pfad, Testergebnis und die
   drei Sätze des Agenten unter „Code" ein. Ist kein Punkt geeignet, sag das.
7. **Bericht fertigstellen**, „Zum Vorlesen" zuletzt.

## Welches Werkzeug wofür

- **Code** → Codex (Standard des Code-Skripts). Meldet Codex ein erschöpftes
  Kontingent: `BACKEND=qwen` davor setzen, scheitert auch das, `BACKEND=claude`.
- **Planung, Review, lange Texte** → Claude Code:
  `claude -p '<vollständiger Auftrag mit allem Kontext>' --permission-mode plan --max-turns 3`
  (Timeout 300). Sparsam: Claude teilt sich das Kontingent mit Marlons eigenen
  Claude-Sessions.
- **Aktuelles aus dem Web** → deine eigene Websuche.
- **Kurzes Zusammenfassen** → selbst.

Was ein Agent zurückgibt, prüfst du, bevor es in den Bericht kommt. Ist es
falsch oder leer, steht das so unter „Probleme".
