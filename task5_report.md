# Task 5: Further Data Transformations — Methodology & Justification

## 5.1 — Spatial Subsample Around an Atlantis-Area Suburb

**Suburb selected:** Robinvale, an official suburb in the City of Cape Town's
Political/Administrative Boundaries layer, in the immediate vicinity of Atlantis.

**Centroid method (no hardcoded coordinates):**
1. Suburb polygons were downloaded programmatically from the City of Cape Town's
   ArcGIS REST endpoint (`Political_Administrative_Boundaries/MapServer/4`,
   layer 4 = official suburbs), requested in WGS 84 (`EPSG:4326`) as GeoJSON.
   The response is cached to disk (`data/official_suburbs.geojson`); if the
   live request fails, the pipeline falls back to the last valid cache rather
   than hardcoding a boundary or a centroid value.
2. The Robinvale polygon(s) were selected by exact (case/whitespace-normalised)
   name match on the `OFC_SBRB_NAME` field.
3. The matched geometry was **reprojected to a metric CRS (`EPSG:32734`, UTM
   zone 34S)** before computing the centroid. Computing a centroid directly on
   unprojected lat/lon degrees distorts the result, since a degree of longitude
   and a degree of latitude do not represent equal ground distances — this is
   avoided by projecting to a metric, locally-appropriate CRS first.
4. The centroid was computed via `union_all().centroid` (Shapely/GeoPandas) on
   the reprojected geometry — a standard, verifiable computational method, not
   a hardcoded value.

**Interpretation of "within 1 minute":** the task's spatial-filtering context
(no timestamp is given as a reference point) indicates a geographic distance,
read as **1 arcminute** — the traditional degree/minute/second coordinate
convention. One arcminute of latitude is a constant ~1,852 m 
everywhere on Earth; one arcminute of longitude is ~1,852 m × cos(latitude),
i.e. ~1,540 m at Cape Town's latitude. Rather than use an anisotropic ellipse,
a straightforward circular buffer of **radius 1,852 m** was used as a
conservative, clearly-documented interpretation. Distance was computed as a
true Euclidean distance in the same metric CRS as the centroid (via
`GeoSeries.distance`), not an approximation. This produced a subsample of
**10,576 of 941,634** service requests.

---

## 5.2 — Wind Data Augmentation (Atlantis AQM Site, 2020)

**Download strategy for an unreliable endpoint:**
- Downloads use `tenacity` with exponential backoff and jitter (4 attempts,
  1–20s backoff), retrying only on `requests.RequestException` — this avoids
  retrying on logic errors (e.g. malformed content) that a retry cannot fix,
  while giving genuine transient network failures a fair chance to succeed.
- Successful downloads are cached to disk. If all retries are exhausted, the
  pipeline falls back to the last valid cached copy rather than failing
  outright, since the underlying dataset (fixed, historical 2020 readings)
  does not change between runs — a stale cache is not a correctness risk here,
  only a staleness risk, and is preferable to blocking the whole pipeline on
  a flaky endpoint. This differs from a live/streaming dataset, where a stale
  cache would be inappropriate.
- **This approach was validated against a real failure during development.**
  The response's format was initially assumed from the filename/URL (ODS), but
  inspection of the actual zip-container contents showed the endpoint serving
  a genuine XLSX file instead. Rather than trusting the file extension or
  advertised `DocumentName`, the code now inspects the zip's internal manifest
  (`META-INF/manifest.xml` vs `[Content_Types].xml`) to select the correct
  parsing engine at runtime — an example of an "unreliable dependency" that
  is unreliable in its *content*, not just its *availability*.

**Parsing strategy:** the workbook uses a wide, multi-station layout with a
two-row header (station name, then sub-metric per station), rather than a
single flat header — this was also discovered from a failed run's diagnostics
rather than assumed up front. The parser reads the two header rows as a
`MultiIndex`, flattens them, and selects the Atlantis-specific wind-direction
and wind-speed columns by name match.

