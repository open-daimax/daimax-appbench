#!/bin/bash

# doctor.sh - Environment detection script for the Android env setup tool
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
    
    # Dispatch to appropriate doctor function
    case "$env_type" in
        android-build)
            doctor_android_build "$project_path"
            ;;
        android-install)
            doctor_android_install
            ;;
        *)
            log_error "Unsupported env_type: $env_type"
            echo "{\"error\":\"Unsupported env_type: $env_type\",\"error_code\":\"ERR_UNSUPPORTED_ENV\"}"
            exit 1
            ;;
    esac
}

# Doctor function for android-build environment
doctor_android_build() {
    local project_path="$1"
    
    log_info "Detecting Android build environment..."
    
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
    local gradle_config="{}"
    local required_jdk_version=17
    if [[ -n "$project_path" ]]; then
        gradle_config=$(parse_gradle_config "$project_path")
        required_jdk_version=$(get_required_jdk_version "$project_path")
        log_info "Required JDK version: $required_jdk_version"
    fi
    
    # Check Xcode Command Line Tools (macOS only)
    if is_macos; then
        if check_xcode_clt; then
            local clt_path
            clt_path=$(xcode-select -p)
            detected_items+=("\"xcode_clt\":\"$clt_path\"")
            log_success "Xcode Command Line Tools: $clt_path"
        else
            missing_items+=('{"name":"xcode-command-line-tools","recommended_version":"latest","reason":"Required for building on macOS"}')
            log_warning "Xcode Command Line Tools not found"
        fi
    fi
    
    # Check Java/JDK
    local java_info
    if java_info=$(detect_java); then
        local java_version
        java_version=$(echo "$java_info" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)
        local java_home
        java_home=$(echo "$java_info" | grep -o '"home":"[^"]*"' | cut -d'"' -f4)
        
        detected_items+=("\"java\":\"$java_version\"")
        detected_items+=("\"java_home\":\"$java_home\"")
        log_success "Java: $java_version at $java_home"
        
        # Check if Java version meets requirements
        local java_major
        java_major=$(echo "$java_version" | cut -d. -f1)
        if [[ $java_major -lt $required_jdk_version ]]; then
            log_warning "Java version $java_version is older than required JDK $required_jdk_version"
            missing_items+=("{\"name\":\"jdk-$required_jdk_version\",\"recommended_version\":\"$required_jdk_version\",\"reason\":\"Current Java $java_version is older than required JDK $required_jdk_version\"}")
        fi
    else
        missing_items+=("{\"name\":\"jdk-$required_jdk_version\",\"recommended_version\":\"$required_jdk_version\",\"reason\":\"Java not found\"}")
        log_warning "Java not found"
    fi
    
    # Check if project uses NDK
    local uses_ndk=false
    local ndk_version_from_gradle=""
    if [[ -n "$project_path" ]]; then
        if detect_ndk_usage "$project_path"; then
            uses_ndk=true
            log_info "Project uses NDK (native code detected)"
            # Extract NDK version from gradle config
            ndk_version_from_gradle=$(echo "$gradle_config" | grep -o '"ndkVersion":"[^"]*"' | cut -d'"' -f4 || echo "")
        fi
    fi
    
    # Check Android SDK
    log_info "Checking Android SDK..." >&2
    local android_sdk_root
    android_sdk_root=$(detect_android_sdk 2>/dev/null) || android_sdk_root=""
    log_info "Android SDK detection completed" >&2
    if [[ -n "$android_sdk_root" ]]; then
        log_info "Android SDK found at: $android_sdk_root" >&2
        detected_items+=("\"android_sdk\":\"$android_sdk_root\"")
        log_success "Android SDK: $android_sdk_root"
        
        # Check for sdkmanager
        log_info "Checking for sdkmanager..." >&2
        local sdkmanager
        if sdkmanager=$(check_sdkmanager); then
            log_info "sdkmanager found at: $sdkmanager" >&2
            detected_items+=("\"sdkmanager\":\"$sdkmanager\"")
            log_success "sdkmanager: $sdkmanager"
            
            # Get installed packages (may be empty if nothing installed yet)
            log_info "Getting installed packages..." >&2
            local installed_packages
            installed_packages=$(get_installed_packages) || installed_packages=""
            log_info "Installed packages retrieved" >&2
            
            # Check platform-tools
            if [[ -n "$installed_packages" ]] && echo "$installed_packages" | grep -q "^platform-tools"; then
                local pt_version
                pt_version=$(echo "$installed_packages" | grep "^platform-tools" | head -n1)
                detected_items+=("\"platform_tools\":\"installed\"")
                log_success "Platform tools: installed"
            else
                missing_items+=('{"name":"platform-tools","recommended_version":"latest","reason":"Required for adb and other tools"}')
                log_warning "Platform tools not installed"
            fi
            
            # Check build-tools
            local build_tools_installed=false
            local required_build_tools=""
            if [[ "$gradle_config" != "{}" ]]; then
                required_build_tools=$(echo "$gradle_config" | grep -o '"buildTools":"[^"]*"' | cut -d'"' -f4)
            fi
            
            if [[ -n "$installed_packages" ]] && echo "$installed_packages" | grep -q "^build-tools;"; then
                local bt_versions
                bt_versions=$(echo "$installed_packages" | grep "^build-tools;" | sed 's/build-tools;//')
                detected_items+=("\"build_tools\":\"$bt_versions\"")
                log_success "Build tools: $bt_versions"
                build_tools_installed=true
                
                # Check if required version is installed
                if [[ -n "$required_build_tools" ]]; then
                    if ! echo "$bt_versions" | grep -q "$required_build_tools"; then
                        missing_items+=("{\"name\":\"build-tools;$required_build_tools\",\"recommended_version\":\"$required_build_tools\",\"reason\":\"Project requires build-tools $required_build_tools\"}")
                        log_warning "Required build-tools $required_build_tools not installed"
                    fi
                fi
            fi
            
            if [[ "$build_tools_installed" == false ]]; then
                if [[ -n "$required_build_tools" ]]; then
                    missing_items+=("{\"name\":\"build-tools;$required_build_tools\",\"recommended_version\":\"$required_build_tools\",\"reason\":\"Required for building Android projects\"}")
                else
                    missing_items+=('{"name":"build-tools;34.0.0","recommended_version":"34.0.0","reason":"Required for building Android projects"}')
                fi
                log_warning "Build tools not installed"
            fi
            
            # Check platforms
            local compile_sdk=""
            if [[ "$gradle_config" != "{}" ]]; then
                compile_sdk=$(echo "$gradle_config" | grep -o '"compileSdk":[0-9]*' | grep -o '[0-9]*')
            fi
            
            if [[ -n "$installed_packages" ]] && echo "$installed_packages" | grep -q "^platforms;"; then
                local platform_versions
                platform_versions=$(echo "$installed_packages" | grep "^platforms;" | sed 's/platforms;android-//')
                detected_items+=("\"platforms\":\"$platform_versions\"")
                log_success "Platforms: $platform_versions"
                
                # Check if required platform is installed
                if [[ -n "$compile_sdk" ]]; then
                    if ! echo "$platform_versions" | grep -q "$compile_sdk"; then
                        missing_items+=("{\"name\":\"platforms;android-$compile_sdk\",\"recommended_version\":\"android-$compile_sdk\",\"reason\":\"Project requires API level $compile_sdk\"}")
                        log_warning "Required platform android-$compile_sdk not installed"
                    fi
                fi
            else
                if [[ -n "$compile_sdk" ]]; then
                    missing_items+=("{\"name\":\"platforms;android-$compile_sdk\",\"recommended_version\":\"android-$compile_sdk\",\"reason\":\"Required for building Android projects\"}")
                else
                    missing_items+=('{"name":"platforms;android-34","recommended_version":"android-34","reason":"Required for building Android projects"}')
                fi
                log_warning "No Android platforms installed"
            fi
            
            # Check NDK if project uses it
            if [[ "$uses_ndk" == true ]]; then
                log_info "Checking NDK..." >&2
                local ndk_info
                if ndk_info=$(detect_ndk); then
                    detected_items+=("\"ndk\":$ndk_info")
                    log_success "NDK installed: $ndk_info"
                    
                    # Check if required NDK version is installed
                    if [[ -n "$ndk_version_from_gradle" ]]; then
                        if ! echo "$ndk_info" | grep -q "\"$ndk_version_from_gradle\""; then
                            missing_items+=("{\"name\":\"ndk;$ndk_version_from_gradle\",\"recommended_version\":\"$ndk_version_from_gradle\",\"reason\":\"Project requires NDK $ndk_version_from_gradle\"}")
                            log_warning "Required NDK $ndk_version_from_gradle not installed"
                        fi
                    fi
                else
                    # Determine which NDK version to install
                    local recommended_ndk
                    if [[ -n "$ndk_version_from_gradle" ]]; then
                        recommended_ndk="$ndk_version_from_gradle"
                    else
                        recommended_ndk=$(get_recommended_ndk_version "$project_path")
                    fi
                    missing_items+=("{\"name\":\"ndk;$recommended_ndk\",\"recommended_version\":\"$recommended_ndk\",\"reason\":\"Project uses native code and requires NDK\"}")
                    log_warning "NDK not installed"
                fi
            fi
        else
            missing_items+=('{"name":"android-commandline-tools","recommended_version":"latest","reason":"sdkmanager not found, needed to manage SDK components"}')
            log_warning "sdkmanager not found"
        fi
    else
        # Android SDK not found - report all required components
        missing_items+=('{"name":"android-sdk","recommended_version":"latest","reason":"Android SDK not found"}')
        missing_items+=('{"name":"android-commandline-tools","recommended_version":"latest","reason":"Required to manage SDK components"}')
        missing_items+=('{"name":"platform-tools","recommended_version":"latest","reason":"Required for adb and other tools"}')
        
        # Add build-tools based on project config
        local required_build_tools=""
        if [[ "$gradle_config" != "{}" ]]; then
            required_build_tools=$(echo "$gradle_config" | grep -o '"buildTools":"[^"]*"' | cut -d'"' -f4 || echo "")
        fi
        if [[ -n "$required_build_tools" ]]; then
            missing_items+=("{\"name\":\"build-tools;$required_build_tools\",\"recommended_version\":\"$required_build_tools\",\"reason\":\"Required for building Android projects\"}")
        else
            missing_items+=('{"name":"build-tools;34.0.0","recommended_version":"34.0.0","reason":"Required for building Android projects"}')
        fi
        
        # Add platforms based on project config
        local compile_sdk=""
        if [[ "$gradle_config" != "{}" ]]; then
            compile_sdk=$(echo "$gradle_config" | grep -o '"compileSdk":[0-9]*' | grep -o '[0-9]*' || echo "")
        fi
        if [[ -n "$compile_sdk" ]]; then
            missing_items+=("{\"name\":\"platforms;android-$compile_sdk\",\"recommended_version\":\"android-$compile_sdk\",\"reason\":\"Required for building Android projects\"}")
        else
            missing_items+=('{"name":"platforms;android-34","recommended_version":"android-34","reason":"Required for building Android projects"}')
        fi
        
        # Add NDK if project uses it
        if [[ "$uses_ndk" == true ]]; then
            local recommended_ndk
            if [[ -n "$ndk_version_from_gradle" ]]; then
                recommended_ndk="$ndk_version_from_gradle"
            else
                recommended_ndk=$(get_recommended_ndk_version "$project_path")
            fi
            missing_items+=("{\"name\":\"ndk;$recommended_ndk\",\"recommended_version\":\"$recommended_ndk\",\"reason\":\"Project uses native code and requires NDK\"}")
        fi
        
        log_warning "Android SDK not found"
    fi
    
    # Check disk space
    log_info "Checking disk space..." >&2
    local available_space
    available_space=$(check_disk_space "$HOME")
    log_info "Available disk space: ${available_space}GB" >&2
    if [[ $available_space -lt 10 ]]; then
        log_warning "Low disk space: ${available_space}GB available (recommend at least 10GB)"
        error_code="ERR_DISK_SPACE"
    fi
    
    # Build JSON output
    log_info "Building JSON output..." >&2
    local detected_json=""
    if [[ ${#detected_items[@]} -gt 0 ]]; then
        detected_json=$(IFS=,; echo "${detected_items[*]}")
    fi
    log_info "Detected items: ${#detected_items[@]}" >&2

    local missing_json=""
    if [[ ${#missing_items[@]} -gt 0 ]]; then
        missing_json=$(IFS=,; echo "${missing_items[*]}")
    fi
    log_info "Missing items: ${#missing_items[@]}" >&2
    
    log_info "Constructing JSON..." >&2
    local output
    output=$(cat <<EOF
{
  "env_type": "$env_type",
  "project_path": "$project_path",
  "gradle_config": $gradle_config,
  "detected": {$detected_json},
  "missing": [$missing_json],
  "install_root": "$DEFAULT_INSTALL_ROOT",
  "available_disk_space_gb": $available_space,
  "error_code": $(if [[ -n "$error_code" ]]; then echo "\"$error_code\""; else echo "null"; fi)
}
EOF
)

    log_info "Validating JSON..." >&2
    # Validate and output JSON
    if validate_json "$output"; then
        log_info "JSON is valid, printing..." >&2
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

# Doctor function for android-install environment
doctor_android_install() {
    log_info "Detecting Android install environment..."
    
    local detected=()
    local missing=()
    local error_code=""
    
    # Check for Android SDK
    log_info "Checking Android SDK..."
    local android_sdk_root
    if android_sdk_root=$(detect_android_sdk); then
        log_success "Android SDK: $android_sdk_root"
        detected+=("\"android_sdk\":\"$android_sdk_root\"")
        
        # Check for sdkmanager (needed to install platform-tools)
        log_info "Checking for sdkmanager..."
        local sdkmanager
        if sdkmanager=$(check_sdkmanager); then
            log_success "sdkmanager: $sdkmanager"
            detected+=("\"sdkmanager\":\"$sdkmanager\"")
            
            # Check for platform-tools (which includes adb)
            log_info "Checking platform-tools..."
            if command -v adb &>/dev/null; then
                local adb_version
                adb_version=$(adb --version 2>&1 | head -n 1)
                log_success "ADB: $adb_version"
                detected+=("\"adb\":\"$adb_version\"")
            else
                log_warning "ADB not found"
                missing+=('{"name":"platform-tools","recommended_version":"latest","reason":"adb not found in PATH"}')
            fi
        else
            log_warning "sdkmanager not found"
            missing+=('{"name":"android-commandline-tools","recommended_version":"latest","reason":"sdkmanager not found, needed to install platform-tools"}')
            missing+=('{"name":"platform-tools","recommended_version":"latest","reason":"adb not found in PATH"}')
        fi
    else
        log_warning "Android SDK not found"
        missing+=('{"name":"android-sdk","recommended_version":"latest","reason":"Android SDK not detected"}')
        missing+=('{"name":"android-commandline-tools","recommended_version":"latest","reason":"Required for SDK management"}')
        missing+=('{"name":"platform-tools","recommended_version":"latest","reason":"Provides adb for device communication"}')
        error_code="ERR_NO_SDK"
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
  "env_type": "android-install",
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
        log_success "Android install environment is ready"
        exit 0
    else
        log_warning "Android install environment has missing dependencies"
        exit 0
    fi
}

# Run main function
main "$@"
