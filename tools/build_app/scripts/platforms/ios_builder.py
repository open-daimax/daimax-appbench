#!/usr/bin/env python3
"""
iOS platform builder
"""

import os
import platform
import sys
import json

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


class IOSBuilder(BaseBuilder):
    """Builder for iOS projects"""
    
    def __init__(self, project_dir, build_type="debug", output_dir=None,
                 clean=False, output_format="ipa"):
        """
        Initialize iOS builder
        
        Args:
            project_dir: Project root directory
            build_type: Build type (debug or release)
            output_dir: Output directory for build artifacts
            clean: Whether to clean before building
            output_format: Output format (ipa or app)
        """
        super().__init__(project_dir, build_type, output_dir, clean)
        self.output_format = output_format or "ipa"
        
        # Inject environment variables from ~/.dev-env/manifest.json
        self._inject_dev_env_variables()
    
    def _inject_dev_env_variables(self):
        """Inject environment variables from ~/.dev-env/manifest.json"""
        manifest_path = os.path.expanduser("~/.dev-env/manifest.json")
        
        if not os.path.exists(manifest_path):
            return
        
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            dependencies = manifest.get('dependencies', [])
            
            # Process each dependency to set up environment
            for dep in dependencies:
                name = dep.get('name', '')
                path = dep.get('path', '')
                
                if not path:
                    continue
                
                # Set DEVELOPER_DIR for Xcode
                if name == 'xcode' and os.path.exists(path):
                    self.env['DEVELOPER_DIR'] = path
                    print_success(f"Set DEVELOPER_DIR={path}")
                
                # Add Command Line Tools to PATH
                if name == 'xcode-command-line-tools' and os.path.exists(path):
                    usr_bin = os.path.join(path, 'usr', 'bin')
                    if os.path.exists(usr_bin):
                        current_path = self.env.get('PATH', '')
                        if usr_bin not in current_path:
                            self.env['PATH'] = f"{usr_bin}:{current_path}"
                            print_success(f"Added {usr_bin} to PATH")
                
                # Add CocoaPods to PATH
                if name == 'cocoapods':
                    # CocoaPods is typically installed as a gem, path points to pod binary
                    pod_dir = os.path.dirname(path)
                    if os.path.exists(pod_dir):
                        current_path = self.env.get('PATH', '')
                        if pod_dir not in current_path:
                            self.env['PATH'] = f"{pod_dir}:{current_path}"
                            print_success(f"Added {pod_dir} to PATH")
            
            print_success(f"Loaded environment variables from {manifest_path}")
                            
        except Exception as e:
            print_warning(f"Failed to inject environment variables from {manifest_path}: {e}")
    
    def check_environment(self):
        """
        Check if iOS build environment is ready
        
        This method performs basic environment checks without attempting to install
        missing dependencies. For environment setup, users should run the built-in
        env setup tool (tools/env_setup/ios) separately before building.
        
        Returns:
            bool: True if environment is ready, False otherwise
        """
        print_info("Checking iOS build environment...")
        
        # Check if running on macOS
        if platform.system() != "Darwin":
            print_error("iOS development requires macOS")
            return False
        
        # Check Xcode Command Line Tools
        if not self._check_xcode_clt():
            print_error("Xcode Command Line Tools not found or not properly configured")
            print_info("Please setup iOS build environment via the built-in env tool:")
            print_info("  bash tools/env_setup/ios/scripts/doctor.sh ios-build <project_path>")
            return False
        
        # Check Xcode
        if not self._check_xcode():
            print_error("Xcode not found or not properly configured")
            print_info("Please setup iOS build environment via the built-in env tool:")
            print_info("  bash tools/env_setup/ios/scripts/doctor.sh ios-build <project_path>")
            return False
        
        # Check CocoaPods if Podfile exists
        if self._has_podfile():
            if not self._check_cocoapods():
                print_error("CocoaPods not found but Podfile exists")
                print_info("Please setup iOS build environment via the built-in env tool:")
                print_info("  bash tools/env_setup/ios/scripts/doctor.sh ios-build <project_path>")
                return False
        
        print_success("iOS build environment is ready")
        return True
    
    def setup_environment(self):
        """
        Setup iOS build environment
        
        Note: This method is deprecated. Environment setup should be done
        separately using the built-in env setup tool before running build-app.

        Returns:
            bool: Always returns True for backward compatibility
        """
        print_warning("setup_environment() is deprecated")
        print_info("Please run tools/env_setup/ios scripts separately before building")
        return True
    
    def validate_project(self):
        """Validate iOS project directory"""
        if not os.path.exists(self.project_dir):
            print_error(f"Project directory not found: {self.project_dir}")
            return False

        # Check for .xcodeproj or .xcworkspace at root level first
        has_xcodeproj = False
        has_xcworkspace = False

        for item in os.listdir(self.project_dir):
            if item.endswith('.xcodeproj'):
                has_xcodeproj = True
                self.xcodeproj_path = os.path.join(self.project_dir, item)
            elif item.endswith('.xcworkspace'):
                has_xcworkspace = True
                self.xcworkspace_path = os.path.join(self.project_dir, item)

        # If not found at root, look in platform subdirectories (e.g., ios/)
        if not (has_xcodeproj or has_xcworkspace):
            for item in os.listdir(self.project_dir):
                subdir = os.path.join(self.project_dir, item)
                if not os.path.isdir(subdir):
                    continue
                for subitem in os.listdir(subdir):
                    if subitem.endswith('.xcodeproj'):
                        has_xcodeproj = True
                        self.xcodeproj_path = os.path.join(subdir, subitem)
                        self.project_dir = subdir
                        print_info(f"Found iOS project in subdirectory: {subdir}")
                        break
                    elif subitem.endswith('.xcworkspace'):
                        has_xcworkspace = True
                        self.xcworkspace_path = os.path.join(subdir, subitem)
                        self.project_dir = subdir
                        print_info(f"Found iOS project in subdirectory: {subdir}")
                        break
                if has_xcodeproj or has_xcworkspace:
                    break

        if not (has_xcodeproj or has_xcworkspace):
            print_error("Not a valid iOS project (.xcodeproj or .xcworkspace not found)")
            return False

        # Prefer workspace over project if both exist
        if has_xcworkspace:
            print_success(f"Valid iOS workspace: {self.xcworkspace_path}")
        else:
            print_success(f"Valid iOS project: {self.xcodeproj_path}")

        return True
    
    def configure_signing(self, keystore_path, keystore_password,
                         key_alias, key_password):
        """
        Configure signing for iOS release build
        
        Note: iOS signing is more complex than Android and typically requires:
        - Provisioning profile
        - Code signing identity (certificate)
        - Team ID
        
        For now, this method validates basic signing requirements.
        """
        if self.build_type != "release":
            return True
        
        # For iOS, signing is typically configured in Xcode project settings
        # or via command-line parameters to xcodebuild
        print_warning("iOS signing configuration should be set up in Xcode project settings")
        print_info("Ensure your project has valid provisioning profiles and code signing identities")
        
        return True
    
    def build(self, output_format=None):
        """Build iOS project"""
        if output_format:
            self.output_format = output_format
        
        print_info(f"Building {self.build_type.upper()} {self.output_format.upper()}")
        
        # Install CocoaPods dependencies if Podfile exists
        if self._has_podfile():
            print_info("Installing CocoaPods dependencies...")
            if not run_command("pod install", cwd=self.project_dir, env=self.env):
                print_warning("CocoaPods installation failed, continuing anyway...")
        
        # Determine build configuration
        configuration = "Debug" if self.build_type == "debug" else "Release"
        
        # Determine what to build (workspace or project)
        if hasattr(self, 'xcworkspace_path'):
            workspace_flag = f"-workspace {os.path.basename(self.xcworkspace_path)}"
        else:
            workspace_flag = f"-project {os.path.basename(self.xcodeproj_path)}"
        
        # Get scheme name (use first scheme found)
        scheme = self._get_scheme_name()
        if not scheme:
            print_error("Could not determine build scheme")
            return False
        
        # Clean if requested
        if self.clean:
            clean_cmd = f"xcodebuild {workspace_flag} -scheme {scheme} clean"
            print_info(f"Cleaning: {clean_cmd}")
            if not run_command(clean_cmd, cwd=self.project_dir, env=self.env):
                print_warning("Clean failed, continuing anyway...")
        
        # Build command
        build_cmd = (
            f"xcodebuild {workspace_flag} "
            f"-scheme {scheme} "
            f"-configuration {configuration} "
            f"-sdk iphonesimulator "
            f"build"
        )
        
        print_info(f"Running: {build_cmd}")
        print_info(f"Working directory: {self.project_dir}")
        
        if not run_command(build_cmd, cwd=self.project_dir, env=self.env):
            print_error("Build failed")
            return False
        
        # Archive and export based on output format
        if self.output_format == "ipa":
            if not self._create_archive_and_export(workspace_flag, scheme, configuration, export_ipa=True):
                print_error("Failed to create IPA")
                return False
        elif self.output_format == "app":
            if not self._create_archive_and_export(workspace_flag, scheme, configuration, export_ipa=False):
                print_error("Failed to create .app")
                return False
        
        print_success("Build completed successfully")
        return True
    
    def copy_output(self):
        """Copy iOS build output to specified directory"""
        if not self.output_dir:
            return True
        
        # Determine file patterns based on output format
        if self.output_format == "ipa":
            patterns = [".ipa"]
        else:
            patterns = [".app"]
        
        return len(self._copy_files_to_output(patterns, self.output_dir)) > 0
    
    def _check_xcode_clt(self):
        """Check if Xcode Command Line Tools are installed"""
        try:
            output = run_command("xcode-select -p", capture_output=True, env=self.env)
            if output and os.path.exists(output.strip()):
                print_success(f"Xcode Command Line Tools found: {output.strip()}")
                return True
            return False
        except Exception:
            return False
    
    def _check_xcode(self):
        """Check if Xcode is installed"""
        try:
            output = run_command("xcodebuild -version", capture_output=True, env=self.env)
            if output and "Xcode" in output:
                version_line = output.split('\n')[0]
                print_success(f"Xcode found: {version_line}")
                return True
            return False
        except Exception:
            return False
    
    def _check_cocoapods(self):
        """Check if CocoaPods is installed"""
        try:
            output = run_command("pod --version", capture_output=True, env=self.env)
            if output:
                print_success(f"CocoaPods found: {output.strip()}")
                return True
            return False
        except Exception:
            return False
    
    def _has_podfile(self):
        """Check if project has a Podfile"""
        podfile_path = os.path.join(self.project_dir, "Podfile")
        return os.path.exists(podfile_path)
    
    def _get_scheme_name(self):
        """Get the main app scheme name (prioritize app schemes over framework/library schemes)"""
        try:
            if hasattr(self, 'xcworkspace_path'):
                cmd = f"xcodebuild -workspace {os.path.basename(self.xcworkspace_path)} -list"
            else:
                cmd = f"xcodebuild -project {os.path.basename(self.xcodeproj_path)} -list"
            
            output = run_command(cmd, cwd=self.project_dir, capture_output=True, env=self.env)
            
            if output:
                # Parse schemes from output
                lines = output.split('\n')
                in_schemes = False
                schemes = []
                
                for line in lines:
                    line = line.strip()
                    if line == "Schemes:":
                        in_schemes = True
                        continue
                    if in_schemes and line and not line.endswith(':'):
                        schemes.append(line)
                
                if not schemes:
                    return None
                
                # Prioritize schemes that are likely to be main apps
                # 1. Look for schemes that match workspace/project name (highest priority)
                # 2. Schemes that don't have common extension suffixes (Extension, Widget, etc.)
                # 3. Schemes that don't contain "Pods-" prefix
                # 4. Schemes that don't end with Kit, SDK, Framework, etc.
                
                # Get workspace/project base name for matching
                if hasattr(self, 'xcworkspace_path'):
                    base_name = os.path.basename(self.xcworkspace_path).replace('.xcworkspace', '')
                else:
                    base_name = os.path.basename(self.xcodeproj_path).replace('.xcodeproj', '')
                
                # First pass: look for exact match with workspace/project name
                for scheme in schemes:
                    if scheme == base_name:
                        print_info(f"Selected app scheme (exact match): {scheme}")
                        return scheme
                
                # Second pass: filter out obvious non-app schemes
                app_schemes = []
                for scheme in schemes:
                    # Skip CocoaPods schemes
                    if scheme.startswith('Pods-'):
                        continue
                    
                    # Skip extension schemes
                    lower_scheme = scheme.lower()
                    if any(ext in lower_scheme for ext in ['extension', 'widget', 'watchkit', 'watch ', 'notification', 'intents']):
                        continue
                    
                    # Skip common framework/library suffixes
                    if any(lower_scheme.endswith(suffix) for suffix in ['kit', 'sdk', 'framework', 'library', 'core', 'api']):
                        continue
                    
                    app_schemes.append(scheme)
                
                # If we found app schemes, return the first one
                if app_schemes:
                    print_info(f"Selected app scheme: {app_schemes[0]}")
                    return app_schemes[0]
                
                # Otherwise, return the first scheme (fallback)
                print_warning(f"No obvious app scheme found, using first scheme: {schemes[0]}")
                return schemes[0]
            
            return None
        except Exception as e:
            print_warning(f"Failed to get scheme name: {e}")
            return None
    
    def _create_archive_and_export(self, workspace_flag, scheme, configuration, export_ipa=True):
        """
        Archive and export IPA (device) or extract .app (simulator).

        Args:
            workspace_flag: Workspace or project flag for xcodebuild
            scheme: Build scheme name
            configuration: Build configuration (Debug/Release)
            export_ipa: If True, export IPA; if False, extract .app from simulator build

        Returns:
            bool: True if successful, False otherwise
        """
        if not export_ipa:
            return self._extract_simulator_app(configuration)

        # --- IPA export (requires device SDK + signing) ---
        archive_path = os.path.join(self.project_dir, "build", f"{scheme}.xcarchive")

        archive_cmd = (
            f"xcodebuild {workspace_flag} "
            f"-scheme {scheme} "
            f"-configuration {configuration} "
            f"-sdk iphoneos "
            f"-archivePath {archive_path} "
            f"archive"
        )

        print_info("Creating archive...")
        if not run_command(archive_cmd, cwd=self.project_dir, env=self.env):
            return False

        app_path = os.path.join(archive_path, "Products", "Applications")
        if not os.path.exists(app_path) or not os.listdir(app_path):
            print_warning("Archive does not contain an application bundle")
            print_info(f"Archive created at: {archive_path}")
            print_info("This may be a framework or library target, not an app target")
            return True

        # Export IPA
        export_path = os.path.join(self.project_dir, "build", "ipa")

        # Create export options plist
        export_options_path = os.path.join(self.project_dir, "build", "ExportOptions.plist")
        self._create_export_options_plist(export_options_path, scheme)

        # Export IPA
        export_cmd = (
            f"xcodebuild -exportArchive "
            f"-archivePath {archive_path} "
            f"-exportPath {export_path} "
            f"-exportOptionsPlist {export_options_path}"
        )

        print_info("Exporting IPA...")
        if not run_command(export_cmd, cwd=self.project_dir, env=self.env):
            print_warning("IPA export failed, but archive was created successfully")
            print_info(f"You can find the archive at: {archive_path}")
            return True

        # Find the generated IPA
        ipa_files = []
        if os.path.exists(export_path):
            for file in os.listdir(export_path):
                if file.endswith('.ipa'):
                    ipa_files.append(os.path.join(export_path, file))

        if ipa_files:
            print_success(f"IPA created: {ipa_files[0]}")

        return True

    def _extract_simulator_app(self, configuration):
        """Extract .app from simulator build products (no archive needed).

        Robustness fixes (2026-05):
        - When falling back to global DerivedData, restrict the search to
          directories whose name starts with the current project's basename and
          pick the most recently modified candidate, instead of taking the first
          arbitrary ``.app`` we trip over (which previously caused a stale empty
          ``.app`` to be "successfully" copied while the real build had failed).
        - After copying, validate the ``.app`` actually contains an ``Info.plist``
          with a non-empty, non-template ``CFBundleIdentifier``. Otherwise fail
          loudly so install/run phases don't see a phantom "successful" build.
        """
        import shutil

        build_dir = os.path.join(self.project_dir, "build")
        app_dir = os.path.join(build_dir, "app")
        os.makedirs(app_dir, exist_ok=True)

        # Use the Xcode project/workspace basename as the DerivedData prefix.
        # NOTE: Do NOT use os.path.basename(self.project_dir) — generated
        # projects live under "generated_projects/ios", which would produce
        # the misleading prefix "ios" and miss every real DerivedData folder.
        if hasattr(self, 'xcworkspace_path'):
            project_name = os.path.basename(self.xcworkspace_path).replace('.xcworkspace', '')
        elif hasattr(self, 'xcodeproj_path'):
            project_name = os.path.basename(self.xcodeproj_path).replace('.xcodeproj', '')
        else:
            project_name = os.path.basename(os.path.normpath(self.project_dir))

        # Search in DerivedData for the simulator build product
        products_dir = os.path.join(
            build_dir, "Build", "Products", f"{configuration}-iphonesimulator"
        )
        if not os.path.exists(products_dir):
            products_dir = self._find_products_dir_in_derived_data(
                project_name, configuration
            )

        if not products_dir or not os.path.exists(products_dir):
            print_error(
                "Could not locate simulator build products for project "
                f"'{project_name}' (configuration={configuration}). "
                "The xcodebuild step may have failed silently."
            )
            return False

        # Resolve the source .app bundle.
        source_app = None
        if products_dir.endswith('.app'):
            source_app = products_dir
        else:
            for item in os.listdir(products_dir):
                if item.endswith('.app'):
                    source_app = os.path.join(products_dir, item)
                    break

        if not source_app or not os.path.isdir(source_app):
            print_error(f"No .app bundle found in {products_dir}")
            return False

        # Validate the SOURCE bundle before copying.
        ok, reason = self._validate_app_bundle(source_app)
        if not ok:
            print_error(
                f"Source .app failed validation ({reason}): {source_app}. "
                "This usually means xcodebuild did not actually produce a usable "
                "bundle for the current project."
            )
            return False

        dest_app = os.path.join(app_dir, os.path.basename(source_app))
        if os.path.exists(dest_app):
            shutil.rmtree(dest_app)
        shutil.copytree(source_app, dest_app)

        # Validate the COPIED bundle (defense in depth: catches partial copies).
        ok, reason = self._validate_app_bundle(dest_app)
        if not ok:
            print_error(
                f"Copied .app failed validation ({reason}): {dest_app}"
            )
            return False

        print_success(f".app created: {dest_app}")
        return True

    def _find_products_dir_in_derived_data(self, project_name, configuration):
        """Locate ``<configuration>-iphonesimulator`` under DerivedData for this project.

        Filters DerivedData entries by project basename prefix and returns the
        most recently modified match. Returns None if nothing found.
        """
        derived_data = os.path.expanduser("~/Library/Developer/Xcode/DerivedData")
        if not os.path.exists(derived_data):
            return None

        target = f"{configuration}-iphonesimulator"
        candidates = []
        for entry in os.listdir(derived_data):
            # Xcode DerivedData folders look like <ProjectName>-<hash>
            if not entry.startswith(f"{project_name}-"):
                continue
            products_dir = os.path.join(
                derived_data, entry, "Build", "Products", target
            )
            if os.path.isdir(products_dir):
                try:
                    mtime = os.path.getmtime(products_dir)
                except OSError:
                    continue
                candidates.append((mtime, products_dir))

        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    @staticmethod
    def _validate_app_bundle(app_path):
        """Verify a ``.app`` bundle is structurally usable.

        Returns ``(True, '')`` on success, otherwise ``(False, reason)``.
        Checks:
        - ``Info.plist`` exists at the bundle root.
        - ``CFBundleIdentifier`` is present and not the unresolved Xcode
          template placeholder ``$(PRODUCT_BUNDLE_IDENTIFIER)``.
        """
        if not os.path.isdir(app_path):
            return False, "not a directory"
        info_plist = os.path.join(app_path, "Info.plist")
        if not os.path.exists(info_plist):
            return False, "missing Info.plist"

        bundle_id = None
        try:
            import plistlib
            with open(info_plist, "rb") as fp:
                data = plistlib.load(fp)
            bundle_id = data.get("CFBundleIdentifier")
        except Exception:
            # Binary plist read failed; try `defaults read` as a best-effort fallback.
            try:
                rc, stdout, _ = run_command(
                    ["defaults", "read", os.path.splitext(info_plist)[0],
                     "CFBundleIdentifier"],
                )
                if rc == 0:
                    bundle_id = (stdout or "").strip()
            except Exception:
                pass

        if not bundle_id:
            return False, "empty CFBundleIdentifier"
        if "$(" in bundle_id or bundle_id.startswith("$"):
            return False, f"unresolved bundle id template: {bundle_id}"
        return True, ""
    
    def _create_export_options_plist(self, path, scheme):
        """Create ExportOptions.plist for IPA export"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # Try to get Team ID from project settings
        team_id = self._get_team_id()
        
        if not team_id:
            print_warning("Could not detect Team ID from project")
            print_info("Attempting to export without explicit Team ID (using automatic signing)")
            # Use automatic signing without explicit teamID
            export_options = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>development</string>
    <key>uploadBitcode</key>
    <false/>
    <key>uploadSymbols</key>
    <false/>
    <key>compileBitcode</key>
    <false/>
    <key>signingStyle</key>
    <string>automatic</string>
</dict>
</plist>
"""
        else:
            print_success(f"Using Team ID: {team_id}")
            export_options = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>method</key>
    <string>development</string>
    <key>teamID</key>
    <string>{team_id}</string>
    <key>uploadBitcode</key>
    <false/>
    <key>uploadSymbols</key>
    <false/>
    <key>compileBitcode</key>
    <false/>
    <key>signingStyle</key>
    <string>automatic</string>
</dict>
</plist>
"""
        
        with open(path, 'w') as f:
            f.write(export_options)
    
    def _get_team_id(self):
        """Get Team ID from project settings"""
        try:
            # Try to get team ID from xcodebuild
            if hasattr(self, 'xcworkspace_path'):
                cmd = f"xcodebuild -workspace {os.path.basename(self.xcworkspace_path)} -showBuildSettings"
            else:
                cmd = f"xcodebuild -project {os.path.basename(self.xcodeproj_path)} -showBuildSettings"
            
            output = run_command(cmd, cwd=self.project_dir, capture_output=True, env=self.env)
            
            if output:
                # Look for DEVELOPMENT_TEAM in build settings
                for line in output.split('\n'):
                    if 'DEVELOPMENT_TEAM' in line and '=' in line:
                        team_id = line.split('=')[1].strip()
                        if team_id and team_id != '""' and team_id != "''":
                            return team_id
            
            return None
        except Exception as e:
            print_warning(f"Failed to get Team ID: {e}")
            return None
