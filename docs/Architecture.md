# Architecture

System architecture overview for the `evalapp` evaluation framework.

## High-Level Overview

The evaluation framework is a CLI-driven pipeline that takes an application artifact (URL, APK, .app, or source directory) and a sample definition, then produces a comprehensive multi-dimensional quality report.

```
┌─────────────────────────────────────────────────────────────────┐
│                         evalapp CLI                              │
├─────────────────────────────────────────────────────────────────┤
│  Commands Layer (evalapp/commands/)                              │
│  evaluate | retest | report | history | migrate-workspace       │
├─────────────────────────────────────────────────────────────────┤
│  Services Layer (evalapp/services/)                              │
│  Orchestration · Report aggregation · Backfill · Rebuild        │
├─────────────────────────────────────────────────────────────────┤
│  Evaluation Engine (evalapp/evaluation/)                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │exec_plan/│ │ runner/  │ │ metrics/ │ │    results/      │   │
│  │Plan load │ │Phase exec│ │Scoring   │ │Models & Reports  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│  Benchmark Set (evalapp/benchset/)                               │
│  samples/ (loading) · testcases/ (loading & design)             │
├─────────────────────────────────────────────────────────────────┤
│  Workspace (evalapp/workspace/)                                  │
│  Metadata · Run records · Cleanup · Migration                   │
├─────────────────────────────────────────────────────────────────┤
│  External Tools (tools/)                                         │
│  ai-ui-test · build_app · install_app · env_setup               │
└─────────────────────────────────────────────────────────────────┘
```

## Evaluation Pipeline

The core evaluation flow proceeds through these stages:

```
Sample + Artifact
    │
    ▼
┌─────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐    ┌────────┐
│  Build  │───▶│ Install │───▶│ E2E Test │───▶│ Collect  │───▶│  Score  │───▶│ Report │
└─────────┘    └─────────┘    └──────────┘    └──────────┘    └─────────┘    └────────┘
```

### Stage Details

| Stage | Description | Skippable |
|-------|-------------|-----------|
| **Build** | Compile source to platform artifact (only for `--project` mode) | Yes (artifact mode) |
| **Install** | Deploy to device/emulator (Android/iOS only) | Yes (web mode) |
| **E2E Test** | TC_LAUNCH gate → sequential test case execution via vision model | No |
| **Collect** | Gather screenshots, device logs, network requests, static analysis, timings | No |
| **Score** | Compute dimension scores per `rules.py` definitions | No |
| **Report** | Generate single-file interactive HTML report | No |

### TC_LAUNCH Gate

Before running sample-specific test cases, a startup verification (TC_LAUNCH) is injected from the common template:

- Located at `dataset/{V1,V2}/common/tc_launch_template.json`
- Injected automatically by `evalapp/benchset/testcases/store.py`
- If TC_LAUNCH fails or detects a white screen → marks startup as failed, scores 0 for success rate
- Short-circuits remaining test cases (no point testing a non-functional app)

## Metrics System

All scores are on a 0–100 scale. Rules are centralized in `evalapp/evaluation/metrics/rules.py` (single source of truth).

### Three Top-Level Metrics

```
┌───────────────────────────────────────────────────────────────┐
│                      Final Score                               │
├───────────────┬───────────────────────┬───────────────────────┤
│ Success Rate  │       Quality         │      Experience       │
│               │                       │                       │
│ • First-gen   │ • Functional          │ • Time        (60%)   │
│   success 60% │   completeness        │ • Package     (20%)   │
│ • Fix    20%  │   (deduction model)   │ • Aesthetics  (20%)   │
│ • Suppl. 20%  │                       │                       │
└───────────────┴───────────────────────┴───────────────────────┘
```

### Dimension Computation

| Dimension | Data Source | Scoring Method |
|-----------|-------------|----------------|
| Functional Completeness | E2E results + stability + backend | Deduction model (see below) |
| Backend Completeness | Network request monitoring during E2E | Pass rate × 100 |
| UI Aesthetics | Runtime screenshots | VL model multi-criteria: color 25%, layout 25%, hierarchy 20%, typography 15%, professionalism 15% |
| Stability | Device logs / diagnostics | `max(0, 1 − issue_rate) × 100` |
| Code Quality | Static source analysis | Static scan 40% + cyclomatic complexity 30% + duplication 30% |
| Package Size | Artifact file size | Piecewise linear: 0MB=100 → 10MB=80 → 30MB=60 → 60MB=40 → 100MB=20 |
| Time | Generation + build duration | Piecewise linear: ≤2min=100, 2–30min=100→5, 30–60min=5→0 |

### Functional Completeness (Deduction Model)

