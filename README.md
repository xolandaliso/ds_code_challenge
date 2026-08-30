<img src="img/city_emblem.png" alt="City Logo"/>

# COCT Attempt of the Data Engineer Challenge

A reproducible Python solution for Data Engineering Tasks 1, 2, and 5.

## 1. AWS Credentials

Task 1 uses S3 Select, which does not permit anonymous requests. Set this up
**before** installing dependencies or running the pipeline — both the venv
and Docker paths below depend on `.env` already existing.

Download the temporary credentials supplied with the challenge:

[Challenge AWS credentials](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/ds_code_challenge_creds.json)

Create the local environment file:

```bash
cp .env.example .env
```

Add the supplied values to `.env`:

```env
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
```

The `.env` file contains credentials and must not be committed.

## 2. Installation and Run

Python 3.11 or later is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

The pipeline runs without interactive input once dependencies and
credentials have been configured.

If you prefer Docker, build and run **after** `.env` has been created — the
`--env-file` flag loads the credentials into the container, and the image's
entrypoint runs the pipeline directly, so no separate `python -m src.main`
step is needed:

```bash
docker build -t cct-de-challenge .
docker run --rm \
  --env-file .env \
  -v "$(pwd)/outputs:/app/outputs" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/data:/app/data" \
  cct-de-challenge
```

## 3. Run the Tests

```bash
python -m pytest -v
```

The tests run offline using synthetic inputs and mocked network dependencies.
They cover:

* S3 Select response parsing and failure handling
* schema-conformance scoring
* Task 1 reference validation
* H3 resolution and missing-coordinate handling
* join thresholds and reference validation
* official-suburb centroid calculation
* metric-radius filtering
* wind-workbook normalisation and caching
* temporal wind matching
* H3 and timestamp anonymisation controls

The current suite contains 37 passing tests.

## Outputs

| Task              | Output                                                        |
| ----------------- | -------------------------------------------------------------- |
| Task 1            | `outputs/task1_extracted_features.json`                        |
| Task 2            | `outputs/sr_hex_joined.csv`                                    |
| Task 5.1          | `outputs/task5_1_subsample.csv`                                 |
| Task 5.2          | `outputs/task5_2_augmented.csv`                                 |
| Task 5.3          | `outputs/task5_3_anonymised.csv`                                |
| Controlled review | `outputs/restricted_manual_review/task5_3_manual_review.csv`   |
| Logs              | `logs/ds_code_challenge_*.log`                                  |

The controlled-review file contains direct identifiers. It must not be
published or committed.

## Design

### Task 1 — Extraction and Validation

`src/extract.py` uses S3 Select to retrieve resolution-8 features directly
from `city-hex-polygons-8-10.geojson` without downloading the complete
mixed-resolution file. Extraction fails explicitly if S3 Select fails or
returns no records.

The extracted indexes are compared with the supplied `city-hex-polygons-8.geojson`
reference dataset. A separate, non-binary schema-conformance score validates
feature properties and polygon geometry against the rules in
`config/hex_schema.yml`.

Extraction, schema validation, and reference validation are timed and logged
separately.

### Task 2 — Request-to-H3 Transformation

`src/transform_join.py` converts valid service-request coordinates to H3
resolution-8 indexes:

* rows with missing latitude or longitude receive the index `"0"`
* invalid, non-null coordinates receive `"join_failed"`
* valid H3 indexes outside the supplied City polygon coverage are retained
  but counted as coverage failures
* the failure rate excludes rows with missing coordinates
* the pipeline stops if the configured 2% failure threshold is exceeded

The threshold and its rationale are documented in `config/join_config.yml`.

`src/validate_join.py` performs a row-level comparison with the supplied
`sr_hex.csv.gz` reference dataset — verifying row count, row alignment using
the configured identifier columns, and the generated H3 value. The pipeline
requires an exact reference match.

### Task 5.1 — Suburb-Centroid Subsample

The City's Official Suburb layer does not contain a polygon named
`Atlantis`. `ROBINVALE` was selected as an official suburb in the Atlantis
area.

`src/subsample_atlantis.py` programmatically downloads the City of Cape
Town Official Suburb polygon layer, selects Robinvale by name, and
calculates its centroid. The geometry is projected from WGS 84
(`EPSG:4326`) to WGS 84 / UTM zone 34S (`EPSG:32734`) before calculating the
centroid and distances in metres.

