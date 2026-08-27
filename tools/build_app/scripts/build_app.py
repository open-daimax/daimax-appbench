#!/usr/bin/env python3
"""
Universal App Build Script
Supports Android and HarmonyOS platforms with intelligent platform detection
"""

import os
import sys
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import (
    print_info,
    print_success,
    print_error,
    print_header,
    load_shell_environment,
    PlatformDetector,
    EnvFixer
)
from platforms import AndroidBuilder, HarmonyBuilder, IOSBuilder, ExpoBuilder




def create_builder(platform, project_dir, build_type, output_dir, clean,
                   output_format, device_id=None):
    """
    Create appropriate builder based on platform

    Args:
        platform: Platform name (android, harmony, ios)
        project_dir: Project directory
        build_type: Build type (debug, release)
        output_dir: Output directory
        clean: Whether to clean build
        output_format: Output format
        device_id: Target device ID (for expo_android / expo_ios)

    Returns:
        Builder instance or None
    """
    if platform == PlatformDetector.PLATFORM_ANDROID:
        return AndroidBuilder(
            project_dir=project_dir,
            build_type=build_type,
            output_dir=output_dir,
            clean=clean,
            output_format=output_format or "apk"
        )
    elif platform == "expo_android":
        return ExpoBuilder(
            project_dir=project_dir,
            build_type=build_type,
            output_dir=output_dir,
            clean=clean,
            output_format=output_format or "apk",
            expo_platform="android",
            device_id=device_id,
        )
    elif platform == PlatformDetector.PLATFORM_HARMONY:
        return HarmonyBuilder(
            project_dir=project_dir,
            build_type=build_type,
            output_dir=output_dir,
            clean=clean,
            output_format=output_format or "hap"
        )
    elif platform == PlatformDetector.PLATFORM_IOS:
        return IOSBuilder(
            project_dir=project_dir,
            build_type=build_type,
            output_dir=output_dir,
            clean=clean,
            output_format=output_format or "ipa"
        )
    elif platform == "expo_ios":
        return ExpoBuilder(
            project_dir=project_dir,
            build_type=build_type,
            output_dir=output_dir,
            clean=clean,
            output_format=output_format or "app",
            expo_platform="ios",
            device_id=device_id,
        )
    else:
        print_error(f"Unsupported platform: {platform}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Universal app build tool supporting Android, HarmonyOS, and iOS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect platform and build debug
  python3 build_app.py --project-dir ~/MyApp

  # Build Android APK
  python3 build_app.py --project-dir ~/MyApp --platform android

  # Build HarmonyOS HAP
  python3 build_app.py --project-dir ~/MyApp --platform harmony

  # Build iOS IPA
  python3 build_app.py --project-dir ~/MyApp --platform ios

  # Build release with signing
  python3 build_app.py --project-dir ~/MyApp --build-type release \\
    --keystore-path ~/keys/release.jks \\
    --keystore-password "pass" --key-alias "alias" --key-password "pass"

  # Build Android AAB for Play Store
  python3 build_app.py --project-dir ~/MyApp --platform android \\
    --build-type release --output-format aab \\
    --keystore-path ~/keys/release.jks \\
    --keystore-password "pass" --key-alias "alias" --key-password "pass"
        """
    )
    
    parser.add_argument(
        "--project-dir",
        required=True,
        help="Project root directory"
    )
    
    parser.add_argument(
        "--platform",
        choices=["android", "harmony", "ios", "expo_android", "expo_ios"],
        help="Target platform (auto-detect if not specified)"
    )
    
    parser.add_argument(
        "--output-dir",
        help="Output directory for build artifacts"
    )
    
    parser.add_argument(
        "--build-type",
        choices=["debug", "release"],
        default="debug",
        help="Build type (default: debug)"
    )
    
    parser.add_argument(
        "--output-format",
        help="Output format: apk/aab (Android), hap/app (Harmony), or ipa (iOS)"
    )
    
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build (remove previous artifacts)"
    )
    
    parser.add_argument(
        "--keystore-path",
        help="Path to keystore file (required for release)"
    )
    
    parser.add_argument(
        "--keystore-password",
        help="Keystore password (required for release)"
    )
    
    parser.add_argument(
        "--key-alias",
        help="Key alias (required for release)"
    )
    
    parser.add_argument(
        "--key-password",
        help="Key password (required for release)"
    )
    
    parser.add_argument(
        '--check-env',
        action='store_true',
        help='Check build environment only'
    )
    
    parser.add_argument(
        '--device-id',
        help='Target device ID (e.g. emulator-5554 for Android)'
    )
    
    args = parser.parse_args()
    
    # Expand project directory path
    project_dir = os.path.abspath(os.path.expanduser(args.project_dir))
    
    # Load shell environment
    print_header("Loading Shell Environment")
    load_shell_environment()
    
    # Detect or validate platform
    if args.platform:
        platform = args.platform
        print_info(f"Using specified platform: {platform}")
        
        # Validate that specified platform matches project
        if not PlatformDetector.validate_platform(project_dir, platform):
            print_error(f"Project does not appear to be a {platform} project")
            print_info("Remove --platform flag to auto-detect, or check project directory")
            sys.exit(1)
    else:
        platform = PlatformDetector.detect_platform(project_dir)
        
        if platform == PlatformDetector.PLATFORM_UNKNOWN:
            print_error("Could not detect platform automatically")
            print_info("Please specify platform with --platform flag:")
            print_info("  --platform android    for Android projects")
            print_info("  --platform harmony    for HarmonyOS projects")
            print_info("  --platform ios        for iOS projects")
            sys.exit(1)
    
    # Create builder
    builder = create_builder(
        platform=platform,
        project_dir=project_dir,
        build_type=args.build_type,
        output_dir=args.output_dir,
        clean=args.clean,
        output_format=args.output_format,
        device_id=args.device_id,
    )
    
    if not builder:
        sys.exit(1)
    
    # Check environment only
    if args.check_env:
        print_header("Checking Build Environment")
        if builder.check_environment():
            print_success("Build environment is ready")
            sys.exit(0)
        else:
            print_error("Build environment is not ready")
            print_info("Run without --check-env to setup environment")
            sys.exit(1)
    
    # Fix hardcoded environment paths before building
    env_fixer = EnvFixer(project_dir)
    if not env_fixer.fix_all(platform=platform):
        print_error("Failed to fix hardcoded environment paths")
        sys.exit(1)
    
    # Run build workflow
    success = builder.run_build_workflow(
        keystore_path=args.keystore_path,
        keystore_password=args.keystore_password,
        key_alias=args.key_alias,
        key_password=args.key_password,
        output_format=args.output_format
    )
    
    if success:
        # Find and output APK/AAB/HAP/IPA path
        import json
        if platform in ("android", "expo_android"):
            output_format = args.output_format or "apk"
        elif platform == "harmony":
            output_format = args.output_format or "hap"
        elif platform == "ios":
            output_format = args.output_format or "ipa"
        elif platform == "expo_ios":
            output_format = args.output_format or "app"
        else:
            output_format = args.output_format
        
        # Search for build output
        apk_path = None
        test_apk_path = None
        
        if platform in ("android", "expo_android"):
            # Search for APK/AAB in build outputs
            for root, dirs, files in os.walk(project_dir):
                # Skip certain directories
                dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', '.idea']]
                
                for file in files:
                    if file.endswith(f".{output_format}"):
                        file_path = os.path.join(root, file)
                        # Check if this is a test APK (androidTest in filename or path)
                        is_test_apk = "androidTest" in file or "androidTest" in root
                        
                        # Prefer debug/release builds over unsigned
                        if args.build_type in file.lower() or "unsigned" not in file.lower():
                            if is_test_apk:
                                if not test_apk_path:
                                    test_apk_path = file_path
                            else:
                                if not apk_path:
                                    apk_path = file_path
        
        elif platform == "harmony":
            # Search for HAP/APP
            for root, dirs, files in os.walk(project_dir):
                dirs[:] = [d for d in dirs if d not in ['node_modules', 'oh_modules', '.git', '.idea']]
                
                for file in files:
                    if file.endswith(f".{output_format}"):
                        apk_path = os.path.join(root, file)
                        break
                if apk_path:
                    break
        
        elif platform in ("ios", "expo_ios"):
            # Search for IPA/APP in build outputs
            skip_dirs = ['Pods', 'node_modules'] if platform == "expo_ios" else ['Pods']
            for root, dirs, files in os.walk(project_dir):
                # Skip Pods and DerivedData (we output to build/ directory)
                dirs[:] = [d for d in dirs if d not in skip_dirs]

                # For expo_ios with .app format, search directories
                if output_format == "app":
                    for d in dirs:
                        if d.endswith(f".{output_format}"):
                            apk_path = os.path.join(root, d)
                            break
                else:
                    # For .ipa format, search directories
                    for d in dirs:
                        if d.endswith(f".{output_format}"):
                            apk_path = os.path.join(root, d)
                            break
                if apk_path:
                    break

            # For expo_ios, the .app bundle may be in Xcode DerivedData rather
            # than inside the project tree.  Search DerivedData as a fallback.
            if not apk_path and platform == "expo_ios" and output_format == "app":
                derived_data_base = os.path.expanduser(
                    "~/Library/Developer/Xcode/DerivedData"
                )
                if os.path.exists(derived_data_base):
                    # Look for directories matching the project name
                    project_name = os.path.basename(project_dir)
                    for dd_entry in os.listdir(derived_data_base):
                        if project_name in dd_entry.lower() or "crossplatform" in dd_entry.lower():
                            dd_path = os.path.join(derived_data_base, dd_entry)
                            products_path = os.path.join(
                                dd_path, "Build", "Products", "Debug-iphonesimulator"
                            )
                            if os.path.exists(products_path):
                                for item in os.listdir(products_path):
                                    if item.endswith(".app"):
                                        apk_path = os.path.join(products_path, item)
                                        break
                            if apk_path:
                                break

        # Output JSON result
        result = {
            "success": True,
            "platform": platform,
            "build_type": args.build_type,
            "output_format": output_format,
            "apk_path": apk_path,
            "test_apk_path": test_apk_path,
        }
        if platform in ("ios", "expo_ios"):
            result["app_path"] = apk_path

        print("\n" + json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()