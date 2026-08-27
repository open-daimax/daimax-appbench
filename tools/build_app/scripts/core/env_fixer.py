#!/usr/bin/env python3
"""
Environment path fixer for build projects
Replaces hardcoded paths with valid environment-dependent paths
"""

import os
import re
import json
from .utils import print_info, print_success, print_warning, print_error, print_header


class EnvFixer:
    """Fix hardcoded environment paths in project files"""
    
    def __init__(self, project_dir, manifest_path="~/.dev-env/manifest.json", env_setup_path="~/.dev-env/env-setup.sh"):
        """
        Initialize environment fixer
        
        Args:
            project_dir: Project root directory
            manifest_path: Path to manifest.json file
            env_setup_path: Path to environment setup script (fallback)
        """
        self.project_dir = os.path.abspath(os.path.expanduser(project_dir))
        self.manifest_path = os.path.abspath(os.path.expanduser(manifest_path))
        self.env_setup_path = os.path.abspath(os.path.expanduser(env_setup_path))
        self.env_vars = {}
        self._load_env_vars()
    
    def _load_env_vars(self):
        """Load environment variables from manifest.json and env-setup.sh, plus shell environment"""
        # Step 1: Load from manifest.json (primary source)
        self._load_from_manifest()
        
        # Step 2: Load from env-setup.sh (fallback/supplement)
        self._load_from_env_setup()
        
        # Step 3: Load from shell environment (complement)
        self._load_from_shell()
        
        print_success(f"Total loaded {len(self.env_vars)} environment variables")
    
    def _load_from_manifest(self):
        """Load environment variables from manifest.json"""
        if not os.path.exists(self.manifest_path):
            print_warning(f"Manifest file not found: {self.manifest_path}")
            return
        
        try:
            with open(self.manifest_path, 'r') as f:
                manifest = json.load(f)
            
            dependencies = manifest.get('dependencies', [])
            if not dependencies:
                print_warning("No dependencies found in manifest.json")
                return
            
            # Build environment variables from dependencies
            for dep in dependencies:
                name = dep.get('name', '')
                path = dep.get('path', '')
                
                if not name or not path:
                    continue
                
                # Map dependency names to environment variable names
                if name == 'android-sdk':
                    self.env_vars['ANDROID_HOME'] = path
                    self.env_vars['ANDROID_SDK_ROOT'] = path
                elif name == 'android-commandline-tools':
                    self.env_vars['ANDROID_CMDLINE_TOOLS'] = path
                elif name == 'platform-tools':
                    self.env_vars['ANDROID_PLATFORM_TOOLS'] = path
                elif name.startswith('build-tools-'):
                    version = name.replace('build-tools-', '')
                    self.env_vars[f'ANDROID_BUILD_TOOLS_{version.replace(".", "_")}'] = path
                    # Also set a generic ANDROID_BUILD_TOOLS to the latest
                    if 'ANDROID_BUILD_TOOLS' not in self.env_vars:
                        self.env_vars['ANDROID_BUILD_TOOLS'] = path
                elif name.startswith('platform-android-'):
                    version = name.replace('platform-android-', '')
                    self.env_vars[f'ANDROID_PLATFORM_{version}'] = path
                elif 'harmony' in name.lower() or 'hwsdk' in name.lower():
                    self.env_vars['HARMONY_HOME'] = path
                elif 'node' in name.lower():
                    self.env_vars['NODE_HOME'] = path
            
            if self.env_vars:
                print_success(f"Loaded {len(self.env_vars)} environment variables from manifest.json")
            
        except json.JSONDecodeError as e:
            print_error(f"Failed to parse manifest.json: {e}")
        except Exception as e:
            print_error(f"Failed to load manifest.json: {e}")
    
    def _load_from_env_setup(self):
        """Load environment variables from env-setup.sh (fallback)"""
        if not os.path.exists(self.env_setup_path):
            print_info(f"Environment setup file not found: {self.env_setup_path} (optional)")
            return
        
        initial_count = len(self.env_vars)
        
        try:
            with open(self.env_setup_path, 'r') as f:
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
                            
                            # Handle variable expansion
                            if '$' in value:
                                # Replace variables with already loaded values
                                for var_name, var_value in self.env_vars.items():
                                    value = value.replace(f'${var_name}', var_value)
                                    value = value.replace(f'${{{var_name}}}', var_value)
                            
                            # Only add if not already present (manifest.json takes precedence)
                            if key not in self.env_vars:
                                self.env_vars[key] = value
            
            new_count = len(self.env_vars) - initial_count
            if new_count > 0:
                print_success(f"Loaded {new_count} additional environment variables from env-setup.sh")
            
        except Exception as e:
            print_error(f"Failed to load environment variables from env-setup.sh: {e}")
    
    def _load_from_shell(self):
        """Load environment variables from current shell environment (complement)"""
        initial_count = len(self.env_vars)
        
        # List of environment variables to check from shell
        shell_env_vars = [
            'ANDROID_HOME',
            'ANDROID_SDK_ROOT',
            'ANDROID_NDK_HOME',
            'JAVA_HOME',
            'GRADLE_HOME',
            'HARMONY_HOME',
            'NODE_HOME',
            'PATH'
        ]
        
        for var_name in shell_env_vars:
            if var_name not in self.env_vars:
                value = os.environ.get(var_name)
                if value:
                    self.env_vars[var_name] = value
        
        new_count = len(self.env_vars) - initial_count
        if new_count > 0:
            print_success(f"Loaded {new_count} additional environment variables from shell")
    
    def fix_android_local_properties(self):
        """
        Fix Android local.properties file
        Replace hardcoded sdk.dir with environment-based path
        
        Returns:
            bool: True if fixed or no fix needed, False if error
        """
        local_props_path = os.path.join(self.project_dir, 'local.properties')
        
        if not os.path.exists(local_props_path):
            print_info("local.properties not found, creating new one")
            return self._create_local_properties()
        
        try:
            # Read current content
            with open(local_props_path, 'r') as f:
                content = f.read()
            
            fixed = False
            
            # Get valid SDK path from environment
            valid_sdk_path = self.env_vars.get('ANDROID_HOME') or self.env_vars.get('ANDROID_SDK_ROOT')
            
            if not valid_sdk_path:
                print_warning("ANDROID_HOME not found in environment setup")
                return True  # Not an error, just skip
            
            # Check if current sdk.dir is different from valid path
            sdk_dir_pattern = r'sdk\.dir\s*=\s*(.+)'
            match = re.search(sdk_dir_pattern, content)
            
            if match:
                current_sdk_path = match.group(1).strip()
                # Normalize paths for comparison
                current_sdk_path = current_sdk_path.replace('\\:', ':').replace('\\\\', '/')
                
                if current_sdk_path != valid_sdk_path:
                    print_info(f"Found hardcoded SDK path: {current_sdk_path}")
                    print_info(f"Replacing with valid path: {valid_sdk_path}")
                    
                    # Replace the sdk.dir line
                    content = re.sub(sdk_dir_pattern, f'sdk.dir={valid_sdk_path}', content)
                    fixed = True
                else:
                    print_success("SDK path is already correct")
            else:
                # sdk.dir not found, add it
                print_info("sdk.dir not found, adding it")
                content += f'\nsdk.dir={valid_sdk_path}\n'
                fixed = True
            
            # Write back if changed
            if fixed:
                with open(local_props_path, 'w') as f:
                    f.write(content)
                print_success(f"Fixed local.properties: {local_props_path}")
            
            return True
            
        except Exception as e:
            print_error(f"Failed to fix local.properties: {e}")
            return False
    
    def _create_local_properties(self):
        """Create new local.properties file with valid SDK path"""
        local_props_path = os.path.join(self.project_dir, 'local.properties')
        
        valid_sdk_path = self.env_vars.get('ANDROID_HOME') or self.env_vars.get('ANDROID_SDK_ROOT')
        
        if not valid_sdk_path:
            print_warning("ANDROID_HOME not found in environment setup")
            return True
        
        try:
            content = f"""## This file is automatically generated by build-app skill.
# Do not modify this file -- YOUR CHANGES WILL BE ERASED!
#
# This file must *NOT* be checked into Version Control Systems,
# as it contains information specific to your local configuration.
#
# Location of the SDK. This is only used by Gradle.
# For customization when using a Version Control System, please read the
# header note.
sdk.dir={valid_sdk_path}
"""
            
            with open(local_props_path, 'w') as f:
                f.write(content)
            
            print_success(f"Created local.properties: {local_props_path}")
            return True
            
        except Exception as e:
            print_error(f"Failed to create local.properties: {e}")
            return False
    
    def fix_gradle_properties(self):
        """
        Fix gradle.properties file
        Replace hardcoded paths with environment-based paths
        
        Returns:
            bool: True if fixed or no fix needed, False if error
        """
        gradle_props_path = os.path.join(self.project_dir, 'gradle.properties')
        
        if not os.path.exists(gradle_props_path):
            print_info("gradle.properties not found, skipping")
            return True
        
        try:
            # Read current content
            with open(gradle_props_path, 'r') as f:
                lines = f.readlines()
            
            fixed = False
            new_lines = []
            
            for line in lines:
                # Check for hardcoded paths in common properties
                if '=' in line and not line.strip().startswith('#'):
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Check if value contains absolute paths that should be environment-based
                    if value.startswith('/') or value.startswith('C:\\') or value.startswith('D:\\'):
                        # Check if this path should be replaced with an environment variable
                        for env_key, env_value in self.env_vars.items():
                            if env_value in value:
                                print_info(f"Found hardcoded path in {key}: {value}")
                                print_info(f"Replacing with environment variable: ${env_key}")
                                line = f"{key}={value.replace(env_value, f'${env_key}')}\n"
                                fixed = True
                                break
                
                new_lines.append(line)
            
            # Write back if changed
            if fixed:
                with open(gradle_props_path, 'w') as f:
                    f.writelines(new_lines)
                print_success(f"Fixed gradle.properties: {gradle_props_path}")
            else:
                print_success("gradle.properties is already correct")
            
            return True
            
        except Exception as e:
            print_error(f"Failed to fix gradle.properties: {e}")
            return False
    
    def fix_harmony_local_properties(self):
        """
        Fix HarmonyOS local.properties file
        Replace hardcoded paths with environment-based paths
        
        Returns:
            bool: True if fixed or no fix needed, False if error
        """
        local_props_path = os.path.join(self.project_dir, 'local.properties')
        
        if not os.path.exists(local_props_path):
            print_info("HarmonyOS local.properties not found, skipping")
            return True
        
        try:
            # Read current content
            with open(local_props_path, 'r') as f:
                content = f.read()
            
            fixed = False
            
            # Get valid Harmony SDK path from environment
            valid_harmony_home = self.env_vars.get('HARMONY_HOME')
            
            if not valid_harmony_home:
                print_warning("HARMONY_HOME not found in environment setup")
                return True
            
            # Check for nodejs.dir, hwsdk.dir, etc.
            patterns = [
                (r'nodejs\.dir\s*=\s*(.+)', 'nodejs.dir', self.env_vars.get('NODE_HOME')),
                (r'hwsdk\.dir\s*=\s*(.+)', 'hwsdk.dir', valid_harmony_home),
            ]
            
            for pattern, key, valid_path in patterns:
                if not valid_path:
                    continue
                
                match = re.search(pattern, content)
                if match:
                    current_path = match.group(1).strip()
                    if current_path != valid_path:
                        print_info(f"Found hardcoded {key}: {current_path}")
                        print_info(f"Replacing with valid path: {valid_path}")
                        content = re.sub(pattern, f'{key}={valid_path}', content)
                        fixed = True
            
            # Write back if changed
            if fixed:
                with open(local_props_path, 'w') as f:
                    f.write(content)
                print_success(f"Fixed HarmonyOS local.properties: {local_props_path}")
            else:
                print_success("HarmonyOS local.properties is already correct")
            
            return True
            
        except Exception as e:
            print_error(f"Failed to fix HarmonyOS local.properties: {e}")
            return False
    
    def fix_all(self, platform="android"):
        """
        Fix all hardcoded paths in project
        
        Args:
            platform: Platform type (android, harmony)
            
        Returns:
            bool: True if all fixes successful, False otherwise
        """
        print_header("Fixing Hardcoded Environment Paths")
        
        if not self.env_vars:
            print_warning("No environment variables loaded, skipping path fixes")
            return True
        
        success = True
        
        if platform == "android":
            success = success and self.fix_android_local_properties()
            success = success and self.fix_gradle_properties()
        elif platform == "harmony":
            success = success and self.fix_harmony_local_properties()
        
        if success:
            print_success("All hardcoded paths fixed successfully")
        else:
            print_error("Some path fixes failed")
        
        return success