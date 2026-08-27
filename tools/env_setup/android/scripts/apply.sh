#!/bin/bash

# apply.sh - Dependency installation script for the Android env setup tool
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
        android-build)
            apply_android_build "$doctor_json"
            ;;
        android-install)
            apply_android_install "$doctor_json"
            ;;
        *)
            log_error "Unsupported env_type: $env_type"
            echo "{\"error\":\"Unsupported env_type: $env_type\",\"error_code\":\"ERR_UNSUPPORTED_ENV\"}"
            exit 1
            ;;
    esac
}

# Apply function for android-build environment
apply_android_build() {
    local doctor_json="$1"
    
    log_info "Installing Android build environment dependencies..."
    
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
            jdk-*)
                local jdk_version="${name#jdk-}"
                if install_jdk "$jdk_version"; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            android-sdk)
                if install_android_sdk; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            android-commandline-tools)
                if install_android_cmdline_tools; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            platform-tools)
                if install_sdk_package "platform-tools"; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            build-tools*)
                if install_sdk_package "$name"; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            platforms*)
                if install_sdk_package "$name"; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            ndk*)
                if install_sdk_package "$name"; then
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
    
    # Accept SDK licenses if sdkmanager is available
    if check_sdkmanager &>/dev/null; then
        log_info "Accepting SDK licenses..."
        accept_sdk_licenses
    fi
    
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
        record_dependencies_to_manifest "android-build"
        
        log_success "Installation completed successfully"
        exit 0
    else
        log_error "Installation completed with errors"
        exit 1
    fi
}

# Install Xcode Command Line Tools (macOS only)
install_xcode_clt() {
    if ! is_macos; then
        log_info "Xcode CLT not required on non-macOS"
        return 0
    fi
    
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
        return 0
    else
        log_error "Xcode Command Line Tools installation failed or timed out"
        return 1
    fi
}