```
Functional Completeness = Test Pass Rate − Stability Penalty − Backend Penalty   (min 0)

Test Pass Rate      = E2E test pass rate × 100
Stability Penalty   = (1 − Stability/100) × Test Pass Rate × 0.2
Backend Penalty     = (1 − Backend Completeness/100) × Test Pass Rate × 0.3
```

- Missing dimensions are not penalized (platform doesn't support stability collection, or sample doesn't require backend)
- Build/install/startup failure → functional completeness and backend completeness score 0

### Weight Normalization

When a dimension has no data (e.g., no screenshots for aesthetics, web has no package size), its weight is excluded and remaining weights are renormalized to sum to 100%.

## Component Descriptions

### `evalapp/benchset/`

**Benchmark domain** — responsible for loading and managing evaluation inputs.

- `samples/` — Sample loading: reads `sample.yaml` files, validates schema, provides sample metadata
- `testcases/` — Test case loading: reads `test_cases_default.json`, injects TC_LAUNCH, normalizes priorities. Also contains `designer.py` for AI-assisted test case generation (protocol only, no built-in implementation)

### `evalapp/evaluation/`

**Evaluation engine** — the core execution and scoring machinery.

- `exec_plan/` — Execution plan loading and auto-generation from sample directories
- `runner/` — Phase executors: `build`, `install`, `test_phase`, plus collectors and the evaluator orchestrator
- `metrics/` — `rules.py` (constants & thresholds), `dimensions/` (scoring logic per dimension), `collectors/` (raw data collection including aesthetics VL prompts)
- `results/` — Result data models, `reporting/` (single-file HTML report generation), `comparison/` (cross-run comparison)

### `evalapp/services/`

**Service layer** — high-level orchestration combining multiple engine capabilities.

- Evaluation orchestration (coordinate the full pipeline)
- Report aggregation and rebuild
- Score backfill (recompute scores with updated rules)

### `evalapp/workspace/`

**Workspace management** — persistent state and run tracking.

- Workspace metadata and configuration
- Run records and history
- Cleanup utilities
- Schema migration for older workspace formats

### `evalapp/commands/`

**CLI layer** — Click-based command implementations.

- Each subcommand (`evaluate`, `retest`, `report`, `history`, `migrate-workspace`) is a separate module
- Plugin commands are discovered and mounted automatically via entry points

### `tools/`

**External tooling** — heterogeneous tools invoked as subprocesses.

| Tool | Purpose |
|------|---------|
| `ai-ui-test/` | Vision-model E2E test runner (Midscene-based) |
| `build_app/` | Cross-platform build scripts |
| `install_app/` | Device installation scripts |
| `env_setup/` | Environment detection and configuration |

### `dataset/`

**Evaluation samples** — organized by generation and category.

```
dataset/
├── V1/                          # Basic regression (51 samples, 10 categories)
│   ├── index.yaml               # Top-level index with execution_policy
│   ├── common/
│   │   └── tc_launch_template.json
│   └── <category>/
│       └── <SampleId>/
│           ├── sample.yaml
│           └── test_cases/
├── V2/                          # Full evaluation (34 samples, 13 categories)
│   ├── common/
│   │   └── tc_launch_template.json
│   └── <category>/
│       ├── index.yaml           # Category-level index
│       └── <SampleId>/
│           ├── sample.yaml
│           └── test_cases/
```

## Data Flow

```
                    ┌─────────────┐
                    │ evalapp.yaml│ (configuration)
                    └──────┬──────┘
                           │
┌──────────┐       ┌──────▼──────┐       ┌──────────────┐
│ dataset/ │──────▶│  Execution  │──────▶│   Workspace  │
│(samples) │       │   Engine    │       │  (run state) │
└──────────┘       └──────┬──────┘       └──────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼───┐ ┌─────▼────┐ ┌────▼─────┐
       │ tools/   │ │ AI Models│ │ Device/  │
       │(build,   │ │(E2E, VL) │ │ Browser  │
       │ install) │ │          │ │          │
       └──────────┘ └──────────┘ └──────────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │  Collectors │ (screenshots, logs, metrics)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Dimensions │ (scoring per rules.py)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ report.html │ (single-file interactive report)
                    └─────────────┘
```

## Design Principles

1. **Single source of truth**: All scoring rules in `rules.py` — changing any constant affects historical score comparability
2. **Deduction model**: Quality starts at 100 and deducts for issues, rather than additive scoring
3. **Graceful degradation**: Missing dimensions are excluded, weights renormalize automatically
4. **Plugin architecture**: Generators and commands registered via entry points, no core code changes needed
5. **Zero manual intervention**: Full pipeline runs unattended in CLI mode
6. **Reproducibility**: Execution plans and workspace records enable exact re-runs
