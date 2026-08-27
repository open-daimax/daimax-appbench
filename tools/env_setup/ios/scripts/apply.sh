#!/bin/bash

# apply.sh - Dependency installation script for the iOS env setup tool
# Usage: ./apply.sh '<doctor_json>'
# Output: JSON report of installation results

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# Main function
main() {
    local doctor_json="${1:-}"
    
    # Validate arguments
    if [[ -z "$doctor_json" ]]; then
        log_error "Usage: $0 '<doctor_json>'"
        echo '{"error":"Missing doctor_json argument","error_code":"ERR_INVALID_ARGS"}'
        exit 1
    fi
    
    # Validate JSON input
    if ! validate_json "$doctor_json"; then
        log_error "Invalid JSON input"
        echo '{"error":"Invalid JSON input","error_code":"ERR_INVALID_JSON"}'
        exit 1
    fi
    
    # Extract env_type from doctor report
    local env_type
    if command -v jq &>/dev/null; then
        env_type=$(echo "$doctor_json" | jq -r '.env_type')
    else
        env_type=$(echo "$doctor_json" | grep -o '"env_type":"[^"]*"' | cut -d'"' -f4)
    fi
    
    # Dispatch to appropriate apply function
    case "$env_type" in
        ios-build)
            apply_ios_build "$doctor_json"
            ;;
        ios-install)
            apply_ios_install "$doctor_json"
            ;;
        *)
            log_error "Unsupported env_type: $env_type"
            echo "{\"error\":\"Unsupported env_type: $env_type\",\"error_code\":\"ERR_UNSUPPORTED_ENV\"}"
            exit 1
            ;;
    esac
}

