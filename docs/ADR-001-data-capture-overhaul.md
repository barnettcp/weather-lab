# ADR-001: Data Capture Overhaul — Multi-Location, Extended Fields, Schema Redesign

**Status:** Proposed  
**Date:** 2026-09-25  
**Relates to:** `notes/data_capture_overhaul.md`

---

## Context

The initial schema captured hourly temperature and apparent temperature for a single
location (Seattle Sand Point / SEAW1) using Open-Meteo forecasts and NWS actuals.
Several limitations motivated this overhaul:

- The Open-Meteo forecast lat/lon was not aligned with the NWS station location.
- Only temperature was captured, limiting future bias analysis to a single dimension.
- A single location cannot support the planned dashboard location selector.
- Dynamic NWS station discovery was fragile and stored state in a meta table.

The database is being dropped and rebuilt from scratch, making this a clean-slate schema
decision rather than a migration.

---

## Decisions

### 1. Multi-location via explicit `STATIONS` config

A `STATIONS` list of dicts replaces the single `LATITUDE`/`LONGITUDE` pair in
`config.py`. Station IDs, coordinates, and display names are co-located.

**Rationale:** All four locations are fetched on every run. The station ID is the
natural key for tying forecasts to actuals, and coordinates are aligned with the physical
station locations (fixing the original lat/lon misalignment).

Backward-compatibility aliases (`LATITUDE`, `LONGITUDE`) are added so that `analysis.py`
and `dashboard.py` — which are out of scope for this overhaul — continue to work.

### 2. `station_id` added to the `forecasts` table

The `forecasts` table previously used raw `latitude`/`longitude` as part of its dedup key.
A `station_id TEXT NOT NULL` column is added and becomes the primary dedup dimension
alongside `fetched_at`, `target_time`, and `model`.

**Rationale:** `station_id` is a more stable and readable dedup key than floating-point
coordinates, and it is required for future forecast-vs-actual joins by location.
`latitude` and `longitude` are retained as audit columns.

### 3. Five new fields — same columns in both `actuals` and `forecasts`

| Column | Unit |
|---|---|
| `cloud_cover_pct` | % (0–100) |
| `wind_speed_kmh` | km/h |
| `wind_direction_deg` | ° |
| `wind_gusts_kmh` | km/h |
| `precipitation_mm` | mm |

All five are nullable to accommodate sensor gaps in NWS observations.

**Rationale:** These are the fields available from both NWS and Open-Meteo that humans
notice directly and that are plausibly biased in forecast models. Using the same column
names and units in both tables simplifies future bias joins.

### 4. Unit normalization at write time

Open-Meteo returns wind in km/h; NWS returns wind in m/s. Open-Meteo returns
precipitation in mm; NWS returns it in meters. Conversion happens in the fetch scripts
before writing, so the database always stores a single consistent unit per field.

**Rationale:** Normalizing at the boundary keeps query logic simple and prevents
analysis bugs from silent unit mismatches.

### 5. NWS cloud cover categorical → numeric approximation

NWS `cloudLayers[*].amount` is a categorical string (`SKC`, `FEW`, `SCT`, `BKN`, `OVC`).
The highest-coverage layer reported is mapped to a percentage midpoint and stored as
`cloud_cover_pct`.

| NWS code | Stored % |
|---|---|
| SKC | 0 |
| FEW | 19 |
| SCT | 44 |
| BKN | 69 |
| OVC | 100 |

**Rationale:** Storing a numeric value makes `cloud_cover_pct` directly comparable to
Open-Meteo's continuous `cloud_cover` output. The approximation is intentional; exact
cloud-cover comparison is not a goal of this project.

### 6. Dynamic NWS station discovery removed

`fetch_actuals.py` previously called `/points/{lat,lon}/stations` to discover the
nearest station and cached the result in the `meta` table. With explicit station IDs in
`config.STATIONS`, this lookup is unnecessary.

**Rationale:** Explicit config is simpler, eliminates a network round-trip and a stateful
meta cache entry, and makes it obvious which station is being fetched. The four configured
station IDs (SEAW1, KPAE, KBLI, KCLS) are stable identifiers in the NWS system.

**Risk:** SEAW1 should be verified to work via direct `/stations/SEAW1/observations`
before the discovery code is deleted.

### 7. `station_id` added to `fetch_log`

A nullable `station_id TEXT` column is added to `fetch_log` so that per-station fetch
results can be distinguished when the multi-station loop writes one log entry per station.

---

## Consequences

**Positive:**
- Schema supports the planned dashboard location selector without further changes.
- Bias analysis can now cover wind, precipitation, and cloud cover in addition to temperature.
- Unit consistency removes a class of analysis bugs.
- Simpler fetch code (no dynamic discovery, explicit station loops).

**Negative / Trade-offs:**
- Five new nullable columns mean more NULLs in early data while stations occasionally
  fail to report sensors.
- Cloud cover is an approximation; the categorical-to-numeric mapping loses fidelity.
- `best_match` Open-Meteo model blends multiple underlying models; precipitation
  definitions may vary slightly between them.
- `analysis.py` and `dashboard.py` are not updated in this pass and will only work
  against the single SEAW1 location until a future overhaul.
