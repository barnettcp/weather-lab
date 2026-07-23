# weather-lab

A personal data collection and analysis project for studying **forecast bias** in hourly temperature predictions. The system gathers forecasts from [Open-Meteo](https://open-meteo.com/) alongside actual observations from the nearest [National Weather Service](https://www.weather.gov/documentation/services-web-api) (NWS) station, stores everything in a local SQLite database, and exposes the data through an interactive Streamlit dashboard.

The central question being investigated: *do temperature forecasts for hot days run systematically colder (or warmer) than what actually happens, and does that bias vary with lead time?*

---

## Project Structure

| File | Description |
|---|---|
| `config.py` | Central configuration: location, data paths, API settings |
| `db.py` | SQLite schema initialization |
| `fetch_forecast.py` | Pulls hourly forecast data from Open-Meteo and stores it |
| `fetch_actuals.py` | Fetches recent NWS station observations and stores them |
| `analysis.py` | Core logic for joining forecasts to actuals and computing bias |
| `dashboard.py` | Streamlit app for exploring bias interactively |

Data is stored under `data/weather.db` (created on first run of `db.py`).

---

## How It Works

### Forecast Collection

`fetch_forecast.py` calls the Open-Meteo API, which returns the full hourly forecast for the next `FORECAST_DAYS` days (default: 10) in a single request. Each hourly point is stored with two timestamps: `fetched_at` (when the request was made) and `target_time` (the hour being predicted). Lead time in hours is derived from the difference between those two values.

Running the fetch script multiple times per day — for example via cron at 00:00, 06:00, 12:00, and 18:00 — captures how the forecast for a given target hour evolves as lead time shrinks. This is what makes bias analysis by lead time possible.

### Actuals Collection

`fetch_actuals.py` identifies the nearest NWS observation station to the configured lat/lon (cached after the first lookup) and retrieves the last `ACTUALS_LOOKBACK_HOURS` of real observations (default: 48 hours), bucketed to the nearest hour. Because each run backfills a rolling window, running this once per day is sufficient and resilient to a missed run.

### Bias Analysis

The dashboard joins forecast rows to actual rows on `target_time`. A forecast only enters the analysis once its target hour is in the past **and** a matching actual observation has been recorded — so meaningful results require at least a day or two of collected data, and statistical confidence in temperature-bucket comparisons requires a few weeks of data spanning a range of conditions.

Bias is visualized by:
- **Lead time** — does accuracy degrade as the forecast looks further out?
- **Actual temperature bucket** — are warm-day forecasts systematically off in one direction?
- **Cross-tab of both** — where in the lead-time × temperature space does bias concentrate?

The dashboard buckets by *actual* recorded temperature (not forecast temperature) to avoid circular bias in the grouping.

---

## Configuration

All settings live in `config.py`:

- **`LATITUDE` / `LONGITUDE`** — location to forecast for (defaults to Lynnwood, WA)
- **`TIMEZONE`** — IANA timezone name, used for display only; all database timestamps are stored in UTC
- **`FORECAST_MODEL`** — defaults to `"best_match"`, which lets Open-Meteo select the best available model per location and lead time. Pin this to a specific model (e.g. `"gfs_seamless"`, `"ecmwf_ifs04"`) to study a single model's bias in isolation rather than a blended signal
- **`NWS_USER_AGENT`** — NWS requires a descriptive User-Agent string including contact information; update this before running

---

## Dependencies

```
requests >= 2.31
pandas >= 2.0
streamlit >= 1.35
```

Install into a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## Running

Initialize the database (one-time):

```bash
python3 db.py
```

Fetch data:

```bash
python3 fetch_forecast.py
python3 fetch_actuals.py
```

Launch the dashboard:

```bash
streamlit run dashboard.py
# To expose on your local network:
streamlit run dashboard.py --server.address 0.0.0.0
```

---

## Scheduling (Raspberry Pi / Linux)

Example crontab (`crontab -e`) for continuous collection:

```cron
# Forecast: 4 snapshots per day to capture lead-time evolution
0 0,6,12,18 * * * cd /home/pi/weather-lab && venv/bin/python3 fetch_forecast.py >> logs/forecast.log 2>&1

# Actuals: once daily, rolling 48-hour backfill
15 3 * * * cd /home/pi/weather-lab && venv/bin/python3 fetch_actuals.py >> logs/actuals.log 2>&1
```

Create the log directory first: `mkdir -p logs`.

---

## AI Assistance Disclaimer

This project was developed with the assistance of AI tools — specifically, [Claude](https://www.anthropic.com/claude) models accessed via [GitHub Copilot](https://github.com/features/copilot). AI assistance was used for code generation, architecture design, and documentation drafting. All code has been reviewed and is maintained by the project author.
