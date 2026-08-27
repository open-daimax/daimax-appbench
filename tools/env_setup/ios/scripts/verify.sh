#!/bin/bash

# verify.sh - Environment verification script for the iOS env setup tool
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
    
    # Check if running on macOS
    if ! is_macos; then
        log_error "iOS development is only supported on macOS"
        echo '{"error":"iOS development requires macOS","error_code":"ERR_UNSUPPORTED_OS"}'
        exit "$ERR_UNSUPPORTED_OS"
    fi
    
    # Dispatch to appropriate verify function
    case "$env_type" in
        ios-build)
            verify_ios_build
            ;;
        ios-install)
            verify_ios_install
            ;;
        *)
            log_error "Unsupported env_type: $env_type"
            echo "{\"error\":\"Unsupported env_type: $env_type\",\"error_code\":\"ERR_UNSUPPORTED_ENV\"}"
            exit 1
            ;;
    esac
}

# Verify ios-build environment
verify_ios_build() {
    log_info "Verifying iOS build environment..."
    
    local verified_tools=()
    local issues=()
    local env_ready=true
    local error_code=""
    
    # Verify Xcode Command Line Tools
    if check_xcode_clt; then
        verified_tools+=("\"xcode-command-line-tools\"")
        log_success "✓ Xcode Command Line Tools"
    else
        issues+=("\"Xcode Command Line Tools not found\"")
        env_ready=false
        error_code="ERR_NO_CLT"
        log_error "✗ Xcode Command Line Tools not found"
    fi
    
    # Verify Xcode
    local xcode_info
    if xcode_info=$(detect_xcode); then
        local xcode_version
        xcode_version=$(echo "$xcode_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
        verified_tools+=("\"xcode\"")
        log_success "✓ Xcode $xcode_version"
        
        # Verify xcodebuild is accessible
        if command -v xcodebuild &>/dev/null; then
            verified_tools+=("\"xcodebuild\"")
            log_success "✓ xcodebuild command"
        else
            issues+=("\"xcodebuild command not accessible\"")
            env_ready=false
            log_error "✗ xcodebuild command not accessible"
        fi
    else
        issues+=("\"Xcode not found\"")
        env_ready=false
        error_code="ERR_NO_XCODE"
        log_error "✗ Xcode not found"
    fi
    
    # Verify Ruby (for CocoaPods)
    if command -v ruby &>/dev/null; then
        verified_tools+=("\"ruby\"")
        local ruby_version
        ruby_version=$(ruby --version 2>/dev/null | awk '{print $2}')
        log_success "✓ Ruby $ruby_version"
    else
        issues+=("\"Ruby not found (needed for CocoaPods)\"")
        log_warning "⚠ Ruby not found (needed for CocoaPods)"
    fi
    
    # Verify CocoaPods (optional but common)
    if command -v pod &>/dev/null; then
        verified_tools+=("\"cocoapods\"")
        local pod_version
        pod_version=$(pod --version 2>/dev/null)
        log_success "✓ CocoaPods $pod_version"
    else
        log_info "ℹ CocoaPods not installed (optional)"
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
  "error_code": $(if [[ -n "$error_code" ]]; then echo "\"$error_code\""; else echo "null"; fi)
}
EOF
)
    
    print_json "$output"
    
    if [[ "$env_ready" == true ]]; then
        log_success "iOS build environment is ready"
        exit 0
    else
        log_error "iOS build environment has issues"
        exit 1
    fi
}

# Verify ios-install environment
verify_ios_install() {
    log_info "Verifying iOS install environment..."
    
    local verified_tools=()
    local issues=()
    local env_ready=true
    local error_code=""
    
    # Verify Xcode Command Line Tools
    if check_xcode_clt; then
        verified_tools+=("\"xcode-command-line-tools\"")
        log_success "✓ Xcode Command Line Tools"
    else
        issues+=("\"Xcode Command Line Tools not found\"")
        env_ready=false
        error_code="ERR_NO_CLT"
        log_error "✗ Xcode Command Line Tools not found"
    fi
    
    # Verify ios-deploy
    if command -v ios-deploy &>/dev/null; then
        verified_tools+=("\"ios-deploy\"")
        local ios_deploy_version
        ios_deploy_version=$(ios-deploy --version 2>/dev/null || echo "unknown")
        log_success "✓ ios-deploy $ios_deploy_version"
        
        # Test ios-deploy functionality
        if ios-deploy --detect &>/dev/null; then
            log_success "✓ ios-deploy can detect devices"
        else
            log_info "ℹ No iOS devices detected (this is normal if no device is connected)"
        fi
    else
        issues+=("\"ios-deploy not found\"")
        env_ready=false
        error_code="ERR_NO_IOS_DEPLOY"
        log_error "✗ ios-deploy not found"
    fi
    
    # Verify libimobiledevice (optional)
    if command -v ideviceinstaller &>/dev/null; then
        verified_tools+=("\"libimobiledevice\"")
        local version
        version=$(ideviceinstaller --version 2>/dev/null | head -n 1 || echo "unknown")
        log_success "✓ libimobiledevice $version"
    else
        log_info "ℹ libimobiledevice not installed (optional)"
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
  "error_code": $(if [[ -n "$error_code" ]]; then echo "\"$error_code\""; else echo "null"; fi)
}
EOF
)
    
    print_json "$output"
    
    if [[ "$env_ready" == true ]]; then
        log_success "iOS install environment is ready"
        exit 0
    else
        log_error "iOS install environment has issues"
        exit 1
    fi
}

# Run main function
main "$@"