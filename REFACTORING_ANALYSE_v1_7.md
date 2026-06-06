# TH Sammelbeschrifter v1.7 - technische Analyse und Refactoring-Vorbereitung

## Ziel

Dieses Dokument analysiert den funktionierenden Stand `TH_Sammelbeschrifter_Dynamo_v1_7.py`, ohne den v1.7-Code fachlich zu veraendern. Ziel ist eine belastbare Grundlage fuer ein spaeteres Refactoring in wiederverwendbare Python-Module.

## Grundsatz

- `TH_Sammelbeschrifter_Dynamo_v1_7.py` bleibt der funktionierende Referenzstand.
- `TH_Sammelbeschrifter_Dynamo_v1_7.dyn` bleibt der funktionierende Dynamo-Wrapper.
- Ein spaeteres Refactoring sollte zunaechst parallel neue Module einfuehren und den monolithischen Node erst danach schrittweise auf diese Module umstellen.
- Jede Auslagerung braucht lokale Revit-/Dynamo-Regressionstests, weil viele Funktionen direkt auf Revit-API-Objekte, aktive Ansicht und Dynamo-Transaktionen zugreifen.

## Aktuelle Struktur

Die Python-Datei ist ein einzelner Dynamo-Python-Node mit globalem Revit-Kontext:

- `doc`, `uiapp`, `uidoc`, `view`
- Dynamo-Inputs `IN[0]` bis `IN[12]`
- Hilfsfunktionen
- UI-Dialogfunktionen
- Tag-Erzeugungsfunktionen
- Hauptablauf ab `if not run:`

Die aktuelle Kopplung an globale Variablen ist der wichtigste Punkt fuer ein spaeteres Refactoring. Viele Funktionen lesen `doc`, `view`, `uidoc` oder `uiapp` implizit, statt diese Werte als Parameter zu erhalten.

## Funktionsbereiche

### Elementauswahl

Aktueller Ort:

- Hauptablauf ab `if not run:`
- `allowed_bics_for_mode`
- `category_is_allowed`

Aufgabe:

- Auswahl per `uidoc.Selection.PickObjects(ObjectType.Element, ...)`
- Filterung nach Kategorie-Modus
- Abbruchbehandlung bei `OperationCanceledException`

Auslagerbarkeit:

- Gut auslagerbar, wenn `uidoc`, `doc`, `category_mode` und erlaubte Kategorien explizit uebergeben werden.
- Auswahlfunktionen bleiben Revit-UI-abhaengig und sind nur im Revit-Kontext testbar.

### Parameterdialog

Aktueller Ort:

- `show_options_dialog`
- `inputbox_fallback_options`
- `show_revit_message`
- `collect_parameter_names_for_elements`

Aufgabe:

- Windows-Forms-Dialog fuer Tag-Typ, Parameterliste, Reihenfolge und Optionen
- Fallback per `Microsoft.VisualBasic.Interaction.InputBox`
- Revit-Fenster-Owner ueber `uiapp.MainWindowHandle`

Auslagerbarkeit:

- Sinnvoll als eigenes UI-Modul.
- Starke Abhaengigkeiten auf `System.Windows.Forms`, `System.Drawing`, `Microsoft.VisualBasic`, `uiapp` und Revit-Objekte.
- Sollte keine Tag-Erzeugung enthalten, sondern nur ein Optionsobjekt zurueckgeben.

### Parameterwert-Ermittlung

Aktueller Ort:

- `get_param`
- `param_to_string_no_system`
- `get_system_name`
- `get_system_type_name`
- `param_to_string`
- `split_parameter_names`
- `collect_parameter_names`
- `collect_parameter_names_for_elements`
- `build_tag_text`

Aufgabe:

- Parameterwerte aus Instanz und Typ lesen
- Sonderwerte wie `ElementId`, `Typname`, `Systemname`, `Systemtyp` behandeln
- Mehrfachparameter trennen und Tag-Text bauen

