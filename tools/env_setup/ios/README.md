# iOS Env Setup Tool

A reusable built-in tool for detecting and installing iOS development environment dependencies.

## Overview

This skill provides automated environment management capabilities that can be used by other skills (like `ios-build`, `ios-install`) to ensure required dependencies exist before executing build or installation tasks.

## Features

- **Environment Detection**: Automatically detects installed tools and missing dependencies
- **User Consent**: Always asks for permission before installing anything
- **Script-Based Installation**: All installations are performed by executable scripts
- **Idempotent Operations**: Scripts can be run multiple times safely
- **Machine-Readable Output**: All outputs are in JSON format for reliable parsing

## Supported Environments

Currently supports:
- `ios-build`: iOS development environment (Xcode Command Line Tools, Xcode, CocoaPods)
- `ios-install`: iOS installation environment (Xcode Command Line Tools, ios-deploy, libimobiledevice)

## Quick Start

### 1. Detect Environment

```bash
./scripts/doctor.sh ios-build /path/to/ios/project
```

This will output a JSON report showing:
- What dependencies are already installed
- What dependencies are missing
- Recommended versions
- Installation location

### 2. Install Missing Dependencies

```bash
./scripts/apply.sh '<doctor_json_output>'
```

Pass the JSON output from the doctor script to install missing dependencies.

### 3. Verify Environment

```bash
./scripts/verify.sh ios-build
```

This will verify that all required tools are accessible and working correctly.

## Workflow Example

```bash
# Step 1: Detect environment
DOCTOR_OUTPUT=$(./scripts/doctor.sh ios-build /path/to/project)
echo "$DOCTOR_OUTPUT"

# Step 2: Check if there are missing dependencies
MISSING_COUNT=$(echo "$DOCTOR_OUTPUT" | jq '.missing | length')

if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "Found $MISSING_COUNT missing dependencies"
    
    # Step 3: Install (after user confirmation)
    ./scripts/apply.sh "$DOCTOR_OUTPUT"
    
    # Step 4: Verify installation
    ./scripts/verify.sh ios-build
fi
```

## Installation Locations

All dependencies are installed to `~/.dev-env/` by default:

- Xcode Command Line Tools: System location (managed by Apple)
- Xcode: `/Applications/Xcode.app` (manual installation required)
- CocoaPods: System gem location
- ios-deploy: Homebrew installation location

## Environment Variables

### Automatic Environment Loading

The scripts automatically load environment variables from `~/.dev-env/manifest.json` before performing any detection or installation operations. This ensures that:

1. Previously installed dependencies are correctly detected
2. Environment variables are available to all detection functions
3. PATH is properly configured for command availability checks

### Environment Variables Set

The scripts work with these environment variables:

- `DEVELOPER_DIR`: Path to Xcode Developer directory
- `PATH`: Updated to include development tools

### Persistence

Environment variables are persisted to `~/.dev-env/manifest.json` during installation. This JSON file contains:
- Dependency names and installation paths
- Version information
- Installation timestamps

The skill scripts automatically load environment variables from this manifest file. For interactive shell sessions, you can manually set up environment variables based on the manifest, or use a shell initialization script that reads from the manifest.

**Note**: The skill scripts automatically load environment variables from the manifest, so no manual configuration is needed for the scripts to work.

## Script Reference

### doctor.sh

**Purpose**: Detect environment dependencies

**Usage**: `./scripts/doctor.sh <env_type> <project_path>`

**Output**: JSON report with detected and missing dependencies

**Example**:
```bash
./scripts/doctor.sh ios-build /path/to/ios/project
```

### apply.sh

**Purpose**: Install missing dependencies

**Usage**: `./scripts/apply.sh '<doctor_json>'`

**Output**: JSON report of installation results

**Example**:
```bash
DOCTOR_JSON=$(./scripts/doctor.sh ios-build /path/to/project)
./scripts/apply.sh "$DOCTOR_JSON"
```

### verify.sh

**Purpose**: Verify environment is ready

**Usage**: `./scripts/verify.sh <env_type>`

**Output**: JSON report of verification results

**Example**:
```bash
./scripts/verify.sh ios-build
```

### common.sh

**Purpose**: Shared utilities and functions

This file is sourced by other scripts and provides:
- **Automatic environment loading**: Loads environment variables from `~/.dev-env/manifest.json` at initialization
- Logging functions
- Environment detection functions
- JSON validation
- Error codes

**Environment Injection**: When `common.sh` is sourced, it automatically loads environment variables from `~/.dev-env/manifest.json` if the file exists. This ensures all scripts have access to previously configured development tools without requiring manual environment setup.

## Error Codes

- `ERR_NO_CLT` (10): Xcode Command Line Tools not installed
- `ERR_NO_XCODE` (11): Xcode not found
- `ERR_NO_COCOAPODS` (12): CocoaPods not found
- `ERR_NO_IOS_DEPLOY` (13): ios-deploy not found
- `ERR_NETWORK` (14): Network connectivity issues
- `ERR_PERMISSION` (15): Permission denied during installation
- `ERR_DISK_SPACE` (16): Insufficient disk space
- `ERR_UNSUPPORTED_OS` (17): Operating system not supported (iOS development requires macOS)
- `ERR_INVALID_PROJECT` (18): Project configuration invalid or unreadable

## Requirements

- macOS (iOS development is only supported on macOS)
- Bash 4.0+
- curl (for downloading dependencies)
- Network connectivity (for downloading dependencies)
- At least 20GB free disk space (for Xcode)
- Homebrew (for installing ios-deploy and libimobiledevice)

## How Other Skills Use This

Example from `ios-build` skill:

```bash
# 1. Detect environment
DOCTOR_OUTPUT=$(./scripts/doctor.sh ios-build "$PROJECT_PATH")

# 2. Parse output
MISSING_COUNT=$(echo "$DOCTOR_OUTPUT" | jq '.missing | length')

# 3. If dependencies are missing, ask user
if [ "$MISSING_COUNT" -gt 0 ]; then
    # Ask user for permission to install
    # ...
    
    # 4. Install if approved
    ./scripts/apply.sh "$DOCTOR_OUTPUT"
    
    # 5. Verify environment
    VERIFY_OUTPUT=$(./scripts/verify.sh ios-build)
    ENV_READY=$(echo "$VERIFY_OUTPUT" | jq -r '.env_ready')
    
    if [ "$ENV_READY" = "true" ]; then
        # 6. Proceed with build
        xcodebuild -project MyApp.xcodeproj -scheme MyApp build
    fi
fi
```

## Extending the Skill

To add support for a new environment type:

1. Add a new `doctor_<env_type>` function in `doctor.sh`
2. Add a new `apply_<env_type>` function in `apply.sh`
3. Add a new `verify_<env_type>` function in `verify.sh`
4. Update the case statements in each script's `main()` function
5. Document the new environment type in `SKILL.md`

## Important Notes

**Xcode Installation**: Xcode must be installed manually from the Mac App Store. The scripts cannot automate this due to Apple's licensing requirements.

**Homebrew Requirement**: Installing `ios-deploy` and `libimobiledevice` requires Homebrew. If not installed, visit https://brew.sh

**CocoaPods Installation**: CocoaPods installation requires `sudo` access for gem installation. Users will be prompted for their password.

**Disk Space**: 
- `ios-build`: ~20-30GB (Xcode is ~15-20GB)
- `ios-install`: ~500MB-1GB

## License

This skill is part of the ACoder skill ecosystem.

## Contributing

When contributing improvements:
- Maintain idempotent behavior
- Keep JSON output format consistent
- Add appropriate error handling
- Update documentation
- Test on macOS