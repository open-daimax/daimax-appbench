# Quick Start Guide

This guide walks you through installing, configuring, and running your first evaluation with `evalapp`.

## Prerequisites

- **Python ≥ 3.10**
- **Git** (to clone the repository)
- For Android evaluation: a connected device or emulator with ADB access
- For iOS evaluation: a connected device or simulator
- For Web evaluation: no additional hardware required

## Installation

```bash
git clone <your-repo-url> daimax-appbench
cd daimax-appbench

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify the installation:

```bash
evalapp --help
```

You should see the CLI help output listing available commands.

### Optional Dependencies

```bash
# Development tools (pytest, coverage)
pip install -e ".[dev]"

# Performance optimization (faster JSON via orjson)
pip install -e ".[perf]"
```

## Configuration

### Create Configuration File

```bash
cp evalapp.yaml.example evalapp.yaml
```

> **Important**: `evalapp.yaml` contains sensitive API keys and is excluded from version control via `.gitignore`. Never commit this file.

### Configuration Fields

| Section | Field | Description |
|---------|-------|-------------|
| `platforms` | — | Target platforms for evaluation: `web`, `android`, `ios` |
| `results_dir` | — | Directory for evaluation results (default: `results`) |
| `models.e2e` | `api_key` | API key for the E2E vision model (env: `MIDSCENE_MODEL_API_KEY`) |
| `models.e2e` | `base_url` | OpenAI-compatible endpoint URL (env: `MIDSCENE_MODEL_BASE_URL`) |
| `models.e2e` | `name` | Model name, e.g. `gpt-4o` (env: `MIDSCENE_MODEL_NAME`) |
| `models.aesthetics` | `api_key` | API key for aesthetics VL model (env: `DASHSCOPE_API_KEY`) |
| `models.aesthetics` | `base_url` | Model endpoint (default: DashScope) |
| `models.aesthetics` | `name` | Model name (default: `qwen-vl-max`) |
| `ai_ui_test` | `timeout` | E2E test timeout in seconds (default: 300) |
| `ai_ui_test` | `replan_limit` | Max replanning attempts per test case (default: 20) |
| `build_app` | `timeout` | Build timeout in seconds (default: 1800) |
| `build_app` | `build_type` | Build type: `debug` or `release` |
| `install_app` | `timeout` | Install timeout in seconds (default: 300) |
| `install_app` | `device_id` | Target device ID (null for auto-detect) |

### Priority Order

Configuration is resolved in this order (highest priority first):

1. Explicit values in `evalapp.yaml`
2. Environment variables
3. Built-in defaults (defined in `evalapp/config.py`)

### Minimal Configuration

At minimum, you need to configure the E2E vision model to run evaluations:

```yaml
models:
  e2e:
    api_key: "your-api-key"
    base_url: "https://your-model-endpoint/v1"
    name: "gpt-4o"
```

The aesthetics model is optional — if not configured, the aesthetics dimension will be skipped and its weight redistributed automatically.

## Running Your First Evaluation

### Evaluate a Web Application

The simplest way to start is evaluating a deployed web application:

```bash
evalapp evaluate --url https://my-app.vercel.app --sample-ids CoffeeRoastLog
```

This will:
1. Load the `CoffeeRoastLog` sample and its test cases
2. Run the TC_LAUNCH startup gate check
3. Execute all E2E test cases against the URL
4. Score all applicable dimensions
5. Generate an interactive `report.html` (opens automatically in your browser)

### Evaluate an APK

```bash
evalapp evaluate --apk ./build/app-debug.apk --sample-ids CoffeeRoastLog
```

### Evaluate from Source Code

```bash
evalapp evaluate --project ./my-expo-app --platform web --sample-ids CoffeeRoastLog
```

When using `--project`, you must specify `--platform` explicitly. The engine will build the project before evaluation.

### Batch Evaluation

Evaluate all samples in a dataset category:

```bash
evalapp evaluate --workspace ./my_workspace \
    --samples-dir ./dataset/V2/beverage \
    --platform web
```

## Understanding Results

### Report

After evaluation completes, a single-file interactive HTML report is generated at the workspace root (or `--output` directory in artifact mode). The report includes:

- **Score cards**: Overall score and per-dimension breakdown
- **Platform comparison**: Cross-platform consistency view (when multiple platforms are evaluated)
- **Per-sample details**: Startup screenshots, E2E test results, backend verification, stability, and aesthetics scores
- **Filtering**: Filter by platform, dataset version, backend requirements, and more

### Scoring Dimensions

| Dimension | Weight Context | Description |
|-----------|---------------|-------------|
| Success Rate | Top-level | First-generation success rate (60%) + issue fix (20%) + requirement supplement (20%) |
| Quality | Top-level | Functional completeness with stability and backend deductions |
| Experience | Top-level | Time (60%) + package size (20%) + aesthetics (20%) |

Missing dimensions are automatically excluded from scoring and weights are renormalized.

## Common Issues

### "No test cases found"

Ensure the `--sample-ids` value matches a directory name under `dataset/V1/` or `dataset/V2/`. Sample IDs are case-sensitive.

### E2E tests timing out

Increase the timeout in `evalapp.yaml`:

```yaml
ai_ui_test:
  timeout: 600  # seconds
  replan_limit: 30
```

### Build failures

- Verify your project has the correct dependencies installed
- Check that `build_app.script_path` points to a valid build script
- Use `--stream-output` for real-time build logs

### Model API errors

- Verify API keys are correctly set (check both `evalapp.yaml` and environment variables)
- Ensure the `base_url` endpoint is reachable from your machine
- Check that the model name is valid for your provider

## Next Steps

- [API Reference](API.md) — Full CLI commands and configuration schema
- [Architecture](Architecture.md) — System design and component overview
