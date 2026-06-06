# TH Sammelbeschrifter Dynamo v1.6

Diese Version behebt den in der Issues-CSV gemeldeten Python-Syntaxfehler:

`SyntaxError: EOL while scanning string literal`

Ursache war eine lange Rückmelde-Zeile nach der Rohrauswahl. In v1.6 ist diese Meldung technisch vereinfacht und ohne kritische Zeilenumbruch-Escapes umgesetzt.

## Ablauf im Dynamo Player

1. Script starten
2. Rohre in gewünschter Reihenfolge auswählen
3. Auswahl abschließen
4. Meldung bestätigen
5. Parameter auswählen, auch mehrere
6. Punkt für den 1. Beschrifter setzen
7. Punkt für den 2. Beschrifter setzen
8. Weitere Beschrifter werden gleichmäßig horizontal oder vertikal platziert

## Voraussetzung

Die Tag-Familie muss den gemeinsamen Textparameter `TH_Beschriftungstext` anzeigen. Das Script schreibt den aus den gewählten Parametern gebildeten Text in diesen Parameter.
