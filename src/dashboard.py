"""Streamlit dashboard for the Mini Process Mining & ETL Pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


@st.cache_data
def load_dashboard_data() -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load all process-analysis outputs used by the dashboard."""
    required_files = {
        "summary": PROCESSED_DIR / "process_summary.json",
        "bottlenecks": PROCESSED_DIR / "bottlenecks.csv",
        "throughput": PROCESSED_DIR / "case_throughput.csv",
        "transitions": PROCESSED_DIR / "transition_durations.csv",
        "violations": PROCESSED_DIR / "sla_violations.csv",
    }
    missing_files = [path.name for path in required_files.values() if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            f"Missing processed files: {', '.join(missing_files)}. Run 'python src/process_analysis.py' first."
        )

    with required_files["summary"].open(encoding="utf-8") as summary_file:
        summary = json.load(summary_file)

    return (
        summary,
        pd.read_csv(required_files["bottlenecks"]),
        pd.read_csv(required_files["throughput"]),
        pd.read_csv(required_files["transitions"]),
        pd.read_csv(required_files["violations"]),
    )


@st.cache_data
def load_optional_json(file_name: str) -> dict | None:
    """Load an optional JSON analysis output when it has been generated."""
    file_path = PROCESSED_DIR / file_name
    if not file_path.exists():
        return None
    with file_path.open(encoding="utf-8") as json_file:
        return json.load(json_file)


@st.cache_data
def load_optional_csv(file_name: str) -> pd.DataFrame | None:
    """Load an optional CSV analysis output when it has been generated."""
    file_path = PROCESSED_DIR / file_name
    return pd.read_csv(file_path) if file_path.exists() else None


def main() -> None:
    """Render a simplified SAP-like process-mining dashboard."""
    st.set_page_config(page_title="Mini Process Mining & ETL Dashboard", layout="wide")
    st.title("Mini Process Mining & ETL Dashboard")
    st.write(
        "This dashboard visualizes a simplified SAP-like order process and shows ETL, "
        "SQL business logic, and process-mining results."
    )

    try:
        summary, bottlenecks, throughput, transitions, violations = load_dashboard_data()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        st.error(str(error))
        st.stop()

    kpi_columns = st.columns(4)
    kpi_columns[0].metric("Total Cases", f"{summary['total_cases']:,}")
    kpi_columns[1].metric("Total Events", f"{summary['total_events']:,}")
    kpi_columns[2].metric("Average Throughput Hours", f"{summary['average_throughput_hours']:.2f}")
    kpi_columns[3].metric("Total SLA Violations", f"{summary['total_sla_violations']:,}")

    st.subheader("Data Quality Summary")
    quality_summary = load_optional_json("data_quality_summary.json")
    if quality_summary is None:
        st.info("Data-quality results are not available yet. Run 'python src/data_quality.py'.")
    else:
        quality_columns = st.columns(2)
        quality_columns[0].metric("Data Quality Score", f"{quality_summary.get('data_quality_score', 0):.2f}/100")
        quality_columns[1].metric("Duplicate Events", quality_summary.get("duplicate_event_count", 0))
        st.caption(
            "Missing steps: "
            f"{quality_summary.get('cases_with_missing_steps', 0)} | "
            "Wrong event counts: "
            f"{quality_summary.get('cases_with_wrong_event_count', 0)} | "
            "Invalid activities: "
            f"{quality_summary.get('invalid_activity_count', 0)}"
        )

    st.subheader("Process Conformance")
    conformance_summary = load_optional_json("conformance_summary.json")
    conformance_report = load_optional_csv("conformance_report.csv")
    if conformance_summary is None or conformance_report is None:
        st.info("Conformance results are not available yet. Run 'python src/conformance_check.py'.")
    else:
        conformance_columns = st.columns(2)
        conformance_columns[0].metric(
            "Conformance Rate", f"{conformance_summary.get('conformance_rate_percent', 0):.2f}%"
        )
        conformance_columns[1].metric(
            "Non-Conformant Cases", conformance_summary.get("non_conformant_cases", 0)
        )
        non_conformant_cases = conformance_report[~conformance_report["is_conformant"].astype(bool)]
        if not non_conformant_cases.empty:
            st.dataframe(non_conformant_cases, use_container_width=True)

    st.subheader("Top Bottleneck")
    st.info(
        f"{summary['top_bottleneck_transition']} — "
        f"{summary['top_bottleneck_avg_hours']:.2f} average hours"
    )

    st.subheader("Bottleneck Chart")
    st.bar_chart(bottlenecks.set_index("transition")["average_duration_hours"])

    st.subheader("Regional Analysis")
    if "region" in transitions.columns:
        regions = sorted(transitions["region"].dropna().unique())
        if regions:
            selected_region = st.selectbox("Select a region", regions)
            regional_durations = (
                transitions[transitions["region"] == selected_region]
                .groupby("transition", as_index=False)["duration_hours"]
                .mean()
                .sort_values("duration_hours", ascending=False)
            )
            st.bar_chart(regional_durations.set_index("transition")["duration_hours"])
        else:
            st.info("No regional transition records are available.")
    else:
        st.info("Regional data is not available in transition_durations.csv.")

    st.subheader("SLA Violations")
    if violations.empty:
        st.success("No SLA violations were found.")
    else:
        st.dataframe(violations.sort_values("duration_hours", ascending=False), use_container_width=True)

    st.subheader("Case Throughput")
    st.dataframe(
        throughput.sort_values("throughput_hours", ascending=False).head(20),
        use_container_width=True,
    )

    st.subheader("Recommendations")
    recommendations = load_optional_csv("recommendations.csv")
    if recommendations is None:
        st.info("Recommendations are not available yet. Run 'python src/recommendations.py'.")
    else:
        priority_order = {"High": 0, "Medium": 1, "Low": 2}
        recommendations = recommendations.sort_values(
            "priority", key=lambda priority: priority.map(priority_order).fillna(99)
        )
        st.dataframe(recommendations, use_container_width=True)


if __name__ == "__main__":
    main()
