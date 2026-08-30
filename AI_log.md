# AI_log.md

## Tool and model

Claude (Claude Sonnet 5), accessed via the Claude.ai.

## Scope of AI assistance

AI assistance was used for **Task 5** (subsample, wind augmentation,
anonymisation) and for cleaning up this repository's documentation. Tasks 1
and 2 (extraction, H3 join) were implemented and debugged independently and
are not covered by this log.

| Area | What was asked | Turns (approx.) |
|---|---|---|
| Interpretation of "within 1 minute" | Clarifying whether the spec meant a time or a geographic distance | 2 |
| Task 5.1 review | Code review of the suburb-centroid/subsample module | 1 |
| Task 5.2/5.3 review | Adding explanatory comments in the style of Task 5.1; drafting `config/task5.yml` review | 1 |
| Debugging | Iteratively diagnosing and fixing a chain of runtime errors surfaced only when actually running the pipeline against real data (see below) | ~6 |


## Example: AI work that was wrong and had to be corrected

The clearest example arose during the Task 5.2 wind-data debugging. Working
from a real error traceback, the AI first assumed the source workbook was
genuinely an ODS file (matching its advertised filename and the challenge
brief's link) and proposed a fix that only handled network/retry failures.
When the pipeline was actually run against the live endpoint, this assumption
proved wrong: the endpoint served a valid XLSX file despite the `.ods` name.
The AI's first-pass fix did not anticipate this and failed on the first real
run with a `KeyError` inside the ODF parser.

The AI was given the actual traceback and corrected its approach: rather than
trusting the filename or URL, the fix was changed to inspect the file's
internal ZIP structure (`META-INF/manifest.xml` vs. `[Content_Types].xml`) to
detect the true format at runtime. This was a genuine correction driven by
real execution feedback, not something the AI got right on the first attempt.

A second, similar instance occurred with the workbook's internal structure:
the AI's first `normalise_wind_frame` implementation assumed a single flat
header row, which failed against the actual multi-station, two-row-header
layout used by the real 2020 workbook. This was only discovered from the
diagnostic output of a failed run and required a second, more substantial
rewrite (`normalise_multistation_wind_frame`) to correctly parse the file.

A third instance was a data-completeness issue rather than a code bug: an
early, arbitrary 5% maximum-unmatched-rate threshold (suggested by the AI
without reference to the actual wind station's coverage) caused the pipeline
to fail. Diagnosis showed the Atlantis station's 2020 export only covers
~101 of 366 days. The threshold was corrected to reflect this documented,
genuine limitation of the source data (65%), rather than being loosened
arbitrarily to make the error disappear.

## What was not delegated to AI

Running the pipeline, supplying real error tracebacks, verifying outputs,
choosing the final anonymisation thresholds and suburb selection, and all
final decisions about what to commit versus keep local (e.g. `.gitignore`
scope, restricted manual-review file handling) were done independently.