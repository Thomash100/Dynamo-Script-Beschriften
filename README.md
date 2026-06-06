# Dynamo-Script-Beschriften

Aktuelle Version: **TH Sammelbeschrifter v1.7**

## Zweck

Der **TH Sammelbeschrifter** erzeugt in Revit ueber Dynamo Player mehrere Beschrifter in einer definierten Reihenfolge. Er ist fuer MEP-Elemente wie Rohre, Luftkanaele, Leerrohre und Kabeltrassen gedacht und schreibt ausgewaehlte Parameterwerte optional in einen gemeinsamen Textparameter, zum Beispiel `TH_Beschriftungstext`.

## Aktuelle Dateien

- Dynamo-Datei: `TH_Sammelbeschrifter_Dynamo_v1_7.dyn`
- Python-Quelltext: `TH_Sammelbeschrifter_Dynamo_v1_7.py`
- Anleitung: `TH_Sammelbeschrifter_README_v1_7.md`
- Komplettpaket: `TH_Sammelbeschrifter_v1_7_Paket.zip`
- Changelog: `CHANGELOG.md`
- Testhinweise: `testhinweise.md`
- Projektzusammenfassung: `PROJEKTZUSAMMENFASSUNG.md`

Historische Dateien liegen unter `archive/`.

## Ablauf

1. Revit-Modell und Zielansicht oeffnen.
2. Dynamo Player starten.
3. `TH_Sammelbeschrifter_Dynamo_v1_7.dyn` ausfuehren und `run=True` setzen.
4. Elemente in der gewuenschten Reihenfolge auswaehlen.
5. Im Dialog Tag-Typ, auszugebende Parameter, Reihenfolge, Mindestabstand und Optionen einstellen.
6. Punkt 1 fuer die Startposition des ersten Beschrifters anklicken.
7. Punkt 2 fuer Richtung und Abstand des zweiten Beschrifters anklicken.
8. Das Script erzeugt die Tags, ordnet sie horizontal oder vertikal an und schreibt optional den Text auf das Quellelement.

## Eingaben

- `IN[0] run`: Startet den Ablauf.
- `IN[1] tag_type_name`: Vorauswahl fuer Tag-Typ oder Familie.
- `IN[2] parameter_names`: Vorauswahl der Parameter, getrennt mit Semikolon.
- `IN[3] target_text_parameter_on_source`: Zielparameter auf dem Quellelement.
- `IN[4] tag_filter_parameter`: optionaler Tag-Filterparameter.
- `IN[5] filter_source_parameter`: optionaler Quellparameter fuer Filterwerte.
- `IN[6] line_spacing_mm`: Mindestabstand der Beschrifter in mm.
- `IN[7] separator`: Trenner zwischen mehreren Parameterwerten.
- `IN[8] use_view_filter_color`: Farbe aus aktiver Ansicht uebernehmen.
- `IN[9] has_leader`: Fuehrungslinie erzeugen.
- `IN[10] category_mode`: `Pipes`, `Ducts`, `Conduits`, `CableTrays`, `MEP` oder `All`.
- `IN[11] write_text_on_source`: Text auf Quellelement schreiben.
- `IN[12] prefix_parameter_names`: Parameternamen im Text anzeigen.

## Abhaengigkeiten

- Revit mit Dynamo Player.
- Dynamo Python Node mit Zugriff auf `RevitAPI`, `RevitAPIUI` und `RevitServices`.
- Desktop-Revit, da der Parameterdialog Windows Forms nutzt.
- Eine geeignete Tag-Familie, die den Zielparameter, zum Beispiel `TH_Beschriftungstext`, anzeigt.

## Bekannte Einschraenkungen

- Der Windows-Forms-Dialog ist fuer Desktop-Revit/Dynamo Player ausgelegt.
- Die Tag-Familie muss den Zielparameter anzeigen; sonst wird der berechnete Text nicht sichtbar.
- Farbermittlung aus Ansichtsfiltern haengt von Filter-Sichtbarkeit, Filter-Reihenfolge und aktiver Ansicht ab.
- Das Script veraendert keine Ansichtsvorlagenlogik; es arbeitet in der aktiven Ansicht.
- Die funktionierende v1.7-Dynamo-Datei wurde in diesem Bereinigungsschritt nicht fachlich umgebaut.

## Lokale Pruefschritte

Siehe `testhinweise.md`.
