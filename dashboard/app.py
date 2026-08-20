from pathlib import Path

import streamlit as st

from src.models import OfficialFact, PublicSignal, SignalCategory
from src.collectors.social_data import load_public_reports
from src.processing.ridership import historical_demand_signal, hourly_baseline, load_ridership
from src.processing.signal_aggregation import aggregate_signals
from src.processing.station_mapping import load_station_mapping, station_names
from src.status import estimate_status

st.set_page_config(page_title="Kelana Jaya Monitor", page_icon="LRT", layout="wide")
st.title("Kelana Jaya Line")
st.caption("Current condition estimate | not an official transport announcement")

data_path = Path(__file__).parents[1] / "data" / "external" / "demo_ridership.csv"
ridership = load_ridership(data_path)
baseline = hourly_baseline(ridership)
station_path = Path(__file__).parents[1] / "data" / "external" / "kelana_jaya_stations.csv"
station_mapping = load_station_mapping(station_path)
official_stations = station_names(station_mapping)

expected_demand = 0.65
signal_station = "PASAR SENI"
crowding = 8
delays = 1

live_tab, historical_tab, reports_tab = st.tabs(["Live Data", "Historical Data", "Public Reports"])
with live_tab:
	st.warning("Live Kelana Jaya vehicle data is not currently stable in the official feed.")
	st.write("The status below is an estimate using historical demand and public-report signals.")
	st.caption("Official source checked: Malaysia data.gov.my Prasarana GTFS.")

with historical_tab:
	historical_upload = st.file_uploader("Upload ridership CSV", type="csv", help="Required columns: service_date, station, hour, passenger_count")
	if historical_upload is not None:
		ridership = load_ridership(historical_upload)
		baseline = hourly_baseline(ridership)
		st.success("Using uploaded historical ridership data.")
	else:
		st.warning("Demo data only: replace with verified ridership data when available.")
	history_left, history_right = st.columns([1, 2])
	with history_left:
		selected_station = st.selectbox("Station", sorted(baseline["station"].unique()))
		selected_hour = st.slider("Hour of day", 0, 23, 8)
		selected_baseline = baseline[
			(baseline["station"] == selected_station) & (baseline["hour"] == selected_hour)
		]
		expected_demand = historical_demand_signal(ridership, selected_station, selected_hour)
	with history_right:
		if selected_baseline.empty:
			st.info("No demonstration observation for this station and hour.")
		else:
			expected = selected_baseline.iloc[0]
			st.metric("Expected passengers", f"{expected['expected_passenger_count']:,.0f}")
			st.caption(f"Based on {int(expected['observations'])} demonstration observations")
		expected_demand = st.slider("Historical demand signal", 0.0, 1.0, expected_demand, 0.05)

with reports_tab:
	reports_upload = st.file_uploader("Upload public reports CSV", type="csv", help="Required columns: text, observed_at. Optional: author_id, source, station")
	if reports_upload is not None:
		try:
			uploaded_signals = load_public_reports(reports_upload, station_mapping)
			st.success(f"Loaded {len(uploaded_signals)} public-report signals.")
		except ValueError as error:
			st.error(str(error))
			uploaded_signals = []
	else:
		uploaded_signals = []
	st.info("Public reports are signals, not proof of actual passenger volume.")
	signal_station = st.selectbox("Station mentioned", official_stations, index=official_stations.index("PASAR SENI"))
	crowding = st.number_input("Crowding reports, last 15 minutes", min_value=0, value=crowding)
	delays = st.number_input("Delay reports, last 15 minutes", min_value=0, value=delays)

if uploaded_signals:
	signals = uploaded_signals
else:
	signals = [PublicSignal(f"crowding report {index}", SignalCategory.CROWDING, station=signal_station) for index in range(crowding)]
	signals.extend(PublicSignal(f"delay report {index}", SignalCategory.DELAY, station=signal_station) for index in range(delays))
estimate = estimate_status(expected_demand, signals, OfficialFact())
signal_summary = aggregate_signals(signals)

st.divider()
st.subheader("Estimated status")
status_left, status_middle, status_right = st.columns(3)
status_left.metric("Line status", estimate.level.value.replace("_", " ").title())
status_middle.metric("Crowding score", f"{estimate.crowding_score:.0%}")
status_right.metric("Confidence", f"{estimate.confidence:.0%}")

with st.expander("Evidence details"):
	st.write("**ESTIMATION**: " + " | ".join(estimate.rationale))
	st.write("**SIGNAL**: 15-minute station summary")
 
if signal_summary:
	st.dataframe(
		[
			{
				"Station": summary.station,
				"Observations": summary.total_observations,
				"Independent": summary.independent_observations,
				"Authors": summary.unique_authors,
				"Crowding": summary.crowding_reports,
				"Delays": summary.delay_reports,
				"Disruptions": summary.disruption_reports,
			}
			for summary in signal_summary
		],
		hide_index=True,
		use_container_width=True,
	)
