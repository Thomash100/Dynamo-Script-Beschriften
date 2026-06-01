# TH Sammelbeschrifter Dynamo v6.6

Dynamo-Python-Script für Revit/Dynamo Player.

## Neu in v6.6

### Einzelne Rohrleitungen beschriften

Wenn die Option **Einzelne Rohrleitungen beschriften** aktiv ist:

- **Führungslinie aus**: keine Punktabfrage mehr. Der Beschrifter wird automatisch auf den Mittelpunkt der Rohrleitung/Rohrachse gesetzt.
- **Führungslinie an**: Punkt 1 und Punkt 2 werden weiterhin abgefragt, damit die Seite/Richtung bestimmt werden kann.

### Trassenbeschriftung

Neue Option:

**Trassenbeschriftung / mehrere Teilstrecken automatisch am Rohrmittelpunkt**

Gedacht für mehrere Teilstrecken, die per Mehrfachauswahl, STRG-Auswahl oder Auswahlfenster gewählt werden.

- **Führungslinie aus**: jeder Beschrifter wird automatisch am Mittelpunkt der jeweiligen Teilstrecke auf der Rohrachse platziert.
- **Führungslinie an**: keine Punktabfrage. Der Tagkopf wird vom Mittelpunkt der jeweiligen Teilstrecke um den eingestellten **Trassenabstand Achse zu Achse [mm im Plan]** verschoben.
- Bei **Übereinander / gestapelt** wird der Achsabstand in View.UpDirection angesetzt.
- Bei **Nebeneinander** wird der Achsabstand in View.RightDirection angesetzt.

## Bestehende Funktionen

- Sammelblock mit übereinander/nebeneinander
- optische Sortierung der Beschrifter nach Rohrlage
- Gesamtmaß/DN-Wert für Außenradius der Rohrdämmung
- maßstabsabhängiger Zusatzabstand in mm im Plan
- Farbübergabe aus Ansicht/Ansichtsfilter
- Wiederholung mit gleicher Beschrifterfamilie
