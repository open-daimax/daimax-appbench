"""
Android platform installer implementation
"""

import os
import sys
import re
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.base_installer import BaseInstaller
from core.device_manager import DeviceManager


class AndroidInstaller(BaseInstaller):
    """
    Android application installer
    """
    
    def __init__(self, app_path: str, device_id: Optional[str] = None):
        super().__init__(app_path, device_id)
        self.adb_path = 'adb'
    
    def check_environment(self) -> Dict[str, Any]:
        """
        Check if ADB is available (works for both physical devices and emulators)
        """
        available = DeviceManager.check_tool_available('adb')

        return {
            'available': available,
            'missing_tools': [] if available else ['adb']
        }

    def get_devices(self) -> List[str]:
        """
        Get list of connected Android devices and emulators
        """
        success, output, error = DeviceManager.run_command([self.adb_path, 'devices'])

        if not success:
            print(f"❌ 获取设备列表失败: {error}")
            return []

        devices = []
        for line in output.split('\n')[1:]:  # Skip header line
            if line.strip() and '\tdevice' in line:
                device_id = line.split('\t')[0].strip()
                devices.append(device_id)

        # Check for emulators that show as offline (not yet booted)
        emulators_booting = []
        for line in output.split('\n')[1:]:
            if line.strip() and '\toffline' in line and line.strip().startswith('emulator-'):
                emulators_booting.append(line.split('\t')[0].strip())

        if not devices and emulators_booting:
            print(f"⚠️  模拟器正在启动中: {', '.join(emulators_booting)}")
            print("💡 请稍后再试，等待模拟器完全启动")

        return devices

    def install(self) -> Dict[str, Any]:
        """
        Install Android APK (physical device or emulator)
        """
        # Verify file exists
        if not os.path.exists(self.app_path):
            return {
                'success': False,
                'message': f'APK文件不存在: {self.app_path}'
            }

        # Verify file extension
        if not self.app_path.lower().endswith('.apk'):
            return {
                'success': False,
                'message': f'不是有效的APK文件: {self.app_path}'
            }

        # Get devices (includes both physical devices and emulators)
        devices = self.get_devices()
        if not devices:
            return {
                'success': False,
                'message': '未找到已连接的Android设备或已启动的模拟器'
            }
        
        # Select device
        target_device = DeviceManager.select_device(devices, self.device_id)
        if not target_device:
            return {
                'success': False,
                'message': '无法选择设备'
            }
        
        print(f"📱 目标设备: {target_device}")
        print(f"📦 安装应用: {os.path.basename(self.app_path)}")
        
        # Install APK
        install_cmd = [self.adb_path, '-s', target_device, 'install', '-r', self.app_path]
        success, output, error = DeviceManager.run_command(install_cmd, timeout=120)
        
        if success and 'Success' in output:
            # Extract package name
            package_name = self._extract_package_name()
            
            return {
                'success': True,
                'message': '应用安装成功',
                'details': {
                    'device_id': target_device,
                    'package_name': package_name,
                    'app_path': self.app_path
                }
            }
        else:
            error_msg = error if error else output
            return {
                'success': False,
                'message': f'应用安装失败: {error_msg}'
            }
    
    def verify_installation(self, package_name: str) -> bool:
        """
        Verify if the application is installed
        """
        devices = self.get_devices()
        if not devices:
            return False
        
        target_device = DeviceManager.select_device(devices, self.device_id)
        if not target_device:
            return False
        
        cmd = [self.adb_path, '-s', target_device, 'shell', 'pm', 'list', 'packages', package_name]
        success, output, _ = DeviceManager.run_command(cmd)
        
        return success and package_name in output
    
    def _extract_package_name(self) -> Optional[str]:
        """
        Extract package name from APK using aapt
        """
        try:
            # Try using aapt
            cmd = ['aapt', 'dump', 'badging', self.app_path]
            success, output, _ = DeviceManager.run_command(cmd)
            
            if success:
                match = re.search(r"package: name='([^']+)'", output)
                if match:
                    return match.group(1)
        except (OSError, FileNotFoundError, AttributeError) as e:
            print(f"⚠️  提取 package 名称失败 ({type(e).__name__}): {e}")
        
        return None