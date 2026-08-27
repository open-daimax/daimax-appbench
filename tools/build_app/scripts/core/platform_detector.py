#!/usr/bin/env python3
"""
Platform detection logic for build system
"""

import os
import json
from .utils import print_info, print_success, print_warning


class PlatformDetector:
    """Detect project platform based on file structure"""
    
    PLATFORM_ANDROID = "android"
    PLATFORM_HARMONY = "harmony"
    PLATFORM_IOS = "ios"
    PLATFORM_WEB = "web"
    PLATFORM_UNKNOWN = "unknown"
    
    @staticmethod
    def detect_platform(project_dir):
        """
        Detect platform based on project structure
        
        Returns:
            str: Platform name (android, harmony, ios, or unknown)
        """
        print_info("Detecting project platform...")
        
        # Check for HarmonyOS first (more specific)
        if PlatformDetector._is_harmony_project(project_dir):
            print_success("Detected platform: HarmonyOS")
            return PlatformDetector.PLATFORM_HARMONY
        
        # Check for iOS
        if PlatformDetector._is_ios_project(project_dir):
            print_success("Detected platform: iOS")
            return PlatformDetector.PLATFORM_IOS
        
        # Check for Android
        if PlatformDetector._is_android_project(project_dir):
            print_success("Detected platform: Android")
            return PlatformDetector.PLATFORM_ANDROID
        
        # Check for Web
        if PlatformDetector._is_web_project(project_dir):
            print_success("Detected platform: Web")
            return PlatformDetector.PLATFORM_WEB
        
        print_warning("Could not detect platform automatically")
        return PlatformDetector.PLATFORM_UNKNOWN
    
    @staticmethod
    def _is_web_project(project_dir):
        """Check if project is a Web project"""
        package_json = os.path.join(project_dir, "package.json")
        return os.path.exists(package_json)
    
    @staticmethod
    def _is_android_project(project_dir):
        """Check if project is an Android project"""
        # Check for build.gradle or build.gradle.kts
        build_gradle = os.path.join(project_dir, "build.gradle")
        build_gradle_kts = os.path.join(project_dir, "build.gradle.kts")
        
        if os.path.exists(build_gradle) or os.path.exists(build_gradle_kts):
            return True
        
        # Check .gitignore for Android-specific patterns
        gitignore = os.path.join(project_dir, ".gitignore")
        if os.path.exists(gitignore):
            try:
                with open(gitignore, 'r') as f:
                    content = f.read()
                    android_patterns = ['*.apk', '*.ap_', '*.dex', '*.class']
                    if any(pattern in content for pattern in android_patterns):
                        return True
            except (OSError, UnicodeDecodeError) as e:
                print(f"⚠️  读取 .gitignore 失败 ({type(e).__name__}): {e}")
        
        return False
    
    @staticmethod
    def _is_harmony_project(project_dir):
        """Check if project is a HarmonyOS project"""
        # Check for hvigorfile.ts (primary indicator)
        hvigorfile = os.path.join(project_dir, "hvigorfile.ts")
        if os.path.exists(hvigorfile):
            return True
        
        # Check for build-profile.json5 (secondary indicator)
        build_profile = os.path.join(project_dir, "build-profile.json5")
        if os.path.exists(build_profile):
            return True
        
        return False
    
    @staticmethod
    def _is_ios_project(project_dir):
        """Check if project is an iOS project"""
        # Check for .xcodeproj or .xcworkspace at root level
        try:
            for item in os.listdir(project_dir):
                if item.endswith('.xcodeproj') or item.endswith('.xcworkspace'):
                    return True
            # Also check platform subdirectories (e.g., ios/)
            for item in os.listdir(project_dir):
                subdir = os.path.join(project_dir, item)
                if not os.path.isdir(subdir):
                    continue
                for subitem in os.listdir(subdir):
                    if subitem.endswith('.xcodeproj') or subitem.endswith('.xcworkspace'):
                        return True
        except (OSError, PermissionError) as e:
            print(f"⚠️  扫描 iOS 项目子目录失败 ({type(e).__name__}): {e}")

        return False

    @staticmethod
    def _is_expo_project(project_dir):
        """Check if project is an Expo/React Native project."""
        package_json = os.path.join(project_dir, "package.json")
        if not os.path.exists(package_json):
            return False
        try:
            with open(package_json, 'r') as f:
                data = json.load(f)
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            return "expo" in deps or "expo-router" in deps
        except (json.JSONDecodeError, OSError):
            return False

    @staticmethod
    def detect_platform_ext(project_dir):
        """
        Detect platform extension based on project dependencies
        
        Returns:
            str or None: Platform extension (e.g., "app_h5") or None if not detected
        """
        package_json_path = os.path.join(project_dir, "package.json")
        
        try:
            if not os.path.exists(package_json_path):
                return None
            
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
            
            # Check all dependency types
            all_deps = {}
            for dep_key in ['dependencies', 'devDependencies', 'peerDependencies']:
                if dep_key in package_data:
                    all_deps.update(package_data[dep_key])
            
            # Check for @ali/amap-lib -> app_h5
            if '@ali/amap-lib' in all_deps:
                return "app_h5"
            
            # TODO: Future extensions can be added here
            # e.g., check for ajx-related dependencies -> return "ajx"
            
            return None
        except (json.JSONDecodeError, IOError, OSError):
            return None
    
    @staticmethod
    def detect_full(project_dir):
        """
        Detect full platform information including platform and platform_ext
        
        Args:
            project_dir: Project directory path
            
        Returns:
            dict: Platform information with keys "platform" and "platform_ext"
        """
        platform = PlatformDetector.detect_platform(project_dir)
        platform_ext = PlatformDetector.detect_platform_ext(project_dir)
        
        result = {
            "platform": platform,
            "platform_ext": platform_ext
        }
        
        print_info(f"Full platform detection result: platform={platform}, platform_ext={platform_ext}")
        
        return result
    
    @staticmethod
    def validate_platform(project_dir, platform):
        """
        Validate that the specified platform matches the project
        
        Args:
            project_dir: Project directory path
            platform: Platform name to validate
            
        Returns:
            bool: True if platform is valid for the project
        """
        if platform == PlatformDetector.PLATFORM_ANDROID:
            return PlatformDetector._is_android_project(project_dir)
        elif platform == PlatformDetector.PLATFORM_HARMONY:
            return PlatformDetector._is_harmony_project(project_dir)
        elif platform == PlatformDetector.PLATFORM_IOS:
            return PlatformDetector._is_ios_project(project_dir)
        elif platform == PlatformDetector.PLATFORM_WEB:
            return PlatformDetector._is_web_project(project_dir)
        elif platform in ("expo_android", "expo_ios"):
            return PlatformDetector._is_expo_project(project_dir)
        else:
            return False