The phrase "within 1 minute" in the challenge is interpreted as a radial
separation of one minute of arc:

$$
1\text{ arc-minute}\approx1.852\text{ km}.
$$

Requests within 1,852 metres of the calculated centroid are retained. The
centroid is never hard-coded. A successful official-layer download is
cached so the pipeline can recover from temporary service failures.

Official suburb source:
[City of Cape Town Official Suburb layer](https://citymaps.capetown.gov.za/agsext/rest/services/Theme_Based/Political_Administrative_Boundaries/MapServer/4)

### Task 5.2 — Wind Enrichment

The original ODS link supplied in the challenge is no longer available. The
pipeline therefore downloads the current official City of Cape Town Wind
2020 Excel workbook from ArcGIS:

[City of Cape Town Wind 2020](https://www.arcgis.com/home/item.html?id=31ef242a23484e79bbb19d6b29203179)

`src/augment_wind.py`:

* retries temporary HTTP failures using exponential backoff and jitter
* verifies that the response is a valid ZIP-based spreadsheet
* caches the most recent successful download
* detects whether the workbook is ODS or XLSX from its internal structure
* identifies the Atlantis AQM wind-direction and wind-speed columns
* joins each request to the nearest wind observation within 90 minutes
* preserves the original request order
* records the temporal offset between the request and wind observation
* stops if the configured maximum unmatched rate is exceeded

The Atlantis series contains 2,324 observations covering 101 distinct days
in 2020. In the latest pipeline run, 4,288 of 10,576 requests were matched
and 6,288 remained unmatched, giving an unmatched rate of 59.46%. Unmatched
requests retain null wind values rather than receiving imputed
measurements. The configured 65% maximum reflects this documented
limitation of the supplied source.

### Task 5.3 — Anonymisation

`src/anonymize.py` creates a publication dataset with reduced spatial and
temporal precision.

Raw latitude and longitude are removed. Location is retained only as an H3
resolution-8 index, representing an approximate spatial precision of 500
metres. Creation, completion, and wind timestamps are floored to fixed
six-hour intervals.

`notification_number` and `reference_number` are removed from the
publication dataset and placed in a separately controlled manual-review
table. A randomly generated surrogate identifier links a publication row to
its controlled-review record without exposing the original identifiers.

The supplied service-request dataset contains no resident name, address,
contact number, or free-text description. The notification and reference
numbers are therefore the principal remaining direct identifiers. The
controlled-review file must be handled separately and must not be
published.

These measures reduce the precision of location and time, remove direct
identifiers, and preserve only the fields required for analysis. However,
anonymisation is treated as a risk-reduction process rather than a
guarantee. Records in the controlled-review table require manual assessment
before any release.

## Configuration

Reviewable schemas, field mappings, thresholds, and Task 5 parameters are
stored in:

```text
config/hex_schema.yml
config/join_config.yml
config/task5.yml
```

This keeps data-quality expectations and operational thresholds separate
from the implementation.

## Repository Structure

```text
config/                     Schemas, mappings and thresholds
src/main.py                 Non-interactive pipeline entrypoint
src/utils.py                Shared timing, YAML and S3 helpers
src/extract.py              Task 1 S3 Select extraction
src/validate_extraction.py  Task 1 reference validation
src/schema_conformance.py   Task 1 conformance scoring
src/transform_join.py       Task 2 H3 assignment
src/validate_join.py        Task 2 reference validation
src/subsample_atlantis.py   Task 5.1 centroid and spatial filter
src/augment_wind.py         Task 5.2 wind download and enrichment
src/anonymize.py            Task 5.3 privacy transformation
tests/                      Offline test suite
AI_log.md                   Record of AI-assisted work
```

## Generated and Sensitive Files

The following must not be committed:

* `.env`
* downloaded source-data caches
* pipeline outputs
* log files
* the controlled manual-review dataset
* Python virtual environments
* Python cache files

# i keep the original below this

-------

## Original challenge brief

The original City of Cape Town challenge description may be retained below this section for reference.


# City of Cape Town - Data Science Unit Code Challenge

## Purpose

The purpose of this challenge is to evaluate the skills of prospective Data Scientists, Engineers, Analysts and Front End Developer for positions in the City of Cape Town's Data Science unit. 

## Intended audience

We will only evaluate responses to this challenge from people who we have requested to complete it. Of course, you are welcome to attempt it for your own enjoyment.

## Way of working and expected structure of submission
Principles of reproducible analysis and code versioning are very important to our workflow. Structuring your work to aid in reproducibility and readability is important. 

So, follow common conventions with respect to directory structure and names to make your work as easy to follow as possible.

## What we're looking for
### Expectation of Effort
We expect you to spend up to 48 calendar hours working on this assessment per position. If you are finding that you are spending significantly more time than this, then please contact whomever sent you the link to this assessment to let them know.

You should have received over 7 days warning that you would be undertaking this assessment. Please notify [Delyno du Toit](delyno.dutoit@capetown.gov.za) if this was not the case.

### Things to focus on
Over and above the tasks specified below, there are particular aspects of each position that we would like you to pay attention to:

* Data Scientist candidates - we're looking for both good, statistical insight into problems, as well as the ability to communicate complex topics. Please make special effort to highlight what you believe to be the crux of a particular problem, as well as how your work addresses it.
* Data Engineer candidates - as the key enablers of our unit's work, we really want to see work done in a sustainable manner: writing for easy comprehension, testing, clean code, modularity all bring us joy.
* Data Analyst candidates - we think our analysts have done a good job when they provide insights that inform actual decisions. Hence, we want evidence of both the ability to surface these insights from data, as well as the skill to convey those insights. Your audience is intelligent, but non-specialist.

### Candidates where programming is required (Data Scientist; Engineers, Visualisation Engineer and Front End Developers)
Requirements and notes:
* For Data Science and Data Engineering, our primary programming languages are `python`, `R` and `SQL`. We will accept code that is packaged in `.py`, `.ipynb`, `.R` and `.Rmd` files. Scripts in `.sql` may also be included where applicable.
* Data Visualisation engineers and Front End Developers should have knowledge of either `python` or `R`, and relevant front-end programming languages (e.g. Javascript, HTML, CSS). We will accept code that is packaged in `.py`, `.R` and appropriate front-end programming language specific files, e.g. `.js`, `.html` etc. Furthermore, we greatly appreciate adherence to the principles and guidelines of [Single Page Applications](https://en.wikipedia.org/wiki/Single-page_application).
* Bash or similar scripting language files are fine for glue. You may develop in any development environment you choose. 
* We expect to be able to clone your repo, immediately identify what script to execute from your README file, and execute it to completion with no human interaction. 
  In order to ensure that our environment has the right libraries or packages, please follow standard python (PEP8) or R guidelines for structure in your code, i.e place `import` and `library()` commands at the top of your scripts.
* If your repo does not clone and run, we will not attempt to fix it.
* If your analysis makes use of any external data, the data must either be included in the repo, or be downloaded automatically during script execution.

### Candidates where programming is not required (Data Analysts)
*Note* If you prefer, you may submit using the requirements described above.

You can use any tool to produce the output, e.g. Python, R, Excel, Power BI, Tableau, etc. The **final deliverable needs to be a pdf report** with your analysis.

### Follow-on Questions
If we invite you to an interview, after completing and submitting this technical assessment, we will be asking follow-up 
questions about the work submitted. These questions might be at a very detailed level, or broadly conceptual, relating to 
the choices made in completing this assessment.

We do not expect perfect recall of what you may have submitted, but we do expect a deep knowledge of the content, and 
how it works.

### Use of Generative AI and/or Coding Agents
There is no restriction on the tools that you may use to complete this assessment. However we have tried to make the nature of this assessment within the scope of someone completing it without using AI assistance, as well as someone using them effectively.

If you do make use of Generative AI/Coding Agents, please include an `AI_log.md` where you log all of the work that you asked AI assistance to undertake, including any prompts, the model used as well number of tokens. It will be of considerable advantage if you can highlight or document at least one instance where the AI undertook work that you then corrected or improved upon.

## How to submit
### Candidates where programming is required (Data Scientist;  Engineers, Visualisation Engineers and Front End Developers)
1. Clone this repository and load it into your development environment. 
2. Work the challenge, committing regularly to document your progress. Try have structured, meaningful commits, where each one adds significant functionality in a coherent manner.
3. Host your repository somewhere that is publicly accessible. If you're using GitHub, please use a fork of our original repository.
4. Inform us via email that your challenge is complete, including a link to your repo. Be sure to make sure it is set to public.

**Be sure to 'watch' this repo for changes - we may push bugfixes**

NOTE: If you would like to _improve_ the content of this repository, by fixing typos or perhaps enhancing the challenge, please do so by submitting a pull request.

### Candidates where programming is not required (Data Analysts)
*NB* If you prefer, you may submit using the workflow described above.

1. Download this repository using the Code -> `Download ZIP` option in the top right-hand corner.
2. Add your work into this folder.
3. Create a compressed archive file with all of your work in it.
4. Send us an email, with your archived project attached. If it is larger than 10 MB, then share it via a cloud storage service such as DropBox, and include the link in your email. 

## Challenge
Follow the below steps, completing those indicated as relevant to the positions for which you are interviewing. If there are any steps that you can not complete after a reasonable amount of effort, rather move on to later steps, attempting everything relevant at least once.

For all roles, we expect the challenge response to include what you consider to be role-appropriate testing and validation. For example, a Data Scientist might want to include MAPE scores or confusion matrices. A Data Engineer may want to include logging and data quality validation tests, as well as unit and even integration tests. A Data Analyst might want to plot histograms of the data in question to ensure that outliers aren't overwhelming your analysis.

Your code should be well formatted according to generally accepted style guides and include whatever is necessary for a team-mate unfamiliar with it to maintain it.

### 0. Setup
#### Data
We have made the following datasets available (each filename is a link). These are all available in an AWS bucket `cct-ds-code-challenge-input-data`, in the `af-south-1` region, with the object name being the filenames below):
* [`sr.csv.gz`](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/sr.csv.gz) contains 12 months of service request data, where each row is a service request. A service request is a request from one of the residents of the City of Cape Town to undertake significant work. This is an important source of information on service delivery, and our performance thereof. *Note* as indicated by the extension, this file is compressed.
* [`sr_hex.csv.gz`](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/sr_hex.csv.gz) contains the same data as `sr.csv` as well as a column `h3_level8_index`, which contains the appropriate resolution level 8 H3 index for that request. If the request doesn't have a valid geolocation, the index value will be `0`. *Note* as indicated by the extension, this file is compressed.
* [`sr_hex_truncated.csv`](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/sr_hex_truncated.csv) is a truncated version of `sr_hex.csv`, containing only 3 months of data.
* [`city-hex-polygons-8.geojson`](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/city-hex-polygons-8.geojson) contains the [H3 spatial indexing system](https://h3geo.org/) polygons and index values for the bounds of the City of Cape Town, at resolution level 8.
* [`city-hex-polygons-8-10.geojson`](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/city-hex-polygons-8-10.geojson) contains the [H3 spatial indexing system](https://h3geo.org/) polygons and index values for resolution levels 8, 9 and 10, for the City of Cape Town.
* `swimming-pool-labels` (`s3://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/images/swimming-pool`) contains a random sample of aerial images from Cape Town, organised into two prefixes, `yes` or `no`, corresponding to whether there is a swimming pool in the image. Within each label prefix, there is a manifest file listing all the images available, i.e. [yes](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/images/swimming-pool/yes/manifest) and [no](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/images/swimming-pool/no/manifest).

In some of the tasks below you will be creating datasets that are similar to these, feel free to use the provided files to validate your work.

#### Dummy AWS Credentials
We have made AWS credentials available in the following file, with the appropriate permissions set, [here](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/ds_code_challenge_creds.json).

*Note* These creds don't have any special access, other than what is already set on these resources for anonymous access. These are more provided to make using the various AWS client libraries easier.

### 1. Data Extraction (if applying for a Data Engineering Position)
Use the [AWS S3 SELECT](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-glacier-select-sql-reference-select.html) command to read in the H3 resolution 8 data from `city-hex-polygons-8-10.geojson`. Use the `city-hex-polygons-8.geojson` file to validate your work.

Please also add an additional validation that checks conformance to a reasonable schema for the dataset. The output of this validation should be a conformance "score" of some sort, with a non-binary threshold of your choice. Explicitly capture the desired schema used to compute this conformance score in a standalone configuration or documentation file.

Please log the time taken to perform the operations described as well as the validation steps, and within reason, try to optimise latency and computational resources used. Please also note the comments above about the nature of the code that we expect.

### 2. Initial Data Transformation (if applying for a Data Engineering, Visualisation Engineer, Front End Developer and/or Science Position)
Join the equivalent of the contents of the file `city-hex-polygons-8.geojson` to the service request dataset, such that each service request is assigned to a single H3 resolution level 8 hexagon. Use the `sr_hex.csv.gz` file to validate your work.

For any requests where the `Latitude` and `Longitude` fields are empty, set the index value to `0`. Use your judgement to include any other appropriate validation.

Include logging that lets the executor know how many of the records failed to join, and include a join error threshold above which the script will error out. Please motivate why you have selected the error threshold that you have. Please also log the time taken to perform the operations described, and within reason, try to optimise latency and computational resources used.

### 3. Descriptive Analytic Tasks (if applying for a Data Analyst Position)
*Note:* We are most interested in how you reason about the problem.

Please use the `sr_hex_truncated.csv` dataset to address the following.

Please provide the following:
1. An answer to the question "In which 3 suburbs should the Urban Waste Management directorate concentrate their infrastructure improvement efforts?". Please motivate how you related the data provided to infrastructure issues.
2. An answer to the questions:
    1. Focusing on the Urban Waste Management directorate - "What is the median & 80th percentile time to complete each service request across the City?" (each row represent a service request).
    2. Focusing on the Urban Waste Management directorate - "What is the median & 80th percentile time to complete each service request for the 3 suburbs identified in (1)?" (each row represent a service request).
    3. "Is there any significant differences in the median and 80th percentile completion times between the City as a whole and the 3 suburbs identified in(1)?".  Please elaborate on the similarities or differences.
3. Provide a visual mock of a dashboard for the purpose of monitoring progress in applying the insights developed in (1) & (2). It should focus the user on performance pain points. Add a note for each visual element, explaining how it helps fulfill this overall function. Please also provide a brief explanation as to how the data provided would be used to realise what is contained in your mock.
4. Identify value-adding insights for the management of Urban Waste Management, from the dataset provided, in regard to waste collection within the City.
 
The **final deliverable** is a report (in PDF form) for the Executive Management team of the City.  An Executive-level, non-specialist should be able to read the report and follow your analysis without guidance.

### 4. Predictive Analytic Tasks (if applying for a Data Science Position)

Please choose __one__ of the following four tasks to solve:  (for the tasks you choose to solve, we expect you to provide (1) an initial solution and (2) an improved solution of your initial solution. For both we expect the code together with evidence or images of training or inference results, e.g. metrics, loss graph, output logs from hyperparameter tuning, confusion matrixs, etc)

1. *Time series challenge*: Predict the weekly number of expected service requests per hex that will be created each week using `sr_hex.csv`, for 4 weeks past the end of the dataset.
2. *Introspection challenge*: (using `sr_hex.csv`)    
   2.1. Reshape the data into number of requests created, per type, per H3 level 8 hex in the last 12 months.  
   2.2. Choose a type, and then develop a model that predicts the number of requests of that type per hex.   
   2.3. Use the model developed in (2.2) to predict the number in (2.1).   
   2.4. Based upon the model, and any other analysis, determine the drivers of requests of that particular type(s).   
3. *Classification challenge*: Classify a hex in `sr_hex.csv` as sparsely or densely populated, solely based on the service request data. Provide an explanation as to how you're using the data to perform this classification. Using your classifier, please highlight any unexpected or unusual classifications, and comment on why that might be the case.
4. *Anomaly Detection challenge*: Reshape the `sr_hex.csv` data into the number of requests created per department, per day. Please identify any days in the first 6 months of 2020 where an anomalous number of requests were created for a particular department. Please describe how you would motivate to the director of that department why they should investigate that anomaly. Your argument should rely upon the contents of the dataset and/or your anomaly detection model.

Item/Task 5 must be solved:  (we expect you to provide (1) an initial solution and (2) an improved solution of your initial solution. For both we expect the code together with evidence or images of training or inference results, e.g. metrics, loss graph, output logs from hyperparameter tuning, confusion matrixs, etc)

5. *Computer Vision classification challenge*: Use a sample of images from the `swimming-pool` dataset to develop a model that classifies whether an image contains a swimming pool or not. Use the provided labels to validate your model.

Feel free to use any other data you can find in the public domain, except for tasks (3) and (5).

**The final output of the execution of your code should be a self-contained `html` file or executed `ipynb` file that is your report.** 
 
A statistically minded layperson should be able to read this report and follow your analysis without guidance. In the 
report there should be evidence of any model training done (e.g. loss graph, output logs from hyperparameter tuning), 
along with quantitative measures or predictions of the quality of any models developed. We also expect to see some 
process commentary, describing the quality of any initial results, refinements made, and the resulting improvement.

Please also log the time taken to perform the operations described, and within reason, try to optimise latency and computation resources used. Please also note the comments above with respect to the nature of work that we expect from data scientists.

### 5. Further Data Transformations (if applying for a Data Engineering Position)
1. Create a subsample of the data by selecting all of the requests in `sr_hex.csv.gz` which are within 1 minute of the centroid of an official suburb in the proximity of Atlantis in the North of the City of Cape Town's bounds. You may determine the centroid of the suburb by the **computational** method of your choice (i.e. do not just hard code the value), but if any external data is used, your code should programmatically download and perform the centroid calculation. Please clearly document your method.

2. Augment your filtered subsample of `sr_hex.csv.gz` from (1) with the appropriate [wind direction and speed data for 2020](https://www.capetown.gov.za/_layouts/OpenDataPortalHandler/DownloadHandler.ashx?DocumentName=Wind_direction_and_speed_2020.ods&DatasetDocument=https%3A%2F%2Fcityapps.capetown.gov.za%2Fsites%2Fopendatacatalog%2FDocuments%2FWind%2FWind_direction_and_speed_2020.ods) from the Atlantis Air Quality Measurement site, from when the notification was created. All of the steps for downloading and preparing the wind data, as well as the join should be performed programmatically within your script. This endpoint can be unreliable - please add an appropriate strategy for handling this, with commentary for why you chose this approach for handling an unreliable dependency.

3. Write a script which anonymises your augmented subsample from (2), but preserves the following precisions (You may use H3 indice or lat/lon coordinates for your spatial data):
   * location accuracy to within approximately 500m
   * temporal accuracy to within 6 hours
   * Any records or columns which you believe could lead to the resident who made the request being identified despite the restrictions made above. For the records removed, make provision for a separate review by a person to anonymise the data by hand.
We expect in the accompanying report that you will justify as to why this data is now anonymised. Please limit this commentary to less than 500 words. If your code is written in a code notebook such as Jupyter notebook or Rmarkdown, you can include this commentary in your notebook.

### 6. Data Visualisation Task (if applying for a Data Visualisation Engineering or Front End Developer Position)

Using the [`sr_hex.csv.gz`](https://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/sr_hex.csv.gz) dataset and open source front-end web technologies (html, css, javascript, etc), develop a data visualisation / dashboard that help to answer the question:

*"In which suburbs should the Water and Sanitation directorate concentrate their infrastructure improvement efforts?".*

The data visualisation / dashboard must include the following:

1. A chart (plot) or charts (plots) that helps to answer the above question.
2. A minimalist cartographic map with identifiable landmark features (e.g. major roads, railways, etc.) and some representation of the data.
3. Make (1) and (2) interactive in some manner, so as to allow users to explore the data and uncover insights. The following example [Map with "range" sliders](https://observablehq.com/d/a040753103477386) demostrates an interactive map. However, you're not limited to this example – feel free to explore other interactive approaches.
4. Data Storytelling: in a separate markdown document, titled `data-driven-storytelling.md`, provide a brief, step-by-step, point form description of how your visualisations (and information from the dataset) outline a data-driven story that answers the above question. 
5. Design Principles: In a separate markdown document, titled `visualisation-design-choices.md`, please provide a brief, point form explanation for why you have chosen certain colours (e.g. for legends), fonts, the layout or anything else that will help us understand your thinking in designing the data visualisation / dashboard to answer the question. 
6. Publish your work using an online service such as https://pages.github.com/ or any other means you are familiar with.  Anyone with an Internet connection and a modern browser such as Google Chrome, Mozilla Firefox or Microsoft Edge, should be able to see the end product and interact with it. Please reference the published link to your visualisation tool in the `README.md` of your repository.

Please also note the comments above about the nature of the code that we expect.

## Contact
You can contact gordon.inggs, muhammed.ockards, kathryn.mcdermott and/or colinscott.anthony @ capetown.gov.za for any questions on the above.
