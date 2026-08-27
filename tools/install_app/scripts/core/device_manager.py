"""
Device management utilities
"""

import os
import sys
import subprocess
from typing import List, Optional

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from env_checker import EnvChecker


class DeviceManager:
    """
    Manages device connections and operations
    """
    
    @staticmethod
    def run_command(command: List[str], timeout: int = 30) -> tuple:
        """
        Run a shell command and return output
        
        Args:
            command: Command to run as list of strings
            timeout: Command timeout in seconds
            
        Returns:
            Tuple of (success: bool, output: str, error: str)
        """
        try:
            # Load shell environment to get PATH and other variables
            env = DeviceManager._load_shell_environment()
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env
            )
            return (
                result.returncode == 0,
                result.stdout.strip(),
                result.stderr.strip()
            )
        except subprocess.TimeoutExpired:
            return False, "", f"Command timed out after {timeout} seconds"
        except Exception as e:
            return False, "", str(e)
    
    @staticmethod
    def _load_shell_environment() -> dict:
        """
        Load environment variables from user's shell
        
        Returns:
            Dictionary of environment variables
        """
        import os
        import subprocess
        
        # Start with current environment
        env = os.environ.copy()
        
        # Try to load from shell config files
        home = os.path.expanduser('~')
        shell_configs = [
            os.path.join(home, '.zshrc'),
            os.path.join(home, '.bashrc'),
            os.path.join(home, '.bash_profile'),
        ]
        
        for config_file in shell_configs:
            if os.path.exists(config_file):
                try:
                    # Source the config file and export environment
                    cmd = f'source "{config_file}" && env'
                    result = subprocess.run(
                        cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        executable='/bin/bash'
                    )
                    
                    if result.returncode == 0:
                        # Parse environment variables
                        for line in result.stdout.split('\n'):
                            if '=' in line:
                                key, _, value = line.partition('=')
                                env[key] = value
                        break
                except Exception:
                    continue
        
        return env
    
    @staticmethod
    def check_tool_available(tool_name: str) -> bool:
        """
        Check if a command-line tool is available
        
        Args:
            tool_name: Name of the tool to check
            
        Returns:
            True if tool is available, False otherwise
        """
        # Use EnvChecker which has improved tool detection
        return EnvChecker.check_tool(tool_name)
    
    @staticmethod
    def select_device(devices: List[str], device_id: Optional[str] = None) -> Optional[str]:
        """
        Select a device from available devices
        
        Args:
            devices: List of available device IDs
            device_id: Optional specific device ID to use
            
        Returns:
            Selected device ID or None if no device available
        """
        if not devices:
            return None
        
        if device_id:
            if device_id in devices:
                return device_id
            else:
                print(f"⚠️  指定的设备 {device_id} 未找到")
                return None
        
        # Use first available device
        return devices[0]