#!/usr/bin/env python3
"""
Base builder class for all platform builders
"""

import os
import shutil
from abc import ABC, abstractmethod
from .utils import print_info, print_success, print_warning, print_error, print_header


class BaseBuilder(ABC):
    """Abstract base class for platform-specific builders"""
    
    def __init__(self, project_dir, build_type="debug", output_dir=None, 
                 clean=False):
        """
        Initialize builder
        
        Args:
            project_dir: Project root directory
            build_type: Build type (debug or release)
            output_dir: Output directory for build artifacts
            clean: Whether to clean before building
        """
        self.project_dir = os.path.abspath(os.path.expanduser(project_dir))
        self.build_type = build_type
        self.output_dir = output_dir
        self.clean = clean
        self.env = os.environ.copy()
    
    @abstractmethod
    def check_environment(self):
        """
        Check if build environment is properly configured
        
        Returns:
            bool: True if environment is ready, False otherwise
        """
        pass
    
    @abstractmethod
    def setup_environment(self):
        """
        Setup build environment (install missing tools if needed)
        
        Returns:
            bool: True if setup successful, False otherwise
        """
        pass
    
    @abstractmethod
    def validate_project(self):
        """
        Validate that project directory is valid for this platform
        
        Returns:
            bool: True if project is valid, False otherwise
        """
        pass
    
    @abstractmethod
    def configure_signing(self, keystore_path, keystore_password, 
                         key_alias, key_password):
        """
        Configure signing for release builds
        
        Args:
            keystore_path: Path to keystore file
            keystore_password: Keystore password
            key_alias: Key alias
            key_password: Key password
            
        Returns:
            bool: True if signing configured successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def build(self, output_format=None):
        """
        Execute the build process
        
        Args:
            output_format: Output format (platform-specific)
            
        Returns:
            bool: True if build successful, False otherwise
        """
        pass
    
    @abstractmethod
    def copy_output(self):
        """
        Copy build output to specified directory
        
        Returns:
            bool: True if copy successful, False otherwise
        """
        pass
    
    def get_platform_name(self):
        """
        Get platform name
        
        Returns:
            str: Platform name
        """
        return self.__class__.__name__.replace('Builder', '')
    
    def run_build_workflow(self, keystore_path=None, keystore_password=None,
                          key_alias=None, key_password=None, output_format=None):
        """
        Run complete build workflow
        
        IMPORTANT: This workflow assumes the build environment has been set up
        separately using the built-in env setup tool (tools/env_setup).
        The check_environment() method
        only verifies that required tools are available, it does NOT install them.
        
        Recommended workflow:
        1. Run the env setup scripts first to setup environment (if needed)
        2. Run build-app to build the project
        
        Build workflow steps:
        - Validate project structure
        - Check environment (verify tools are available)
        - Configure signing (for release builds)
        - Execute build
        - Copy output files
        
        Args:
            keystore_path: Path to keystore file (for release builds)
            keystore_password: Keystore password (for release builds)
            key_alias: Key alias (for release builds)
            key_password: Key password (for release builds)
            output_format: Output format (platform-specific)
            
        Returns:
            bool: True if workflow completed successfully, False otherwise
        """
        print_header(f"Building {self.get_platform_name()} Project")
        
        # Validate project
        if not self.validate_project():
            return False
        
        # Check environment
        # Note: check_environment() only verifies that required tools are available.
        # It does NOT install missing dependencies. Users should run the built-in
        # env setup tool (tools/env_setup) separately before building if needed.
        print_header("Checking Build Environment")
        if not self.check_environment():
            print_error("Build environment check failed")
            print_info("Please setup the build environment via tools/env_setup scripts")
            return False
        
        # Configure signing for release builds
        if self.build_type == "release":
            if not self.configure_signing(keystore_path, keystore_password,
                                         key_alias, key_password):
                return False
        
        # Build project
        if not self.build(output_format):
            return False
        
        # Copy output
        if self.output_dir:
            if not self.copy_output():
                print_warning("Failed to copy output, but build was successful")
        
        print_header("Build Completed Successfully")
        return True
    
    def _copy_files_to_output(self, source_patterns, output_dir):
        """
        Helper method to copy files matching patterns to output directory
        
        Args:
            source_patterns: List of file patterns to search for
            output_dir: Destination directory
            
        Returns:
            list: List of copied file paths
        """
        print_info(f"Copying build output to: {output_dir}")
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        copied_files = []
        
        # Search for files
        for root, dirs, files in os.walk(self.project_dir):
            # Skip certain directories
            dirs[:] = [d for d in dirs if d not in ['node_modules', 'oh_modules', '.git', '.idea']]
            
            for file in files:
                # Check if file matches any pattern
                if any(file.endswith(pattern) for pattern in source_patterns):
                    source_file = os.path.join(root, file)
                    dest_file = os.path.join(output_dir, file)
                    
                    try:
                        shutil.copy2(source_file, dest_file)
                        copied_files.append(dest_file)
                        print_success(f"Copied: {file}")
                    except Exception as e:
                        print_warning(f"Failed to copy {file}: {e}")
        
        if copied_files:
            print_success(f"Build output copied to: {output_dir}")
            print_info(f"Total files copied: {len(copied_files)}")
            for file in copied_files:
                file_size = os.path.getsize(file)
                size_mb = file_size / (1024 * 1024)
                print_info(f"  - {os.path.basename(file)} ({size_mb:.1f} MB)")
        else:
            print_warning("No output files found to copy")
        
        return copied_files