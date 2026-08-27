#!/bin/bash

# common.sh - Shared utilities for the iOS env setup tool
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
                xcode)
                    if [[ -d "$path" ]]; then
                        export DEVELOPER_DIR="$path"
                    fi
                    ;;
                cocoapods)
                    if [[ -d "$path" ]]; then
                        export PATH="${path}/bin:${PATH}"
                    fi
                    ;;
                ios-deploy)
                    if [[ -d "$path" ]]; then
                        export PATH="${path}/bin:${PATH}"
                    fi
                    ;;
                libimobiledevice)
                    if [[ -d "$path" ]]; then
                        export PATH="${path}/bin:${PATH}"
                    fi
                    ;;
            esac
        done < <(jq -c '.dependencies[]' "$manifest_file" 2>/dev/null)
        
        # Log that environment was loaded (only if logging functions are available)
        if declare -f log_info >/dev/null 2>&1; then
            log_info "Loaded environment variables from $manifest_file"
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
readonly ERR_NO_XCODE=11
readonly ERR_NO_COCOAPODS=12
readonly ERR_NO_IOS_DEPLOY=13
readonly ERR_NETWORK=14
readonly ERR_PERMISSION=15
readonly ERR_DISK_SPACE=16
readonly ERR_UNSUPPORTED_OS=17
readonly ERR_INVALID_PROJECT=18

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

# Check if Xcode Command Line Tools are installed
check_xcode_clt() {
    if is_macos; then
        if xcode-select -p &>/dev/null; then
            return 0
        else
            return 1
        fi
    fi
    return 1  # iOS development only on macOS
}

# Detect Xcode installation
detect_xcode() {
    local xcode_path=""
    local xcode_version=""
    
    # Try DEVELOPER_DIR environment variable first
    if [[ -n "${DEVELOPER_DIR:-}" ]] && [[ -d "$DEVELOPER_DIR" ]]; then
        xcode_path="$DEVELOPER_DIR"
    # Try xcode-select
    elif xcode-select -p &>/dev/null; then
        xcode_path=$(xcode-select -p)
    # Try common locations
    elif [[ -d "/Applications/Xcode.app/Contents/Developer" ]]; then
        xcode_path="/Applications/Xcode.app/Contents/Developer"
    fi
    
    if [[ -n "$xcode_path" ]]; then
        # Get Xcode version
        if [[ -x "${xcode_path}/usr/bin/xcodebuild" ]]; then
            xcode_version=$("${xcode_path}/usr/bin/xcodebuild" -version 2>/dev/null | head -n 1 | awk '{print $2}')
        fi
        
        echo "{\"path\":\"$xcode_path\",\"version\":\"${xcode_version:-unknown}\"}"
        return 0
    else
        echo "{}"
        return 1
    fi
}

# Detect CocoaPods installation
detect_cocoapods() {
    local pod_path=""
    local pod_version=""
    
    # Check if pod command is available
    if command -v pod &>/dev/null; then
        pod_path=$(command -v pod)
        pod_version=$(pod --version 2>/dev/null || echo "unknown")
        echo "{\"path\":\"$pod_path\",\"version\":\"$pod_version\"}"
        return 0
    fi
    
    echo "{}"
    return 1
}

# Detect Ruby installation
detect_ruby() {
    local ruby_version=""
    local ruby_path=""
    
    if command -v ruby &>/dev/null; then
        ruby_path=$(command -v ruby)
        ruby_version=$(ruby --version 2>/dev/null | awk '{print $2}')
        echo "{\"path\":\"$ruby_path\",\"version\":\"$ruby_version\"}"
        return 0
    fi
    
    echo "{}"
    return 1
}

# Detect ios-deploy installation
detect_ios_deploy() {
    local ios_deploy_path=""
    local ios_deploy_version=""
    
    if command -v ios-deploy &>/dev/null; then
        ios_deploy_path=$(command -v ios-deploy)
        ios_deploy_version=$(ios-deploy --version 2>/dev/null || echo "unknown")
        echo "{\"path\":\"$ios_deploy_path\",\"version\":\"$ios_deploy_version\"}"
        return 0
    fi
    
    echo "{}"
    return 1
}

# Detect libimobiledevice installation
detect_libimobiledevice() {
    local ideviceinstaller_path=""
    local version=""
    
    if command -v ideviceinstaller &>/dev/null; then
        ideviceinstaller_path=$(command -v ideviceinstaller)
        version=$(ideviceinstaller --version 2>/dev/null | head -n 1 || echo "unknown")
        echo "{\"path\":\"$ideviceinstaller_path\",\"version\":\"$version\"}"
        return 0
    fi
    
    echo "{}"
    return 1
}

