# TH Sammelbeschrifter v1.7

## Ablauf
1. Dynamo Player starten und `run=True` setzen.
2. Elemente in gewünschter Reihenfolge auswählen.
3. Parameterdialog (Windows Forms) öffnen:
   - Parameter aus ComboBox wählen und mit **Hinzufügen** übernehmen
   - Reihenfolge mit **Hoch/Runter** steuern
   - **Parameternamen im Text anzeigen** optional aktivieren
   - **Farbe aus Ansicht übernehmen** optional aktivieren
   - Mindestabstand in mm setzen
4. Punkt 1 wählen (Startposition erster Tag).
5. Punkt 2 wählen (Richtung + Abstand, horizontal/vertikal).
6. Tags werden erstellt und Texte in `TH_Beschriftungstext` geschrieben.

## Bekannte Einschränkungen
- Der Dialog nutzt Windows Forms und ist auf Desktop-Revit/Dynamo Player ausgelegt.
- Für die Textanzeige muss die Tag-Familie auf `TH_Beschriftungstext` parametriert sein.
- Die Farbermittlung aus Filtern hängt von der Filter-Sichtbarkeit und Reihenfolge in der aktiven Ansicht ab.
