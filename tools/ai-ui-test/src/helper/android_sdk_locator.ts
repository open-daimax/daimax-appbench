import { existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';
import { execSync } from 'child_process';

/**
 * Android SDK 可能的安装路径
 */
const POSSIBLE_SDK_PATHS = [
  // macOS
  join(homedir(), 'Library', 'Android', 'sdk'),
  '/usr/local/android-sdk',
  '/opt/android-sdk',
  
  // Linux
  join(homedir(), 'Android', 'Sdk'),
  '/usr/lib/android-sdk',
  '/opt/android-sdk-linux',
  
  // Windows
  join(homedir(), 'AppData', 'Local', 'Android', 'Sdk'),
  'C:\\Android\\sdk',
  'C:\\Program Files\\Android\\Android Studio\\sdk',
  'C:\\Program Files (x86)\\Android\\android-sdk',
];

/**
 * 从 Android Studio 配置中查找 SDK 路径
 */
function findSdkFromAndroidStudio(): string | null {
  try {
    const platform = process.platform;
    let configPath: string;

    if (platform === 'darwin') {
      // macOS
      configPath = join(homedir(), 'Library', 'Application Support', 'Google', 'AndroidStudio*', 'options', 'jdk.table.xml');
    } else if (platform === 'linux') {
      // Linux
      configPath = join(homedir(), '.config', 'Google', 'AndroidStudio*', 'options', 'jdk.table.xml');
    } else if (platform === 'win32') {
      // Windows
      configPath = join(homedir(), 'AppData', 'Roaming', 'Google', 'AndroidStudio*', 'options', 'jdk.table.xml');
    } else {
      return null;
    }

    // 尝试读取配置文件（这里简化处理，实际可能需要解析XML）
    // 由于配置文件路径包含通配符，这里只是示例
    return null;
  } catch (error) {
    return null;
  }
}

/**
 * 从 shell 配置文件中查找 ANDROID_HOME
 */
function findSdkFromShellConfig(): string | null {
  try {
    const platform = process.platform;
    if (platform === 'win32') {
      // Windows 使用注册表或环境变量
      return null;
    }

    // Unix-like 系统
    const shellConfigFiles = [
      join(homedir(), '.zshrc'),
      join(homedir(), '.bashrc'),
      join(homedir(), '.bash_profile'),
      join(homedir(), '.profile'),
    ];

    for (const configFile of shellConfigFiles) {
      if (existsSync(configFile)) {
        try {
          const content = require('fs').readFileSync(configFile, 'utf-8');
          
          // 查找 ANDROID_HOME 或 ANDROID_SDK_ROOT 的设置
          const androidHomeMatch = content.match(/export\s+ANDROID_HOME=["']?([^"'\n]+)["']?/);
          if (androidHomeMatch && androidHomeMatch[1]) {
            const path = androidHomeMatch[1].replace(/\$HOME/g, homedir());
            if (existsSync(path)) {
              return path;
            }
          }

          const androidSdkMatch = content.match(/export\s+ANDROID_SDK_ROOT=["']?([^"'\n]+)["']?/);
          if (androidSdkMatch && androidSdkMatch[1]) {
            const path = androidSdkMatch[1].replace(/\$HOME/g, homedir());
            if (existsSync(path)) {
              return path;
            }
          }
        } catch (error) {
          // 忽略读取错误，继续尝试下一个文件
        }
      }
    }
  } catch (error) {
    return null;
  }

  return null;
}

/**
 * 验证 SDK 路径是否有效
 */
function isValidSdkPath(path: string): boolean {
  if (!existsSync(path)) {
    return false;
  }

  // 检查关键目录是否存在
  const platformToolsPath = join(path, 'platform-tools');
  const adbPath = join(platformToolsPath, process.platform === 'win32' ? 'adb.exe' : 'adb');
  
  return existsSync(platformToolsPath) && existsSync(adbPath);
}

/**
 * 自动查找 Android SDK 路径
 */
export function findAndroidSdk(): string | null {
  // 1. 首先检查环境变量
  if (process.env.ANDROID_HOME && isValidSdkPath(process.env.ANDROID_HOME)) {
    return process.env.ANDROID_HOME;
  }

  if (process.env.ANDROID_SDK_ROOT && isValidSdkPath(process.env.ANDROID_SDK_ROOT)) {
    return process.env.ANDROID_SDK_ROOT;
  }

  // 2. 从 shell 配置文件中查找
  const sdkFromShell = findSdkFromShellConfig();
  if (sdkFromShell && isValidSdkPath(sdkFromShell)) {
    return sdkFromShell;
  }

  // 3. 检查常见安装路径
  for (const path of POSSIBLE_SDK_PATHS) {
    if (isValidSdkPath(path)) {
      return path;
    }
  }

  // 4. 尝试从 Android Studio 配置中查找
  const sdkFromStudio = findSdkFromAndroidStudio();
  if (sdkFromStudio && isValidSdkPath(sdkFromStudio)) {
    return sdkFromStudio;
  }

  return null;
}

/**
 * 设置 Android SDK 环境变量
 */
export function setupAndroidSdkEnvironment(): boolean {
  // 如果已经设置了有效的环境变量，直接返回
  if (process.env.ANDROID_HOME && isValidSdkPath(process.env.ANDROID_HOME)) {
    console.debug(`[Android SDK] 使用已有的 ANDROID_HOME: ${process.env.ANDROID_HOME}`);
    return true;
  }

  if (process.env.ANDROID_SDK_ROOT && isValidSdkPath(process.env.ANDROID_SDK_ROOT)) {
    console.debug(`[Android SDK] 使用已有的 ANDROID_SDK_ROOT: ${process.env.ANDROID_SDK_ROOT}`);
    // 同时设置 ANDROID_HOME 以保持兼容性
    process.env.ANDROID_HOME = process.env.ANDROID_SDK_ROOT;
    return true;
  }

  // 自动查找 SDK
  const sdkPath = findAndroidSdk();
  
  if (sdkPath) {
    console.log(`[Android SDK] 自动找到 Android SDK: ${sdkPath}`);
    
    // 设置环境变量
    process.env.ANDROID_HOME = sdkPath;
    process.env.ANDROID_SDK_ROOT = sdkPath;
    
    // 添加 platform-tools 到 PATH
    const platformToolsPath = join(sdkPath, 'platform-tools');
    const toolsPath = join(sdkPath, 'tools');
    
    if (process.env.PATH) {
      // 检查是否已经在 PATH 中
      if (!process.env.PATH.includes(platformToolsPath)) {
        process.env.PATH = `${platformToolsPath}${process.platform === 'win32' ? ';' : ':'}${process.env.PATH}`;
      }
      if (!process.env.PATH.includes(toolsPath)) {
        process.env.PATH = `${toolsPath}${process.platform === 'win32' ? ';' : ':'}${process.env.PATH}`;
      }
    } else {
      process.env.PATH = `${platformToolsPath}${process.platform === 'win32' ? ';' : ':'}${toolsPath}`;
    }
    
    console.log(`[Android SDK] 已设置环境变量:`);
    console.log(`  ANDROID_HOME=${process.env.ANDROID_HOME}`);
    console.log(`  ANDROID_SDK_ROOT=${process.env.ANDROID_SDK_ROOT}`);
    console.log(`  PATH 已更新，包含 platform-tools 和 tools`);
    
    return true;
  }

  console.warn('[Android SDK] 未找到 Android SDK，请手动设置 ANDROID_HOME 环境变量');
  console.warn('[Android SDK] 常见安装路径:');
  console.warn('  macOS: ~/Library/Android/sdk');
  console.warn('  Linux: ~/Android/Sdk');
  console.warn('  Windows: %LOCALAPPDATA%\\Android\\Sdk');
  
  return false;
}

/**
 * 验证 adb 是否可用
 */
export function verifyAdbAvailable(): boolean {
  try {
    execSync('adb version', { stdio: 'pipe' });
    return true;
  } catch (error) {
    return false;
  }
}