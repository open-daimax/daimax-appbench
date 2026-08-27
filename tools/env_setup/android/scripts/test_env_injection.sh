#!/bin/bash

# test_env_injection.sh - Test script to verify environment variable injection
# This script tests that common.sh correctly loads environment variables from manifest.json

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "Testing Environment Variable Injection"
echo "=========================================="
echo ""

# Display current environment before sourcing common.sh
echo "1. Environment BEFORE sourcing common.sh:"
echo "   JAVA_HOME: ${JAVA_HOME:-<not set>}"
echo "   ANDROID_HOME: ${ANDROID_HOME:-<not set>}"
echo "   ANDROID_SDK_ROOT: ${ANDROID_SDK_ROOT:-<not set>}"
echo ""

# Check if manifest.json exists
if [[ -f "${HOME}/.dev-env/manifest.json" ]]; then
    echo "2. Found manifest.json at: ${HOME}/.dev-env/manifest.json"
    echo "   Contents:"
    if command -v jq &>/dev/null; then
        cat "${HOME}/.dev-env/manifest.json" | jq . | sed 's/^/   /'
    else
        cat "${HOME}/.dev-env/manifest.json" | sed 's/^/   /'
    fi
    echo ""
else
    echo "2. WARNING: manifest.json not found at ${HOME}/.dev-env/manifest.json"
    echo ""
fi

# Source common.sh (which should load environment variables)
echo "3. Sourcing common.sh..."
source "${SCRIPT_DIR}/common.sh"
echo ""

# Display environment after sourcing common.sh
echo "4. Environment AFTER sourcing common.sh:"
echo "   JAVA_HOME: ${JAVA_HOME:-<not set>}"
echo "   ANDROID_HOME: ${ANDROID_HOME:-<not set>}"
echo "   ANDROID_SDK_ROOT: ${ANDROID_SDK_ROOT:-<not set>}"
echo ""

# Test detection functions
echo "5. Testing detection functions:"
echo ""

echo "   a) Testing detect_java():"
if java_info=$(detect_java); then
    echo "      ✅ Java detected successfully"
    echo "      $java_info" | sed 's/^/      /'
else
    echo "      ❌ Java not detected"
fi
echo ""

echo "   b) Testing detect_android_sdk():"
if sdk_root=$(detect_android_sdk); then
    echo "      ✅ Android SDK detected successfully"
    echo "      SDK Root: $sdk_root"
else
    echo "      ❌ Android SDK not detected"
fi
echo ""

echo "   c) Testing check_sdkmanager():"
if sdkmanager=$(check_sdkmanager); then
    echo "      ✅ sdkmanager found"
    echo "      Path: $sdkmanager"
else
    echo "      ❌ sdkmanager not found"
fi
echo ""

# Verify PATH includes expected directories
echo "6. Verifying PATH configuration:"
echo ""

if [[ -n "${JAVA_HOME:-}" ]]; then
    if [[ ":$PATH:" == *":${JAVA_HOME}/bin:"* ]]; then
        echo "   ✅ JAVA_HOME/bin is in PATH"
    else
        echo "   ❌ JAVA_HOME/bin is NOT in PATH"
    fi
fi

if [[ -n "${ANDROID_HOME:-}" ]]; then
    if [[ ":$PATH:" == *":${ANDROID_HOME}/platform-tools:"* ]]; then
        echo "   ✅ ANDROID_HOME/platform-tools is in PATH"
    else
        echo "   ❌ ANDROID_HOME/platform-tools is NOT in PATH"
    fi
    
    if [[ ":$PATH:" == *":${ANDROID_HOME}/cmdline-tools"* ]]; then
        echo "   ✅ ANDROID_HOME/cmdline-tools is in PATH"
    else
        echo "   ❌ ANDROID_HOME/cmdline-tools is NOT in PATH"
    fi
fi
echo ""

# Test command availability
echo "7. Testing command availability:"
echo ""

if command -v java &>/dev/null; then
    echo "   ✅ java command is available"
    java -version 2>&1 | head -n 1 | sed 's/^/      /'
else
    echo "   ❌ java command is NOT available"
fi

if command -v adb &>/dev/null; then
    echo "   ✅ adb command is available"
    adb --version 2>&1 | head -n 1 | sed 's/^/      /'
else
    echo "   ❌ adb command is NOT available"
fi

if command -v sdkmanager &>/dev/null; then
    echo "   ✅ sdkmanager command is available"
else
    echo "   ❌ sdkmanager command is NOT available"
fi
echo ""

echo "=========================================="
echo "Test Complete"
echo "=========================================="