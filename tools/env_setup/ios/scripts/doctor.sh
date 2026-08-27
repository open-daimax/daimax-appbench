#!/bin/bash

# doctor.sh - Environment detection script for the iOS env setup tool
# Usage: ./doctor.sh <env_type> <project_path>
# Output: JSON report of detected and missing dependencies

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# Main function
main() {
    local env_type="${1:-}"
    local project_path="${2:-}"
    
    # Validate arguments
    if [[ -z "$env_type" ]]; then
        log_error "Usage: $0 <env_type> <project_path>"
        echo '{"error":"Missing env_type argument","error_code":"ERR_INVALID_ARGS"}'
        exit 1
    fi
    
    # Check if running on macOS
    if ! is_macos; then
        log_error "iOS development is only supported on macOS"
        echo '{"error":"iOS development requires macOS","error_code":"ERR_UNSUPPORTED_OS"}'
        exit "$ERR_UNSUPPORTED_OS"
    fi
    
    # Dispatch to appropriate doctor function
    case "$env_type" in
        ios-build)
            doctor_ios_build "$project_path"
            ;;
        ios-install)
            doctor_ios_install
            ;;
        *)
            log_error "Unsupported env_type: $env_type"
            echo "{\"error\":\"Unsupported env_type: $env_type\",\"error_code\":\"ERR_UNSUPPORTED_ENV\"}"
            exit 1
            ;;
    esac
}