# Parse Xcode project to extract required iOS version
parse_ios_project_config() {
    local project_path="$1"
    local pbxproj_file=""
    
    # Find .xcodeproj file
    if [[ -d "$project_path" ]]; then
        pbxproj_file=$(find "$project_path" -name "project.pbxproj" -type f | head -n 1)
    fi
    
    if [[ -z "$pbxproj_file" ]]; then
        log_warning "No Xcode project file found"
        echo "{}"
        return 0
    fi
    
    local ios_deployment_target=""
    local swift_version=""
    
    # Extract IPHONEOS_DEPLOYMENT_TARGET
    ios_deployment_target=$(grep -m 1 "IPHONEOS_DEPLOYMENT_TARGET" "$pbxproj_file" | grep -oE "[0-9]+\.[0-9]+" | head -n 1)
    
    # Extract SWIFT_VERSION
    swift_version=$(grep -m 1 "SWIFT_VERSION" "$pbxproj_file" | grep -oE "[0-9]+\.[0-9]+" | head -n 1)
    
    # Build JSON output
    local json="{"
    [[ -n "$ios_deployment_target" ]] && json+="\"iosDeploymentTarget\":\"$ios_deployment_target\","
    [[ -n "$swift_version" ]] && json+="\"swiftVersion\":\"$swift_version\","
    json="${json%,}"  # Remove trailing comma
    json+="}"
    
    echo "$json"
}

# Check if project uses CocoaPods
check_cocoapods_usage() {
    local project_path="$1"
    
    # Check for Podfile
    if [[ -f "${project_path}/Podfile" ]]; then
        return 0
    fi
    
    return 1
}

# Check available disk space (in GB)
check_disk_space() {
    local path="${1:-$HOME}"
    local available_gb
    
    if is_macos; then
        available_gb=$(df -g "$path" | tail -1 | awk '{print $4}')
    else
        available_gb=0
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

# Validate JSON output
validate_json() {
    local json="$1"
    if command -v jq &>/dev/null; then
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
        printf '%s\n' "$json" | jq . 2>/dev/null || printf '%s\n' "$json"
    else
        printf '%s\n' "$json"
    fi
}

# Update manifest.json with installed dependencies
update_manifest() {
    local name="$1"
    local path="$2"
    local version="${3:-unknown}"
    
    local manifest_file="${DEFAULT_INSTALL_ROOT}/manifest.json"
    
    # Ensure the .dev-env directory exists
    ensure_dir "$DEFAULT_INSTALL_ROOT"
    
    # Initialize manifest.json if it doesn't exist
    if [[ ! -f "$manifest_file" ]]; then
        log_info "Creating manifest file: $manifest_file"
        echo '{"dependencies":[]}' > "$manifest_file"
    fi
    
    # Read existing manifest
    local manifest_content
    manifest_content=$(cat "$manifest_file")
    
    # Check if dependency already exists
    local existing_entry=""
    if command -v jq &>/dev/null; then
        existing_entry=$(echo "$manifest_content" | jq -r ".dependencies[] | select(.name == \"$name\") | .name" 2>/dev/null || echo "")
    fi
    
    # Build new dependency entry
    local new_entry
    new_entry=$(cat <<EOF
{
  "name": "$name",
  "path": "$path",
  "version": "$version",
  "installed_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF
)
    
    # Update manifest
    if [[ -n "$existing_entry" ]]; then
        # Update existing entry
        log_info "Updating dependency in manifest: $name"
        if command -v jq &>/dev/null; then
            manifest_content=$(echo "$manifest_content" | jq --argjson entry "$new_entry" \
                'del(.dependencies[] | select(.name == $entry.name)) | .dependencies += [$entry]')
        fi
    else
        # Add new entry
        log_info "Adding dependency to manifest: $name"
        if command -v jq &>/dev/null; then
            manifest_content=$(echo "$manifest_content" | jq --argjson entry "$new_entry" \
                '.dependencies += [$entry]')
        fi
    fi
    
    # Write updated manifest
    if command -v jq &>/dev/null; then
        echo "$manifest_content" | jq . > "$manifest_file"
    else
        echo "$manifest_content" > "$manifest_file"
    fi
    
    log_success "Manifest updated: $manifest_file"
}