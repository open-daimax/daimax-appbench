#!/bin/bash

# common.sh - Shared utilities for the Android env setup tool
# This file provides common functions used by doctor.sh, apply.sh, and verify.sh

set -euo pipefail

# Load environment variables from manifest.json if it exists
load_env_from_manifest() {
    local manifest_file="${HOME}/.dev-env/manifest.json"
    
    if [[ ! -f "$manifest_file" ]]; then
        return 0
    fi
    
    # Parse manifest and set environment variables
    if command -v jq &>/dev/null; then
        # Use jq for reliable JSON parsing
        local dependencies
        dependencies=$(jq -r '.dependencies[]' "$manifest_file" 2>/dev/null || echo "")
        
        if [[ -z "$dependencies" ]]; then
            return 0
        fi
        
        # Process each dependency
        while IFS= read -r dep; do
            local name path
            name=$(echo "$dep" | jq -r '.name' 2>/dev/null)
            path=$(echo "$dep" | jq -r '.path' 2>/dev/null)
            
            [[ -z "$name" || -z "$path" ]] && continue
            
            # Set environment variables based on dependency type
            case "$name" in
                jdk)
                    if [[ -d "$path" ]]; then
                        export JAVA_HOME="$path"
                        export PATH="${JAVA_HOME}/bin:${PATH}"
                    fi
                    ;;
                android-sdk)
                    if [[ -d "$path" ]]; then
                        export ANDROID_HOME="$path"
                        export ANDROID_SDK_ROOT="$path"
                    fi
                    ;;
                android-commandline-tools)
                    if [[ -d "$path" ]]; then
                        export PATH="${path}/bin:${PATH}"
                    fi
                    ;;
                platform-tools)
                    if [[ -d "$path" ]]; then
                        export PATH="${path}:${PATH}"
                    fi
                    ;;
                harmony-sdk)
                    if [[ -d "$path" ]]; then
                        export HARMONY_HOME="$path"
                    fi
                    ;;
            esac
        done < <(jq -c '.dependencies[]' "$manifest_file" 2>/dev/null)
        
        # Log that environment was loaded (only if logging functions are available)
        if declare -f log_info >/dev/null 2>&1; then
            log_info "Loaded environment variables from $manifest_file"
        fi
    else
        # Fallback: basic parsing without jq (less reliable)
        # Try to extract key dependencies
        if grep -q '"android-sdk"' "$manifest_file"; then
            local android_sdk_path
            android_sdk_path=$(grep -A 3 '"android-sdk"' "$manifest_file" | grep '"path"' | head -n 1 | cut -d'"' -f4)
            if [[ -n "$android_sdk_path" && -d "$android_sdk_path" ]]; then
                export ANDROID_HOME="$android_sdk_path"
                export ANDROID_SDK_ROOT="$android_sdk_path"
            fi
        fi
        
        if grep -q '"jdk"' "$manifest_file"; then
            local jdk_path
            jdk_path=$(grep -A 3 '"jdk"' "$manifest_file" | grep '"path"' | head -n 1 | cut -d'"' -f4)
            if [[ -n "$jdk_path" && -d "$jdk_path" ]]; then
                export JAVA_HOME="$jdk_path"
                export PATH="${JAVA_HOME}/bin:${PATH}"
            fi
        fi
        
        if grep -q '"platform-tools"' "$manifest_file"; then
            local platform_tools_path
            platform_tools_path=$(grep -A 3 '"platform-tools"' "$manifest_file" | grep '"path"' | head -n 1 | cut -d'"' -f4)
            if [[ -n "$platform_tools_path" && -d "$platform_tools_path" ]]; then
                export PATH="${platform_tools_path}:${PATH}"
            fi
        fi
    fi
}

# Load environment variables at script initialization
load_env_from_manifest

