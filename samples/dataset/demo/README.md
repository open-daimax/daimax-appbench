# Demo Dataset Sample

This directory is a **synthetic, self-contained example** of a single evaluation
sample. It exists to show newcomers the dataset directory convention — none of the
data here is real, and it is not wired into the V1/V2 sample sets.

## What is a "sample"?

A **sample** describes *what application to build* — a requirement specification
plus the pages, navigation, and constraints an implementation must satisfy. A sample
answers "what do we want?"; it deliberately says nothing about *how* to test or which
platform to run on (that lives in the execution plan). Given a sample and an app
artifact (URL / APK / .app / source project), the tool runs the full pipeline:
build → install → E2E test → multi-dimension scoring → HTML report.

## Directory structure convention

In the real dataset (`dataset/V1`, `dataset/V2`), samples are organized three levels
deep — version → category → sample — and each sample lives in its own directory whose
name equals the `sample_id`:

```
dataset/V2/<category>/            # category directory
├── index.yaml                    # category index (lists sample IDs under samples_index)
└── <SampleId>/                   # sample directory (dir name == sample_id)
    ├── sample.yaml               # requirement spec (the sample metadata)
    └── test_cases/
        └── test_cases_default.json   # atomic E2E test cases
```

This `demo/` sample mirrors that layout with two differences to keep the example
compact and easy to read:

- The requirement metadata is provided here as **`meta.json`** (JSON) rather than
  `sample.yaml`. The fields are identical in meaning; the production loader reads
  `sample.yaml`, so treat `meta.json` as a readable illustration of the same schema.
- No `index.yaml` / `test_cases/` are included — a real sample would ship a
  `test_cases/test_cases_default.json` alongside its spec.

## Fields in meta.json

### Required

| Field | Meaning |
|-------|---------|
| `sample_id` | Unique sample identifier; must match the directory name |
| `title` | Human-readable name of the app |
| `app_type` | Application category (passed to the aesthetics model for category-aware scoring) |
| `dataset_version` | Which generation the sample belongs to (`V1` / `V2`) |
| `complexity` | Complexity tier (`low` / `medium` / `high`) |
| `requires_backend` | Whether a real backend is required — directly decides if backend-completeness is scored |
| `requires_auth` | Whether a login state is required |
| `requirement` | Full requirement description, grouped by Tab / page with numbered feature points |
| `pages` | Page inventory; each entry has `name`, `level` (L1/L2/L3), and `entry_from` (entry path) |

### Optional

| Field | Meaning |
|-------|---------|
| `version` | Schema version of the sample spec |
| `navigation` | Navigation structure (e.g. `bottom_tab` and each tab's name/icon/landing page) |
| `core_functions` | List of the core feature areas to verify |
| `constraints` | Engineering constraints (e.g. front-end only + localStorage, preset data counts) |
| `notes` | Free-text verification focus / reviewer notes |

## How a sample is used in the pipeline

1. **Load** — the sample spec is loaded from its directory; `requires_backend` /
   `requires_auth` and `pages` gate which scoring dimensions apply and which UI paths
   the test steps may traverse.
2. **Test cases** — the sample's `test_cases_default.json` supplies atomic E2E cases;
   a shared `TC_LAUNCH` launch-gate case is auto-injected as the first case.
3. **Run** — for each `sample_id × platform` task in the execution plan, the tool
   builds/installs the artifact, runs the launch gate then each case, and collects
   screenshots, device logs, network requests, artifact size, and stage durations.
4. **Score & report** — dimensions are scored against the rules and rolled up into the
   single-file HTML report (see `../../reports/example_report.json` for the output
   structure).

> All content in this directory is example-only synthetic data — no brands, no real
> API keys, no proprietary information.
