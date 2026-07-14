# Mini Process Mining & ETL Pipeline

An interview-preparation project for a Data Engineering & Process Optimization internship. It turns simulated SAP-like order events into clean, queryable process insights.

## Motivation

The project demonstrates a small end-to-end data workflow: generating realistic operational data, applying ETL, loading a database, analysing process performance, and presenting the results in a dashboard.

## Scenario

A company processes 600 orders through six steps: Order Created, Order Approved, Production Started, Quality Check, Shipping Started, and Delivered. The simulated data includes regional differences, priority orders, quantity variation, waiting times, bottlenecks, and SLA violations.

## Tech Stack

- Python
- pandas
- SQLite
- Streamlit

## Project Structure

```text
bosch-process-mining-etl/
├── data/
│   ├── raw/                 # Generated SAP-like event log
│   └── processed/           # Cleaned data and process-analysis outputs
├── src/
│   ├── generate_data.py     # Step 1: source data generation
│   ├── extract.py           # Step 2: extract stage
│   ├── transform.py         # Step 2: transform stage
│   ├── load.py              # Step 2: SQLite load stage
│   ├── main.py              # Step 2: ETL pipeline entry point
│   ├── process_analysis.py  # Steps 3–4: process mining analysis
│   ├── dashboard.py         # Step 5: Streamlit dashboard
│   ├── data_quality.py      # Advanced: ETL data-quality checks
│   ├── conformance_check.py # Advanced: process-conformance check
│   └── recommendations.py   # Advanced: rule-based recommendations
├── sql/
│   └── business_queries.sql # Step 3: business SQL queries
├── requirements.txt
└── README.md
```

## How to Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Generate the raw event log:

```bash
python src/generate_data.py
```

Run the ETL pipeline to create the cleaned CSV and SQLite database:

```bash
python src/main.py
```

Run process analysis to create bottleneck, throughput, and SLA outputs:

```bash
python src/process_analysis.py
```

Run the advanced analysis checks and recommendation layer:

```bash
python src/data_quality.py
python src/conformance_check.py
python src/recommendations.py
```

Start the dashboard:

```bash
streamlit run src/dashboard.py
```

## What Each Step Does

1. **Data generation:** Creates 3,600 deterministic, SAP-like process events for 600 orders.
2. **ETL pipeline:** Extracts raw CSV data, validates and enriches it, then loads it into SQLite.
3. **SQL business logic:** Provides reusable queries for regional volume, quantities, priorities, activities, and customers.
4. **Process analysis:** Calculates transition durations, case throughput, bottlenecks, and SLA violations in a simplified Celonis-style analysis.
5. **Dashboard:** Displays KPIs, bottlenecks, regional duration analysis, SLA violations, and slowest cases.
6. **Advanced analysis:** Checks data quality, validates process conformance, and produces rule-based recommendations.

## Data Quality Checks

Run `python src/data_quality.py` after the ETL pipeline to check the cleaned event log for missing values, duplicate events, missing process steps, timestamp-order issues, incorrect event counts, and invalid activities. The script saves a detailed CSV report, a JSON summary, and a `data_quality_report` table in SQLite.

## Process Conformance Check

Run `python src/conformance_check.py` after the ETL pipeline to compare every order case with the expected six-step process. It identifies missing steps, unexpected activities, and incorrect activity order, then saves a CSV report, a JSON summary, and a `conformance_report` table in SQLite.

## Relevance to Data Engineering & Process Optimization

This project mirrors typical internship tasks: building reliable data pipelines, cleaning operational source data, maintaining a SQL-ready data store, defining business metrics, and translating event data into process-improvement opportunities. It also demonstrates how to identify long waits and SLA risks that process owners can investigate.