# Doctor function for ios-build environment
doctor_ios_build() {
    local project_path="$1"
    
    log_info "Detecting iOS build environment..."
    
    # Initialize result structure
    local detected_items=()
    local missing_items=()
    local error_code=""
    
    # Check if project path exists and is valid
    if [[ -n "$project_path" ]] && [[ ! -d "$project_path" ]]; then
        log_error "Project path does not exist: $project_path"
        echo "{\"error\":\"Project path not found\",\"error_code\":\"ERR_INVALID_PROJECT\"}"
        exit "$ERR_INVALID_PROJECT"
    fi
    
    # Parse project configuration if project path provided
    local project_config="{}"
    if [[ -n "$project_path" ]]; then
        project_config=$(parse_ios_project_config "$project_path")
        log_info "Project configuration: $project_config"
    fi
    
    # Check Xcode Command Line Tools
    if check_xcode_clt; then
        local clt_path
        clt_path=$(xcode-select -p)
        detected_items+=("\"xcode_clt\":\"$clt_path\"")
        log_success "Xcode Command Line Tools: $clt_path"
    else
        missing_items+=('{"name":"xcode-command-line-tools","recommended_version":"latest","reason":"Required for iOS development"}')
        log_warning "Xcode Command Line Tools not found"
        error_code="ERR_NO_CLT"
    fi
    
    # Check Xcode
    local xcode_info
    if xcode_info=$(detect_xcode); then
        local xcode_version
        xcode_version=$(echo "$xcode_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
        local xcode_path
        xcode_path=$(echo "$xcode_info" | grep -o '"path":"[^"]*"' | cut -d'"' -f4)
        
        detected_items+=("\"xcode\":\"$xcode_version\"")
        detected_items+=("\"xcode_path\":\"$xcode_path\"")
        log_success "Xcode: $xcode_version at $xcode_path"
    else
        missing_items+=('{"name":"xcode","recommended_version":"latest","reason":"Required for iOS development and building"}')
        log_warning "Xcode not found"
        error_code="ERR_NO_XCODE"
    fi
    
    # Check Ruby (needed for CocoaPods)
    local ruby_info
    if ruby_info=$(detect_ruby); then
        local ruby_version
        ruby_version=$(echo "$ruby_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
        detected_items+=("\"ruby\":\"$ruby_version\"")
        log_success "Ruby: $ruby_version"
    else
        log_warning "Ruby not found (needed for CocoaPods)"
        # Ruby is usually pre-installed on macOS, but we'll note it
    fi
    
    # Check CocoaPods if project uses it
    local uses_cocoapods=false
    if [[ -n "$project_path" ]]; then
        if check_cocoapods_usage "$project_path"; then
            uses_cocoapods=true
            log_info "Project uses CocoaPods"
            
            local cocoapods_info
            if cocoapods_info=$(detect_cocoapods); then
                local pod_version
                pod_version=$(echo "$cocoapods_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
                detected_items+=("\"cocoapods\":\"$pod_version\"")
                log_success "CocoaPods: $pod_version"
            else
                missing_items+=('{"name":"cocoapods","recommended_version":"latest","reason":"Project uses CocoaPods for dependency management"}')
                log_warning "CocoaPods not found"
            fi
        fi
    else
        # If no project path, check if CocoaPods is installed anyway
        local cocoapods_info
        if cocoapods_info=$(detect_cocoapods); then
            local pod_version
            pod_version=$(echo "$cocoapods_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
            detected_items+=("\"cocoapods\":\"$pod_version\"")
            log_success "CocoaPods: $pod_version"
        fi
    fi
    
    # Check disk space
    log_info "Checking disk space..."
    local available_space
    available_space=$(check_disk_space "$HOME")
    log_info "Available disk space: ${available_space}GB"
    if [[ $available_space -lt 20 ]]; then
        log_warning "Low disk space: ${available_space}GB available (recommend at least 20GB for Xcode)"
        error_code="ERR_DISK_SPACE"
    fi
    
    # Build JSON output
    local detected_json=""
    if [[ ${#detected_items[@]} -gt 0 ]]; then
        detected_json=$(IFS=,; echo "${detected_items[*]}")
    fi
    
    local missing_json=""
    if [[ ${#missing_items[@]} -gt 0 ]]; then
        missing_json=$(IFS=,; echo "${missing_items[*]}")
    fi
    
    local output
    output=$(cat <<EOF
{
  "env_type": "$env_type",
  "project_path": "$project_path",
  "project_config": $project_config,
  "detected": {$detected_json},
  "missing": [$missing_json],
  "install_root": "$DEFAULT_INSTALL_ROOT",
  "available_disk_space_gb": $available_space,
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
    if [[ ${#missing_items[@]} -gt 0 ]]; then
        log_info "Doctor completed: ${#missing_items[@]} missing dependencies"
        exit 0  # Not an error, just reporting missing items
    else
        log_success "Doctor completed: All dependencies satisfied"
        exit 0
    fi
}

# Doctor function for ios-install environment
doctor_ios_install() {
    log_info "Detecting iOS install environment..."
    
    local detected=()
    local missing=()
    local error_code=""
    
    # Check Xcode Command Line Tools
    if check_xcode_clt; then
        local clt_path
        clt_path=$(xcode-select -p)
        detected+=("\"xcode_clt\":\"$clt_path\"")
        log_success "Xcode Command Line Tools: $clt_path"
    else
        missing+=('{"name":"xcode-command-line-tools","recommended_version":"latest","reason":"Required for iOS device communication"}')
        log_warning "Xcode Command Line Tools not found"
        error_code="ERR_NO_CLT"
    fi
    
    # Check for ios-deploy
    log_info "Checking for ios-deploy..."
    local ios_deploy_info
    if ios_deploy_info=$(detect_ios_deploy); then
        local ios_deploy_version
        ios_deploy_version=$(echo "$ios_deploy_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
        detected+=("\"ios_deploy\":\"$ios_deploy_version\"")
        log_success "ios-deploy: $ios_deploy_version"
    else
        missing+=('{"name":"ios-deploy","recommended_version":"latest","reason":"Required for installing apps to iOS devices"}')
        log_warning "ios-deploy not found"
    fi
    
    # Check for libimobiledevice (alternative tool)
    log_info "Checking for libimobiledevice..."
    local libimobiledevice_info
    if libimobiledevice_info=$(detect_libimobiledevice); then
        local version
        version=$(echo "$libimobiledevice_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
        detected+=("\"libimobiledevice\":\"$version\"")
        log_success "libimobiledevice: $version"
    else
        log_info "libimobiledevice not found (optional, ios-deploy is preferred)"
    fi
    
    # Build JSON output
    local detected_json=""
    local missing_json=""
    
    if [[ ${#detected[@]} -gt 0 ]]; then
        detected_json=$(IFS=,; echo "${detected[*]}")
    fi
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        missing_json=$(IFS=,; echo "${missing[*]}")
    fi
    
    local output
    output=$(cat <<EOF
{
  "env_type": "ios-install",
  "project_path": null,
  "detected": {$detected_json},
  "missing": [$missing_json],
  "install_root": "$DEFAULT_INSTALL_ROOT",
  "error_code": $(if [[ -n "$error_code" ]]; then echo "\"$error_code\""; else echo "null"; fi)
}
EOF
)
    
    print_json "$output"
    
    if [[ ${#missing[@]} -eq 0 ]]; then
        log_success "iOS install environment is ready"
        exit 0
    else
        log_warning "iOS install environment has missing dependencies"
        exit 0
    fi
}

# Run main function
main "$@"