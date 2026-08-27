"""
Environment checker and auto-installer
"""

import os
import subprocess
import platform
from typing import Dict, List, Optional


class EnvChecker:
    """
    Checks environment dependencies and provides installation guidance
    """
    
    # Tool installation commands for different platforms
    INSTALL_COMMANDS = {
        'darwin': {  # macOS
            'adb': 'brew install android-platform-tools',
            'hdc': None,  # HDC needs manual installation
        },
        'linux': {
            'adb': 'sudo apt-get install -y android-tools-adb',
            'hdc': None,
        },
        'windows': {
            'adb': None,  # Needs manual installation on Windows
            'hdc': None,
        }
    }
    
    TOOL_DESCRIPTIONS = {
        'adb': 'Android Debug Bridge - Android设备调试工具',
        'hdc': 'HarmonyOS Device Connector - Harmony设备调试工具',
    }
    
    MANUAL_INSTALL_GUIDES = {
        'adb': {
            'darwin': 'brew install android-platform-tools',
            'linux': 'sudo apt-get install android-tools-adb',
            'windows': '请从 https://developer.android.com/studio/releases/platform-tools 下载并安装',
        },
        'hdc': {
            'darwin': '请从 HarmonyOS SDK 中获取 hdc 工具',
            'linux': '请从 HarmonyOS SDK 中获取 hdc 工具',
            'windows': '请从 HarmonyOS SDK 中获取 hdc 工具',
        }
    }
    
    @staticmethod
    def get_system() -> str:
        """
        Get current operating system
        
        Returns:
            System name: 'darwin', 'linux', or 'windows'
        """
        system = platform.system().lower()
        if system == 'darwin':
            return 'darwin'
        elif system == 'linux':
            return 'linux'
        elif system == 'windows':
            return 'windows'
        return 'unknown'
    
    @staticmethod
    def find_tool_in_common_paths(tool_name: str) -> Optional[str]:
        """
        Find tool in common installation paths
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Full path to tool if found, None otherwise
        """
        common_paths = []
        home = os.path.expanduser('~')
        
        if tool_name == 'adb':
            # Common Android SDK locations
            common_paths = [
                os.path.join(home, 'Library', 'Android', 'sdk', 'platform-tools', 'adb'),  # macOS
                os.path.join(home, 'Android', 'Sdk', 'platform-tools', 'adb'),  # Linux
                os.path.join(home, 'AppData', 'Local', 'Android', 'Sdk', 'platform-tools', 'adb.exe'),  # Windows
                '/usr/local/bin/adb',
                '/usr/bin/adb',
            ]
        elif tool_name == 'hdc':
            # Common HarmonyOS SDK locations
            common_paths = [
                # DevEco Studio SDK locations (macOS)
                '/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc',
                '/Applications/DevEco-Studio.app/Contents/sdk/openharmony/toolchains/hdc',
                # User home SDK locations
                os.path.join(home, 'Library', 'Huawei', 'Sdk', 'openharmony', 'toolchains', 'hdc'),
                os.path.join(home, 'Library', 'Huawei', 'Sdk', 'toolchains', 'hdc'),
                os.path.join(home, 'Huawei', 'Sdk', 'openharmony', 'toolchains', 'hdc'),
                os.path.join(home, 'Huawei', 'Sdk', 'toolchains', 'hdc'),
                # System paths
                '/usr/local/bin/hdc',
                '/usr/bin/hdc',
            ]
        
        for path in common_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
        
        return None
    
    @staticmethod
    def check_tool(tool_name: str) -> bool:
        """
        Check if a tool is available
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            True if available, False otherwise
        """
        # First try using shell to get the tool (this will use user's PATH from shell config)
        try:
            # Get user's default shell
            user_shell = os.environ.get('SHELL', '/bin/bash')
            
            # Load shell configuration and check for tool
            # Use login shell (-l) to ensure profile is loaded
            result = subprocess.run(
                f'{user_shell} -l -c "which {tool_name}"',
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                tool_path = result.stdout.strip()
                # Add the directory to PATH for this process
                tool_dir = os.path.dirname(tool_path)
                current_path = os.environ.get('PATH', '')
                if tool_dir not in current_path:
                    os.environ['PATH'] = f"{tool_dir}:{current_path}"
                return True
        except Exception:
            # Silently continue to fallback methods
            pass
        
        # If not found in PATH, try common installation locations
        tool_path = EnvChecker.find_tool_in_common_paths(tool_name)
        if tool_path:
            # Add the directory to PATH for this process
            tool_dir = os.path.dirname(tool_path)
            os.environ['PATH'] = f"{tool_dir}:{os.environ.get('PATH', '')}"
            return True
        
        return False
    
    @staticmethod
    def get_install_command(tool_name: str) -> Optional[str]:
        """
        Get installation command for a tool
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Installation command or None if not available
        """
        system = EnvChecker.get_system()
        if system in EnvChecker.INSTALL_COMMANDS:
            return EnvChecker.INSTALL_COMMANDS[system].get(tool_name)
        return None
    
    @staticmethod
    def get_manual_guide(tool_name: str) -> str:
        """
        Get manual installation guide for a tool
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Installation guide string
        """
        system = EnvChecker.get_system()
        if tool_name in EnvChecker.MANUAL_INSTALL_GUIDES:
            return EnvChecker.MANUAL_INSTALL_GUIDES[tool_name].get(
                system,
                '请参考官方文档安装'
            )
        return '请参考官方文档安装'
    
    @staticmethod
    def install_tool(tool_name: str, auto_confirm: bool = False) -> bool:
        """
        Install a tool (requires user confirmation unless auto_confirm is True)
        
        Args:
            tool_name: Name of the tool to install
            auto_confirm: If True, skip user confirmation
            
        Returns:
            True if installation successful, False otherwise
        """
        install_cmd = EnvChecker.get_install_command(tool_name)
        
        if not install_cmd:
            print(f"\n❌ 无法自动安装 {tool_name}")
            print(f"📖 手动安装指南: {EnvChecker.get_manual_guide(tool_name)}")
            return False
        
        description = EnvChecker.TOOL_DESCRIPTIONS.get(tool_name, tool_name)
        
        if not auto_confirm:
            print(f"\n⚠️  缺少工具: {description}")
            print(f"📦 安装命令: {install_cmd}")
            response = input("是否自动安装? (y/n): ").strip().lower()
            
            if response != 'y':
                print("❌ 用户取消安装")
                print(f"📖 手动安装指南: {EnvChecker.get_manual_guide(tool_name)}")
                return False
        
        print(f"\n🔧 正在安装 {tool_name}...")
        try:
            result = subprocess.run(
                install_cmd,
                shell=True,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                print(f"✅ {tool_name} 安装成功")
                return True
            else:
                print(f"❌ {tool_name} 安装失败")
                print(f"错误信息: {result.stderr}")
                print(f"📖 手动安装指南: {EnvChecker.get_manual_guide(tool_name)}")
                return False
        except Exception as e:
            print(f"❌ 安装过程出错: {str(e)}")
            print(f"📖 手动安装指南: {EnvChecker.get_manual_guide(tool_name)}")
            return False
    
    @staticmethod
    def check_and_install_tools(tools: List[str], auto_confirm: bool = False) -> Dict[str, bool]:
        """
        Check and optionally install multiple tools
        
        Args:
            tools: List of tool names to check
            auto_confirm: If True, skip user confirmation for installation
            
        Returns:
            Dict mapping tool names to availability status
        """
        results = {}
        
        for tool in tools:
            # Check if tool is available
            is_available = EnvChecker.check_tool(tool)
            
            if is_available:
                results[tool] = True
                print(f"✅ {tool} 已安装")
            else:
                print(f"⚠️  {tool} 未安装")
                if EnvChecker.install_tool(tool, auto_confirm):
                    results[tool] = True
                else:
                    results[tool] = False
        
        return results