# Apply function for ios-build environment
apply_ios_build() {
    local doctor_json="$1"
    
    log_info "Installing iOS build environment dependencies..."
    
    # Initialize result tracking
    local installed=()
    local skipped=()
    local failed=()
    local overall_success=true
    
    # Extract missing items
    local missing_items
    if command -v jq &>/dev/null; then
        missing_items=$(echo "$doctor_json" | jq -r '.missing[] | @json')
    else
        # Fallback: extract missing array manually
        missing_items=$(echo "$doctor_json" | grep -o '"missing":\[[^]]*\]' | sed 's/"missing":\[//;s/\]$//' | tr ',' '\n')
    fi
    
    if [[ -z "$missing_items" ]]; then
        log_success "No missing dependencies to install"
        echo '{"success":true,"installed":[],"skipped":[],"failed":[],"error_code":null,"error_message":null}'
        exit 0
    fi
    
    # Ensure install root exists
    ensure_dir "$DEFAULT_INSTALL_ROOT"
    
    # Process each missing item
    while IFS= read -r item; do
        [[ -z "$item" ]] && continue
        
        local name
        if command -v jq &>/dev/null; then
            name=$(echo "$item" | jq -r '.name')
        else
            name=$(echo "$item" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
        fi
        
        log_info "Processing: $name"
        
        case "$name" in
            xcode-command-line-tools)
                if install_xcode_clt; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            xcode)
                # Xcode must be installed manually from App Store
                log_warning "Xcode must be installed manually from the Mac App Store"
                log_info "Please visit: https://apps.apple.com/app/xcode/id497799835"
                skipped+=("\"$name (manual installation required)\"")
                ;;
            cocoapods)
                if install_cocoapods; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            *)
                log_warning "Unknown dependency: $name (skipping)"
                skipped+=("\"$name\"")
                ;;
        esac
    done <<< "$missing_items"
    
    # Build JSON output
    local installed_json=""
    local skipped_json=""
    local failed_json=""
    
    if [[ ${#installed[@]} -gt 0 ]]; then
        installed_json=$(IFS=,; echo "${installed[*]}")
    fi
    
    if [[ ${#skipped[@]} -gt 0 ]]; then
        skipped_json=$(IFS=,; echo "${skipped[*]}")
    fi
    
    if [[ ${#failed[@]} -gt 0 ]]; then
        failed_json=$(IFS=,; echo "${failed[*]}")
    fi
    
    local output
    output=$(cat <<EOF
{
  "success": $overall_success,
  "installed": [$installed_json],
  "skipped": [$skipped_json],
  "failed": [$failed_json],
  "error_code": $(if [[ "$overall_success" == false ]]; then echo "\"ERR_INSTALL_FAILED\""; else echo "null"; fi),
  "error_message": $(if [[ "$overall_success" == false ]]; then echo "\"Some installations failed\""; else echo "null"; fi)
}
EOF
)
    
    print_json "$output"
    
    if [[ "$overall_success" == true ]]; then
        # Record dependencies to manifest
        record_dependencies_to_manifest "ios-build"
        
        log_success "Installation completed successfully"
        exit 0
    else
        log_error "Installation completed with errors"
        exit 1
    fi
}

# Apply function for ios-install environment
apply_ios_install() {
    local doctor_json="$1"
    
    log_info "Installing iOS install environment dependencies..."
    
    # Initialize result tracking
    local installed=()
    local skipped=()
    local failed=()
    local overall_success=true
    
    # Extract missing items
    local missing_items
    if command -v jq &>/dev/null; then
        missing_items=$(echo "$doctor_json" | jq -r '.missing[] | @json')
    else
        # Fallback: extract missing array manually
        missing_items=$(echo "$doctor_json" | grep -o '"missing":\[[^]]*\]' | sed 's/"missing":\[//;s/\]$//' | tr ',' '\n')
    fi
    
    if [[ -z "$missing_items" ]]; then
        log_success "No missing dependencies to install"
        echo '{"success":true,"installed":[],"skipped":[],"failed":[],"error_code":null,"error_message":null}'
        exit 0
    fi
    
    # Ensure install root exists
    ensure_dir "$DEFAULT_INSTALL_ROOT"
    
    # Process each missing item
    while IFS= read -r item; do
        [[ -z "$item" ]] && continue
        
        local name
        if command -v jq &>/dev/null; then
            name=$(echo "$item" | jq -r '.name')
        else
            name=$(echo "$item" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
        fi
        
        log_info "Processing: $name"
        
        case "$name" in
            xcode-command-line-tools)
                if install_xcode_clt; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            ios-deploy)
                if install_ios_deploy; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            libimobiledevice)
                if install_libimobiledevice; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            *)
                log_warning "Unknown dependency: $name (skipping)"
                skipped+=("\"$name\"")
                ;;
        esac
    done <<< "$missing_items"
    
    # Build JSON output
    local installed_json=""
    local skipped_json=""
    local failed_json=""
    
    if [[ ${#installed[@]} -gt 0 ]]; then
        installed_json=$(IFS=,; echo "${installed[*]}")
    fi
    
    if [[ ${#skipped[@]} -gt 0 ]]; then
        skipped_json=$(IFS=,; echo "${skipped[*]}")
    fi
    
    if [[ ${#failed[@]} -gt 0 ]]; then
        failed_json=$(IFS=,; echo "${failed[*]}")
    fi
    
    local output
    output=$(cat <<EOF
{
  "success": $overall_success,
  "installed": [$installed_json],
  "skipped": [$skipped_json],
  "failed": [$failed_json],
  "error_code": $(if [[ "$overall_success" == false ]]; then echo "\"ERR_INSTALL_FAILED\""; else echo "null"; fi),
  "error_message": $(if [[ "$overall_success" == false ]]; then echo "\"Some installations failed\""; else echo "null"; fi)
}
EOF
)
    
    print_json "$output"
    
    if [[ "$overall_success" == true ]]; then
        # Record dependencies to manifest
        record_dependencies_to_manifest "ios-install"
        
        log_success "Installation completed successfully"
        exit 0
    else
        log_error "Installation completed with errors"
        exit 1
    fi
}

# Install Xcode Command Line Tools
install_xcode_clt() {
    if check_xcode_clt; then
        log_info "Xcode Command Line Tools already installed"
        return 0
    fi
    
    log_info "Installing Xcode Command Line Tools..."
    log_warning "This requires user interaction. Please follow the prompts."
    
    # Trigger installation
    xcode-select --install 2>/dev/null || true
    
    # Wait for installation (with timeout)
    local timeout=300  # 5 minutes
    local elapsed=0
    while ! check_xcode_clt && [[ $elapsed -lt $timeout ]]; do
        sleep 5
        elapsed=$((elapsed + 5))
        log_info "Waiting for Xcode CLT installation... (${elapsed}s)"
    done
    
    if check_xcode_clt; then
        log_success "Xcode Command Line Tools installed"
        
        # Update manifest
        local clt_path
        clt_path=$(xcode-select -p)
        update_manifest "xcode-command-line-tools" "$clt_path" "latest"
        
        return 0
    else
        log_error "Xcode Command Line Tools installation failed or timed out"
        return 1
    fi
}

# Install CocoaPods
install_cocoapods() {
    # Check if already installed
    if detect_cocoapods &>/dev/null; then
        log_info "CocoaPods already installed"
        return 0
    fi
    
    log_info "Installing CocoaPods..."
    
    # Check if we have sudo access
    if ! sudo -n true 2>/dev/null; then
        log_warning "CocoaPods installation requires sudo access"
        log_info "You may be prompted for your password"
    fi
    
    # Install CocoaPods using gem
    if sudo gem install cocoapods 2>&1 | tee /tmp/cocoapods_install.log; then
        log_success "CocoaPods installed"
        
        # Update manifest
        local pod_path
        pod_path=$(command -v pod)
        local pod_version
        pod_version=$(pod --version 2>/dev/null || echo "unknown")
        update_manifest "cocoapods" "$pod_path" "$pod_version"
        
        return 0
    else
        log_error "Failed to install CocoaPods"
        cat /tmp/cocoapods_install.log >&2
        return 1
    fi
}

# Install ios-deploy
install_ios_deploy() {
    # Check if already installed
    if detect_ios_deploy &>/dev/null; then
        log_info "ios-deploy already installed"
        return 0
    fi
    
    log_info "Installing ios-deploy..."
    
    # Check if Homebrew is available
    if ! command -v brew &>/dev/null; then
        log_error "Homebrew is required to install ios-deploy"
        log_info "Please install Homebrew from https://brew.sh"
        return 1
    fi
    
    # Install ios-deploy using Homebrew
    if brew install ios-deploy 2>&1 | tee /tmp/ios_deploy_install.log; then
        log_success "ios-deploy installed"
        
        # Update manifest
        local ios_deploy_path
        ios_deploy_path=$(command -v ios-deploy)
        local ios_deploy_version
        ios_deploy_version=$(ios-deploy --version 2>/dev/null || echo "unknown")
        update_manifest "ios-deploy" "$ios_deploy_path" "$ios_deploy_version"
        
        return 0
    else
        log_error "Failed to install ios-deploy"
        cat /tmp/ios_deploy_install.log >&2
        return 1
    fi
}

# Install libimobiledevice
install_libimobiledevice() {
    # Check if already installed
    if detect_libimobiledevice &>/dev/null; then
        log_info "libimobiledevice already installed"
        return 0
    fi
    
    log_info "Installing libimobiledevice..."
    
    # Check if Homebrew is available
    if ! command -v brew &>/dev/null; then
        log_error "Homebrew is required to install libimobiledevice"
        log_info "Please install Homebrew from https://brew.sh"
        return 1
    fi
    
    # Install libimobiledevice using Homebrew
    if brew install libimobiledevice ideviceinstaller 2>&1 | tee /tmp/libimobiledevice_install.log; then
        log_success "libimobiledevice installed"
        
        # Update manifest
        local ideviceinstaller_path
        ideviceinstaller_path=$(command -v ideviceinstaller)
        local version
        version=$(ideviceinstaller --version 2>/dev/null | head -n 1 || echo "unknown")
        update_manifest "libimobiledevice" "$ideviceinstaller_path" "$version"
        
        return 0
    else
        log_error "Failed to install libimobiledevice"
        cat /tmp/libimobiledevice_install.log >&2
        return 1
    fi
}

# Record all installed dependencies to manifest
record_dependencies_to_manifest() {
    local env_type="$1"
    
    log_info "Recording installed dependencies to manifest..."
    
    # Record dependencies based on what's installed
    case "$env_type" in
        ios-build)
            # Record Xcode Command Line Tools
            if check_xcode_clt; then
                local clt_path
                clt_path=$(xcode-select -p)
                update_manifest "xcode-command-line-tools" "$clt_path" "latest"
            fi
            
            # Record Xcode
            local xcode_info
            if xcode_info=$(detect_xcode); then
                local xcode_path xcode_version
                xcode_path=$(echo "$xcode_info" | grep -o '"path":"[^"]*"' | cut -d'"' -f4)
                xcode_version=$(echo "$xcode_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
                update_manifest "xcode" "$xcode_path" "$xcode_version"
            fi
            
            # Record CocoaPods
            local cocoapods_info
            if cocoapods_info=$(detect_cocoapods); then
                local pod_path pod_version
                pod_path=$(echo "$cocoapods_info" | grep -o '"path":"[^"]*"' | cut -d'"' -f4)
                pod_version=$(echo "$cocoapods_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
                update_manifest "cocoapods" "$pod_path" "$pod_version"
            fi
            ;;
            
        ios-install)
            # Record Xcode Command Line Tools
            if check_xcode_clt; then
                local clt_path
                clt_path=$(xcode-select -p)
                update_manifest "xcode-command-line-tools" "$clt_path" "latest"
            fi
            
            # Record ios-deploy
            local ios_deploy_info
            if ios_deploy_info=$(detect_ios_deploy); then
                local ios_deploy_path ios_deploy_version
                ios_deploy_path=$(echo "$ios_deploy_info" | grep -o '"path":"[^"]*"' | cut -d'"' -f4)
                ios_deploy_version=$(echo "$ios_deploy_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
                update_manifest "ios-deploy" "$ios_deploy_path" "$ios_deploy_version"
            fi
            
            # Record libimobiledevice
            local libimobiledevice_info
            if libimobiledevice_info=$(detect_libimobiledevice); then
                local path version
                path=$(echo "$libimobiledevice_info" | grep -o '"path":"[^"]*"' | cut -d'"' -f4)
                version=$(echo "$libimobiledevice_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
                update_manifest "libimobiledevice" "$path" "$version"
            fi
            ;;
    esac
    
    log_success "Dependencies recorded to manifest"
}

# Run main function
main "$@"