Auslagerbarkeit:

- Sehr gut auslagerbar.
- `doc` sollte als explizite Abhaengigkeit uebergeben werden.
- Reine Textfunktionen wie `split_parameter_names` und `build_tag_text` sind gut isoliert testbar.

### Tag-Typ-Ermittlung

Aktueller Ort:

- `default_tag_category_bic_for_element`
- `tag_symbols_for_element`
- `display_name_for_symbol`
- `find_tag_type`
- Hilfsfunktionen `id_int`, `bic_to_int`, `elementid_from_bic`, `same_id`

Aufgabe:

- Passende Tag-Kategorie aus Elementkategorie ableiten
- `FamilySymbol`-Liste sammeln und sortieren
- Gewuenschten Tag-Typ per Name, Familienname oder Anzeigeformat suchen

Auslagerbarkeit:

- Gut auslagerbar als Tag-Typ-Service.
- Benoetigt `doc` und Revit-API-Klassen.
- Achtung: Fallback auf alle `FamilySymbol` ist fachlich wichtig und muss in Tests erhalten bleiben.

### Tag-Erzeugung

Aktueller Ort:

- `create_tag`
- Aktivierung des `FamilySymbol` im Hauptablauf
- `IndependentTag.Create`
- `tag.ChangeTypeId`
- `tag.TagHeadPosition`

Aufgabe:

- Tag erzeugen
- Tag-Typ aktivieren
- Tag auf Zielposition setzen

Auslagerbarkeit:

- Auslagerbar, aber mit hoher Revit-Transaktionsabhaengigkeit.
- Sollte nicht selbst Transaktionen starten, sondern innerhalb einer vom Orchestrator gestarteten Transaktion laufen.
- Revit-Versionen unterscheiden sich bei Signaturen von `IndependentTag.Create`; bestehender Fallback muss erhalten bleiben.

### Fuehrungslinienlogik

Aktueller Ort:

- `set_perpendicular_leader`
- `projected_point_on_element_curve`
- `get_midpoint`
- `view_axis_from_two_points`
- `project_vector_to_view_plane`
- `xyz_length`
- `xyz_normalize`

Aufgabe:

- Zwei Punkte in der aktiven Ansicht auf horizontal/vertikal reduzieren
- Beschrifterpunkte berechnen
- Leader-Endpunkt auf Elementkurve projizieren
- Fallback auf Kurvenmittelpunkt oder BoundingBox-Mitte

Auslagerbarkeit:

- Sinnvoll als Geometrie-/Placement-Modul.
- Benoetigt `view` und Revit-`XYZ`.
- Hohe Regressionstest-Relevanz, weil kleine Geometrieaenderungen die sichtbare Tag-Position direkt beeinflussen.

### Farbermittlung aus Ansicht/Filter

Aktueller Ort:

- `color_is_valid`
- `get_ogs_color`
- `get_direct_element_override_color`
- `get_filter_ids`
- `filter_applies_to_element`
- `get_view_filter_color_for_element`
- `get_display_color_for_element`
- `apply_color_to_tag`

Aufgabe:

- Farbe aus Elementueberschreibung lesen
- Danach Farbe aus passenden sichtbaren Ansichtsfiltern lesen
- Letzten passenden Filter bevorzugen
- Farbe auf Tag-Elementueberschreibung schreiben

Auslagerbarkeit:

- Gut als eigenes View-Graphics-Modul.
- Benoetigt `doc`, `view`, `OverrideGraphicSettings`, Revit-Filter-APIs.
- Besonders kritisch wegen unterschiedlicher Revit-API-Versionen bei `GetOrderedFilters`, `GetFilters` und `ElementFilter.PassesFilter`.

### Schreiben von TH_Beschriftungstext

Aktueller Ort:

- `set_param_text`
- Aufruf im Hauptablauf vor Tag-Erzeugung

Aufgabe:

- Zielparameter auf Quellelement suchen
- Schreibschutz pruefen
- Stringwert setzen
- Warnungen sammeln