# Color codes for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# Error codes
readonly ERR_NO_CLT=10
readonly ERR_NO_JAVA=11
readonly ERR_NO_SDK=12
readonly ERR_NETWORK=13
readonly ERR_PERMISSION=14
readonly ERR_DISK_SPACE=15
readonly ERR_UNSUPPORTED_OS=16
readonly ERR_INVALID_PROJECT=17

# Default installation root
readonly DEFAULT_INSTALL_ROOT="${HOME}/.dev-env"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $*" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*" >&2
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

# Check if running on macOS
is_macos() {
    [[ "$(uname -s)" == "Darwin" ]]
}

# Check if running on Linux
is_linux() {
    [[ "$(uname -s)" == "Linux" ]]
}

# Check if Xcode Command Line Tools are installed (macOS only)
check_xcode_clt() {
    if is_macos; then
        if xcode-select -p &>/dev/null; then
            return 0
        else
            return 1
        fi
    fi
    return 0  # Not required on non-macOS
}

# Detect Java installation and version
detect_java() {
    local java_home=""
    local java_version=""
    
    # Try JAVA_HOME environment variable first
    if [[ -n "${JAVA_HOME:-}" ]] && [[ -x "${JAVA_HOME}/bin/java" ]]; then
        java_home="$JAVA_HOME"
        java_version=$("${JAVA_HOME}/bin/java" -version 2>&1 | head -n 1 | awk -F '"' '{print $2}')
    # Check manifest.json for JAVA_HOME configuration
    elif [[ -f "${DEFAULT_INSTALL_ROOT}/manifest.json" ]]; then
        local configured_java_home=""
        if command -v jq &>/dev/null; then
            configured_java_home=$(jq -r '.dependencies[] | select(.name == "jdk") | .path' "${DEFAULT_INSTALL_ROOT}/manifest.json" 2>/dev/null || echo "")
        else
            # Fallback without jq
            configured_java_home=$(grep -A 3 '"jdk"' "${DEFAULT_INSTALL_ROOT}/manifest.json" | grep '"path"' | head -n 1 | cut -d'"' -f4)
        fi
        
        if [[ -n "$configured_java_home" ]] && [[ -x "${configured_java_home}/bin/java" ]]; then
            java_home="$configured_java_home"
            # Verify java actually works (not just a stub)
            if java_version=$("${configured_java_home}/bin/java" -version 2>&1 | head -n 1 | awk -F '"' '{print $2}'); then
                : # Version extracted successfully
            else
                java_version=""
                java_home=""
            fi
        fi
    fi
    
    # Try java in PATH using command -v (only if not found above)
    if [[ -z "$java_version" ]] && command -v java &>/dev/null; then
        # Verify java actually works (not just a stub like /usr/bin/java on macOS)
        if java_version=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}' 2>/dev/null); then
            # Try to find JAVA_HOME from java executable using java_home command on macOS
            if is_macos && command -v /usr/libexec/java_home &>/dev/null; then
                java_home=$(/usr/libexec/java_home 2>/dev/null || echo "")
            else
                # Fallback: try to derive from java path (without following symlinks to avoid hanging)
                local java_path
                java_path=$(command -v java)
                # Simple parent directory derivation without symlink resolution
                java_home=$(dirname "$(dirname "$java_path")")
            fi
        fi
    fi
    
    if [[ -n "$java_version" ]]; then
        echo "{\"version\":\"$java_version\",\"home\":\"$java_home\"}"
        return 0
    else
        echo "{}"
        return 1
    fi
}

