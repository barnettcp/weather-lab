# ADR-002: Analytics & Dashboard Behavior for Multi-Station / Multi-Model Data

**Status:** Accepted  
**Date:** 2026-10-06  

---

## Context

ADR-001 introduced multi-station and multi-model weather capture. After that change,
the analytics/dashboard layer still behaved like a single-station view in several places,
and some visualizations could unintentionally mix data dimensions in ways that were hard
to interpret.

Key issues observed during dashboard iteration:

- Need a clear default station experience for day-to-day use.
- Need a transparent meaning for aggregated station views.
- Need station-to-station comparison visuals that remain stable regardless of local
  station selection.
- Need geographic visualization with reliable attribution and no external API key setup.
- Need convergence plots that avoid model-mixing artifacts when "All models" is selected.
- Join logic must remain station-safe when comparing forecast vs actual.

---

## Decisions

### 1) Station selector default and aggregate label

- Default station selection is **SEAW1 / Seattle Sand Point**.
- Aggregated option is explicitly labeled **"All Stations (Mean)"**.

**Rationale:**  
Seattle Sand Point is a practical daily default. The aggregate option is retained as an
overview, but labeled to make its meaning explicit and avoid implying "best station."

### 2) Semantics of "All Stations (Mean)"

When "All Stations (Mean)" is selected for the main temperature line view:

- actual line = mean of station actual temperatures per target hour
- forecast line = mean of station forecast temperatures per target hour

**Rationale:**  
This provides a network-level overview while preserving single-station drill-down.

### 3) Station-safe forecast/actual joins

Forecast/actual joins must match on:

- `target_time` / `observed_time`
- `station_id`

**Rationale:**  
Timestamp-only joins can cross-contaminate station comparisons and distort model/station
analysis.

### 4) Station-to-station accuracy and map scope

The station accuracy bar chart and station map are computed from **all stations** by
default (still respecting selected date range and model filter), independent of the
main station selector used for the top line chart.

**Rationale:**  
The purpose of this section is cross-station comparison; filtering it to one selected
station removes that comparison value.

### 5) Shared station color system across visuals

A single station color palette is used for:

- station MAE bar chart
- station map pins
- station-differentiated convergence traces

Legends are hidden where redundant.

**Rationale:**  
Consistent color identity improves readability and lowers cognitive load across plots.

### 6) Geographic visualization choice

Station map is rendered as Plotly `scatter_mapbox` with:

- `mapbox_style="open-street-map"`
- explicit OSM attribution in UI copy
- no legend (colors align with adjacent bar chart)

**Rationale:**  
OpenStreetMap tiles provide a familiar, readable map backdrop in the dashboard panel and
fit the desired "map in tile" UX.

### 7) Convergence tab behavior by scope

Convergence views now have explicit scope rules:

1. **Forecast error by lead time**  
   Uses selected station/model/date filters.

2. **Forecast error by actual temperature**  
   Shows all configured stations together (respecting selected model/date), colored by station.

3. **Forecast convergence toward actual**  
   Always station-differentiated across all stations (respecting selected model/date).

**Rationale:**  
This keeps each visualization aligned to its analytic purpose while exposing station-level
behavior clearly.

### 8) Handling "All models" in convergence views

When model filter is **"All models"**, convergence data is collapsed to one value per:

- `station_id`
- `target_time`
- `lead_hours`

using mean aggregation prior to plotting.

**Rationale:**  
Without this, line traces can oscillate due to alternating model points at similar lead
times (visual flip-flop artifact), which can be mistaken for station behavior or data issues.

---

## Consequences

**Positive:**

- Dashboard semantics are explicit for station and model aggregation.
- Cross-station sections remain useful even when single-station is selected elsewhere.
- Convergence charts are less prone to misleading model-mixing artifacts.
- Forecast/actual joins are station-safe for multi-location analysis.
- Geographic panel is readable and consistently styled with nearby comparisons.

**Trade-offs:**

- "All Stations (Mean)" smooths true station-specific variability by design.
- Averaging "All models" hides model-specific divergence unless a single model is selected.
- OpenStreetMap tile rendering depends on external tile availability at runtime.

---

## Follow-ups

1. Add explicit **Model handling mode** in convergence:
   - selected model only
   - all-model mean (current behavior)
   - split by model (separate traces)

2. Add diagnostics panel for per-station/per-model row counts by lead bucket to detect
   data sparsity and sensor/reporting asymmetry.

3. Consider station legend ordering lock and optional pinned station hover summaries for
   improved interpretability.

