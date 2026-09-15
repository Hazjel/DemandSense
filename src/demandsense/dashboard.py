from __future__ import annotations

import os

import requests
import streamlit as st

st.set_page_config(page_title="DemandSense", page_icon="📦", layout="wide")
st.title("DemandSense")
st.caption("Demand forecasting and inventory decision support — M0 technical foundation")

api_url = os.getenv("DEMANDSENSE_API_URL", "http://127.0.0.1:8000")
try:
    response = requests.get(f"{api_url}/health", timeout=3)
    response.raise_for_status()
    health = response.json()
    st.success(f"API connected · version {health['version']}")
except (requests.RequestException, KeyError, ValueError) as exc:
    st.warning(f"API is not available yet: {exc}")

st.info("Forecast and inventory views will be enabled after validated artifacts exist.")