# Detect Android SDK installation
detect_android_sdk() {
    local sdk_root=""
    
    # Try ANDROID_HOME first
    if [[ -n "${ANDROID_HOME:-}" ]] && [[ -d "$ANDROID_HOME" ]]; then
        sdk_root="$ANDROID_HOME"
    # Try ANDROID_SDK_ROOT
    elif [[ -n "${ANDROID_SDK_ROOT:-}" ]] && [[ -d "$ANDROID_SDK_ROOT" ]]; then
        sdk_root="$ANDROID_SDK_ROOT"
    # Try common locations
    elif [[ -d "${HOME}/Library/Android/sdk" ]]; then
        sdk_root="${HOME}/Library/Android/sdk"
    elif [[ -d "${HOME}/Android/Sdk" ]]; then
        sdk_root="${HOME}/Android/Sdk"
    elif [[ -d "${DEFAULT_INSTALL_ROOT}/android-sdk" ]]; then
        sdk_root="${DEFAULT_INSTALL_ROOT}/android-sdk"
    fi
    
    if [[ -n "$sdk_root" ]]; then
        echo "$sdk_root"
        return 0
    else
        return 1
    fi
}

# Check if sdkmanager is available
check_sdkmanager() {
    local sdk_root
    sdk_root=$(detect_android_sdk) || return 1
    
    # Check for sdkmanager in cmdline-tools
    if [[ -x "${sdk_root}/cmdline-tools/latest/bin/sdkmanager" ]]; then
        echo "${sdk_root}/cmdline-tools/latest/bin/sdkmanager"
        return 0
    elif [[ -x "${sdk_root}/cmdline-tools/bin/sdkmanager" ]]; then
        echo "${sdk_root}/cmdline-tools/bin/sdkmanager"
        return 0
    # Check in tools (older SDK structure)
    elif [[ -x "${sdk_root}/tools/bin/sdkmanager" ]]; then
        echo "${sdk_root}/tools/bin/sdkmanager"
        return 0
    fi
    
    return 1
}

# Get installed Android SDK packages
get_installed_packages() {
    local sdkmanager
    sdkmanager=$(check_sdkmanager) || return 1
    
    "$sdkmanager" --list_installed 2>/dev/null | grep -v "^Info:" | grep -v "^Warning:" | grep -v "^Loading" | grep -v "^---" | grep -v "^Installed packages:" | awk '{print $1}' | grep -v "^$"
}

# Parse Gradle file to extract required versions
parse_gradle_config() {
    local project_path="$1"
    local build_gradle="${project_path}/build.gradle"
    local build_gradle_kts="${project_path}/build.gradle.kts"
    local app_build_gradle="${project_path}/app/build.gradle"
    local app_build_gradle_kts="${project_path}/app/build.gradle.kts"
    
    local compile_sdk=""
    local build_tools=""
    local min_sdk=""
    local target_sdk=""
    local ndk_version=""
    
    # Try to find build.gradle or build.gradle.kts
    local gradle_file=""
    if [[ -f "$app_build_gradle" ]]; then
        gradle_file="$app_build_gradle"
    elif [[ -f "$app_build_gradle_kts" ]]; then
        gradle_file="$app_build_gradle_kts"
    elif [[ -f "$build_gradle" ]]; then
        gradle_file="$build_gradle"
    elif [[ -f "$build_gradle_kts" ]]; then
        gradle_file="$build_gradle_kts"
    fi
    
    if [[ -z "$gradle_file" ]]; then
        log_warning "No build.gradle file found in project"
        echo "{}"
        return 0
    fi
    
    # Extract compileSdk
    compile_sdk=$(grep -E "compileSdk[[:space:]]*=?[[:space:]]*[0-9]+" "$gradle_file" | head -n 1 | grep -oE "[0-9]+" | head -n 1)
    
    # Extract buildToolsVersion
    build_tools=$(grep -E "buildToolsVersion[[:space:]]*[\"']?[0-9.]+" "$gradle_file" | head -n 1 | grep -oE "[0-9]+\.[0-9]+\.[0-9]+" | head -n 1)
    
    # Extract minSdk
    min_sdk=$(grep -E "minSdk[[:space:]]*=?[[:space:]]*[0-9]+" "$gradle_file" | head -n 1 | grep -oE "[0-9]+" | head -n 1)
    
    # Extract targetSdk
    target_sdk=$(grep -E "targetSdk[[:space:]]*=?[[:space:]]*[0-9]+" "$gradle_file" | head -n 1 | grep -oE "[0-9]+" | head -n 1)
    
    # Extract ndkVersion
    ndk_version=$(grep -E "ndkVersion[[:space:]]*[\"']?[0-9.]+" "$gradle_file" | head -n 1 | grep -oE "[0-9]+\.[0-9]+\.[0-9]+" | head -n 1)
    
    # Build JSON output
    local json="{"
    [[ -n "$compile_sdk" ]] && json+="\"compileSdk\":$compile_sdk,"
    [[ -n "$build_tools" ]] && json+="\"buildTools\":\"$build_tools\","
    [[ -n "$min_sdk" ]] && json+="\"minSdk\":$min_sdk,"
    [[ -n "$target_sdk" ]] && json+="\"targetSdk\":$target_sdk,"
    [[ -n "$ndk_version" ]] && json+="\"ndkVersion\":\"$ndk_version\","
    json="${json%,}"  # Remove trailing comma
    json+="}"
    
    echo "$json"
}