# Install JDK
install_jdk() {
    local version="$1"
    
    # Check if already installed
    if detect_java &>/dev/null; then
        local current_version
        current_version=$(detect_java | grep -o '"version":"[^"]*"' | cut -d'"' -f4 | cut -d. -f1)
        if [[ $current_version -ge $version ]]; then
            log_info "JDK $current_version already installed (>= required $version)"
            return 0
        fi
    fi
    
    log_info "Installing JDK $version..."
    
    local jdk_dir="${DEFAULT_INSTALL_ROOT}/jdk"
    ensure_dir "$jdk_dir"
    
    # Determine download URL based on OS and architecture
    local os_type=""
    local arch_type=""
    
    if is_macos; then
        os_type="macos"
        arch_type=$(uname -m)
        if [[ "$arch_type" == "arm64" ]]; then
            arch_type="aarch64"
        else
            arch_type="x64"
        fi
    elif is_linux; then
        os_type="linux"
        arch_type=$(uname -m)
        if [[ "$arch_type" == "aarch64" ]]; then
            arch_type="aarch64"
        else
            arch_type="x64"
        fi
    else
        log_error "Unsupported OS for JDK installation"
        return 1
    fi
    
    # Use Adoptium/Eclipse Temurin (open source JDK)
    # Try multiple download sources
    local jdk_archive="${jdk_dir}/jdk-${version}.tar.gz"
    local download_success=false
    
    # Determine the correct file name for Tsinghua mirror
    local tuna_filename=""
    if [[ "$os_type" == "macos" ]]; then
        if [[ "$arch_type" == "aarch64" ]]; then
            tuna_filename="OpenJDK${version}U-jdk_aarch64_mac_hotspot_${version}.0.13_11.tar.gz"
        else
            tuna_filename="OpenJDK${version}U-jdk_x64_mac_hotspot_${version}.0.13_11.tar.gz"
        fi
    elif [[ "$os_type" == "linux" ]]; then
        if [[ "$arch_type" == "aarch64" ]]; then
            tuna_filename="OpenJDK${version}U-jdk_aarch64_linux_hotspot_${version}.0.13_11.tar.gz"
        else
            tuna_filename="OpenJDK${version}U-jdk_x64_linux_hotspot_${version}.0.13_11.tar.gz"
        fi
    fi
    
    # Try Tsinghua mirror first (fastest in China)
    local jdk_url="https://mirrors.tuna.tsinghua.edu.cn/Adoptium/${version}/jdk/${arch_type}/${os_type}/${tuna_filename}"
    log_info "Downloading JDK from Tsinghua mirror (attempt 1)..."
    if download_file "$jdk_url" "$jdk_archive"; then
        download_success=true
    else
        # Try Adoptium API v3
        jdk_url="https://api.adoptium.net/v3/binary/latest/${version}/ga/${os_type}/${arch_type}/jdk/hotspot/normal/eclipse"
        log_info "Trying Adoptium API (attempt 2)..."
        if download_file "$jdk_url" "$jdk_archive"; then
            download_success=true
        else
            # Try GitHub releases
            jdk_url="https://github.com/adoptium/temurin${version}-binaries/releases/download/jdk-${version}.0.13%2B11/${tuna_filename}"
            log_info "Trying GitHub releases (attempt 3)..."
            if download_file "$jdk_url" "$jdk_archive"; then
                download_success=true
            else
                # Try using Homebrew as last resort on macOS
                if is_macos && command -v brew &>/dev/null; then
                    log_info "Trying Homebrew installation (attempt 4)..."
                    log_warning "This may require sudo password..."
                    if brew install openjdk@${version} 2>&1; then
                        # Find the installed JDK
                        local brew_jdk="/opt/homebrew/opt/openjdk@${version}"
                        if [[ ! -d "$brew_jdk" ]]; then
                            brew_jdk="/usr/local/opt/openjdk@${version}"
                        fi
                        if [[ -d "$brew_jdk" ]]; then
                            # Create symlink to our jdk directory
                            ln -sf "$brew_jdk" "$jdk_dir"
                            download_success=true
                        fi
                    fi
                fi
            fi
        fi
    fi
    
    if [[ "$download_success" == false ]]; then
        log_error "Failed to download JDK from all sources"
        return 1
    fi
    
    # Extract if we downloaded an archive
    if [[ -f "$jdk_archive" ]]; then
        log_info "Extracting JDK..."
        tar -xzf "$jdk_archive" -C "$jdk_dir" --strip-components=1
        rm "$jdk_archive"
    fi
    
    # Set JAVA_HOME for current session
    export JAVA_HOME="$jdk_dir"
    export PATH="${JAVA_HOME}/bin:${PATH}"
    
    log_success "JDK $version installed to $jdk_dir"
    return 0
}

# Install Android SDK base
install_android_sdk() {
    local sdk_root="${DEFAULT_INSTALL_ROOT}/android-sdk"
    
    if [[ -d "$sdk_root" ]]; then
        log_info "Android SDK directory already exists: $sdk_root"
        export ANDROID_HOME="$sdk_root"
        export ANDROID_SDK_ROOT="$sdk_root"
        return 0
    fi
    
    log_info "Creating Android SDK directory..."
    ensure_dir "$sdk_root"
    
    export ANDROID_HOME="$sdk_root"
    export ANDROID_SDK_ROOT="$sdk_root"
    
    log_success "Android SDK directory created: $sdk_root"
    return 0
}

# Install Android Command-line Tools
install_android_cmdline_tools() {
    local sdk_root="${ANDROID_HOME:-${DEFAULT_INSTALL_ROOT}/android-sdk}"
    
    # Check if already installed
    if check_sdkmanager &>/dev/null; then
        log_info "Android command-line tools already installed"
        return 0
    fi
    
    log_info "Installing Android command-line tools..."
    
    ensure_dir "$sdk_root"
    local cmdline_dir="${sdk_root}/cmdline-tools"
    ensure_dir "$cmdline_dir"
    
    # Determine download URL based on OS
    local cmdline_url=""
    if is_macos; then
        cmdline_url="https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip"
    elif is_linux; then
        cmdline_url="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
    else
        log_error "Unsupported OS for Android SDK installation"
        return 1
    fi
    
    local cmdline_zip="${cmdline_dir}/cmdline-tools.zip"
    
    log_info "Downloading command-line tools..."
    if ! download_file "$cmdline_url" "$cmdline_zip"; then
        log_error "Failed to download command-line tools"
        return 1
    fi
    
    log_info "Extracting command-line tools..."
    unzip -q -o "$cmdline_zip" -d "$cmdline_dir"
    rm "$cmdline_zip"
    
    # Move to 'latest' directory structure
    if [[ -d "${cmdline_dir}/cmdline-tools" ]]; then
        mv "${cmdline_dir}/cmdline-tools" "${cmdline_dir}/latest"
    fi
    
    # Update PATH
    export PATH="${cmdline_dir}/latest/bin:${PATH}"
    
    log_success "Android command-line tools installed"
    return 0
}

