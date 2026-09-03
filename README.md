# Mini Process Mining & ETL Pipeline

Ein Projekt, das ein reales Event-Log per ETL-Pipeline aufbereitet, mit Process-Mining-Methoden auswertet und die Ergebnisse in einem Dashboard darstellt.

## Motivation

Dieses Projekt entstand als frei gewähltes Portfolio-Projekt im Rahmen des Kurses „Datenmanagement und Datenbanksysteme" (DMDS) an der Technischen Hochschule Würzburg-Schweinfurt (THWS), der Datenmodellierung, ETL-Prozesse und Datenbanksysteme behandelt. Das Thema wurde frei gewählt; das Projekt zeigt einen kleinen, durchgängigen Datenworkflow: Extraktion, Bereinigung und Laden eines realen Event-Logs, Analyse der Prozessleistung und Darstellung der Ergebnisse in einem Dashboard.

## Szenario

Die Pipeline verarbeitet das BPI-Challenge-2012-Event-Log, einen öffentlich verfügbaren Datensatz aus dem Kreditantragsprozess eines niederländischen Finanzinstituts. Er umfasst rund 13.000 Anträge (Cases) und 262.000 Events über 24 unterschiedliche Aktivitäten (z. B. `A_SUBMITTED`, `W_Completeren aanvraag`, `O_SELECTED`), jeweils erfasst mit einer Lifecycle-Phase (SCHEDULE/START/COMPLETE), einer Ressource — oder keiner, bei systemautomatisierten Schritten — sowie dem beantragten Kreditbetrag. Anders als bei einem festen sechsstufigen Prozess variieren die Cases frei in Länge und Aktivitätsreihenfolge, was reales Verhalten von Antragstellern und Sachbearbeitern widerspiegelt.

## Tech-Stack

- Python
- pandas
- SQLite
- Streamlit

## Projektstruktur

```text
bosch-process-mining-etl/
├── data/
│   ├── raw/                 # Rohes Event-Log
│   └── processed/           # Bereinigte Daten und Process-Analysis-Outputs
├── src/
│   ├── generate_data.py     # Schritt 1: Generierung von Beispieldaten
│   ├── extract.py           # Schritt 2: Extract-Stufe
│   ├── transform.py         # Schritt 2: Transform-Stufe
│   ├── load.py              # Schritt 2: SQLite-Load-Stufe
│   ├── main.py               # Schritt 2: Einstiegspunkt der ETL-Pipeline
│   ├── process_analysis.py  # Schritte 3–4: Process-Mining-Analyse
│   ├── dashboard.py          # Schritt 5: Streamlit-Dashboard
│   ├── data_quality.py       # Erweitert: ETL-Datenqualitätsprüfungen
│   ├── conformance_check.py  # Erweitert: Prozesskonformitätsprüfung
│   └── recommendations.py    # Erweitert: regelbasierte Empfehlungen
├── sql/
│   └── business_queries.sql  # Schritt 3: fachliche SQL-Abfragen
├── requirements.txt
└── README.md
```

## Ausführung

Abhängigkeiten installieren:

```bash
pip install -r requirements.txt
```

Rohes Event-Log erzeugen:

```bash
python src/generate_data.py
```

ETL-Pipeline ausführen, um die bereinigte CSV-Datei und die SQLite-Datenbank zu erzeugen:

```bash
python src/main.py
```

Process-Analysis ausführen, um Bottleneck-, Durchlaufzeit- und SLA-Outputs zu erzeugen:

```bash
python src/process_analysis.py
```

Erweiterte Analysen und die Empfehlungsschicht ausführen:

```bash
python src/data_quality.py
python src/conformance_check.py
python src/recommendations.py
```

Dashboard starten:

```bash
streamlit run src/dashboard.py
```

## Was jeder Schritt macht

1. **Datengenerierung / Datenquelle:** Liefert das rohe Event-Log als Ausgangsbasis für die Pipeline.
2. **ETL-Pipeline:** Extrahiert die rohen CSV-Daten, validiert und reichert sie an und lädt sie anschließend in SQLite.
3. **SQL-Fachlogik:** Stellt wiederverwendbare Abfragen für regionale Volumina, Mengen, Prioritäten, Aktivitäten und Kunden bereit.
4. **Process-Analysis:** Berechnet Übergangsdauern, Case-Durchlaufzeiten, Bottlenecks und SLA-Verletzungen in einer vereinfachten, an Celonis angelehnten Analyse.
5. **Dashboard:** Zeigt KPIs, Bottlenecks, regionale Dauer-Analysen, SLA-Verletzungen und die langsamsten Cases.
6. **Erweiterte Analyse:** Prüft die Datenqualität, validiert die Prozesskonformität und erzeugt regelbasierte Empfehlungen.

## Datenqualitätsprüfungen

`python src/data_quality.py` nach der ETL-Pipeline ausführen, um das bereinigte Event-Log auf fehlende Werte, doppelte Events, fehlende Prozessschritte, Probleme in der zeitlichen Reihenfolge, falsche Event-Anzahlen und ungültige Aktivitäten zu prüfen. Das Skript speichert einen detaillierten CSV-Bericht, eine JSON-Zusammenfassung sowie eine Tabelle `data_quality_report` in SQLite.

## Prozesskonformitätsprüfung

`python src/conformance_check.py` nach der ETL-Pipeline ausführen, um jeden Case mit dem erwarteten Referenzprozess zu vergleichen. Das Skript identifiziert fehlende Schritte, unerwartete Aktivitäten und falsche Aktivitätsreihenfolgen und speichert einen CSV-Bericht, eine JSON-Zusammenfassung sowie eine Tabelle `conformance_report` in SQLite.

## Bezug zu Datenmanagement und ETL-Prozessen

Dieses Projekt wendet zentrale Inhalte des DMDS-Kurses praktisch an: den Aufbau einer belastbaren Datenpipeline, die Bereinigung realer, unvollständiger Prozessdaten, die Pflege eines SQL-fähigen Datenspeichers, die Definition fachlicher Kennzahlen sowie die Übersetzung von Event-Daten in Aussagen zur Prozessverbesserung. Es zeigt außerdem, wie sich aus einem realen Event-Log lange Wartezeiten, SLA-Risiken und Konformitätsabweichungen identifizieren lassen.