**Join strategy:** each service request is matched to its **nearest** wind
observation in time via `pandas.merge_asof(direction="nearest")`, within a
90-minute tolerance, rather than an exact timestamp match (request creation
times rarely align exactly with the station's sampling interval). Both sides
are aligned to timezone-aware SAST (`Africa/Johannesburg`, UTC+02:00, no DST)
before the join, since request timestamps are timezone-aware and the parsed
wind timestamps are not — this was made explicit rather than allowing an
implicit/incorrect comparison. **Assumption, not independently verified:** the
station's timestamps are local SAST clock time, consistent with a
City-operated sensor; this has not been confirmed against station metadata
and is flagged here as an open assumption.

**A second, distinct form of "unreliable dependency" — data completeness:**
after resolving the format and timezone issues, ~59% of the 2020 subsample
requests still could not be matched to a wind observation within the
tolerance window. Diagnosis showed this was not a bug: the Atlantis AQM
station's 2020 export covers only **101 of 366 days (~28%)**, with additional
gaps within those days (2,324 total readings, versus ~24/day if fully
populated). This is a genuine limitation of the source data, not the join
logic. Rather than silently fabricating wind values for uncovered periods, or
hard-failing the whole pipeline on an arbitrarily-chosen match-rate threshold,
unmatched rows are enriched with null wind fields and the coverage gap is
logged explicitly. This choice prioritises transparency over an artificially
"clean" but misleading dataset.

---

## 5.3 — Anonymisation 

The augmented subsample is anonymised to preserve analytical usefulness while
reducing re-identification risk, as follows.

**Location, ~500 m:** raw latitude/longitude are dropped entirely and replaced
by a resolution-8 H3 index (already present in the joined dataset). A
resolution-8 H3 hexagon has an average edge length of ~461 m, meaning any
point's true location lies within its assigned cell's ~461 m circumradius —
closely matching the required "approximately 500 m" precision without
resorting to an arbitrary rounding scheme. Every H3 value is validated as a
genuine, resolution-8 cell before release, so a mis-joined or wrong-resolution
value cannot silently ship.

**Time, within 6 hours:** all timestamp columns (request creation,
completion, and matched wind observation) are floored — not rounded — to
6-hour buckets (00:00 / 06:00 / 12:00 / 18:00 SAST). Flooring guarantees the
published time is always earlier than or equal to the true time and never
more than 6 hours off in either direction, avoiding the subtler leak that
rounding-to-nearest would introduce (a value near a bucket edge would reveal
which side of the boundary the true time falls on more precisely than 6
hours allows).

**Direct identifiers:** `notification_number` and `reference_number` are
removed from the published table entirely. Rather than being discarded, they
are moved — keyed by a randomly generated `surrogate_id` (UUID4) — into a
separate, access-controlled manual-review table. This preserves the ability
for a human reviewer to re-link and manually assess these specific records
(as required) without exposing the identifiers in the general-release data.
The surrogate key is unlinkable to the source identifier without that
separate table.

**Residual risk — flagged, not yet resolved:** the current pipeline does not
inspect free-text fields (e.g. request description/notes), which are a common
vector for embedded personal detail (names, exact addresses, phone numbers)
in this class of civic dataset. These columns are not currently in the
released schema for this subsample, but any free-text column added in future
iterations should be routed to the same manual-review table rather than the
public output, pending a decision on redaction versus wholesale exclusion.

**Why this is now reasonably anonymised:** the combination of (1) removing
exact coordinates in favour of a ~500 m cell, (2) coarsening all timestamps to
a 6-hour window, and (3) isolating unique record identifiers to a
separately-controlled table means no single published row can be tied back to
an exact address, an exact time, or a unique government-issued reference
number. Re-identification would require an attacker to already possess
independent, precise knowledge of a specific resident's request — the dataset
itself no longer supplies that precision.