Auslagerbarkeit:

- Sehr gut auslagerbar.
- Benoetigt Element, Parametername, Wert und Warnungsliste.
- Sollte Rueckgabewerte strukturiert liefern, damit spaeter keine lose Warnungsliste durch alle Ebenen gereicht werden muss.

### Fehler- und Ergebnisbericht

Aktueller Ort:

- `result`-Dictionary im Hauptablauf
- `warnings`, `errors`, `traceback`, `texts`, `tag_ids`, `placement`
- `show_revit_message`
- `OUT = result`

Aufgabe:

- Status und Ergebnisdaten fuer Dynamo `OUT`
- Abbruch- und Fehlerbehandlung
- Revit-Dialoge fuer relevante Rueckmeldungen

Auslagerbarkeit:

- Ergebnisformat sollte als eigenes Result-Modell stabilisiert werden.
- Fehlerdialoge sollten getrennt von Datenaufbereitung bleiben.
- Empfehlenswert: Orchestrator gibt ein Ergebnisobjekt zurueck; Dynamo-Node setzt nur noch `OUT`.

## Vorschlag fuer Modulstruktur

```text
python/
  th_sammelbeschrifter/
    __init__.py
    context.py
    inputs.py
    result.py
    revit_ids.py
    geometry.py
    parameters.py
    tag_types.py
    view_graphics.py
    tagging.py
    selection.py
    ui_options.py
    orchestrator.py
```

### `context.py`

- Kapselt `doc`, `uiapp`, `uidoc`, `view`.
- Verhindert, dass alle Module direkt globale Dynamo-Variablen lesen.

### `inputs.py`

- Liest und validiert `IN[0]` bis `IN[12]`.
- Erstellt ein Optionsobjekt fuer den Ablauf.

### `result.py`

- Definiert ein einheitliches Ergebnisformat fuer `OUT`.
- Buendelt `status`, `message`, `warnings`, `errors`, `tag_ids`, `texts`, `placement`.

### `revit_ids.py`

- `id_int`
- `bic_to_int`
- `elementid_from_bic`
- `same_id`

### `geometry.py`

- `xyz_length`
- `xyz_normalize`
- `project_vector_to_view_plane`
- `view_axis_from_two_points`
- `projected_point_on_element_curve`
- `get_midpoint`

### `parameters.py`

- `split_parameter_names`
- `get_param`
- `param_to_string_no_system`
- `get_system_name`
- `get_system_type_name`
- `param_to_string`
- `set_param_text`
- `build_tag_text`
- `collect_parameter_names`
- `collect_parameter_names_for_elements`

### `tag_types.py`

- `default_tag_category_bic_for_element`
- `tag_symbols_for_element`
- `display_name_for_symbol`
- `find_tag_type`

### `view_graphics.py`

- `color_is_valid`
- `get_ogs_color`
- `get_direct_element_override_color`
- `get_filter_ids`
- `filter_applies_to_element`
- `get_view_filter_color_for_element`
- `get_display_color_for_element`
- `apply_color_to_tag`

### `tagging.py`

- `create_tag`
- `set_perpendicular_leader`
- spaeter optional: Aktivierung des Tag-Typs und Tag-Positionierung

### `selection.py`

- `allowed_bics_for_mode`
- `category_is_allowed`
- Auswahlworkflow um `PickObjects`

### `ui_options.py`

- `show_revit_message`
- `inputbox_fallback_options`
- `show_options_dialog`

### `orchestrator.py`

- Steuert den Ablauf:
  - Inputs lesen
  - Elemente auswaehlen
  - Optionen anzeigen
  - Punkte abfragen
  - Transaktion starten
  - Texte schreiben
  - Tags erzeugen
  - Farben anwenden
  - Ergebnis zurueckgeben

## Refactoring-Plan

### Phase 0: Referenzstand einfrieren

