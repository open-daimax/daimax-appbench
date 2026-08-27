# API Reference

Complete reference for the `evalapp` CLI commands, configuration schema, and extension points.

## CLI Commands

### Command Overview

| Command | Description |
|---------|-------------|
| `evalapp evaluate` | Evaluate artifacts or workspace code (build → install → E2E → score → report) |
| `evalapp retest` | Re-run E2E tests and regenerate report |
| `evalapp report` | Generate or regenerate report for a completed evaluation |
| `evalapp history` | View workspace execution history |
| `evalapp migrate-workspace` | Migrate legacy workspace directory structures |

### `evalapp evaluate`

The primary command for running evaluations. Supports three modes:

#### Artifact Mode (Recommended)

Evaluate a pre-built artifact directly:

```bash
# Web application (URL)
evalapp evaluate --url <url> --sample-ids <id> [OPTIONS]

# Android APK
evalapp evaluate --apk <path> --sample-ids <id> [OPTIONS]

# iOS application
evalapp evaluate --app <path> --sample-ids <id> [OPTIONS]

# Source project (requires --platform)
evalapp evaluate --project <dir> --platform <platform> --sample-ids <id> [OPTIONS]
```

#### Batch Mode

Evaluate multiple samples from a dataset directory:

```bash
evalapp evaluate --workspace <path> --samples-dir <dir> --platform <platform> [OPTIONS]
```

#### Execution Plan Mode

Fine-grained control over evaluation order and scope:

```bash
evalapp evaluate --workspace <path> --exec-plan <file> [OPTIONS]
```

#### Parameters

| Parameter | Description |
|-----------|-------------|
| `--url` | Deployed web application URL (artifact mode) |
| `--apk` | Pre-built Android APK path (artifact mode) |
| `--app` | Pre-built iOS .app path (artifact mode) |
| `--project` | Source code project directory (artifact mode, requires `--platform`) |
| `--output` | Results output directory (artifact mode, default: `./eval_output`) |
| `--workspace` | Existing workspace directory path (optional in artifact mode) |
| `--samples-dir` | Sample dataset directory (batch mode, mutually exclusive with `--exec-plan`) |
| `--exec-plan` | Execution plan YAML path (mutually exclusive with `--samples-dir`) |
| `--platform` | Target platform: `web` / `android` / `ios` |
| `--sample-ids` | Comma-separated sample ID list (defaults to all samples in plan) |
| `--sample-id` | Single sample ID (deprecated, use `--sample-ids`) |
| `--generator` | Generator name (default: inferred from workspace directory name) |
| `--workers` | Concurrent evaluation threads (default: 1) |
| `--show-browser` | Show browser UI (headed mode); default is headless |
| `--no-uninstall` | Keep app installed after evaluation |
| `--no-open-report` | Don't auto-open report in browser |
| `--wait-generate` | Pipeline mode: wait for generation per sample before evaluating |

#### Platform Auto-Detection

| Artifact Flag | Inferred Platform |
|---------------|-------------------|
| `--url` | `web` |
| `--apk` | `android` |
| `--app` | `ios` |
| `--project` | Must specify `--platform` explicitly |

### `evalapp retest`

Re-run E2E tests for previously evaluated samples without rebuilding or reinstalling.

#### Single-Sample Mode

```bash
evalapp retest --workspace <path> --sample-id <id> --platform <platform> [OPTIONS]
```

#### Multi-Sample Mode

```bash
evalapp retest --workspace <path> --sample-ids <id1>,<id2> --exec-plan <file> [OPTIONS]
```

#### Parameters

| Parameter | Description |
|-----------|-------------|
| `--workspace` | Workspace path (required) |
| `--sample-id` | Single sample ID (single-sample mode) |
| `--sample-ids` | Comma-separated sample IDs (multi-sample mode) |
| `--platform` | Target platform (required in single-sample mode) |
| `--exec-plan` | Execution plan YAML (recommended for multi-sample mode) |
| `--test-case-ids` | Comma-separated test case IDs to re-run (single-sample mode only) |

### `evalapp report`

Generate or regenerate evaluation reports.

```bash
# Regenerate report for latest evaluation
evalapp report

# Specify a particular run
evalapp report --run-id <run_id>

# Generate comparison report with history
evalapp report --compare

# Regenerate summary for a workspace
evalapp report --workspace <workspace_path>
```

### Global Parameters

Available for all commands:

| Parameter | Description |
|-----------|-------------|
| `--config` | Configuration file path (default: `evalapp.yaml`) |
| `--verbose` | Enable verbose output |
| `--stream-output` | Stream subprocess logs in real-time |

## Configuration Schema

