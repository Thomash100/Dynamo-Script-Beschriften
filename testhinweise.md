# Testhinweise

## Automatische Pruefung

```bash
python -m py_compile TH_Sammelbeschrifter_Dynamo_v1_7.py
python -m json.tool TH_Sammelbeschrifter_Dynamo_v1_7.dyn
```

## Lokale Pruefung in Revit/Dynamo

1. Revit-Modell mit geeigneter Ansicht oeffnen.
2. Sicherstellen, dass eine passende Tag-Familie geladen ist.
3. Pruefen, dass der Zielparameter, zum Beispiel `TH_Beschriftungstext`, in der Tag-Familie sichtbar ist.
4. Dynamo Player starten.
5. `TH_Sammelbeschrifter_Dynamo_v1_7.dyn` auswaehlen.
6. `run=True` setzen.
7. Elemente in gewuenschter Reihenfolge auswaehlen.
8. Im Dialog Tag-Typ und Parameter auswaehlen.
9. Zwei Punkte fuer Startposition, Richtung und Abstand setzen.
10. Ergebnis in der aktiven Ansicht pruefen.
11. Pruefen, ob Texte in der erwarteten Reihenfolge erscheinen.
12. Pruefen, ob Fuehrungslinien korrekt auf die Elemente zeigen.
13. Optional pruefen, ob Farben aus Elementueberschreibungen oder Ansichtsfiltern uebernommen werden.
14. Pruefen, dass keine Ansichtsvorlage fachlich veraendert wurde.

## Erwartetes Ergebnis

- Tags werden in Auswahlreihenfolge erzeugt.
- Texte werden horizontal oder vertikal mit gleichmaessigem Abstand angeordnet.
- Der Zielparameter wird nur geschrieben, wenn `write_text_on_source=True` gesetzt ist.
- Fehler und Abbrueche werden ueber `OUT` bzw. Revit-Dialoge rueckgemeldet.

## Offen

- Fachliche Endpruefung muss lokal in Revit/Dynamo erfolgen.
- Projektspezifische Tag-Familien und Parameter koennen nicht automatisch im Repository getestet werden.
