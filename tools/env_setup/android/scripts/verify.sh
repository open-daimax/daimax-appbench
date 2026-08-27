#!/bin/bash

# verify.sh - Environment verification script for the Android env setup tool
# Usage: ./verify.sh <env_type>
# Output: JSON report of verification results

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# Main function
main() {
    local env_type="${1:-}"
    
    # Validate arguments
    if [[ -z "$env_type" ]]; then
        log_error "Usage: $0 <env_type>"
        echo '{"error":"Missing env_type argument","error_code":"ERR_INVALID_ARGS"}'
        exit 1
    fi
    
    # Dispatch to appropriate verify function
    case "$env_type" in
        android-build)
            verify_android_build
            ;;
        android-install)
            verify_android_install
            ;;
        *)
            log_error "Unsupported env_type: $env_type"
            echo "{\"error\":\"Unsupported env_type: $env_type\",\"error_code\":\"ERR_UNSUPPORTED_ENV\"}"
            exit 1
            ;;
    esac
}

# Verify function for android-install environment
verify_android_install() {
    log_info "Verifying Android install environment..."
    
    local verified_tools=()
    local issues=()
    local env_ready=true
    local error_code=""
    
    # Verify Android SDK
    log_info "Checking Android SDK..."
    local android_sdk_root
    if android_sdk_root=$(detect_android_sdk); then
        log_success "Android SDK: $android_sdk_root"
        
        # Verify ANDROID_HOME
        if [[ -n "${ANDROID_HOME:-}" ]]; then
            log_success "ANDROID_HOME: $ANDROID_HOME"
        else
            log_warning "ANDROID_HOME not set (but SDK detected at $android_sdk_root)"
        fi
        
        # Verify sdkmanager
        log_info "Checking sdkmanager..."
        local sdkmanager
        if sdkmanager=$(check_sdkmanager); then
            log_success "sdkmanager: $sdkmanager"
            verified_tools+=("\"sdkmanager\"")
            
            # Test sdkmanager execution
            if "$sdkmanager" --version &>/dev/null; then
                log_success "sdkmanager execution test passed"
            else
                log_error "sdkmanager execution test failed"
                issues+=('{"tool":"sdkmanager","issue":"Execution test failed"}')
                env_ready=false
            fi
        else
            log_error "sdkmanager not found"
            issues+=('{"tool":"sdkmanager","issue":"Not found"}')
            env_ready=false
            error_code="ERR_NO_SDK"
        fi
    else
        log_error "Android SDK not found"
        issues+=('{"tool":"android_sdk","issue":"Not found"}')
        env_ready=false
        error_code="ERR_NO_SDK"
    fi
    
    # Verify platform-tools (adb) - CRITICAL for android-install
    log_info "Checking platform-tools..."
    if command -v adb &>/dev/null; then
        local adb_version
        adb_version=$(adb --version 2>&1 | head -n 1)
        log_success "adb: $adb_version"
        verified_tools+=("\"adb\"")
        
        # Test adb execution
        if adb --version &>/dev/null; then
            log_success "adb execution test passed"
        else
            log_error "adb execution test failed"
            issues+=('{"tool":"adb","issue":"Execution test failed"}')
            env_ready=false
        fi
        
        # Test adb devices command
        log_info "Testing adb devices command..."
        if adb devices &>/dev/null; then
            log_success "adb devices command works"
        else
            log_warning "adb devices command failed (may need to start adb server)"
        fi
    else
        log_error "adb not found in PATH"
        issues+=('{"tool":"adb","issue":"Not found in PATH"}')
        env_ready=false
        error_code="ERR_NO_ADB"
    fi
    
    # Check PATH
    log_info "Checking PATH configuration..."
    local path_issues=()
    
    if [[ -n "${ANDROID_HOME:-}" ]]; then
        if [[ ":$PATH:" != *":${ANDROID_HOME}/platform-tools:"* ]]; then
            log_warning "ANDROID_HOME/platform-tools not in PATH"
            path_issues+=("platform-tools")
        fi
        if [[ ":$PATH:" != *":${ANDROID_HOME}/cmdline-tools"* ]]; then
            log_warning "ANDROID_HOME/cmdline-tools not in PATH"
            path_issues+=("cmdline-tools")
        fi
    fi
    
    if [[ ${#path_issues[@]} -gt 0 ]]; then
        local path_issues_str=$(IFS=,; echo "${path_issues[*]}")
        issues+=("{\"tool\":\"path\",\"issue\":\"Missing in PATH: $path_issues_str\"}")
    fi
    
    # Build JSON output
    local verified_json=""
    if [[ ${#verified_tools[@]} -gt 0 ]]; then
        verified_json=$(IFS=,; echo "${verified_tools[*]}")
    fi
    
    local issues_json=""
    if [[ ${#issues[@]} -gt 0 ]]; then
        issues_json=$(IFS=,; echo "${issues[*]}")
    fi
    
    local output
    output=$(cat <<EOF
{
  "env_ready": $env_ready,
  "verified_tools": [$verified_json],
  "issues": [$issues_json],
  "environment_variables": {
    "ANDROID_HOME": "$(echo ${ANDROID_HOME:-null} | sed 's/^$/null/')",
    "ANDROID_SDK_ROOT": "$(echo ${ANDROID_SDK_ROOT:-null} | sed 's/^$/null/')"
  },
  "error_code": $(if [[ -n "$error_code" ]]; then echo "\"$error_code\""; else echo "null"; fi)
}
EOF
)
    
    # Validate and output JSON
    if validate_json "$output"; then
        print_json "$output"
    else
        log_error "Generated invalid JSON"
        echo '{"error":"Invalid JSON generated","error_code":"ERR_INTERNAL"}'
        exit 1
    fi
    
    # Exit with appropriate code
    if [[ "$env_ready" == true ]]; then
        log_success "Verification completed: Environment is ready"
        exit 0
    else
        log_error "Verification completed: Environment has issues"
        exit 1
    fi
}

# Verify function for android-build environment
verify_android_build() {
    log_info "Verifying Android build environment..."
    
    local verified_tools=()
    local issues=()
    local env_ready=true
    local error_code=""
    
    # Verify Java
    log_info "Checking Java..."
    if command -v java &>/dev/null; then
        local java_version
        java_version=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}')
        log_success "Java: $java_version"
        verified_tools+=("\"java\"")
        
        # Test Java execution
        if java -version &>/dev/null; then
            log_success "Java execution test passed"
        else
            log_error "Java execution test failed"
            issues+=('{"tool":"java","issue":"Execution test failed"}')
            env_ready=false
        fi
    else
        log_error "Java not found in PATH"
        issues+=('{"tool":"java","issue":"Not found in PATH"}')
        env_ready=false
        error_code="ERR_NO_JAVA"
    fi
    
    # Verify JAVA_HOME
    if [[ -n "${JAVA_HOME:-}" ]]; then
        if [[ -d "$JAVA_HOME" ]] && [[ -x "${JAVA_HOME}/bin/java" ]]; then
            log_success "JAVA_HOME: $JAVA_HOME"
        else
            log_warning "JAVA_HOME set but invalid: $JAVA_HOME"
            issues+=('{"tool":"java_home","issue":"JAVA_HOME set but invalid"}')
        fi
    else
        log_warning "JAVA_HOME not set"
    fi
    
    # Verify Android SDK
    log_info "Checking Android SDK..."
    local android_sdk_root
    if android_sdk_root=$(detect_android_sdk); then
        log_success "Android SDK: $android_sdk_root"
        
        # Verify ANDROID_HOME
        if [[ -n "${ANDROID_HOME:-}" ]]; then
            log_success "ANDROID_HOME: $ANDROID_HOME"
        else
            log_warning "ANDROID_HOME not set (but SDK detected at $android_sdk_root)"
        fi
        
        # Verify sdkmanager
        log_info "Checking sdkmanager..."
        local sdkmanager
        if sdkmanager=$(check_sdkmanager); then
            log_success "sdkmanager: $sdkmanager"
            verified_tools+=("\"sdkmanager\"")
            
            # Test sdkmanager execution
            if "$sdkmanager" --version &>/dev/null; then
                log_success "sdkmanager execution test passed"
            else
                log_error "sdkmanager execution test failed"
                issues+=('{"tool":"sdkmanager","issue":"Execution test failed"}')
                env_ready=false
            fi
            
            # List installed packages
            log_info "Checking installed SDK packages..."
            if get_installed_packages &>/dev/null; then
                local package_count
                package_count=$(get_installed_packages | wc -l | tr -d ' ')
                log_success "Found $package_count installed SDK packages"
            else
                log_warning "Could not list installed packages"
            fi
        else
            log_error "sdkmanager not found"
            issues+=('{"tool":"sdkmanager","issue":"Not found"}')
            env_ready=false
            error_code="ERR_NO_SDK"
        fi
    else
        log_error "Android SDK not found"
        issues+=('{"tool":"android_sdk","issue":"Not found"}')
        env_ready=false
        error_code="ERR_NO_SDK"
    fi
    
    # Verify platform-tools (adb)
    log_info "Checking platform-tools..."
    if command -v adb &>/dev/null; then
        local adb_version
        adb_version=$(adb --version 2>&1 | head -n 1)
        log_success "adb: $adb_version"
        verified_tools+=("\"adb\"")
        
        # Test adb execution
        if adb --version &>/dev/null; then
            log_success "adb execution test passed"
        else
            log_error "adb execution test failed"
            issues+=('{"tool":"adb","issue":"Execution test failed"}')
            env_ready=false
        fi
    else
        log_warning "adb not found in PATH (platform-tools may not be installed)"
        issues+=('{"tool":"adb","issue":"Not found in PATH"}')
    fi
    
    # Verify build-tools
    log_info "Checking build-tools..."
    if [[ -n "${android_sdk_root:-}" ]]; then
        local build_tools_dir="${android_sdk_root}/build-tools"
        if [[ -d "$build_tools_dir" ]]; then
            local build_tools_count
            build_tools_count=$(find "$build_tools_dir" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
            if [[ $build_tools_count -gt 0 ]]; then
                log_success "Found $build_tools_count build-tools version(s)"
                verified_tools+=("\"build-tools\"")
            else
                log_warning "build-tools directory exists but is empty"
                issues+=('{"tool":"build-tools","issue":"Directory empty"}')
            fi
        else
            log_warning "build-tools directory not found"
            issues+=('{"tool":"build-tools","issue":"Directory not found"}')
        fi
    fi
    
    # Verify platforms
    log_info "Checking platforms..."
    if [[ -n "${android_sdk_root:-}" ]]; then
        local platforms_dir="${android_sdk_root}/platforms"
        if [[ -d "$platforms_dir" ]]; then
            local platforms_count
            platforms_count=$(find "$platforms_dir" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
            if [[ $platforms_count -gt 0 ]]; then
                log_success "Found $platforms_count platform(s)"
                verified_tools+=("\"platforms\"")
            else
                log_warning "platforms directory exists but is empty"
                issues+=('{"tool":"platforms","issue":"Directory empty"}')
            fi
        else
            log_warning "platforms directory not found"
            issues+=('{"tool":"platforms","issue":"Directory not found"}')
        fi
    fi
    
    # Verify NDK
    log_info "Checking NDK..."
    if [[ -n "${android_sdk_root:-}" ]]; then
        local ndk_dir="${android_sdk_root}/ndk"
        if [[ -d "$ndk_dir" ]]; then
            local ndk_count
            ndk_count=$(find "$ndk_dir" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
            if [[ $ndk_count -gt 0 ]]; then
                log_success "Found $ndk_count NDK version(s)"
                verified_tools+=("\"ndk\"")
                
                # List NDK versions
                local ndk_versions=()
                for version_dir in "$ndk_dir"/*; do
                    if [[ -d "$version_dir" ]]; then
                        local version
                        version=$(basename "$version_dir")
                        ndk_versions+=("$version")
                    fi
                done
                log_info "NDK versions: ${ndk_versions[*]}"
            else
                log_info "NDK directory exists but is empty (NDK not required for all projects)"
            fi
        else
            log_info "NDK directory not found (NDK not required for all projects)"
        fi
    fi
    
    # Verify Xcode CLT (macOS only)
    if is_macos; then
        log_info "Checking Xcode Command Line Tools..."
        if check_xcode_clt; then
            local clt_path
            clt_path=$(xcode-select -p)
            log_success "Xcode CLT: $clt_path"
            verified_tools+=("\"xcode_clt\"")
        else
            log_warning "Xcode Command Line Tools not found"
            issues+=('{"tool":"xcode_clt","issue":"Not found"}')
        fi
    fi
    
    # Check PATH
    log_info "Checking PATH configuration..."
    local path_issues=()
    
    if [[ -n "${JAVA_HOME:-}" ]]; then
        if [[ ":$PATH:" != *":${JAVA_HOME}/bin:"* ]]; then
            log_warning "JAVA_HOME/bin not in PATH"
            path_issues+=("java")
        fi
    fi
    
    if [[ -n "${ANDROID_HOME:-}" ]]; then
        if [[ ":$PATH:" != *":${ANDROID_HOME}/platform-tools:"* ]]; then
            log_warning "ANDROID_HOME/platform-tools not in PATH"
            path_issues+=("platform-tools")
        fi
        if [[ ":$PATH:" != *":${ANDROID_HOME}/cmdline-tools"* ]]; then
            log_warning "ANDROID_HOME/cmdline-tools not in PATH"
            path_issues+=("cmdline-tools")
        fi
    fi
    
    if [[ ${#path_issues[@]} -gt 0 ]]; then
        local path_issues_str=$(IFS=,; echo "${path_issues[*]}")
        issues+=("{\"tool\":\"path\",\"issue\":\"Missing in PATH: $path_issues_str\"}")
    fi
    
    # Build JSON output
    local verified_json=$(IFS=,; echo "${verified_tools[*]}")
    local issues_json=$(IFS=,; echo "${issues[*]}")
    
    local output
    output=$(cat <<EOF
{
  "env_ready": $env_ready,
  "verified_tools": [$verified_json],
  "issues": [$issues_json],
  "environment_variables": {
    "JAVA_HOME": "$(echo ${JAVA_HOME:-null} | sed 's/^$/null/')",
    "ANDROID_HOME": "$(echo ${ANDROID_HOME:-null} | sed 's/^$/null/')",
    "ANDROID_SDK_ROOT": "$(echo ${ANDROID_SDK_ROOT:-null} | sed 's/^$/null/')"
  },
  "error_code": $(if [[ -n "$error_code" ]]; then echo "\"$error_code\""; else echo "null"; fi)
}
EOF
)
    
    # Validate and output JSON
    if validate_json "$output"; then
        print_json "$output"
    else
        log_error "Generated invalid JSON"
        echo '{"error":"Invalid JSON generated","error_code":"ERR_INTERNAL"}'
        exit 1
    fi
    
    # Exit with appropriate code
    if [[ "$env_ready" == true ]]; then
        log_success "Verification completed: Environment is ready"
        exit 0
    else
        log_error "Verification completed: Environment has issues"
        exit 1
    fi
}

# Run main function
main "$@"