The `evalapp.yaml` file defines all runtime configuration. See `evalapp.yaml.example` for a complete annotated template.

### Top-Level Fields

```yaml
platforms: [web, android, ios]   # Target platforms
results_dir: results              # Results output directory
```

### Models Configuration

```yaml
models:
  e2e:
    api_key: ""       # Vision model API key (env: MIDSCENE_MODEL_API_KEY)
    base_url: ""      # OpenAI-compatible endpoint (env: MIDSCENE_MODEL_BASE_URL)
    name: ""          # Model name (env: MIDSCENE_MODEL_NAME)
    family: ""        # Model family identifier (env: MIDSCENE_MODEL_FAMILY)
  aesthetics:
    api_key: ""       # Aesthetics VL model key (env: DASHSCOPE_API_KEY)
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    name: "qwen-vl-max"   # (env: AESTHETICS_MODEL)
    family: ""
```

### AI UI Test Configuration

```yaml
ai_ui_test:
  timeout: 300          # Per-test-case timeout in seconds
  replan_limit: 20      # Max replanning attempts per test case
```

### Build Configuration

```yaml
build_app:
  script_path: tools/build_app/scripts/build_app.py
  timeout: 1800         # Build timeout in seconds
  build_type: debug     # debug | release
  clean: false          # Clean build
  android_output_format: apk   # apk | aab
  ios_output_format: app       # app | ipa
```

### Install Configuration

```yaml
install_app:
  script_path: tools/install_app/scripts/install_app.py
  timeout: 300
  device_id: null       # null = auto-detect
  auto_install: false
```

### Optional Integrations

```yaml
# External model service (optional, advanced capabilities)
external_service:
  enabled: false
  api_key: ""           # env: EXTERNAL_SERVICE_API_KEY

# MCP tool servers (optional)
mcp:
  enabled: false
  servers: []
```

### Report Configuration

```yaml
report:
  auto_open: true       # Auto-open report in browser
  eval_version: "2.0"   # Evaluation version identifier
```

## Extension Points

The framework uses Python entry points for plugin discovery. Sister repositories can register capabilities without modifying this codebase.

### Generator Plugins

Entry point group: `evalapp.generators`

Register an `AppGenerator` subclass to provide code generation capabilities:

```toml
# In your package's pyproject.toml
[project.entry-points."evalapp.generators"]
my_generator = "my_package.generator:MyGenerator"
```

Generators are discovered at runtime via `evalapp.generators.get_generator(name)`.

### CLI Command Plugins

Entry point group: `evalapp.commands`

Register additional CLI subcommands that mount to the `evalapp` command group:

```toml
# In your package's pyproject.toml
[project.entry-points."evalapp.commands"]
generate = "my_package.commands:generate_cmd"
design-samples = "my_package.commands:design_samples_cmd"
```

Commands are auto-discovered and mounted at startup.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (configuration, missing files, etc.) |
| 2 | CLI usage error (invalid arguments) |

## Sample Dataset Schema

### `sample.yaml` Fields

| Field | Type | Description |
|-------|------|-------------|
| `sample_id` | string | Unique sample identifier (matches directory name) |
| `title` | string | Human-readable sample name |
| `app_type` | string | Application category (passed to aesthetics model) |
| `dataset_version` | string | Dataset generation: `V1` or `V2` |
| `complexity` | string | Complexity tier |
| `requires_backend` | boolean | Whether real backend is required |
| `requires_auth` | boolean | Whether authentication is required |
| `requirement` | string | Full requirement description |
| `pages` | list | Page definitions with `name`, `level` (L1/L2/L3), `entry_from` |
| `navigation` | object | Navigation structure (e.g., bottom tabs) |
| `core_functions` | list | Core function descriptions |
| `constraints` | list | Engineering constraints |
| `notes` | list | Verification emphasis points |

### Test Case Schema

```json
{
  "prompt_id": "SampleId",
  "platform": "default",
  "test_cases": [
    {
      "id": "TC002",
      "name": "Test case name",
      "description": "What this test verifies",
      "steps": [
        "Action -> Expected: Result"
      ],
      "expected_result": "Overall expected outcome",
      "priority": "P0",
      "category": "core_crud"
    }
  ]
}
```

#### Priority Levels

| Priority | Meaning |
|----------|---------|
| `P0` | Highest — core functionality |
| `P1` | Important — secondary features |
| `P2` | Nice-to-have — edge cases |

#### Categories

| Category | Description |
|----------|-------------|
| `launch_check` | Application startup verification |
| `core_crud` | Core CRUD operations |
| `form_validation` | Form input and validation |
| `navigation` | Page navigation and routing |

Legacy priority values (`high`, `medium`, `low`) are automatically normalized on load.
