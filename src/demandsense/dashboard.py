from __future__ import annotations

import os

import requests
import streamlit as st

st.set_page_config(page_title="DemandSense", page_icon="📦", layout="wide")
st.title("DemandSense")
st.caption("Demand forecasting and inventory decision support — M1 complete")

api_url = os.getenv("DEMANDSENSE_API_URL", "http://127.0.0.1:8000")
try:
    response = requests.get(f"{api_url}/health", timeout=3)
    response.raise_for_status()
    health = response.json()
    st.success(f"API connected · version {health['version']}")
    metadata_response = requests.get(f"{api_url}/metadata", timeout=3)
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    if metadata.get("dataset_version") != "not_prepared":
        st.success(
            "Validated dataset · "
            f"{metadata['dataset_version']} · "
            f"{metadata.get('series_count', 0)} series"
        )
    else:
        st.info("No validated dataset metadata is available to the API yet.")
except (requests.RequestException, KeyError, ValueError) as exc:
    st.warning(f"API is not available yet: {exc}")

st.info("Forecast and inventory views are scheduled for the application milestone.")