# Install SDK package using sdkmanager
install_sdk_package() {
    local package="$1"
    
    local sdkmanager
    if ! sdkmanager=$(check_sdkmanager); then
        log_error "sdkmanager not found, cannot install $package"
        return 1
    fi
    
    log_info "Installing SDK package: $package"
    
    # Check if already installed
    if get_installed_packages | grep -q "^${package}$"; then
        log_info "Package already installed: $package"
        return 0
    fi
    
    # Install package - use a more robust approach
    local install_output
    local install_status=0
    
    # Create a temporary file for yes output to avoid SIGPIPE
    local yes_fifo="/tmp/sdkmanager_yes_$$"
    mkfifo "$yes_fifo" 2>/dev/null || true
    
    # Run yes in background and redirect to fifo
    (yes 2>/dev/null || true) > "$yes_fifo" &
    local yes_pid=$!
    
    # Run sdkmanager with input from fifo
    install_output=$("$sdkmanager" "$package" < "$yes_fifo" 2>&1) || install_status=$?
    
    # Clean up
    kill $yes_pid 2>/dev/null || true
    rm -f "$yes_fifo" 2>/dev/null || true
    
    # Filter and display output
    echo "$install_output" | grep -v "^Info:" | grep -v "^Warning:" | grep -v "^Loading" >&2 || true
    
    # Exit status 141 (SIGPIPE) is acceptable - it means sdkmanager closed the pipe
    if [[ $install_status -eq 0 ]] || [[ $install_status -eq 141 ]]; then
        # Verify package is now installed
        if get_installed_packages | grep -q "^${package}$"; then
            log_success "Installed: $package"
            return 0
        else
            # Check if the output indicates success
            if echo "$install_output" | grep -q "done"; then
                log_success "Installed: $package"
                return 0
            else
                log_error "Installation reported success but package not found: $package"
                return 1
            fi
        fi
    else
        log_error "Failed to install: $package (exit status: $install_status)"
        return 1
    fi
}

# Apply function for android-install environment
apply_android_install() {
    local doctor_json="$1"
    
    log_info "Installing Android install environment dependencies..."
    
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
            android-sdk)
                if install_android_sdk; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            android-commandline-tools)
                if install_android_cmdline_tools; then
                    installed+=("\"$name\"")
                else
                    failed+=("\"$name\"")
                    overall_success=false
                fi
                ;;
            platform-tools)
                if install_sdk_package "platform-tools"; then
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
    
    # Accept SDK licenses if sdkmanager is available
    if check_sdkmanager &>/dev/null; then
        log_info "Accepting SDK licenses..."
        accept_sdk_licenses
    fi
    
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
        record_dependencies_to_manifest "android-install"
        
        log_success "Installation completed successfully"
        exit 0
    else
        log_error "Installation completed with errors"
        exit 1
    fi
}

