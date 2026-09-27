"""
Central configuration for the weather-bias-tracker project.
Edit LATITUDE / LONGITUDE / TIMEZONE for your actual location.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # load .env file if present, so we can override config values

# --- Locations ------------------------------------------------------------
# SEAW1 is the default / primary station (NOAA Western Regional Center, Seattle).
STATIONS = [
    {"id": "SEAW1", "latitude": 47.68528, "longitude": -122.25111, "name": "Seattle Sand Point"},
    {"id": "KPAE",  "latitude": 47.90510, "longitude": -122.28140, "name": "Seattle Paine Field"},
    {"id": "KBLI",  "latitude": 48.79911, "longitude": -122.54064, "name": "Bellingham Airport"},
    {"id": "KCLS",  "latitude": 46.67700, "longitude": -122.98280, "name": "Chehalis-Centralia Airport"},
]
# Backward-compat aliases so analysis.py and dashboard.py keep working unchanged.
LATITUDE  = STATIONS[0]["latitude"]
LONGITUDE = STATIONS[0]["longitude"]
TIMEZONE = "America/Los_Angeles"  # IANA tz name, used for the dashboard only;
                                  # all DB timestamps are stored in UTC.

# --- Storage ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "weather.db")

# --- Open-Meteo forecast settings ------------------------------------------
# Named models are fetched separately so each row has deterministic attribution.
FORECAST_MODELS = ["gfs_seamless", "ecmwf_ifs04"]
FORECAST_DAYS = 10          # how far ahead to pull each time we fetch
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# --- NWS (api.weather.gov) settings -----------------------------------------
NWS_BASE_URL = "https://api.weather.gov"
# NWS requires a descriptive User-Agent with contact info per their API rules.
NWS_USER_AGENT = os.environ.get(
    "NWS_USER_AGENT",
    "weather-lab-ml (no-contact-provided@example.com)"
)

# How far back to look each time we fetch actuals. NWS stations report every
# ~20-60 minutes, so pulling the last 2 days each run keeps things resilient
# to a missed cron run without re-querying huge windows.
ACTUALS_LOOKBACK_HOURS = 48
