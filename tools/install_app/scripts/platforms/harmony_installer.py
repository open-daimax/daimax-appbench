"""
HarmonyOS platform installer implementation
"""

import os
import sys
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.base_installer import BaseInstaller
from core.device_manager import DeviceManager


class HarmonyInstaller(BaseInstaller):
    """
    Harmony application installer
    """
    
    def __init__(self, app_path: str, device_id: Optional[str] = None):
        super().__init__(app_path, device_id)
        self.hdc_path = 'hdc'
    
    def check_environment(self) -> Dict[str, Any]:
        """
        Check if HDC is available
        """
        available = DeviceManager.check_tool_available('hdc')
        
        return {
            'available': available,
            'missing_tools': [] if available else ['hdc']
        }
    
    def get_devices(self) -> List[str]:
        """
        Get list of connected Harmony devices
        """
        success, output, error = DeviceManager.run_command([self.hdc_path, 'list', 'targets'])
        
        if not success:
            print(f"❌ 获取设备列表失败: {error}")
            return []
        
        devices = []
        for line in output.split('\n'):
            line = line.strip()
            if line and not line.startswith('['):
                devices.append(line)
        
        return devices
    
    def install(self) -> Dict[str, Any]:
        """
        Install Harmony HAP
        """
        # Verify file exists
        if not os.path.exists(self.app_path):
            return {
                'success': False,
                'message': f'HAP文件不存在: {self.app_path}'
            }
        
        # Verify file extension
        if not self.app_path.lower().endswith('.hap'):
            return {
                'success': False,
                'message': f'不是有效的HAP文件: {self.app_path}'
            }
        
        # Get devices
        devices = self.get_devices()
        if not devices:
            return {
                'success': False,
                'message': '未找到已连接的Harmony设备'
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
        
        # Install HAP
        install_cmd = [self.hdc_path, '-t', target_device, 'install', '-r', self.app_path]
        success, output, error = DeviceManager.run_command(install_cmd, timeout=120)
        
        if success and ('successfully' in output.lower() or 'install bundle successfully' in output.lower()):
            # Extract bundle name
            bundle_name = self._extract_bundle_name()
            
            return {
                'success': True,
                'message': '应用安装成功',
                'details': {
                    'device_id': target_device,
                    'bundle_name': bundle_name,
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
        
        cmd = [self.hdc_path, '-t', target_device, 'shell', 'bm', 'dump', '-n', package_name]
        success, output, _ = DeviceManager.run_command(cmd)
        
        return success and package_name in output
    
    def _extract_bundle_name(self) -> Optional[str]:
        """
        Extract bundle name from HAP file path
        """
        try:
            # Try to extract from filename
            filename = os.path.basename(self.app_path)
            # Remove .hap extension
            bundle_name = filename.replace('.hap', '')
            return bundle_name
        except (OSError, AttributeError) as e:
            print(f"⚠️  提取 bundle 名称失败 ({type(e).__name__}): {e}")
        
        return None