# Detect if project uses NDK (checks for native code)
detect_ndk_usage() {
    local project_path="$1"
    
    # Check for common indicators of NDK usage
    # 1. Check for CMakeLists.txt
    if find "$project_path" -name "CMakeLists.txt" -type f 2>/dev/null | grep -q .; then
        return 0
    fi
    
    # 2. Check for Android.mk
    if find "$project_path" -name "Android.mk" -type f 2>/dev/null | grep -q .; then
        return 0
    fi
    
    # 3. Check for .cpp, .c, .cc files in jni or cpp directories
    if find "$project_path" -type d \( -name "jni" -o -name "cpp" \) -exec find {} -type f \( -name "*.cpp" -o -name "*.c" -o -name "*.cc" \) \; 2>/dev/null | grep -q .; then
        return 0
    fi
    
    # 4. Check for externalNativeBuild in build.gradle
    if find "$project_path" -name "build.gradle*" -type f -exec grep -l "externalNativeBuild" {} \; 2>/dev/null | grep -q .; then
        return 0
    fi
    
    return 1
}

# Get recommended NDK version based on AGP version
get_recommended_ndk_version() {
    local project_path="$1"
    local gradle_wrapper="${project_path}/gradle/wrapper/gradle-wrapper.properties"
    
    # Default to a stable NDK version
    local ndk_version="26.1.10909125"
    
    if [[ -f "$gradle_wrapper" ]]; then
        local gradle_version
        gradle_version=$(grep "distributionUrl" "$gradle_wrapper" | grep -oE "[0-9]+\.[0-9]+" | head -n 1)
        
        if [[ -n "$gradle_version" ]]; then
            local major_version
            major_version=$(echo "$gradle_version" | cut -d. -f1)
            
            # Gradle 8.x - use NDK 26.x (latest stable)
            if [[ $major_version -ge 8 ]]; then
                ndk_version="26.1.10909125"
            # Gradle 7.x - use NDK 25.x
            elif [[ $major_version -eq 7 ]]; then
                ndk_version="25.2.9519653"
            # Gradle 6.x - use NDK 23.x
            elif [[ $major_version -eq 6 ]]; then
                ndk_version="23.1.7779620"
            fi
        fi
    fi
    
    echo "$ndk_version"
}

