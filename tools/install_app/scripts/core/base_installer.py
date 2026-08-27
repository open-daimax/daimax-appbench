"""
Base installer class for all platforms
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class BaseInstaller(ABC):
    """
    Abstract base class for platform-specific installers
    """
    
    def __init__(self, app_path: str, device_id: Optional[str] = None):
        """
        Initialize installer
        
        Args:
            app_path: Path to the application package
            device_id: Optional device ID to install to
        """
        self.app_path = app_path
        self.device_id = device_id
    
    @abstractmethod
    def check_environment(self) -> Dict[str, Any]:
        """
        Check if required tools are available
        
        Returns:
            Dict with 'available' (bool) and 'missing_tools' (list) keys
        """
        pass
    
    @abstractmethod
    def get_devices(self) -> list:
        """
        Get list of connected devices
        
        Returns:
            List of device IDs
        """
        pass
    
    @abstractmethod
    def install(self) -> Dict[str, Any]:
        """
        Install the application
        
        Returns:
            Dict with 'success' (bool), 'message' (str), and optional 'details' keys
        """
        pass
    
    @abstractmethod
    def verify_installation(self, package_name: str) -> bool:
        """
        Verify if the application is installed
        
        Args:
            package_name: Package name to verify
            
        Returns:
            True if installed, False otherwise
        """
        pass
    
    def get_platform_name(self) -> str:
        """
        Get the platform name
        
        Returns:
            Platform name string
        """
        return self.__class__.__name__.replace('Installer', '').lower()