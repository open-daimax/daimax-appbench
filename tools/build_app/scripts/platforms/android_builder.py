#!/usr/bin/env python3
"""
Android platform builder
"""

import os
import platform
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
    run_command
)


class AndroidBuilder(BaseBuilder):
    """Builder for Android projects"""
    
    def __init__(self, project_dir, build_type="debug", output_dir=None,
                 clean=False, output_format="apk"):
        """
        Initialize Android builder
        
        Args:
            project_dir: Project root directory
            build_type: Build type (debug or release)
            output_dir: Output directory for build artifacts
            clean: Whether to clean before building
            output_format: Output format (apk or aab)
        """
        super().__init__(project_dir, build_type, output_dir, clean)
        self.output_format = output_format or "apk"
        
        # Inject environment variables from ~/.dev-env/env-setup.sh
        self._inject_dev_env_variables()
    
    def _inject_dev_env_variables(self):
        """Inject environment variables from ~/.dev-env/env-setup.sh"""
        env_setup_path = os.path.expanduser("~/.dev-env/env-setup.sh")
        
        if not os.path.exists(env_setup_path):
            return
        
        try:
            # First, try to source the file and get all environment variables
            # This ensures proper variable expansion
            import subprocess
            result = subprocess.run(
                f'bash -c "source {env_setup_path} && env"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                # Parse environment variables from output
                for line in result.stdout.split('\n'):
                    if '=' in line:
                        key, _, value = line.partition('=')
                        if key and not key.startswith('_'):
                            # Only override if not already set in self.env or if it's a critical variable
                            if key not in self.env or key in ['JAVA_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT']:
                                self.env[key] = value
                
                print_success(f"Loaded {len([k for k in self.env.keys() if k in ['JAVA_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'PATH']])} environment variables from {env_setup_path}")
            else:
                # Fallback to manual parsing if sourcing fails
                self._manual_parse_env_setup(env_setup_path)
                            
        except Exception as e:
            print_warning(f"Failed to inject environment variables from {env_setup_path}: {e}")
            # Try manual parsing as fallback
            self._manual_parse_env_setup(env_setup_path)
    
    def _manual_parse_env_setup(self, env_setup_path):
        """Manually parse env-setup.sh file (fallback method)"""
        try:
            with open(env_setup_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if not line or line.startswith('#') or line.startswith('echo'):
                        continue
                    
                    # Parse export statements
                    if line.startswith('export '):
                        # Remove 'export ' prefix
                        line = line[7:].strip()
                        
                        # Split by '=' to get key and value
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Remove quotes from value
                            if value.startswith('"') and value.endswith('"'):
                                value = value[1:-1]
                            elif value.startswith("'") and value.endswith("'"):
                                value = value[1:-1]
                            
                            # Handle variable expansion like $HOME, $JAVA_HOME, $ANDROID_HOME, $PATH
                            if '$' in value:
                                # Replace $HOME
                                if '$HOME' in value:
                                    value = value.replace('$HOME', os.path.expanduser('~'))
                                
                                # Replace $JAVA_HOME
                                if '$JAVA_HOME' in value and 'JAVA_HOME' in self.env:
                                    value = value.replace('$JAVA_HOME', self.env['JAVA_HOME'])
                                
                                # Replace $ANDROID_HOME
                                if '$ANDROID_HOME' in value and 'ANDROID_HOME' in self.env:
                                    value = value.replace('$ANDROID_HOME', self.env['ANDROID_HOME'])
                                
                                # Replace $PATH - append to existing PATH
                                if '$PATH' in value and key == 'PATH':
                                    value = value.replace('$PATH', self.env.get('PATH', ''))
                            
                            # Set environment variable
                            self.env[key] = value
        except Exception as e:
            print_warning(f"Manual parsing of {env_setup_path} failed: {e}")
    
    def check_environment(self):
        """
        Check if Android build environment is ready
        
        This method performs basic environment checks without attempting to install
        missing dependencies. For environment setup, users should run the built-in
        env setup tool (tools/env_setup/android) separately before building.
        
        Returns:
            bool: True if environment is ready, False otherwise
        """
        print_info("Checking Android build environment...")
        
        # Check Java
        if not self._check_java():
            print_error("Java not found or not properly configured")
            print_info("Please setup Android build environment via the built-in env tool:")
            print_info("  bash tools/env_setup/android/scripts/doctor.sh android-build <project_path>")
            return False
        
        # Check Android SDK
        if not self._check_android_sdk():
            print_error("Android SDK not found or not properly configured")
            print_info("Please setup Android build environment via the built-in env tool:")
            print_info("  bash tools/env_setup/android/scripts/doctor.sh android-build <project_path>")
            return False
        
        # Check Gradle
        if not self._check_gradle():
            print_error("Gradle not found or not properly configured")
            print_info("Please ensure Gradle wrapper exists in project or Gradle is installed globally")
            return False
        
        print_success("Android build environment is ready")
        return True
    
    def setup_environment(self):
        """
        Setup Android build environment
        
        Note: This method is deprecated. Environment setup should be done
        separately using the built-in env setup tool before running build-app.

        Returns:
            bool: Always returns True for backward compatibility
        """
        print_warning("setup_environment() is deprecated")
        print_info("Please run tools/env_setup/android scripts separately before building")
        return True
    
    def validate_project(self):
        """Validate Android project directory"""
        if not os.path.exists(self.project_dir):
            print_error(f"Project directory not found: {self.project_dir}")
            return False
        
        # Check for build.gradle or build.gradle.kts
        build_gradle = os.path.join(self.project_dir, "build.gradle")
        build_gradle_kts = os.path.join(self.project_dir, "build.gradle.kts")
        
        if not (os.path.exists(build_gradle) or os.path.exists(build_gradle_kts)):
            print_error("Not a valid Android project (build.gradle not found)")
            return False
        
        print_success(f"Valid Android project: {self.project_dir}")
        return True
    
    def configure_signing(self, keystore_path, keystore_password,
                         key_alias, key_password):
        """Configure signing for Android release build"""
        if not all([keystore_path, keystore_password, key_alias, key_password]):
            print_error("Missing signing configuration for release build")
            print_info("Required: keystore_path, keystore_password, key_alias, key_password")
            return False
        
        if not os.path.exists(keystore_path):
            print_error(f"Keystore file not found: {keystore_path}")
            return False
        
        # Set environment variables for Gradle
        self.env['RELEASE_STORE_FILE'] = os.path.abspath(keystore_path)
        self.env['RELEASE_STORE_PASSWORD'] = keystore_password
        self.env['RELEASE_KEY_ALIAS'] = key_alias
        self.env['RELEASE_KEY_PASSWORD'] = key_password
        
        print_success("Signing configuration set")
        return True
    
    def build(self, output_format=None):
        """Build Android project"""
        if output_format:
            self.output_format = output_format
        
        print_info(f"Building {self.build_type.upper()} {self.output_format.upper()}")
        
        gradle_cmd = self._get_gradle_command()
        
        # Build command
        tasks = []
        
        if self.clean:
            tasks.append("clean")
        
        # Determine build task
        if self.output_format == "apk":
            if self.build_type == "debug":
                tasks.append("assembleDebug")
            else:
                tasks.append("assembleRelease")
        else:  # aab
            if self.build_type == "debug":
                tasks.append("bundleDebug")
            else:
                tasks.append("bundleRelease")
        
        cmd = f"{gradle_cmd} {' '.join(tasks)}"
        
        print_info(f"Running: {cmd}")
        print_info(f"Working directory: {self.project_dir}")
        
        if not run_command(cmd, cwd=self.project_dir, env=self.env):
            print_error("Build failed")
            return False
        
        print_success("Build completed successfully")
        return True
    
    def copy_output(self):
        """Copy Android build output to specified directory"""
        if not self.output_dir:
            return True
        
        # Determine file patterns based on output format
        patterns = [f".{self.output_format}"]
        
        return len(self._copy_files_to_output(patterns, self.output_dir)) > 0
    
    def _check_java(self):
        """Check if Java is installed"""
        try:
            output = run_command("java -version 2>&1", capture_output=True, env=self.env)
            if output and "version" in output.lower():
                version_line = output.split('\n')[0]
                print_success(f"Java found: {version_line}")
                return True
            return False
        except Exception:
            return False
    
    def _check_android_sdk(self):
        """Check if Android SDK is installed"""
        # First, try to get from environment variables
        android_home = self.env.get('ANDROID_HOME') or self.env.get('ANDROID_SDK_ROOT')
        
        # If not in environment, try to read from local.properties
        if not android_home:
            android_home = self._read_local_properties()
            if android_home:
                # Set environment variable for Gradle to use
                self.env['ANDROID_HOME'] = android_home
                self.env['ANDROID_SDK_ROOT'] = android_home
        
        if android_home and os.path.exists(android_home):
            print_success(f"Android SDK found: {android_home}")
            return True
        
        return False
    
    def _check_gradle(self):
        """Check if Gradle wrapper exists in project"""
        gradlew = os.path.join(self.project_dir, 'gradlew')
        gradlew_bat = os.path.join(self.project_dir, 'gradlew.bat')
        
        if os.path.exists(gradlew) or os.path.exists(gradlew_bat):
            print_success("Gradle wrapper found in project")
            return True
        
        # Check if gradle is installed globally
        try:
            output = run_command("gradle --version", capture_output=True, env=self.env)
            if output:
                print_success("Gradle found globally")
                return True
        except (OSError, FileNotFoundError, RuntimeError) as e:
            print(f"⚠️  Gradle 检测失败 ({type(e).__name__}): {e}")
        
        return False
    
    def _read_local_properties(self):
        """Read Android SDK path from local.properties"""
        local_props = os.path.join(self.project_dir, 'local.properties')
        
        if os.path.exists(local_props):
            try:
                with open(local_props, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith('sdk.dir='):
                            sdk_path = line.split('=', 1)[1].strip()
                            # Handle escaped backslashes on Windows
                            sdk_path = sdk_path.replace('\\:', ':').replace('\\\\', '/')
                            if os.path.exists(sdk_path):
                                print_info(f"Found SDK path in local.properties: {sdk_path}")
                                return sdk_path
            except Exception as e:
                print_warning(f"Failed to read local.properties: {e}")
        
        return None
    
    def _get_gradle_command(self):
        """Get the appropriate Gradle command for the platform"""
        system = platform.system()
        
        if system == "Windows":
            gradlew = os.path.join(self.project_dir, "gradlew.bat")
            if os.path.exists(gradlew):
                return gradlew
        else:
            gradlew = os.path.join(self.project_dir, "gradlew")
            if os.path.exists(gradlew):
                # Make sure it's executable
                os.chmod(gradlew, 0o755)
                return f"./{os.path.basename(gradlew)}"
        
        # Fall back to global gradle
        return "gradle"
    