# Accept SDK licenses
accept_sdk_licenses() {
    local sdkmanager
    if ! sdkmanager=$(check_sdkmanager); then
        log_warning "sdkmanager not found, cannot accept licenses"
        return 1
    fi
    
    log_info "Accepting SDK licenses..."
    yes | "$sdkmanager" --licenses 2>&1 | grep -v "^Info:" | grep -v "^Warning:" >&2 || true
    log_success "SDK licenses accepted"
    return 0
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
        else
            # Fallback: recreate manifest without jq (less reliable)
            log_warning "jq not available, using fallback method"
            manifest_content='{"dependencies":['
            manifest_content+="$new_entry"
            manifest_content+=']}'
        fi
    else
        # Add new entry
        log_info "Adding dependency to manifest: $name"
        if command -v jq &>/dev/null; then
            manifest_content=$(echo "$manifest_content" | jq --argjson entry "$new_entry" \
                '.dependencies += [$entry]')
        else
            # Fallback: append to dependencies array
            log_warning "jq not available, using fallback method"
            manifest_content="${manifest_content%\}*}"
            if [[ "$manifest_content" == *"[]"* ]]; then
                manifest_content="${manifest_content%\[\]}"
                manifest_content+="[$new_entry]}"
            else
                manifest_content="${manifest_content%\]}"
                manifest_content+=",$new_entry]}"
            fi
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

# Record all installed dependencies to manifest
record_dependencies_to_manifest() {
    local env_type="$1"
    
    log_info "Recording installed dependencies to manifest..."
    
    # Record dependencies based on what's installed
    case "$env_type" in
        android-build|android-install)
            # Record Android SDK
            if [[ -d "${DEFAULT_INSTALL_ROOT}/android-sdk" ]]; then
                update_manifest "android-sdk" "${DEFAULT_INSTALL_ROOT}/android-sdk" "latest"
            fi
            
            # Record Android command-line tools
            if [[ -d "${DEFAULT_INSTALL_ROOT}/android-sdk/cmdline-tools/latest" ]]; then
                local cmdline_version="latest"
                update_manifest "android-commandline-tools" "${DEFAULT_INSTALL_ROOT}/android-sdk/cmdline-tools/latest" "$cmdline_version"
            fi
            
            # Record platform-tools
            if [[ -d "${DEFAULT_INSTALL_ROOT}/android-sdk/platform-tools" ]]; then
                local platform_tools_version=""
                if [[ -f "${DEFAULT_INSTALL_ROOT}/android-sdk/platform-tools/source.properties" ]]; then
                    platform_tools_version=$(grep "Pkg.Revision" "${DEFAULT_INSTALL_ROOT}/android-sdk/platform-tools/source.properties" | cut -d'=' -f2 | tr -d ' ')
                fi
                update_manifest "platform-tools" "${DEFAULT_INSTALL_ROOT}/android-sdk/platform-tools" "${platform_tools_version:-unknown}"
            fi
            
            # Record JDK if installed
            if [[ -d "${DEFAULT_INSTALL_ROOT}/jdk" ]]; then
                local jdk_version=""
                if [[ -x "${DEFAULT_INSTALL_ROOT}/jdk/bin/java" ]]; then
                    jdk_version=$("${DEFAULT_INSTALL_ROOT}/jdk/bin/java" -version 2>&1 | head -n 1 | awk -F '"' '{print $2}')
                fi
                update_manifest "jdk" "${DEFAULT_INSTALL_ROOT}/jdk" "${jdk_version:-unknown}"
            fi
            
            # Record build-tools versions
            if [[ -d "${DEFAULT_INSTALL_ROOT}/android-sdk/build-tools" ]]; then
                for build_tool_dir in "${DEFAULT_INSTALL_ROOT}/android-sdk/build-tools"/*; do
                    if [[ -d "$build_tool_dir" ]]; then
                        local build_tool_version
                        build_tool_version=$(basename "$build_tool_dir")
                        update_manifest "build-tools-${build_tool_version}" "$build_tool_dir" "$build_tool_version"
                    fi
                done
            fi
            
            # Record platforms
            if [[ -d "${DEFAULT_INSTALL_ROOT}/android-sdk/platforms" ]]; then
                for platform_dir in "${DEFAULT_INSTALL_ROOT}/android-sdk/platforms"/*; do
                    if [[ -d "$platform_dir" ]]; then
                        local platform_name
                        platform_name=$(basename "$platform_dir")
                        update_manifest "platform-${platform_name}" "$platform_dir" "$platform_name"
                    fi
                done
            fi
            ;;
            
        harmony-build|harmony-install)
            # Record Harmony SDK
            if [[ -d "${DEFAULT_INSTALL_ROOT}/harmony-sdk" ]]; then
                update_manifest "harmony-sdk" "${DEFAULT_INSTALL_ROOT}/harmony-sdk" "latest"
            fi
            ;;
    esac
    
    log_success "Dependencies recorded to manifest"
}

# Run main function
main "$@"
