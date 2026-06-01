# TH Sammelbeschrifter Dynamo v6.5

## Änderung gegenüber v6.4

v6.5 korrigiert einen optischen Fehler im Beschrifterdialog:

- Zahlenfelder für **Textabstand** und **Zusatzabstand** sind breiter.
- Beschriftungstexte überlappen die Eingabefelder nicht mehr.
- Eingabefelder sind rechtsbündig ausgerichtet.
- Werte nahe 0 werden sauber als `0` angezeigt.
- Das Dialogfenster wurde geringfügig verbreitert.

Die Platzierungslogik aus v6.4 bleibt unverändert:

- Sammelblock oder Einzelbeschriftung per Checkbox.
- Übereinander / Nebeneinander.
- Zusatzabstand in mm im Plan, maßstabsabhängig.
- Außenkante über Gesamtmaß / DN-Wert.
- Führungslinie aus: Tagkopf auf Rohrachse.

## Empfehlung

Bei Maßstab 1:50:

- Zusatzabstand `1` = 50 mm im Modell.
- Zusatzabstand `0` = direkt an Außenkante/Dämmung.
