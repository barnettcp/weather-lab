"""
Central configuration for the weather-bias-tracker project.
Edit LATITUDE / LONGITUDE / TIMEZONE for your actual location.
"""

import os

# --- Location -------------------------------------------------------------
# Defaults to Lynnwood, WA. Change these to your Pi's actual location.
LATITUDE = 47.8209
LONGITUDE = -122.3151
TIMEZONE = "America/Los_Angeles"  # IANA tz name, used for the dashboard only;
                                  # all DB timestamps are stored in UTC.

# --- Storage ----------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "weather.db")

# --- Open-Meteo forecast settings ------------------------------------------
# "best_match" lets Open-Meteo pick the best model for your location.
# You can instead pin a specific model (e.g. "gfs_seamless", "ecmwf_ifs04")
# if you want to study bias for one specific model rather than a blend.
FORECAST_MODEL = "best_match"
FORECAST_DAYS = 10          # how far ahead to pull each time we fetch
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# --- NWS (api.weather.gov) settings -----------------------------------------
NWS_BASE_URL = "https://api.weather.gov"
# NWS requires a descriptive User-Agent with contact info per their API rules.
NWS_USER_AGENT = "weather-bias-tracker (replace-with-your-email@example.com)"

# How far back to look each time we fetch actuals. NWS stations report every
# ~20-60 minutes, so pulling the last 2 days each run keeps things resilient
# to a missed cron run without re-querying huge windows.
ACTUALS_LOOKBACK_HOURS = 48
