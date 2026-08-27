#!/usr/bin/env python3
"""
Expo platform builder for expo_android and expo_ios targets.

For iOS, separates build from Metro bundler:
  1. `npx expo prebuild --platform ios` to generate native project
  2. `xcodebuild build` to build the .app (exits normally)
For Android, separates build from Metro bundler:
  1. `npx expo prebuild --platform android` to generate native project
  2. `./gradlew assembleRelease` to build the APK (exits normally)
Metro is managed separately during the install/E2E test phase.
"""

import os
import signal
import socket
import sys
import glob
import shutil
import subprocess

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core import (
    BaseBuilder,
    print_info,
    print_success,
    print_warning,
    print_error,
    run_command
)


class ExpoBuilder(BaseBuilder):
    """Builder for Expo projects targeting Android or iOS emulators."""

    def __init__(self, project_dir, build_type="debug", output_dir=None,
                 clean=False, output_format="apk", expo_platform="android",
                 device_id=None):
        """
        Initialize Expo builder.

        Args:
            project_dir: Project root directory (Expo/React Native project)
            build_type: Build type (debug or release)
            output_dir: Output directory for build artifacts
            clean: Whether to clean before building
            output_format: Output format (apk for android, app for ios)
            expo_platform: Expo target platform ("android" or "ios")
            device_id: Target device ID (e.g. "emulator-5554" for Android)
        """
        super().__init__(project_dir, build_type, output_dir, clean)
        self.output_format = output_format or ("apk" if expo_platform == "android" else "app")
        self.expo_platform = expo_platform  # "android" or "ios"
        self.device_id = device_id

    def check_environment(self):
        """Check if Expo build environment is ready."""
        print_info(f"Checking Expo {self.expo_platform} build environment...")

        # Check Node.js / npm
        if not self._check_node():
            print_error("Node.js/npm not found")
            return False

        # Check project has package.json with expo dependency
        if not self._check_expo_project():
            print_error("Not a valid Expo project (package.json with expo not found)")
            return False

        if self.expo_platform == "android":
            if not self._check_android_sdk():
                print_error("Android SDK not found (required for expo run:android)")
                return False
        elif self.expo_platform == "ios":
            import platform as _platform
            if _platform.system() != "Darwin":
                print_error("iOS builds require macOS")
                return False
            if not self._check_xcode():
                print_error("Xcode not found (required for expo run:ios)")
                return False

        print_success(f"Expo {self.expo_platform} build environment is ready")
        return True

    def setup_environment(self):
        """Setup is done separately; this is a no-op for compatibility."""
        print_warning("setup_environment() is deprecated for Expo projects")
        return True

    def validate_project(self):
        """Validate Expo project directory."""
        if not os.path.exists(self.project_dir):
            print_error(f"Project directory not found: {self.project_dir}")
            return False

        package_json = os.path.join(self.project_dir, "package.json")
        if not os.path.exists(package_json):
            print_error("Not a valid project (package.json not found)")
            return False

        print_success(f"Valid Expo project: {self.project_dir}")
        return True

    def configure_signing(self, keystore_path, keystore_password,
                          key_alias, key_password):
        """Signing configuration is not required for Expo debug builds."""
        if self.build_type != "release":
            return True
        print_warning("Expo release signing should be configured via EAS Build")
        return True

    def _ensure_ios_pods(self):
        """确保 iOS Pod 依赖已安装（修复 Podfile.lock 缺失导致构建失败）"""
        # 查找 ios 目录中的 Podfile
        ios_dir = os.path.join(self.project_dir, "ios")
        if not os.path.isdir(ios_dir):
            return True  # 没有 ios 目录，跳过

        podfile = os.path.join(ios_dir, "Podfile")
        if not os.path.exists(podfile):
            return True  # 没有 Podfile，不需要 Pod

        # 检查 Podfile.lock 和 xcworkspace 是否存在
        podfile_lock = os.path.join(ios_dir, "Podfile.lock")
        xcworkspace_exists = any(
            item.endswith(".xcworkspace") for item in os.listdir(ios_dir)
        )

        if os.path.exists(podfile_lock) and xcworkspace_exists:
            print_info("Pod 依赖状态有效，跳过 pod install")
            return True

        # 需要执行 pod install
        if not os.path.exists(podfile_lock):
            print_warning("Podfile.lock 缺失，执行 pod install...")
        elif not xcworkspace_exists:
            print_warning(".xcworkspace 缺失，执行 pod install...")

        # 检查 pod 命令是否可用
        pod_path = shutil.which("pod")
        if not pod_path:
            print_error("pod 命令未找到，跳过 pod install")
            return False

        # 执行 pod install
        print_info(f"运行 pod install (目录: {ios_dir})")
        result = subprocess.run(
            ["pod", "install"],
            cwd=ios_dir,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            print_error(f"pod install 失败: {result.stderr[:500]}")
            return False

        # 验证结果
        if not os.path.exists(podfile_lock):
            print_error("pod install 后 Podfile.lock 仍然缺失")
            return False

        print_success("pod install 完成，Pod 依赖已就绪")
        return True

    def _get_free_port(self) -> int:
        """Allocate a free TCP port on localhost for Metro bundler."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def _ensure_adb_server(self) -> bool:
        """Ensure ADB server is running before build to avoid concurrent start-server conflicts.

        Multiple concurrent expo builds each try to start ADB server simultaneously,
        which corrupts the daemon state. Pre-starting ADB avoids this race condition.
        """
        import time

        adb_path = os.path.join(
            os.environ.get("ANDROID_HOME", os.path.expanduser("~/Library/Android/sdk")),
            "platform-tools", "adb"
        )

        if not os.path.exists(adb_path):
            print_warning(f"ADB not found at {adb_path}, skipping ADB pre-check")
            return True

        # Check if ADB server is already responsive
        try:
            result = subprocess.run(
                [adb_path, "devices"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass

        # ADB not responsive, try to start it (with retry)
        print_info("ADB server not responsive, starting...")
        for attempt in range(3):
            try:
                # Kill any zombie ADB processes first
                subprocess.run([adb_path, "kill-server"], capture_output=True, timeout=10)
                time.sleep(2)
                result = subprocess.run(
                    [adb_path, "start-server"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    # Verify it's responsive
                    time.sleep(1)
                    verify = subprocess.run(
                        [adb_path, "devices"],
                        capture_output=True, text=True, timeout=10
                    )
                    if verify.returncode == 0:
                        print_info("ADB server started successfully")
                        return True
            except (subprocess.TimeoutExpired, OSError) as e:
                print_warning(f"ADB start attempt {attempt + 1}/3 failed: {e}")
                time.sleep(3)

        print_warning("Failed to start ADB server after 3 attempts, proceeding anyway")
        return False

    def _cleanup_metro_port(self, port=8081):
        """Kill any process listening on the given Metro dev-server port.

        `npx expo run:android/ios` starts a Metro bundler on the default
        port 8081.  When multiple samples are evaluated sequentially the
        previous bundler may still be alive, causing port conflicts and
        non-interactive-mode failures for subsequent builds.
        """
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                for pid_str in result.stdout.strip().split("\n"):
                    pid_str = pid_str.strip()
                    if not pid_str:
                        continue
                    try:
                        pid = int(pid_str)
                        # Only kill node/metro processes, NOT emulator or
                        # other unrelated processes that happen to have
                        # connections on this port.
                        try:
                            proc_result = subprocess.run(
                                ["ps", "-p", str(pid), "-o", "comm="],
                                capture_output=True, text=True, timeout=5,
                            )
                            proc_name = proc_result.stdout.strip().lower()
                            if "node" not in proc_name and "metro" not in proc_name:
                                continue
                        except Exception:
                            continue
                        os.kill(pid, signal.SIGKILL)
                        print_info(f"Killed Metro process {pid} on port {port}")
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
        except Exception as e:
            print_warning(f"Failed to cleanup Metro port {port}: {e}")

    def build(self, output_format=None):
        """Build Expo project.

        For iOS: uses `npx expo run:ios` which builds AND installs.
        For Android: separates build from Metro bundler to avoid the
        process-hanging issue where `expo run:android` keeps Metro running
        indefinitely. Instead, the Android build is split into:
          1. prebuild: `npx expo prebuild --platform android` (if needed)
          2. gradle: `./gradlew assembleRelease` (exits normally)
        Metro is not started here; it should be managed in the install/test
        phase as needed.
        """
        if output_format:
            self.output_format = output_format

        print_info(f"Building Expo {self.expo_platform} ({self.build_type})")

        # Ensure node_modules is managed by npm (not pnpm) to avoid Metro
        # TreeFS conflicts when pnpm's .ignored directory is present.
        # iOS 例外：Pods 的 xcconfig 已基于生成阶段的 pnpm 结构硬编码了
        # node_modules/.pnpm/<pkg>@<ver>_<hash>/... 路径，若此处用 npm
        # 重装 node_modules 会破坏这些路径，导致 xcodebuild 在
        # PhaseScriptExecution / Copy PrivacyInfo 等阶段全部失败。
        if self.expo_platform != "ios":
            self._ensure_npm_modules()

        # Ensure npm registry is reachable before installing dependencies
        try:
            from evalapp.utils.npm_registry import ensure_npm_registry_reachable
            ensure_npm_registry_reachable(self.project_dir)
        except Exception as e:
            print_warning(f"npm registry check failed (non-fatal): {e}")

        # Install dependencies.
        # iOS 评测：生成阶段已用 pnpm 装好 node_modules 且 pod install 已基于该
        # 结构生成 Pods，禁止在此处再次重装；仅当 node_modules 缺失时才按
        # lockfile 优先级（pnpm-lock.yaml > package-lock.json）补装，避免破坏
        # Pods xcconfig 中的 .pnpm 硬编码路径。
        node_modules_dir = os.path.join(self.project_dir, "node_modules")
        if self.expo_platform == "ios":
            if os.path.isdir(node_modules_dir):
                print_info(
                    "iOS: node_modules already present, skipping reinstall to "
                    "preserve Pods xcconfig hardcoded .pnpm paths"
                )
            else:
                pnpm_lock = os.path.join(self.project_dir, "pnpm-lock.yaml")
                if os.path.exists(pnpm_lock) and shutil.which("pnpm"):
                    print_info("iOS: node_modules missing, installing via pnpm...")
                    if not run_command(
                        "pnpm install --frozen-lockfile",
                        cwd=self.project_dir,
                        env=self.env,
                    ):
                        print_warning("pnpm install failed, falling back to npm install...")
                        if not run_command("npm install", cwd=self.project_dir, env=self.env):
                            print_warning("npm install failed, continuing anyway...")
                else:
                    print_info("iOS: node_modules missing, installing via npm...")
                    if not run_command("npm install", cwd=self.project_dir, env=self.env):
                        print_warning("npm install failed, continuing anyway...")
        else:
            print_info("Installing npm dependencies...")
            if not run_command("npm install", cwd=self.project_dir, env=self.env):
                print_warning("npm install failed, continuing anyway...")

        # Determine the build command from package.json scripts
        build_script = f"build:{self.expo_platform}"  # e.g., build:android, build:ios

        # Check if the build script exists in package.json and is NOT an EAS
        # (Expo Application Services) cloud build command.  EAS Build requires
        # eas-cli and a cloud account; local eval environments typically don't
        # have either, so we fall back to the local npx expo run:xxx command.
        has_build_script = self._has_npm_script(build_script)
        if has_build_script:
            script_cmd = self._get_npm_script(build_script)
            if script_cmd and "eas " in script_cmd:
                print_warning(
                    f"npm script '{build_script}' uses EAS Build ('{script_cmd}'); "
                    "skipping because eas-cli is not available locally"
                )
                has_build_script = False
            elif script_cmd and "expo run" in script_cmd:
                print_warning(
                    f"npm script '{build_script}' uses 'expo run' ('{script_cmd}'); "
                    "skipping because expo run starts Metro indefinitely. "
                    "Using prebuild + xcodebuild/gradle instead."
                )
                has_build_script = False

        # === Build environment setup (common for all platforms) ===
        build_env = dict(self.env) if self.env else os.environ.copy()
        build_env["CI"] = "1"

        # For iOS builds, the Android NDK clang++ may appear earlier in PATH
        # than /usr/bin/clang++.  The NDK compiler does not recognise the
        # '-std=c++20' flag that React Native 0.81+ requires, which causes
        # xcodebuild sub-processes to fail.  We prepend the Xcode toolchain
        # (and /usr/bin as a fallback) so the Apple clang is picked first.
        if self.expo_platform == "ios":
            xcode_tc = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin"
            path_parts = build_env.get("PATH", "").split(os.pathsep)
            # 确保系统 python3 可用（/usr/bin 和 /opt/homebrew/bin）
            new_path = [xcode_tc, "/usr/bin", "/opt/homebrew/bin"]
            for p in path_parts:
                if p not in new_path:
                    new_path.append(p)
            build_env["PATH"] = os.pathsep.join(new_path)

        # For Android builds, inject ANDROID_HOME and related PATH entries so
        # that gradle/expo can locate the SDK, emulator and adb even when the
        # user's shell has not configured them.
        if self.expo_platform == "android":
            android_home = self._detect_android_sdk()
            if android_home:
                print_info(f"Detected Android SDK: {android_home}")
                build_env["ANDROID_HOME"] = android_home
                build_env["ANDROID_SDK_ROOT"] = android_home
                path_parts = build_env.get("PATH", "").split(os.pathsep)
                android_paths = [
                    os.path.join(android_home, "emulator"),
                    os.path.join(android_home, "platform-tools"),
                    os.path.join(android_home, "cmdline-tools", "latest", "bin"),
                ]
                # 确保系统 python3 可用，Gradle 调用 node-gyp 时需要
                new_path = ["/usr/bin", "/opt/homebrew/bin"]
                new_path.extend([p for p in android_paths if p not in new_path])
                for p in path_parts:
                    if p not in new_path:
                        new_path.append(p)
                build_env["PATH"] = os.pathsep.join(new_path)
                # Disable ccache for NDK cross-compilation - it hangs in
                # uninterruptible sleep (UE state) on macOS ARM64.
                build_env["CCACHE_DISABLE"] = "1"
                build_env["ANDROID_CCACHE"] = ""
            else:
                print_warning(
                    "Android SDK not detected; relying on existing environment or letting expo fail"
                )

        # === P0-2: iOS 构建前确保 Pod 依赖已安装 ===
        if self.expo_platform == "ios":
            if not self._ensure_ios_pods():
                print_warning("Pod 依赖检查失败，继续构建（可能会失败）")

        # Kill any leftover Metro bundler from a previous sample before
        # starting the build.
        self._cleanup_metro_port()

        # Pre-start ADB server for Android to avoid concurrent
        # `adb start-server` race conditions.
        if self.expo_platform != "ios":
            self._ensure_adb_server()

        # === Platform-specific build execution ===
        if self.expo_platform == "android":
            # --- Android: prebuild + gradle (构建与 Metro 分离) ---
            # `expo run:android` 在构建+安装后会启动 Metro bundler 且不退出，
            # 导致评测系统等待超时后判定构建失败。
            # 改为分步执行：prebuild → gradle assembleRelease，不启动 Metro。

            # Step 1: Prebuild (generate native android project if needed)
            # clean_build=True 时，强制执行 prebuild --clean 以重新生成 codegen 产物
            # （避免 ./gradlew clean 清除 codegen JNI 产物后 CMake 找不到依赖目录）
            android_dir = os.path.join(self.project_dir, "android")
            if self.clean:
                print_info("clean build 模式：强制执行 npx expo prebuild --clean --platform android...")
                if not run_command(
                    "npx expo prebuild --clean --platform android",
                    cwd=self.project_dir,
                    env=build_env,
                ):
                    print_error("Expo prebuild --clean 失败")
                    return False
                print_success("Expo prebuild --clean 完成")
            elif not os.path.isdir(android_dir):
                print_info("android/ 目录不存在，执行 npx expo prebuild --platform android...")
                if not run_command(
                    "npx expo prebuild --platform android",
                    cwd=self.project_dir,
                    env=build_env,
                ):
                    print_error("Expo prebuild 失败")
                    return False
                print_success("Expo prebuild 完成")
            else:
                print_info("android/ 目录已存在，跳过 prebuild")

            # Step 2: Ensure gradlew has execute permission
            gradlew_path = os.path.join(android_dir, "gradlew")
            if os.path.exists(gradlew_path):
                os.chmod(gradlew_path, 0o755)
                print_info("已确保 gradlew 具有执行权限")

            # Step 3: Run gradle assembleRelease (exits normally, no Metro)
            print_info("运行 gradle assembleRelease...")
            if not run_command(
                "./gradlew assembleRelease",
                cwd=android_dir,
                env=build_env,
            ):
                print_error("Gradle 构建失败")
                return False

            # Verify APK output
            apk_path = os.path.join(
                android_dir, "app", "build", "outputs", "apk", "release", "app-release.apk"
            )
            if os.path.exists(apk_path):
                print_success(f"APK 构建成功: {apk_path}")
            else:
                print_warning(f"APK 未在预期路径找到: {apk_path}")

            print_success("Expo Android 构建完成")
            return True

        else:
            # --- iOS: prebuild + xcodebuild (构建与 Metro 分离) ---
            # `expo run:ios` 在构建+安装后会启动 Metro bundler 且不退出，
            # 导致评测系统等待超时后判定构建失败。
            # 改为分步执行：prebuild → xcodebuild build，不启动 Metro。

            # Step 1: Prebuild (generate native ios project if needed)
            ios_dir = os.path.join(self.project_dir, "ios")
            if not os.path.isdir(ios_dir):
                print_info("ios/ 目录不存在，执行 npx expo prebuild --platform ios...")
                if not run_command(
                    "npx expo prebuild --platform ios",
                    cwd=self.project_dir,
                    env=build_env,
                ):
                    print_error("Expo prebuild 失败")
                    return False
                print_success("Expo prebuild 完成")
            else:
                print_info("ios/ 目录已存在，跳过 prebuild")

            # Step 2: Determine Xcode workspace / project and scheme
            workspace_path = None
            project_path = None
            xcworkspaces = glob.glob(os.path.join(ios_dir, "*.xcworkspace"))
            if xcworkspaces:
                workspace_path = xcworkspaces[0]
                scheme_name = os.path.splitext(os.path.basename(workspace_path))[0]
                print_info(f"找到 workspace: {workspace_path}, scheme: {scheme_name}")
            else:
                xcprojects = glob.glob(os.path.join(ios_dir, "*.xcodeproj"))
                if xcprojects:
                    project_path = xcprojects[0]
                    scheme_name = os.path.splitext(os.path.basename(project_path))[0]
                    print_info(f"未找到 xcworkspace，使用 project: {project_path}, scheme: {scheme_name}")
                else:
                    print_error("ios/ 目录下未找到 .xcworkspace 或 .xcodeproj")
                    return False

            # Step 3: Run xcodebuild build (exits normally, no Metro)
            if has_build_script:
                print_info(f"使用自定义 build script: npm run {build_script}")
                if not run_command(
                    f"npm run {build_script}",
                    cwd=self.project_dir,
                    env=build_env,
                ):
                    print_error("自定义 build script 失败")
                    return False
            else:
                build_cmd_parts = [
                    "xcodebuild",
                    f"-scheme {scheme_name}",
                    "-configuration Release",
                    "-sdk iphonesimulator",
                    "-derivedDataPath ios/build",
                    "build",
                ]
                if workspace_path:
                    build_cmd_parts.insert(1, f"-workspace {workspace_path}")
                elif project_path:
                    build_cmd_parts.insert(1, f"-project {project_path}")

                build_cmd = " ".join(build_cmd_parts)
                print_info("运行 xcodebuild...")
                print_info(f"  命令: {build_cmd}")

                if not run_command(build_cmd, cwd=self.project_dir, env=build_env):
                    print_error("xcodebuild 构建失败")
                    return False

            # Verify .app output
            app_search_dir = os.path.join(ios_dir, "build", "Build", "Products", "Release-iphonesimulator")
            app_files = glob.glob(os.path.join(app_search_dir, "*.app"))
            if app_files:
                print_success(f"APP 构建成功: {app_files[0]}")
            else:
                print_warning(f"APP 未在预期路径找到: {app_search_dir}")

            print_success("Expo iOS 构建完成")
            return True

    def copy_output(self):
        """Copy Expo build output to specified directory."""
        if not self.output_dir:
            return True

        patterns = [f".{self.output_format}"]
        return len(self._copy_files_to_output(patterns, self.output_dir)) > 0

    def _ensure_npm_modules(self):
        """确保 node_modules 由 npm 管理（非 pnpm），避免 Metro TreeFS 冲突。

        pnpm 创建的 node_modules/.ignored/ 目录会导致 Metro bundler 的
        TreeFS 在 release 构建 exportEmbedAsync 阶段报错：
        "TreeFS: Could not add directory node_modules/react-native, adding
        node_modules/react-native/package.json. node_modules/react-native
        already exists in the file map as a file."

        本方法检测 pnpm 产物，删除后用 npm 重新安装依赖。
        """
        pnpm_lock = os.path.join(self.project_dir, "pnpm-lock.yaml")
        ignored_dir = os.path.join(self.project_dir, "node_modules", ".ignored")

        if not os.path.exists(pnpm_lock) and not os.path.exists(ignored_dir):
            return

        print_info("Detected pnpm artifacts, reinstalling with npm for Metro compatibility...")

        # 删除 pnpm-lock.yaml
        if os.path.exists(pnpm_lock):
            os.remove(pnpm_lock)
            print_info("Removed pnpm-lock.yaml")

        # 删除 node_modules（pnpm 的 symlink 结构会导致 Metro 冲突）
        node_modules = os.path.join(self.project_dir, "node_modules")
        if os.path.exists(node_modules):
            shutil.rmtree(node_modules)
            print_info("Removed node_modules (pnpm-managed)")

        # Ensure npm registry is reachable before reinstalling
        try:
            from evalapp.utils.npm_registry import ensure_npm_registry_reachable
            ensure_npm_registry_reachable(self.project_dir)
        except Exception as e:
            print_warning(f"npm registry check failed (non-fatal): {e}")

        # 用 npm install 重新安装依赖
        print_info("Running npm install to rebuild node_modules...")
        result = subprocess.run(
            ["npm", "install"],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
            timeout=300,
            env=self.env or os.environ.copy(),
        )
        if result.returncode != 0:
            print_warning(f"npm install warning: {result.stderr[:500]}")
        else:
            print_success("npm install completed, node_modules now managed by npm")

    # --- Private helpers ---

    def _check_node(self):
        """Check if Node.js and npm are installed."""
        try:
            output = run_command("node --version", capture_output=True, env=self.env)
            if output:
                print_success(f"Node.js found: {output.strip()}")
            npm_output = run_command("npm --version", capture_output=True, env=self.env)
            if npm_output:
                print_success(f"npm found: {npm_output.strip()}")
            return bool(output and npm_output)
        except Exception:
            return False

    def _check_expo_project(self):
        """Check if the project is an Expo project."""
        import json
        package_json_path = os.path.join(self.project_dir, "package.json")
        if not os.path.exists(package_json_path):
            return False
        try:
            with open(package_json_path, 'r') as f:
                pkg = json.load(f)
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            return "expo" in deps or "expo-router" in deps
        except (json.JSONDecodeError, OSError):
            return False

    def _detect_android_sdk(self):
        """Detect Android SDK path from environment variables or common locations."""
        # 1. Check existing environment variables
        for env_var in ["ANDROID_HOME", "ANDROID_SDK_ROOT"]:
            path = (self.env or {}).get(env_var) or os.environ.get(env_var)
            if path and os.path.exists(path):
                return path

        # 2. Check common default paths
        for path in [
            os.path.expanduser("~/Library/Android/sdk"),  # macOS default
            os.path.expanduser("~/Android/Sdk"),           # Linux default
        ]:
            if os.path.exists(path):
                return path

        return None

    def _check_android_sdk(self):
        """Check if Android SDK is available."""
        android_home = self._detect_android_sdk()
        if android_home:
            if self.env is None:
                self.env = {}
            self.env["ANDROID_HOME"] = android_home
            print_success(f"Android SDK found: {android_home}")
            return True
        return False

    def _check_xcode(self):
        """Check if Xcode is installed."""
        try:
            output = run_command("xcodebuild -version", capture_output=True, env=self.env)
            if output and "Xcode" in output:
                print_success(f"Xcode found: {output.split(chr(10))[0]}")
                return True
            return False
        except Exception:
            return False

    def _has_npm_script(self, script_name):
        """Check if package.json defines the given script."""
        import json
        package_json_path = os.path.join(self.project_dir, "package.json")
        if not os.path.exists(package_json_path):
            return False
        try:
            with open(package_json_path, 'r') as f:
                pkg = json.load(f)
            return script_name in pkg.get("scripts", {})
        except (json.JSONDecodeError, OSError):
            return False

    def _get_npm_script(self, script_name):
        """Return the shell command for the given npm script, or None."""
        import json
        package_json_path = os.path.join(self.project_dir, "package.json")
        if not os.path.exists(package_json_path):
            return None
        try:
            with open(package_json_path, 'r') as f:
                pkg = json.load(f)
            return pkg.get("scripts", {}).get(script_name)
        except (json.JSONDecodeError, OSError):
            return None
