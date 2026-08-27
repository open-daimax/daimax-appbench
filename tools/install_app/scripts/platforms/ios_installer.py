"""
iOS platform installer implementation
支持模拟器(xcrun simctl)和真机(ios-deploy)安装
"""

import os
import sys
import re
import json
import plistlib
import subprocess
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.base_installer import BaseInstaller
from core.device_manager import DeviceManager


class IOSInstaller(BaseInstaller):
    """
    iOS application installer - supports both Simulator and Physical devices
    """

    def __init__(self, app_path: str, device_id: Optional[str] = None):
        super().__init__(app_path, device_id)
        self.ios_deploy_path = 'ios-deploy'
        self.ideviceinstaller_path = 'ideviceinstaller'

    def check_environment(self) -> Dict[str, Any]:
        """
        检查环境: 模拟器只需要 xcrun, 真机需要 ios-deploy/ideviceinstaller
        """
        # If a device_id was explicitly provided (e.g. from executor.py's
        # get_or_boot_ios_simulator), check whether it belongs to a known
        # simulator.  If so, we ONLY require xcrun and skip physical-device
        # tool checks (ios-deploy / ideviceinstaller).
        if self.device_id:
            try:
                result = subprocess.run(
                    ['xcrun', 'simctl', 'list', 'devices', '-j'],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    is_known_simulator = False
                    for runtime, device_list in data.get('devices', {}).items():
                        for device in device_list:
                            if device.get('udid') == self.device_id:
                                is_known_simulator = True
                                break
                        if is_known_simulator:
                            break

                    if is_known_simulator:
                        xcrun_available = DeviceManager.check_tool_available('xcrun')
                        return {
                            'available': xcrun_available,
                            'missing_tools': [] if xcrun_available else ['xcrun'],
                            'tools_found': {'xcrun': xcrun_available},
                        }
            except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
                print(f"⚠️  检测模拟器失败，回退通用检查 ({type(e).__name__}): {e}")

        # Generic checks (no device_id or unknown device)
        xcrun_available = DeviceManager.check_tool_available('xcrun')

        # 检查真机工具
        ios_deploy_available = DeviceManager.check_tool_available('ios-deploy')
        ideviceinstaller_available = DeviceManager.check_tool_available('ideviceinstaller')

        # 模拟器模式: 只要有 xcrun 就能工作
        available = xcrun_available or ios_deploy_available or ideviceinstaller_available

        missing_tools = []
        if not xcrun_available and not ios_deploy_available and not ideviceinstaller_available:
            missing_tools.append('xcrun')

        return {
            'available': available,
            'missing_tools': missing_tools,
            'tools_found': {
                'xcrun': xcrun_available,
                'ios-deploy': ios_deploy_available,
                'ideviceinstaller': ideviceinstaller_available,
            }
        }

    def get_simulators(self) -> List[Dict[str, str]]:
        """
        获取已启动的 iOS 模拟器列表
        返回 [{'name': str, 'udid': str, 'runtime': str}, ...]
        """
        try:
            result = subprocess.run(
                ['xcrun', 'simctl', 'list', 'devices', 'booted', '-j'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)
            simulators = []
            for runtime, device_list in data.get('devices', {}).items():
                for device in device_list:
                    name = device.get('name', '')
                    if 'iPhone' in name or 'iPad' in name or name:
                        simulators.append({
                            'name': name,
                            'udid': device.get('udid', ''),
                            'runtime': runtime,
                        })
            return simulators
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
            print(f"⚠️  获取已启动模拟器列表失败 ({type(e).__name__}): {e}")
            return []

    def get_devices(self) -> List[str]:
        """
        返回已连接设备ID列表:
        - 优先返回已启动的模拟器 UDID
        - 其次返回物理设备 UDID (通过 ios-deploy / ideviceinstaller)
        """
        # 1) 模拟器优先
        simulators = self.get_simulators()
        if simulators:
            return [s['udid'] for s in simulators]

        # 2) If a device_id was explicitly provided, check if it's a known
        #    simulator (even if not yet booted). This handles the case where
        #    executor.py passes a simulator UDID but the boot process hasn't
        #    fully completed yet.
        if self.device_id:
            try:
                result = subprocess.run(
                    ['xcrun', 'simctl', 'list', 'devices', '-j'],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    for runtime, device_list in data.get('devices', {}).items():
                        for device in device_list:
                            if device.get('udid') == self.device_id:
                                return [self.device_id]
            except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
                print(f"⚠️  检查指定模拟器 UDID 失败 ({type(e).__name__}): {e}")

        # 3) 物理设备
        if DeviceManager.check_tool_available('ios-deploy'):
            success, output, _ = DeviceManager.run_command(
                [self.ios_deploy_path, '--detect', '--timeout', '1']
            )
            if success and output:
                devices = []
                for line in output.split('\n'):
                    if 'Found' in line and 'connected through USB' in line:
                        match = re.search(r'Found ([A-Fa-f0-9-]+) connected', line)
                        if match:
                            devices.append(match.group(1))
                if devices:
                    return devices

        if DeviceManager.check_tool_available('ideviceinstaller'):
            success, output, _ = DeviceManager.run_command(
                ['idevice_id', '-l']
            )
            if success and output:
                devices = [line.strip() for line in output.split('\n') if line.strip()]
                if devices:
                    return devices

        return []

    def _get_device_type(self, device_id: str) -> str:
        """判断设备是模拟器还是物理设备"""
        # Check booted simulators first
        simulators = self.get_simulators()
        for s in simulators:
            if s['udid'] == device_id:
                return 'simulator'

        # Also check ALL simulators (including not-yet-booted) by querying
        # xcrun simctl list devices without the 'booted' filter.
        try:
            result = subprocess.run(
                ['xcrun', 'simctl', 'list', 'devices', '-j'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for runtime, device_list in data.get('devices', {}).items():
                    for device in device_list:
                        if device.get('udid') == device_id:
                            return 'simulator'
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
            print(f"⚠️  查询设备类型失败，默认为物理设备 ({type(e).__name__}): {e}")

        return 'physical'

    def install(self) -> Dict[str, Any]:
        """
        Install iOS IPA or .app bundle (simulator or physical device)
        """
        # Verify file exists
        if not os.path.exists(self.app_path):
            return {
                'success': False,
                'message': f'应用文件不存在: {self.app_path}'
            }

        # Verify file extension (.ipa or .app)
        is_ipa = self.app_path.lower().endswith('.ipa')
        is_app = self.app_path.lower().endswith('.app') or os.path.isdir(self.app_path)

        if not (is_ipa or is_app):
            return {
                'success': False,
                'message': f'不是有效的iOS应用文件 (.ipa 或 .app): {self.app_path}'
            }

        # Get devices
        devices = self.get_devices()
        if not devices:
            return {
                'success': False,
                'message': '未找到已连接的iOS设备或已启动的模拟器'
            }

        # Select device
        target_device = DeviceManager.select_device(devices, self.device_id)
        if not target_device:
            return {
                'success': False,
                'message': '无法选择设备'
            }

        device_type = self._get_device_type(target_device)
        print(f"📱 目标设备: {target_device} ({device_type})")
        print(f"📦 安装应用: {os.path.basename(self.app_path)}")

        # 模拟器安装 (使用 xcrun simctl, 仅需 .app 格式)
        if device_type == 'simulator':
            return self._install_on_simulator(target_device)

        # 物理设备安装
        is_app_bundle = self.app_path.lower().endswith('.app') or os.path.isdir(self.app_path)
        if is_app_bundle:
            if DeviceManager.check_tool_available('ios-deploy'):
                return self._install_app_with_ios_deploy(target_device)
            else:
                return {
                    'success': False,
                    'message': '安装.app文件到真机需要ios-deploy工具: npm install -g ios-deploy'
                }

        if DeviceManager.check_tool_available('ios-deploy'):
            return self._install_with_ios_deploy(target_device)

        if DeviceManager.check_tool_available('ideviceinstaller'):
            return self._install_with_ideviceinstaller(target_device)

        return {
            'success': False,
            'message': '未找到可用的安装工具 (ios-deploy 或 ideviceinstaller)'
        }

    def _install_on_simulator(self, udid: str) -> Dict[str, Any]:
        """
        安装 .app 到模拟器
        流程: xcrun simctl install <udid> <app_path>
        """
        # .app 文件可以直接安装, .ipa 需要先解压
        app_path = self.app_path
        temp_app = None

        if self.app_path.lower().endswith('.ipa'):
            # 解压 IPA 获取 .app (IPA 是 zip, .app 在 Payload/ 下)
            import zipfile
            import tempfile
            try:
                temp_dir = tempfile.mkdtemp()
                with zipfile.ZipFile(self.app_path, 'r') as zf:
                    zf.extractall(temp_dir)
                # 找到 Payload 下的 .app
                payload_dir = os.path.join(temp_dir, 'Payload')
                if os.path.exists(payload_dir):
                    for item in os.listdir(payload_dir):
                        if item.endswith('.app'):
                            app_path = os.path.join(payload_dir, item)
                            break
                if not os.path.isdir(app_path):
                    return {
                        'success': False,
                        'message': '无法从IPA中提取.app文件'
                    }
            except Exception as e:
                return {
                    'success': False,
                    'message': f'解压IPA失败: {e}'
                }

        # Boot the simulator if not already running
        import time
        booted_sims = self.get_simulators()
        if udid not in [s['udid'] for s in booted_sims]:
            print(f"🔌 模拟器未运行，正在启动: {udid}")
            boot_result = subprocess.run(
                ['xcrun', 'simctl', 'boot', udid],
                capture_output=True, text=True, timeout=300,
            )
            if boot_result.returncode != 0:
                # Simulator may already be booting; wait a moment
                time.sleep(15)
            else:
                # Wait for the simulator to finish booting
                time.sleep(15)

        # 安装到模拟器
        install_cmd = ['xcrun', 'simctl', 'install', udid, app_path]
        success, output, error = DeviceManager.run_command(install_cmd, timeout=120)

        # 清理临时文件
        if temp_app and os.path.exists(temp_app):
            import shutil
            shutil.rmtree(temp_app, ignore_errors=True)

        if success or 'complete' in (output + error).lower() or 'installed' in (output + error).lower():
            bundle_id = self._extract_bundle_id()

            # 启动应用验证
            if bundle_id:
                launch_cmd = ['xcrun', 'simctl', 'launch', udid, bundle_id]
                DeviceManager.run_command(launch_cmd, timeout=15)

            return {
                'success': True,
                'message': '应用安装成功 (模拟器)',
                'details': {
                    'device_id': udid,
                    'bundle_id': bundle_id,
                    'app_path': self.app_path,
                    'tool': 'xcrun simctl',
                    'device_type': 'simulator',
                }
            }
        else:
            error_msg = error if error else output
            return {
                'success': False,
                'message': f'模拟器安装失败: {error_msg}'
            }
    
    def _install_app_with_ios_deploy(self, device_id: str) -> Dict[str, Any]:
        """
        Install .app bundle using ios-deploy
        """
        install_cmd = [
            self.ios_deploy_path,
            '--id', device_id,
            '--bundle', self.app_path,
            '--no-wifi'
        ]
        
        success, output, error = DeviceManager.run_command(install_cmd, timeout=180)
        
        if success or 'installed' in output.lower() or 'installed' in error.lower():
            # Extract bundle ID from .app
            bundle_id = self._extract_bundle_id_from_app()
            
            return {
                'success': True,
                'message': '应用安装成功',
                'details': {
                    'device_id': device_id,
                    'bundle_id': bundle_id,
                    'app_path': self.app_path,
                    'tool': 'ios-deploy',
                    'format': 'app'
                }
            }
        else:
            error_msg = error if error else output
            return {
                'success': False,
                'message': f'应用安装失败: {error_msg}'
            }
    
    def _install_with_ios_deploy(self, device_id: str) -> Dict[str, Any]:
        """
        Install IPA using ios-deploy
        """
        install_cmd = [
            self.ios_deploy_path,
            '--id', device_id,
            '--bundle', self.app_path,
            '--no-wifi'
        ]
        
        success, output, error = DeviceManager.run_command(install_cmd, timeout=180)
        
        if success or 'installed' in output.lower() or 'installed' in error.lower():
            # Extract bundle ID
            bundle_id = self._extract_bundle_id()
            
            return {
                'success': True,
                'message': '应用安装成功',
                'details': {
                    'device_id': device_id,
                    'bundle_id': bundle_id,
                    'app_path': self.app_path,
                    'tool': 'ios-deploy',
                    'format': 'ipa'
                }
            }
        else:
            error_msg = error if error else output
            return {
                'success': False,
                'message': f'应用安装失败: {error_msg}'
            }
    
    def _install_with_ideviceinstaller(self, device_id: str) -> Dict[str, Any]:
        """
        Install using ideviceinstaller
        """
        install_cmd = [
            self.ideviceinstaller_path,
            '-u', device_id,
            '-i', self.app_path
        ]
        
        success, output, error = DeviceManager.run_command(install_cmd, timeout=180)
        
        if success or 'Complete' in output or 'installed' in output.lower():
            # Extract bundle ID
            bundle_id = self._extract_bundle_id()
            
            return {
                'success': True,
                'message': '应用安装成功',
                'details': {
                    'device_id': device_id,
                    'bundle_id': bundle_id,
                    'app_path': self.app_path,
                    'tool': 'ideviceinstaller',
                    'format': 'ipa'
                }
            }
        else:
            error_msg = error if error else output
            return {
                'success': False,
                'message': f'应用安装失败: {error_msg}'
            }
    
    def verify_installation(self, bundle_id: str) -> bool:
        """
        Verify if the application is installed
        """
        devices = self.get_devices()
        if not devices:
            return False
        
        target_device = DeviceManager.select_device(devices, self.device_id)
        if not target_device:
            return False
        
        # Try with ideviceinstaller
        if DeviceManager.check_tool_available('ideviceinstaller'):
            cmd = [self.ideviceinstaller_path, '-u', target_device, '-l']
            success, output, _ = DeviceManager.run_command(cmd)
            
            if success and bundle_id in output:
                return True
        
        # Try with ios-deploy
        if DeviceManager.check_tool_available('ios-deploy'):
            cmd = [self.ios_deploy_path, '--id', target_device, '--list_bundle_id']
            success, output, _ = DeviceManager.run_command(cmd)
            
            if success and bundle_id in output:
                return True
        
        return False
    
    def _extract_bundle_id_from_app(self) -> Optional[str]:
        """
        Extract bundle ID from .app bundle
        """
        try:
            # .app is a directory, find Info.plist directly
            info_plist_path = os.path.join(self.app_path, 'Info.plist')
            
            if os.path.exists(info_plist_path):
                with open(info_plist_path, 'rb') as f:
                    plist_data = plistlib.load(f)
                    bundle_id = plist_data.get('CFBundleIdentifier')
                    return bundle_id
        except Exception as e:
            print(f"⚠️  无法从.app提取Bundle ID: {str(e)}")
        
        return None
    
    def _extract_bundle_id(self) -> Optional[str]:
        """
        Extract bundle ID from IPA or .app
        """
        # Check if it's a .app bundle
        if self.app_path.lower().endswith('.app') or os.path.isdir(self.app_path):
            return self._extract_bundle_id_from_app()
        
        # Otherwise, treat as IPA
        try:
            import zipfile
            import tempfile
            
            # IPA is a zip file, extract Info.plist
            with zipfile.ZipFile(self.app_path, 'r') as zip_ref:
                # Find Info.plist in Payload/*.app/
                for file_name in zip_ref.namelist():
                    if file_name.startswith('Payload/') and file_name.endswith('.app/Info.plist'):
                        # Extract to temp location
                        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                            tmp_file.write(zip_ref.read(file_name))
                            tmp_path = tmp_file.name
                        
                        try:
                            # Parse plist
                            with open(tmp_path, 'rb') as f:
                                plist_data = plistlib.load(f)
                                bundle_id = plist_data.get('CFBundleIdentifier')
                                return bundle_id
                        finally:
                            os.unlink(tmp_path)
        except Exception as e:
            print(f"⚠️  无法从IPA提取Bundle ID: {str(e)}")
        
        return None
