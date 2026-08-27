#!/usr/bin/env python3
"""
HarmonyOS platform builder
"""

import os
import platform
import re
import sys

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core import (
    BaseBuilder,
    print_info,
    print_success,
    print_warning,
    print_error,
    run_command,
    find_tool_in_path
)


class HarmonyBuilder(BaseBuilder):
    """Builder for HarmonyOS projects"""
    
    def __init__(self, project_dir, build_type="debug", output_dir=None,
                 clean=False, output_format="hap"):
        """
        Initialize HarmonyOS builder
        
        Args:
            project_dir: Project root directory
            build_type: Build type (debug or release)
            output_dir: Output directory for build artifacts
            clean: Whether to clean before building
            output_format: Output format (hap or app)
        """
        super().__init__(project_dir, build_type, output_dir, clean)
        self.output_format = output_format or "hap"
    
    def check_environment(self):
        """Check if HarmonyOS build environment is ready using install-har-env skill"""
        print_info("Checking HarmonyOS build environment using install-har-env skill...")
        
        # Get the install-har-env skill path
        skill_path = self._get_install_har_env_skill_path()
        if not skill_path:
            print_warning("install-har-env skill not found (not yet implemented)")
            print_info("Falling back to basic environment check...")
            return self._check_node() and self._check_ohpm() and self._check_harmony_sdk()
        
        # Run doctor script to detect environment
        doctor_script = os.path.join(skill_path, "scripts", "doctor.sh")
        if not os.path.exists(doctor_script):
            print_error(f"Doctor script not found: {doctor_script}")
            print_info("Falling back to basic environment check...")
            return self._check_node() and self._check_ohpm() and self._check_harmony_sdk()
        
        cmd = f'"{doctor_script}" harmony-build "{self.project_dir}"'
        output = run_command(cmd, capture_output=True, env=self.env)
        
        if not output:
            print_error("Failed to run environment detection")
            print_info("Falling back to basic environment check...")
            return self._check_node() and self._check_ohpm() and self._check_harmony_sdk()
        
        # Parse JSON output
        try:
            import json
            doctor_result = json.loads(output)
            
            # Check if there are missing dependencies
            missing = doctor_result.get('missing', [])
            if not missing:
                print_success("All required components are installed")
                return True
            
            # Store doctor result for setup_environment
            self._doctor_result = doctor_result
            return False
            
        except Exception as e:
            print_error(f"Failed to parse doctor output: {e}")
            print_info("Falling back to basic environment check...")
            return self._check_node() and self._check_ohpm() and self._check_harmony_sdk()
    
    def setup_environment(self):
        """Setup HarmonyOS build environment using install-har-env skill"""
        # Check if we have doctor result from check_environment
        if not hasattr(self, '_doctor_result'):
            print_error("No environment detection result available")
            print_info("Please run check_environment first")
            return False
        
        doctor_result = self._doctor_result
        missing = doctor_result.get('missing', [])
        
        if not missing:
            print_success("All required components are installed")
            return True
        
        # Display missing components
        print_warning("Missing components:")
        for item in missing:
            print_info(f"  - {item.get('name')}: {item.get('reason')}")
        
        # Ask user for permission
        response = input("\nDo you want to install missing components? (y/n): ")
        if response.lower() != 'y':
            print_info("Installation cancelled. Please install components manually.")
            return False
        
        # Get the install-har-env skill path
        skill_path = self._get_install_har_env_skill_path()
        if not skill_path:
            print_error("install-har-env skill not found")
            return False
        
        # Run apply script to install missing dependencies
        apply_script = os.path.join(skill_path, "scripts", "apply.sh")
        if not os.path.exists(apply_script):
            print_error(f"Apply script not found: {apply_script}")
            return False
        
        print_info("Installing missing dependencies...")
        
        import json
        doctor_json = json.dumps(doctor_result)
        cmd = f'"{apply_script}" \'{doctor_json}\''
        
        if not run_command(cmd, env=self.env):
            print_error("Failed to install dependencies")
            return False
        
        # Verify environment after installation
        verify_script = os.path.join(skill_path, "scripts", "verify.sh")
        if os.path.exists(verify_script):
            print_info("Verifying environment...")
            cmd = f'"{verify_script}" harmony-build'
            output = run_command(cmd, capture_output=True, env=self.env)
            
            if output:
                try:
                    verify_result = json.loads(output)
                    if verify_result.get('env_ready'):
                        print_success("Build environment setup completed successfully")
                        return True
                    else:
                        print_error("Environment verification failed")
                        issues = verify_result.get('issues', [])
                        for issue in issues:
                            print_warning(f"  - {issue}")
                        return False
                except Exception as e:
                    print_warning(f"Failed to parse verify output: {e}")
        
        print_success("Build environment setup completed")
        return True
    
    def validate_project(self):
        """Validate HarmonyOS project directory"""
        if not os.path.exists(self.project_dir):
            print_error(f"Project directory not found: {self.project_dir}")
            return False
        
        hvigorfile = os.path.join(self.project_dir, "hvigorfile.ts")
        
        if not os.path.exists(hvigorfile):
            print_error("Not a valid Harmony project (hvigorfile.ts not found)")
            return False
        
        build_profile = os.path.join(self.project_dir, "build-profile.json5")
        if not os.path.exists(build_profile):
            print_warning("build-profile.json5 not found, may cause build issues")
        
        # Check for local SDK configuration
        self._load_local_sdk_config()
        
        print_success(f"Valid Harmony project: {self.project_dir}")
        return True
    
    def configure_signing(self, keystore_path, keystore_password,
                         key_alias, key_password):
        """Configure signing for HarmonyOS release build"""
        if not all([keystore_path, keystore_password, key_alias, key_password]):
            print_error("Missing signing configuration for release build")
            print_info("Required: keystore_path, keystore_password, key_alias, key_password")
            return False
        
        if not os.path.exists(keystore_path):
            print_error(f"Keystore file not found: {keystore_path}")
            return False
        
        self.env['HARMONY_STORE_FILE'] = os.path.abspath(keystore_path)
        self.env['HARMONY_STORE_PASSWORD'] = keystore_password
        self.env['HARMONY_KEY_ALIAS'] = key_alias
        self.env['HARMONY_KEY_PASSWORD'] = key_password
        
        print_success("Signing configuration set")
        return True
    
    def build(self, output_format=None):
        """Build HarmonyOS project"""
        if output_format:
            self.output_format = output_format
        
        print_info(f"Building {self.build_type.upper()} Package")
        
        # Install dependencies
        print_info("Installing dependencies with ohpm...")
        self._install_dependencies()
        
        # Get hvigor command
        hvigor_cmd = self._get_hvigor_command()
        if not hvigor_cmd:
            print_error("Cannot find hvigor build tool")
            return False
        
        # Clean build if requested
        if self.clean:
            clean_cmd = f"{hvigor_cmd} clean"
            print_info(f"Running clean: {clean_cmd}")
            run_command(clean_cmd, cwd=self.project_dir, env=self.env, check=False)
        
        # Detect modules
        modules = self._detect_build_modules()
        
        # Try different build commands
        build_commands = [
            f"{hvigor_cmd} --mode module -p module=entry@default -p product=default assembleHap",
            f"{hvigor_cmd} assembleHap",
            f"{hvigor_cmd} default",
        ]
        
        # Add module-specific commands
        for module in modules:
            build_commands.insert(1, f"{hvigor_cmd} --mode module -p module={module}@default -p product=default assembleHap")
        
        build_success = False
        for cmd in build_commands:
            print_info(f"Attempting: {cmd}")
            print_info(f"Working directory: {self.project_dir}")
            print_info(f"Environment: HARMONY_HOME={self.env.get('HARMONY_HOME', 'not set')}")
            
            result = run_command(cmd, cwd=self.project_dir, env=self.env, check=False, timeout=900)
            
            if result:
                print_success("Build completed successfully")
                build_success = True
                break
            else:
                print_warning("Build attempt failed, trying next command...")
        
        if not build_success:
            print_error("All build attempts failed")
            print_info("\nTroubleshooting tips:")
            print_info("1. Check if the required SDK version is installed in DevEco Studio")
            print_info("2. Verify SDK path in local.properties matches your installation")
            print_info("3. Try running './hvigorw --mode module -p module=entry@default -p product=default assembleHap' manually")
            print_info("4. Check build-profile.json5 for SDK version compatibility")
            print_info("5. Ensure Node.js version is >= 14.19.1")
            return False
        
        return True
    
    def copy_output(self):
        """Copy HarmonyOS build output to specified directory"""
        if not self.output_dir:
            return True
        
        # Determine file patterns based on output format
        patterns = ['.hap', '.app', '.har']
        
        return len(self._copy_files_to_output(patterns, self.output_dir)) > 0
    
    def _check_node(self):
        """Check if Node.js is installed"""
        node_path = find_tool_in_path("node", self.env)
        if not node_path:
            return False
        
        try:
            output = run_command("node --version", capture_output=True, env=self.env)
            if output:
                print_success(f"Node.js found: {output}")
                version = output.replace('v', '').split('.')
                major = int(version[0])
                if major >= 14:
                    return True
                else:
                    print_warning(f"Node.js version {output} is too old. Requires >= 14.19.1")
                    return False
            return False
        except Exception:
            return False
    
    def _check_ohpm(self):
        """Check if ohpm is installed"""
        ohpm_path = find_tool_in_path("ohpm", self.env)
        if not ohpm_path:
            return False
        
        try:
            output = run_command("ohpm --version", capture_output=True, env=self.env)
            if output:
                print_success(f"ohpm found: {output}")
                return True
            return False
        except Exception:
            return False
    
    def _check_harmony_sdk(self):
        """Check if HarmonyOS SDK is installed"""
        env_vars = ['HARMONY_HOME', 'HOS_SDK_HOME', 'DEVECO_SDK_HOME', 'OHOS_SDK_HOME']
        
        # Check if SDK is already configured
        for var in env_vars:
            sdk_path = self.env.get(var)
            if sdk_path and os.path.exists(sdk_path):
                print_success(f"HarmonyOS SDK found via ${var}: {sdk_path}")
                self._setup_sdk_environment(sdk_path)
                return True
        
        # Try to find SDK in common locations
        possible_paths = [
            "/Applications/DevEco-Studio.app/Contents/sdk",
            os.path.expanduser("~/Library/Huawei/Sdk"),
            os.path.expanduser("~/Huawei/Sdk"),
            "C:\\Program Files\\Huawei\\DevEco Studio\\sdk",
            "C:\\Users\\%USERNAME%\\Huawei\\Sdk",
        ]
        
        for path in possible_paths:
            expanded_path = os.path.expandvars(os.path.expanduser(path))
            if os.path.exists(expanded_path):
                print_success(f"HarmonyOS SDK found: {expanded_path}")
                self._setup_sdk_environment(expanded_path)
                return True
        
        return False
    
    def _setup_sdk_environment(self, sdk_root):
        """Setup all required SDK environment variables"""
        if os.path.basename(sdk_root) in ['default', 'HarmonyOS-NEXT-DB6', 'HarmonyOS-5.0.0']:
            harmony_home = sdk_root
            deveco_sdk_home = os.path.dirname(sdk_root)
        elif os.path.basename(sdk_root) in ['sdk', 'Sdk']:
            deveco_sdk_home = sdk_root
            default_sdk = os.path.join(sdk_root, 'default')
            if os.path.exists(default_sdk):
                harmony_home = default_sdk
            else:
                try:
                    versions = [d for d in os.listdir(sdk_root) 
                               if os.path.isdir(os.path.join(sdk_root, d)) and not d.startswith('.')]
                    if versions:
                        harmony_home = os.path.join(sdk_root, versions[0])
                    else:
                        harmony_home = sdk_root
                except:
                    harmony_home = sdk_root
        else:
            harmony_home = sdk_root
            deveco_sdk_home = sdk_root
        
        self.env['HARMONY_HOME'] = harmony_home
        self.env['HOS_SDK_HOME'] = harmony_home
        self.env['OHOS_SDK_HOME'] = harmony_home
        self.env['DEVECO_SDK_HOME'] = deveco_sdk_home
        
        print_success(f"Set HARMONY_HOME: {harmony_home}")
        print_success(f"Set DEVECO_SDK_HOME: {deveco_sdk_home}")
        
        toolchains_path = os.path.join(harmony_home, "toolchains")
        if os.path.exists(toolchains_path):
            current_path = self.env.get('PATH', '')
            if toolchains_path not in current_path:
                self.env['PATH'] = f"{toolchains_path}:{current_path}"
                print_success(f"Added to PATH: {toolchains_path}")
    
    def _load_local_sdk_config(self):
        """Load SDK configuration from local.properties"""
        local_props = os.path.join(self.project_dir, "local.properties")
        if os.path.exists(local_props):
            try:
                with open(local_props, 'r') as f:
                    for line in f:
                        if line.strip().startswith('sdk.dir='):
                            sdk_path = line.split('=', 1)[1].strip()
                            if os.path.exists(sdk_path):
                                print_success(f"Found SDK in local.properties: {sdk_path}")
                                self._setup_sdk_environment(sdk_path)
                                break
            except Exception as e:
                print_warning(f"Failed to read local.properties: {e}")
    
    def _get_hvigor_command(self):
        """Get the appropriate hvigor command"""
        system = platform.system()
        
        # Priority 1: DevEco Studio built-in hvigor
        deveco_hvigor_paths = [
            "/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw",
            "C:\\Program Files\\Huawei\\DevEco Studio\\tools\\hvigor\\bin\\hvigorw.bat",
        ]
        
        for deveco_path in deveco_hvigor_paths:
            if os.path.exists(deveco_path):
                print_success(f"Using DevEco Studio built-in hvigor: {deveco_path}")
                return f'"{deveco_path}"'
        
        # Priority 2: Project hvigor wrapper
        hvigor_wrappers = [
            os.path.join(self.project_dir, "hvigor", "hvigor-pnpm-wrapper.js"),
            os.path.join(self.project_dir, "hvigor", "hvigor-wrapper.js"),
        ]
        
        for wrapper in hvigor_wrappers:
            if os.path.exists(wrapper):
                print_success(f"Using project hvigor wrapper: {wrapper}")
                return f'node "{wrapper}"'
        
        # Priority 3: Project-local hvigorw
        if system == "Windows":
            hvigorw = os.path.join(self.project_dir, "hvigorw.bat")
            if os.path.exists(hvigorw):
                print_success(f"Using project hvigorw: {hvigorw}")
                return f'"{hvigorw}"'
        else:
            hvigorw = os.path.join(self.project_dir, "hvigorw")
            if os.path.exists(hvigorw):
                try:
                    os.chmod(hvigorw, 0o755)
                except Exception as e:
                    print_warning(f"Failed to make hvigorw executable: {e}")
                
                print_success(f"Using project hvigorw: {hvigorw}")
                return f'"{os.path.abspath(hvigorw)}"'
        
        # Priority 4: Global hvigorw
        hvigorw_path = find_tool_in_path("hvigorw", self.env)
        if hvigorw_path:
            print_success(f"Using global hvigorw: {hvigorw_path}")
            return "hvigorw"
        
        # Priority 5: Global hvigor
        hvigor_path = find_tool_in_path("hvigor", self.env)
        if hvigor_path:
            print_success(f"Using global hvigor: {hvigor_path}")
            return "hvigor"
        
        print_error("No hvigor build tool found!")
        return None
    
    def _install_dependencies(self):
        """Install project dependencies"""
        oh_package = os.path.join(self.project_dir, "oh-package.json5")
        if not os.path.exists(oh_package):
            print_info("oh-package.json5 not found, dependencies will be managed by hvigor")
            return True
        
        hvigor_wrappers = [
            os.path.join(self.project_dir, "hvigor", "hvigor-pnpm-wrapper.js"),
            os.path.join(self.project_dir, "hvigor", "hvigor-wrapper.js"),
        ]
        
        has_wrapper = any(os.path.exists(w) for w in hvigor_wrappers)
        
        if has_wrapper:
            print_success("Found hvigor wrapper, dependencies will be auto-managed during build")
            return True
        
        print_info("No hvigor wrapper found, attempting manual dependency installation...")
        try:
            result = run_command("ohpm install", cwd=self.project_dir, env=self.env, check=False, timeout=600)
            if result:
                print_success("Dependencies installed successfully")
                return True
            else:
                print_warning("ohpm install failed, but continuing (build may handle dependencies)")
                return True
        except Exception as e:
            print_warning(f"Dependency installation error: {e}, continuing with build")
            return True
    
    def _detect_build_modules(self):
        """Detect available build modules"""
        build_profile = os.path.join(self.project_dir, "build-profile.json5")
        modules = ["entry"]
        
        if os.path.exists(build_profile):
            try:
                with open(build_profile, 'r', encoding='utf-8') as f:
                    content = f.read()
                    module_matches = re.findall(r'"name"\s*:\s*"([^"]+)"', content)
                    if module_matches:
                        modules = list(set(module_matches))
                        print_info(f"Detected modules: {', '.join(modules)}")
            except Exception as e:
                print_warning(f"Failed to parse build-profile.json5: {e}")
        
        return modules
    
    def _get_install_har_env_skill_path(self):
        """Get the path to install-har-env skill (placeholder for future implementation)"""
        # Try common skill locations
        possible_paths = [
            os.path.expanduser("~/Documents/ACoder/skills/install-har-env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "install-har-env"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # Skill not yet implemented
        return None