# Detect installed NDK versions
detect_ndk() {
    local sdk_root
    sdk_root=$(detect_android_sdk) || return 1
    
    local ndk_dir="${sdk_root}/ndk"
    
    if [[ ! -d "$ndk_dir" ]]; then
        return 1
    fi
    
    # List installed NDK versions
    local ndk_versions=()
    for version_dir in "$ndk_dir"/*; do
        if [[ -d "$version_dir" ]]; then
            local version
            version=$(basename "$version_dir")
            ndk_versions+=("$version")
        fi
    done
    
    if [[ ${#ndk_versions[@]} -eq 0 ]]; then
        return 1
    fi
    
    # Return as JSON array
    local json="["
    for version in "${ndk_versions[@]}"; do
        json+="\"$version\","
    done
    json="${json%,}"
    json+="]"
    
    echo "$json"
    return 0
}

# Determine required JDK version based on AGP version
get_required_jdk_version() {
    local project_path="$1"
    local gradle_wrapper="${project_path}/gradle/wrapper/gradle-wrapper.properties"
    
    # Default to JDK 17 (safe for most modern Android projects)
    local jdk_version=17
    
    if [[ -f "$gradle_wrapper" ]]; then
        local gradle_version
        gradle_version=$(grep "distributionUrl" "$gradle_wrapper" | grep -oE "[0-9]+\.[0-9]+" | head -n 1)
        
        if [[ -n "$gradle_version" ]]; then
            local major_version
            major_version=$(echo "$gradle_version" | cut -d. -f1)
            
            # Gradle 8.x requires JDK 17+
            if [[ $major_version -ge 8 ]]; then
                jdk_version=17
            # Gradle 7.x can use JDK 11 or 17
            elif [[ $major_version -eq 7 ]]; then
                jdk_version=11
            # Gradle 6.x requires JDK 11
            elif [[ $major_version -eq 6 ]]; then
                jdk_version=11
            fi
        fi
    fi
    
    echo "$jdk_version"
}

# Check available disk space (in GB)
check_disk_space() {
    local path="${1:-$HOME}"
    local available_gb
    
    if is_macos; then
        available_gb=$(df -g "$path" | tail -1 | awk '{print $4}')
    else
        available_gb=$(df -BG "$path" | tail -1 | awk '{print $4}' | sed 's/G//')
    fi
    
    echo "$available_gb"
}

# Download file with retry
download_file() {
    local url="$1"
    local output="$2"
    local max_retries=3
    local retry=0
    
    while [[ $retry -lt $max_retries ]]; do
        if curl -fsSL --connect-timeout 10 --max-time 300 -o "$output" "$url"; then
            log_success "Downloaded: $output"
            return 0
        else
            retry=$((retry + 1))
            log_warning "Download failed (attempt $retry/$max_retries)"
            sleep 2
        fi
    done
    
    log_error "Failed to download after $max_retries attempts: $url"
    return 1
}

# Create directory if it doesn't exist
ensure_dir() {
    local dir="$1"
    if [[ ! -d "$dir" ]]; then
        mkdir -p "$dir"
        log_info "Created directory: $dir"
    fi
}

# Export environment variables for current session
export_env_vars() {
    local java_home="$1"
    local android_home="$2"
    
    if [[ -n "$java_home" ]] && [[ -d "$java_home" ]]; then
        export JAVA_HOME="$java_home"
        export PATH="${JAVA_HOME}/bin:${PATH}"
        log_info "Set JAVA_HOME=$JAVA_HOME"
    fi
    
    if [[ -n "$android_home" ]] && [[ -d "$android_home" ]]; then
        export ANDROID_HOME="$android_home"
        export ANDROID_SDK_ROOT="$android_home"
        export PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/emulator:${PATH}"
        log_info "Set ANDROID_HOME=$ANDROID_HOME"
    fi
}

# Validate JSON output
validate_json() {
    local json="$1"
    if command -v jq &>/dev/null; then
        # Use printf to avoid issues with echo and special characters
        printf '%s\n' "$json" | jq . >/dev/null 2>&1
        return $?
    else
        # Basic validation without jq
        if [[ "$json" =~ ^\{.*\}$ ]] || [[ "$json" =~ ^\[.*\]$ ]]; then
            return 0
        else
            return 1
        fi
    fi
}

# Pretty print JSON if jq is available
print_json() {
    local json="$1"
    if command -v jq &>/dev/null; then
        # Use printf to avoid issues with echo and special characters
        printf '%s\n' "$json" | jq . 2>/dev/null || printf '%s\n' "$json"
    else
        printf '%s\n' "$json"
    fi
}
