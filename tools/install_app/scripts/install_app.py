#!/usr/bin/env python3
"""
Unified app installer for Android and Harmony platforms
"""

import sys
import os
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.env_checker import EnvChecker
from platforms.android_installer import AndroidInstaller
from platforms.harmony_installer import HarmonyInstaller
from platforms.ios_installer import IOSInstaller


# Platform registry
PLATFORMS = {
    'android': AndroidInstaller,
    'expo_android': AndroidInstaller,
    'harmony': HarmonyInstaller,
    'ios': IOSInstaller,
    'expo_ios': IOSInstaller,
}


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='统一应用安装工具 - 支持Android和Harmony平台',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 安装Android应用
  python3 install_app.py --platform android --app-path /path/to/app.apk
  
  # 安装Harmony应用到指定设备
  python3 install_app.py --platform harmony --app-path /path/to/app.hap --device-id FMR0223C13000649
  
  # 安装iOS应用
  python3 install_app.py --platform ios --app-path /path/to/app.ipa
  
  # 自动安装缺失的工具（无需确认）
  python3 install_app.py --platform android --app-path /path/to/app.apk --auto-install
        """
    )
    
    parser.add_argument(
        '--platform',
        required=True,
        choices=['android', 'harmony', 'ios', 'expo_android', 'expo_ios'],
        help='目标平台类型'
    )
    
    parser.add_argument(
        '--app-path',
        required=True,
        help='应用包路径（APK或HAP文件）'
    )
    
    parser.add_argument(
        '--device-id',
        help='指定设备ID（可选，不指定则使用第一个可用设备）'
    )
    
    parser.add_argument(
        '--auto-install',
        action='store_true',
        help='自动安装缺失的工具，无需用户确认'
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("📱 统一应用安装工具")
    print("=" * 60)
    
    # Get installer class
    installer_class = PLATFORMS.get(args.platform)
    if not installer_class:
        print(f"❌ 不支持的平台: {args.platform}")
        sys.exit(1)
    
    # Create installer instance
    installer = installer_class(args.app_path, args.device_id)
    
    print(f"\n🔍 检查 {args.platform.upper()} 环境...")
    
    # Check environment
    env_check = installer.check_environment()
    
    if not env_check['available']:
        missing_tools = env_check['missing_tools']
        print(f"\n⚠️  缺少必需工具: {', '.join(missing_tools)}")
        
        # Try to install missing tools
        results = EnvChecker.check_and_install_tools(missing_tools, args.auto_install)
        
        # Check if all tools are now available
        if not all(results.values()):
            print("\n❌ 环境配置不完整，无法继续安装")
            sys.exit(1)
    else:
        print("✅ 环境检查通过")
    
    # Check devices
    print("\n🔍 检查已连接的设备...")
    devices = installer.get_devices()
    
    if not devices:
        print("❌ 未找到可用设备")
        print("\n请确保:")
        if args.platform in ('android', 'expo_android'):
            print("  【推荐】先启动 Android 模拟器：")
            print("     emulator -list-avds   # 查看可用 AVD")
            print("     emulator -avd <name> -no-snapshot -no-window -no-audio &")
            print("     adb wait-for-device")
            print("  或者使用真机:")
            print("     1. 设备已通过 USB 连接")
            print("     2. 已开启 USB 调试并授权本计算机")
            print("  运行 `adb devices` 确认设备状态为 `device`。")
        elif args.platform == 'harmony':
            print("  1. Harmony设备已通过USB连接")
            print("  2. 设备已开启开发者模式")
            print("  3. 已授权此计算机进行调试")
        else:  # ios / expo_ios
            print("  【推荐】先启动 iOS 模拟器：")
            print("     xcrun simctl list devices booted")
            print("     xcrun simctl boot <UDID>   # 或 open -a Simulator")
            print("  或者使用真机:")
            print("     1. iOS设备已通过USB连接并信任该计算机")
            print("     2. 设备已解锁")
        sys.exit(1)
    
    print(f"✅ 找到 {len(devices)} 个设备:")
    for device in devices:
        print(f"   - {device}")
    
    # Install application
    print("\n📦 开始安装应用...")
    result = installer.install()
    
    if result['success']:
        print(f"\n✅ {result['message']}")
        
        if 'details' in result:
            details = result['details']
            print("\n📋 安装详情:")
            print(f"   - 设备ID: {details.get('device_id', 'N/A')}")
            if 'package_name' in details and details['package_name']:
                print(f"   - 包名: {details['package_name']}")
            elif 'bundle_name' in details and details['bundle_name']:
                print(f"   - Bundle名: {details['bundle_name']}")
            elif 'bundle_id' in details and details['bundle_id']:
                print(f"   - Bundle ID: {details['bundle_id']}")
            print(f"   - 应用路径: {details.get('app_path', 'N/A')}")
        
        print("\n" + "=" * 60)
        print("✅ 安装成功")
        print("=" * 60)
        sys.exit(0)
    else:
        print(f"\n❌ {result['message']}")
        print("\n" + "=" * 60)
        print("❌ 安装失败")
        print("=" * 60)
        sys.exit(1)


if __name__ == '__main__':
    main()