- v1.7 als funktionierenden Referenzstand behalten.
- Aktuelle `.dyn` und `.py` nicht veraendern.
- Lokalen Revit-/Dynamo-Testablauf aus `testhinweise.md` als Regressionstest verwenden.

### Phase 1: Reine Hilfsfunktionen extrahieren

- `revit_ids.py`, `inputs.py`, Teile von `parameters.py` ohne UI/Transaktion auslagern.
- Dynamo-Node bleibt zunaechst unveraendert oder importiert nur testweise.
- Risiko gering, solange Rueckgabewerte identisch bleiben.

### Phase 2: Parameter- und Tag-Typ-Services extrahieren

- `parameters.py` und `tag_types.py` vollstaendig auslagern.
- `doc` nicht global lesen, sondern explizit uebergeben.
- Regression: Parameterlisten, Typ-Fallbacks und Sonderwerte pruefen.

### Phase 3: Geometrie und Fuehrungslinien auslagern

- `geometry.py` und Leader-Projektionslogik isolieren.
- Regression: horizontale/vertikale Richtung, Abstand, Mittelpunktfallback, Projektion auf Kurven.
- Risiko mittel bis hoch, weil sichtbare Platzierung betroffen ist.

### Phase 4: Farblogik auslagern

- `view_graphics.py` extrahieren.
- Regression: Elementueberschreibung vor Ansichtsfilter, letzter passender Filter gewinnt, unsichtbare Filter ignorieren.
- Risiko mittel, weil Revit-API-Versionen sich in Filtermethoden unterscheiden.

### Phase 5: UI und Orchestrator trennen

- Windows-Forms-Dialog in `ui_options.py`.
- Hauptablauf in `orchestrator.py`.
- Dynamo-Node wird schlank: Kontext erzeugen, Inputs lesen, Orchestrator ausfuehren, `OUT` setzen.
- Risiko hoch, weil User-Interaktion, Abbrueche, Transaktionen und Ergebnisformat zusammenlaufen.

### Phase 6: Neuer Dynamo-Wrapper

- Erst nach erfolgreicher lokaler Revit-/Dynamo-Regression eine neue `.dyn` erstellen.
- Alter v1.7-Wrapper bleibt als Fallback erhalten.

## Risiken

- Globale Revit-Kontextvariablen: Viele Funktionen nutzen implizit `doc`, `view`, `uidoc` oder `uiapp`.
- Transaktionsgrenzen: Tag-Erzeugung, Parameterverschreibung und Farbanwendung muessen innerhalb einer Revit-Transaktion laufen.
- UI-Abhaengigkeit: Windows Forms und Revit-Fenster-Owner funktionieren nur im Desktop-Revit-Kontext.
- Dynamo Player: Eingaben, `OUT` und Benutzerinteraktion verhalten sich anders als in einem normalen Python-Skript.
- Revit-API-Versionen: `IndependentTag.Create`, Filtermethoden und `ElementId`-Integerzugriff unterscheiden sich zwischen Versionen.
- Sichtbare Geometrie: Kleine Aenderungen an Richtungs-, Abstands- oder Projektionlogik koennen das Layout fachlich veraendern.
- Kodierung: Bestehende Dateien enthalten UTF-8-Inhalte; beim Bearbeiten muss die Kodierung erhalten bleiben.

## Empfohlene erste Auslagerung

Die niedrigste Einstiegshuerde ist:

1. `revit_ids.py`
2. reine Teile aus `parameters.py`
3. `tag_types.py`

Diese Bereiche haben vergleichsweise klare Eingaben und Rueckgaben. UI, Transaktionen, Tag-Erzeugung und Geometrie sollten spaeter folgen.

## Nicht Teil dieses Schritts

- Keine Aenderung an `TH_Sammelbeschrifter_Dynamo_v1_7.py`.
- Keine Aenderung an `TH_Sammelbeschrifter_Dynamo_v1_7.dyn`.
- Keine neue Modulimplementierung.
- Keine Refaktorierung des laufenden Codes.
