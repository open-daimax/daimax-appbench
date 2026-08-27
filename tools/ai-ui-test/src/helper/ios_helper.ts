import { execSync, spawn, ChildProcess } from 'child_process';
import { existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { logger } from './logger.js';
import { ReturnAsResultError } from '../types.js';

// 获取项目根目录
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..', '..');

/**
 * WDA 启动超时错误
 */
export class WDATimeoutError extends ReturnAsResultError {
  constructor(message: string) {
    super(message);
    this.name = 'WDATimeoutError';
  }
}

/**
 * iOS 开发者模式未开启错误
 */
export class DeveloperModeDisabledError extends ReturnAsResultError {
  constructor(message: string) {
    super(message);
    this.name = 'DeveloperModeDisabledError';
  }
}

/**
 * iOS 应用未信任错误
 */
export class AppNotTrustedError extends ReturnAsResultError {
  constructor(message: string) {
    super(message);
    this.name = 'AppNotTrustedError';
  }
}

/**
 * iOS 设备未配对错误
 */
export class DeviceNotPairedError extends ReturnAsResultError {
  constructor(message: string) {
    super(message);
    this.name = 'DeviceNotPairedError';
  }
}

/**
 * 真机 WDA 不再支持错误
 * 继承 ReturnAsResultError 以穿透上层 catch，向用户明确提示真机已退役
 */
export class PhysicalWDAUnsupportedError extends ReturnAsResultError {
  constructor(message: string = '真机 WDA 已不再支持，请使用 iOS 模拟器运行测试') {
    super(message);
    this.name = 'PhysicalWDAUnsupportedError';
  }
}

/**
 * iOS 设备信息接口
 */
export interface IOSDeviceInfo {
  id: string;        // xcrun devicectl 返回的设备 ID
  name: string;
  type: 'physical' | 'simulator';
  udid?: string;     // idevice_id 返回的 UDID（用于 iproxy，仅物理设备）
}

/**
 * WDA 配置（仅模拟器；真机 WDA 已移除）
 */
const WDA_CONFIG = {
  // 模拟器 WDA 内置 zip（vendor 目录，不再走网络下载）
  simulatorZipPath: join(PROJECT_ROOT, 'vendor', 'WDA_simulator.zip'),
  // 解压目录（首次使用时从 vendor/ 解压到 cache/）
  simulatorExtractDir: join(PROJECT_ROOT, 'cache', 'ios', 'WDA_simulator'),
  // 新的目录结构：解压后包含 Debug-iphonesimulator 目录
  simulatorAppPath: join(PROJECT_ROOT, 'cache', 'ios', 'WDA_simulator', 'Debug-iphonesimulator', 'WebDriverAgentRunner-Runner.app'),
  simulatorXctestrunPath: join(PROJECT_ROOT, 'cache', 'ios', 'WDA_simulator', 'WebDriverAgentRunner_iphonesimulator26.2-arm64-x86_64.xctestrun'),
  // 模拟器 WDA Bundle ID（用于 simctl listapps 检查安装状态）
  simulatorBundleId: 'com.seven.WebDriverAgentRunner.xctrunner',
};

/**
 * iOS 设备管理辅助类
 */
export class IOSHelper {
  private static portForwardProcess: ChildProcess | null = null;

  /**
   * 检查 WDA 是否已下载
   * @param device 设备信息
   * @returns 是否已下载
   */
  static isWDADownloaded(device: IOSDeviceInfo): boolean {
    if (device.type === 'physical') {
      throw new PhysicalWDAUnsupportedError();
    }
    // 模拟器：检查解压后的 .app 和 .xctestrun 文件（源为内置 vendor/ zip）
    return existsSync(WDA_CONFIG.simulatorAppPath) && existsSync(WDA_CONFIG.simulatorXctestrunPath);
  }

  /**
   * 从内置 vendor 目录解压模拟器 WDA（不再走网络下载）
   * @returns 是否解压成功
   */
  private static async extractSimulatorWDA(): Promise<boolean> {
    // 检查内置 vendor zip 是否存在
    if (!existsSync(WDA_CONFIG.simulatorZipPath)) {
      logger.error(`模拟器 WDA zip 不存在: ${WDA_CONFIG.simulatorZipPath}`);
      logger.error('请确认 vendor/WDA_simulator.zip 已正确内置');
      return false;
    }

    try {
      logger.info('开始解压模拟器 WDA（从内置 vendor 目录）...');

      // 解压 zip 文件到 WDA_simulator 目录
      if (!existsSync(WDA_CONFIG.simulatorExtractDir)) {
        mkdirSync(WDA_CONFIG.simulatorExtractDir, { recursive: true });
      }

      execSync(`unzip -o "${WDA_CONFIG.simulatorZipPath}" -d "${WDA_CONFIG.simulatorExtractDir}"`, {
        encoding: 'utf-8',
        stdio: 'pipe'
      });

      logger.info('模拟器 WDA 解压完成');
      return true;
    } catch (error) {
      logger.error('解压模拟器 WDA 失败', error);
      return false;
    }
  }

  /**
   * 检查 WDA 是否已安装到设备
   * @param device 设备信息
   * @returns 是否已安装
   */
  static isWDAInstalled(device: IOSDeviceInfo): boolean {
    if (device.type === 'physical') {
      throw new PhysicalWDAUnsupportedError();
    }
    try {
      // 模拟器使用 simctl 检查
      const output = execSync(
        `xcrun simctl listapps ${device.id} | grep -i "${WDA_CONFIG.simulatorBundleId}"`,
        { encoding: 'utf-8', stdio: 'pipe' }
      );
      return output.trim().length > 0;
    } catch (error) {
      // grep 未找到匹配时会返回非零退出码
      logger.debug(`检查 WDA 安装状态失败: ${error}`);
      return false;
    }
  }

  /**
   * 安装 WDA.ipa 到设备
   * @param device 设备信息
   * @returns 是否安装成功
   */
  static async installWDA(device: IOSDeviceInfo): Promise<boolean> {
    try {
      // 1. 先检查是否已安装
      if (this.isWDAInstalled(device)) {
        logger.info('WDA 已安装');
        return true;
      }

      // 2. 检查 WDA 是否已解压（未解压则从内置 vendor 目录解压）
      if (!this.isWDADownloaded(device)) {
        logger.info('WDA 未解压，开始从内置 vendor 目录解压...');
        const extractSuccess = await this.extractSimulatorWDA();
        if (!extractSuccess) {
          logger.error('WDA 解压失败，无法继续安装');
          return false;
        }
      } else {
        logger.info('WDA 已存在');
      }

      // 3. 安装 WDA（模拟器使用 simctl 安装 .app）
      logger.info(`正在安装 WDA 到设备 ${device.name}...`);
      execSync(
        `xcrun simctl install ${device.id} "${WDA_CONFIG.simulatorAppPath}"`,
        { encoding: 'utf-8', stdio: 'pipe' }
      );

      logger.info('WDA 安装成功');
      return true;
    } catch (error: unknown) {
      // 获取完整的错误信息（包括 stderr）
      const err = error as { stderr?: string; message?: string };
      const errorMessage = err.stderr || err.message || String(error);
      
      // 检查是否是设备未配对的错误
      if (errorMessage.includes('device must be paired') || 
          errorMessage.includes('RemotePairingError') ||
          errorMessage.includes('CoreDeviceError error 2')) {
        const detailedMessage = [
          '安装 WDA.ipa 失败: 设备未配对',
          '解决方法：',
          '  1. 尝试拔掉 USB 线',
          '  2. 重新连接到 Mac',
          '  3. 在弹出的信任弹窗中点击"信任"',
          '  4. 重新运行测试'
        ].join('\n');
        
        throw new DeviceNotPairedError(detailedMessage);
      }
      
      // 检查是否是开发者模式未开启的错误
      if (errorMessage.includes('Developer Mode is disabled') || errorMessage.includes('10005')) {
        const detailedMessage = [
          '安装 WDA.ipa 失败: 设备未开启开发者模式',
          '解决方法：',
          '  1. 打开设备的"设置"应用',
          '  2. 进入"隐私与安全性" → "开发者模式"',
          '  3. 开启"开发者模式"开关',
          '  4. 重启设备后重新运行',
          '',
          '注意：iOS 16 及以上版本需要开启开发者模式才能安装和运行测试应用'
        ].join('\n');
        
        throw new DeveloperModeDisabledError(detailedMessage);
      }
      
      logger.error('安装 WDA.ipa 失败', error);
      throw error;
    }
  }

  /**
   * 确保 WDA 已准备就绪（下载并安装）
   * @param device 设备信息
   * @returns 是否准备就绪
   */
  static async ensureWDAReady(device: IOSDeviceInfo): Promise<boolean> {
    // 直接调用 installWDA，让异常自然传播
    // ReturnAsResultError 会自动向上传播
    const installSuccess = await this.installWDA(device);
    if (!installSuccess) {
      logger.error('WDA 准备失败');
      return false;
    }
    return true;
  }

  /**
   * 获取 iproxy 使用的 UDID 列表
   * @returns UDID 数组
   */
  private static getIproxyUDIDs(): string[] {
    try {
      const output = execSync('idevice_id -l', {
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'pipe']
      });
      
      return output.trim().split('\n').filter(line => line.trim());
    } catch (error) {
      logger.debug(`获取 iproxy UDID 失败: ${error}`);
      return [];
    }
  }

  /**
   * 获取可用的物理设备列表
   * @returns 设备信息数组
   */
  private static getPhysicalDevices(): IOSDeviceInfo[] {
    try {
      const output = execSync('xcrun devicectl list devices', {
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'pipe']
      });

      const devices: IOSDeviceInfo[] = [];
      const lines = output.split('\n');
      
      // 获取 iproxy 使用的 UDID 列表（只有已连接的设备才会出现在这里）
      const iproxyUDIDs = this.getIproxyUDIDs();
      
      for (const line of lines) {
        // 跳过表头和分隔线
        if (line.includes('Identifier') || line.includes('---') || !line.trim()) {
          continue;
        }
        
        // 检查设备状态，只处理 available 或 connected 状态的设备
        // 跳过 unavailable 状态的设备（已断开连接）
        if (line.includes('unavailable') || line.includes('disconnected')) {
          logger.debug(`跳过未连接的设备: ${line.trim()}`);
          continue;
        }

        // 匹配 UUID 格式的设备 ID
        const match = line.match(/([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})/i);
        if (match && match[1]) {
          // 提取设备名称（第一列）
          const nameMatch = line.match(/^([^\s]+(?:\s+[^\s]+)*?)\s{2,}/);
          const name = nameMatch ? nameMatch[1].trim() : 'Unknown Device';
          
          const deviceId = match[1];
          
          // 为每个设备分配对应的 iproxy UDID
          // 假设设备顺序一致（这是一个简化假设，实际可能需要更复杂的匹配逻辑）
          const udid = iproxyUDIDs.length > devices.length ? iproxyUDIDs[devices.length] : undefined;
          
          devices.push({
            id: deviceId,
            name,
            type: 'physical',
            udid
          });
        }
      }

      return devices;
    } catch (error) {
      logger.debug(`获取物理设备失败: ${error}`);
      return [];
    }
  }

  /**
   * 获取可用的模拟器列表
   * @returns 设备信息数组
   */
  private static getSimulators(): IOSDeviceInfo[] {
    try {
      const output = execSync('xcrun simctl list devices available --json', {
        encoding: 'utf-8',
        stdio: ['pipe', 'pipe', 'pipe']
      });

      const data = JSON.parse(output);
      const devices: IOSDeviceInfo[] = [];

      // 遍历所有运行时版本
      for (const runtime in data.devices) {
        const runtimeDevices = data.devices[runtime];
        for (const device of runtimeDevices) {
          // 只添加已启动的模拟器
          if (device.state === 'Booted') {
            devices.push({
              id: device.udid,
              name: device.name,
              type: 'simulator'
            });
          }
        }
      }

      return devices;
    } catch (error) {
      logger.debug(`获取模拟器失败: ${error}`);
      return [];
    }
  }

  /**
   * 获取所有可用的 iOS 设备（自动检测真机和模拟器）
   * @returns 设备信息数组
   */
  static getAllDevices(): IOSDeviceInfo[] {
    // 优先获取物理设备
    const physicalDevices = this.getPhysicalDevices();
    const simulators = this.getSimulators();
    
    const allDevices = [...physicalDevices, ...simulators];
    
    if (allDevices.length === 0) {
      logger.warn('未找到可用的 iOS 设备');
    } else {
      logger.info(`找到 ${allDevices.length} 个 iOS 设备: ${allDevices.map(d => d.name).join(', ')}`);
    }

    return allDevices;
  }

  /**
   * 获取可用的 iOS 设备 ID 列表（兼容旧接口）
   * @returns 设备 ID 数组
   */
  static getAvailableDevices(): string[] {
    const devices = this.getAllDevices();
    return devices.map(d => d.id);
  }

  /**
   * 获取第一个可用的设备
   * @param preferSimulator 是否优先选择模拟器（expo_ios 场景下应用安装到模拟器，应优先选择模拟器）
   * @returns 设备信息，如果没有可用设备则返回 null
   */
  static getFirstAvailableDevice(preferSimulator: boolean = false): IOSDeviceInfo | null {
    const devices = this.getAllDevices();
    if (devices.length === 0) {
      return null;
    }

    if (preferSimulator) {
      // expo_ios 等场景：优先选择模拟器
      const simulator = devices.find(d => d.type === 'simulator');
      if (simulator) {
        return simulator;
      }
      logger.warn('preferSimulator=true 但未找到模拟器，回退到默认设备选择');
    }

    return devices[0];
  }

  /**
   * 根据设备 ID 查找设备信息
   * @param deviceId 设备 ID
   * @returns 设备信息，如果未找到则返回 null
   */
  static findDevice(deviceId: string): IOSDeviceInfo | null {
    const devices = this.getAllDevices();
    return devices.find(d => d.id === deviceId) || null;
  }

  /**
   * 启动模拟器 WDA
   * @param device 设备信息
   * @returns 是否启动成功
   */
  private static launchSimulatorWDA(device: IOSDeviceInfo): boolean {
    try {
      logger.info('模拟器使用 xcodebuild test-without-building 启动 WDA');
      
      // 使用 spawn 在后台启动 xcodebuild，因为它会持续运行
      // 需要在 WDA_simulator 目录下执行，这样 xctestrun 文件中的相对路径才能正确解析
      const xcodebuildProcess = spawn(
        'xcodebuild',
        [
          'test-without-building',
          '-xctestrun', WDA_CONFIG.simulatorXctestrunPath,
          '-destination', `id=${device.id}`
        ],
        {
          cwd: WDA_CONFIG.simulatorExtractDir, // 在 WDA_simulator 目录下执行
          stdio: 'pipe',
          detached: true
        }
      );

      // 不等待进程结束，让它在后台运行
      xcodebuildProcess.unref();

      // 监听输出
      xcodebuildProcess.stdout?.on('data', (data) => {
        const output = data.toString();
        logger.debug(`WDA 输出: ${output}`);
      });

      xcodebuildProcess.stderr?.on('data', (data) => {
        logger.debug(`WDA 错误输出: ${data.toString()}`);
      });

      xcodebuildProcess.on('error', (error) => {
        logger.error('WDA 进程启动失败', error);
      });

      logger.info('WDA 启动指令已发出（后台运行）');
      return true;
    } catch (error: unknown) {
      const err = error as { stderr?: string; message?: string };
      const errorMessage = err.stderr || err.message || String(error);
      if (errorMessage.includes('Unable to find a destination')) {
        throw new Error(`模拟器 WDA 启动失败: 未找到指定的模拟器 (${device.id})\n请确保模拟器已启动`);
      }
      
      if (errorMessage.includes('xcodebuild: error:')) {
        throw new Error(`模拟器 WDA 启动失败: Xcode 构建错误\n${errorMessage}`);
      }
      
      throw new Error(`模拟器 WDA 启动失败: ${error}`);
    }
  }

  /**
   * 启动 WebDriverAgent (WDA)（仅模拟器）
   * @param device 设备信息
   * @returns 是否启动成功
   */
  static launchWDA(device: IOSDeviceInfo): boolean {
    logger.info('正在启动 WDA...');

    if (device.type === 'physical') {
      throw new PhysicalWDAUnsupportedError();
    }
    return this.launchSimulatorWDA(device);
  }

  /**
   * 检查 Homebrew 是否已安装
   * @returns 是否已安装
   */
  static isHomebrewInstalled(): boolean {
    try {
      execSync('which brew', { encoding: 'utf-8', stdio: 'pipe' });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * 安装 Homebrew
   * @returns 是否安装成功
   */
  static installHomebrew(): boolean {
    try {
      logger.info('正在安装 Homebrew（可能需要几分钟）...');

      // 使用官方安装脚本
      execSync(
        '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
        {
          encoding: 'utf-8',
          stdio: 'inherit'
        }
      );

      logger.info('Homebrew 安装成功');
      return true;
    } catch (error) {
      logger.error('Homebrew 安装失败', error);
      logger.warn('请手动安装: https://brew.sh');
      return false;
    }
  }

  /**
   * 检查 libimobiledevice 是否已安装
   * @returns 是否已安装
   */
  static isLibimobiledeviceInstalled(): boolean {
    try {
      execSync('which iproxy', { encoding: 'utf-8', stdio: 'pipe' });
      return true;
    } catch {
      return false;
    }
  }

  /**
   * 安装 libimobiledevice
   * 用于 iproxy 端口转发
   * @returns 是否安装成功
   */
  static installLibimobiledevice(): boolean {
    try {
      // 检查 Homebrew 是否已安装
      if (!this.isHomebrewInstalled()) {
        logger.warn('Homebrew 未安装，正在尝试安装 Homebrew...');
        const brewInstalled = this.installHomebrew();
        if (!brewInstalled) {
          throw new Error('Homebrew 安装失败，无法继续安装 libimobiledevice');
        }
      }

      logger.info('正在安装 libimobiledevice...');
      execSync('brew install libimobiledevice', {
        encoding: 'utf-8',
        stdio: 'inherit'
      });
      logger.info('安装成功');
      return true;
    } catch (error) {
      throw new Error(`安装 libimobiledevice 失败: ${error}`);
    }
  }

  /**
   * 启动端口转发（仅物理设备需要）
   * @param device 设备信息
   * @param localPort 本地端口，默认 8100
   * @param remotePort 远程端口，默认 8100
   * @returns 是否启动成功
   */
  static async startPortForward(
    device: IOSDeviceInfo,
    localPort: number = 8100,
    remotePort: number = 8100
  ): Promise<boolean> {
    // 模拟器不需要端口转发
    if (device.type === 'simulator') {
      logger.info('模拟器不需要端口转发');
      return true;
    }
    try {
      // 检查是否已安装 libimobiledevice
      if (!this.isLibimobiledeviceInstalled()) {
        logger.warn('libimobiledevice 未安装，正在尝试安装...');
        this.installLibimobiledevice();
      }

      // 如果已有端口转发进程在运行，先停止
      if (this.portForwardProcess) {
        logger.info('停止现有的端口转发进程...');
        this.stopPortForward();
      }

      logger.info(`正在启动端口转发 ${localPort}:${remotePort}...`);

      // 使用 spawn 启动 iproxy，以便保持进程运行
      // 优先使用 udid（idevice_id 返回的），如果没有则不指定让 iproxy 自动检测
      const args = [localPort.toString(), remotePort.toString()];
      if (device.udid) {
        args.push('--udid', device.udid);
        logger.debug(`使用 UDID: ${device.udid}`);
      }
      
      this.portForwardProcess = spawn('iproxy', args, {
        stdio: 'inherit'
      });

      // 监听进程退出
      this.portForwardProcess.on('exit', (code) => {
        logger.info(`端口转发进程退出，退出码: ${code}`);
        this.portForwardProcess = null;
      });

      // 监听错误
      this.portForwardProcess.on('error', (error) => {
        logger.error('端口转发进程错误', error);
        this.portForwardProcess = null;
      });

      // 等待一小段时间确保进程启动
      return new Promise<boolean>((resolve) => {
        setTimeout(() => {
          if (this.portForwardProcess && !this.portForwardProcess.killed) {
            logger.info('端口转发启动成功');
            resolve(true);
          } else {
            logger.error('端口转发启动失败');
            resolve(false);
          }
        }, 1000);
      });
    } catch (error) {
      throw new Error(`启动端口转发失败: ${error}`);
    }
  }

  /**
   * 停止端口转发
   */
  static stopPortForward(): void {
    if (this.portForwardProcess) {
      try {
        this.portForwardProcess.kill();
        this.portForwardProcess = null;
        logger.info('端口转发已停止');
      } catch (error) {
        logger.error('停止端口转发失败', error);
      }
    }
  }

  /**
   * 检查 WDA 是否正在运行
   * @param port WDA 端口，默认 8100
   * @returns 是否正在运行
   */
  static async isWDARunning(port: number = 8100): Promise<boolean> {
    try {
      const response = await fetch(`http://localhost:${port}/status`);
      if (!response.ok) {
        return false;
      }
      const data = await response.json() as { value?: { ready?: boolean } };
      return data.value?.ready === true;
    } catch {
      return false;
    }
  }

  /**
   * 完整的 iOS 设备初始化流程
   * @param deviceId 设备 ID（可选），如果不提供则自动选择第一个可用设备
   * @param throwOnTimeout 是否在 WDA 启动超时时抛出异常（默认 false）
   * @returns 初始化是否成功
   */
  static async initializeDevice(deviceId?: string, throwOnTimeout: boolean = false, preferSimulator: boolean = false): Promise<boolean> {
    // 1. 获取设备信息
    let device: IOSDeviceInfo | null = null;
    
    if (deviceId) {
      // 如果指定了设备 ID，查找该设备
      device = this.findDevice(deviceId);
      if (!device) {
        logger.error(`未找到设备 ID 为 ${deviceId} 的设备`);
        return false;
      }
    } else {
      // 否则自动选择第一个可用设备
      device = this.getFirstAvailableDevice(preferSimulator);
      if (!device) {
        logger.error('未找到可用的 iOS 设备或模拟器');
        return false;
      }
    }

    logger.info(`使用设备: ${device.name} (${device.type})`);

    // 2. 确保 WDA 已准备就绪（下载并安装）
    // ReturnAsResultError (如 DeveloperModeDisabledError) 会自动向上传播
    const wdaReady = await this.ensureWDAReady(device);
    if (!wdaReady) {
      logger.error('WDA 准备失败');
      return false;
    }

    // 3. 启动端口转发（仅物理设备需要）
    // 必须在检查 WDA 状态之前启动，否则无法访问 WDA 的 status 接口
    const portForwardSuccess = await this.startPortForward(device);
    if (!portForwardSuccess && device.type === 'physical') {
      logger.error('端口转发启动失败');
      return false;
    }

    // 4. 检查 WDA 是否已经在运行
    const isRunning = await this.isWDARunning();
    
    if (isRunning) {
      logger.info('WDA 已在运行');
      return true;
    }

    // 5. 如果 WDA 未运行，则启动 WDA
    this.launchWDA(device);

    // 6. 等待 WDA 就绪
    logger.info('正在等待 WDA 启动，请耐心等候...');
    const wdaStartTime = Date.now();
    let retries = 30;
    let checkCount = 0;
    while (retries > 0) {
      checkCount++;
      if (await this.isWDARunning()) {
        const elapsed = Date.now() - wdaStartTime;
        logger.info(`WDA 已就绪，耗时 ${elapsed}ms`);

        // 预热：创建临时 session 验证 session API 可用后再删除
        logger.info('正在预热 WDA session...');
        try {
          const sessionResponse = await fetch('http://localhost:8100/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              capabilities: {
                alwaysMatch: {
                  platformName: 'iOS',
                  automationName: 'XCUITest',
                },
              },
            }),
          });
          if (sessionResponse.ok) {
            const sessionData = await sessionResponse.json() as {
              value?: { sessionId?: string };
              sessionId?: string;
            };
            const tempSessionId = sessionData.value?.sessionId || sessionData.sessionId;
            if (tempSessionId) {
              await fetch(`http://localhost:8100/session/${tempSessionId}`, {
                method: 'DELETE',
              });
              logger.info('WDA 预热完成');
            } else {
              logger.warn('WDA 预热：未能获取临时 session ID');
            }
          } else {
            logger.warn(`WDA 预热：创建 session 失败，HTTP ${sessionResponse.status}`);
          }
        } catch (warmupError) {
          logger.warn(`WDA 预热失败: ${warmupError instanceof Error ? warmupError.message : String(warmupError)}`);
        }

        return true;
      }

      // 记录当前状态以便诊断
      try {
        const statusResponse = await fetch('http://localhost:8100/status');
        if (statusResponse.status === 404) {
          logger.debug(`WDA 状态检查 #${checkCount}: 返回 404，服务尚未初始化`);
        } else if (!statusResponse.ok) {
          logger.debug(`WDA 状态检查 #${checkCount}: HTTP ${statusResponse.status}`);
        } else {
          const statusData = await statusResponse.json() as {
            value?: { ready?: boolean; state?: string };
          };
          logger.debug(
            `WDA 状态检查 #${checkCount}: ready=${statusData.value?.ready}, state=${statusData.value?.state}`
          );
        }
      } catch (connError) {
        logger.debug(
          `WDA 状态检查 #${checkCount}: 连接失败 (${connError instanceof Error ? connError.message : String(connError)})`
        );
      }

      // 每隔几次检查输出一次等待提示，避免过多日志
      if (checkCount % 5 === 0) {
        logger.info(`正在等待 WDA 响应... (${checkCount}/30)`);
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
      retries--;
    }

    const errorMessage = [
      'WDA 启动超时',
      '可能的原因：',
      '  1. 设备重启后首次运行 WDA，需要在设备上为 XCTest 输入密码',
      '  2. 需要在设备设置中信任企业证书（设置-通用-VPN与设备管理-"Autonavi Software Co., Ltd"）',
      '请检查设备屏幕是否有提示，完成授权后重新运行'
    ].join('\n');
    
    logger.error(errorMessage);
    
    // 根据参数决定是否抛出异常
    if (throwOnTimeout) {
      throw new WDATimeoutError(errorMessage);
    }
    return false;
  }

  /**
   * 清理资源
   */
  static cleanup(): void {
    this.stopPortForward();
  }
}

