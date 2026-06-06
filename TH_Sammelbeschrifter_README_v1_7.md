# TH Sammelbeschrifter v1.7

## Zweck

Der TH Sammelbeschrifter erstellt in Revit ueber Dynamo Player mehrere Beschrifter fuer ausgewaehlte Elemente. Die Beschrifter werden in Auswahlreihenfolge angelegt, horizontal oder vertikal ausgerichtet und koennen Parameterwerte gesammelt anzeigen.

## Ablauf

1. Dynamo Player starten und `run=True` setzen.
2. Elemente in gewuenschter Reihenfolge auswaehlen.
3. Parameterdialog oeffnen:
   - Tag-Typ/Familie auswaehlen
   - Parameter aus ComboBox waehlen und mit **Hinzufuegen** uebernehmen
   - Reihenfolge mit **Hoch** und **Runter** steuern
   - **Parameternamen im Text anzeigen** optional aktivieren
   - **Farbe aus Ansicht uebernehmen** optional aktivieren
   - Mindestabstand in mm setzen
4. Punkt 1 waehlen: Startposition erster Tag.
5. Punkt 2 waehlen: Richtung und Abstand fuer die Beschrifterreihe.
6. Tags werden erstellt und Texte optional in `TH_Beschriftungstext` geschrieben.

## Eingaben

- `run`: bool, startet den Ablauf.
- `tag_type_name`: string, Vorauswahl Tag-Typ/Familie, zum Beispiel `TH_Rohr_Sammelzeile`.
- `parameter_names`: string, Vorauswahl Parameter, zum Beispiel `Groesse` oder `Groesse; Systemtyp`.
- `target_text_parameter_on_source`: string, Zielparameter auf dem Quellelement, zum Beispiel `TH_Beschriftungstext`.
- `tag_filter_parameter`: string, optionaler Filterparameter am Tag.
- `filter_source_parameter`: string, optionaler Quellparameter; leer bedeutet automatische Systemtyp/Systemname-Auswertung.
- `line_spacing_mm`: number, Mindestabstand entlang Stapelpfad.
- `separator`: string, Trenner zwischen mehreren Parameterwerten.
- `use_view_filter_color`: bool, Farbe aus Elementueberschreibung oder Ansichtfilter uebernehmen.
- `has_leader`: bool, Fuehrungslinie erzeugen.
- `category_mode`: string, `Pipes`, `Ducts`, `Conduits`, `CableTrays`, `MEP` oder `All`.
- `write_text_on_source`: bool, Text auf Quellelement schreiben.
- `prefix_parameter_names`: bool, Parameternamen im Tag-Text anzeigen.

## Abhaengigkeiten

- Revit mit Dynamo Player.
- Dynamo Python Node im Revit-Kontext.
- Revit-Assemblies: `RevitAPI`, `RevitAPIUI`.
- Dynamo-Assembly: `RevitServices`.
- Windows Forms fuer den Auswahl- und Parameterdialog.
- Geeignete Tag-Familie mit sichtbarem Zielparameter, zum Beispiel `TH_Beschriftungstext`.

## Bekannte Einschraenkungen

- Der Dialog nutzt Windows Forms und ist auf Desktop-Revit/Dynamo Player ausgelegt.
- Fuer die Textanzeige muss die Tag-Familie auf den Zielparameter parametriert sein.
- Die Farbermittlung aus Filtern haengt von Filter-Sichtbarkeit und Reihenfolge in der aktiven Ansicht ab.
- Fuer frei waehlbare Parameter muss die verwendete Tag-Familie den geschriebenen Zielparameter anzeigen.
- Der Ablauf ist interaktiv und erfordert Elementauswahl sowie zwei Punktklicks in Revit.

## Lokale Pruefschritte

Siehe `testhinweise.md`.
