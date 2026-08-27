#!/usr/bin/env bash
#
# Android emulator environment setup script for daimax-appbench.
#
# - Detects macOS / Linux
# - Ensures Java is installed
# - Installs Android command-line tools, platform-tools, emulator and system image
# - Creates a default Pixel 7 API 34 AVD
# - Idempotent: skips already-installed components
#
# Usage:
#   bash scripts/setup-android-env.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── Detect OS ───────────────────────────────────────────────────────────────
OS=""
ARCH="$(uname -m)"
case "$(uname -s)" in
    Darwin*) OS="macos" ;;
    Linux*)  OS="linux" ;;
    *)
        error "Unsupported OS: $(uname -s). This script supports macOS and Linux only."
        exit 1
        ;;
esac

info "Detected OS: $OS, architecture: $ARCH"

# ── Java check ──────────────────────────────────────────────────────────────
if ! command -v java &>/dev/null; then
    warn "Java not found."
    if [[ "$OS" == "macos" ]]; then
        if command -v brew &>/dev/null; then
            info "Installing OpenJDK via Homebrew..."
            brew install openjdk
            # Homebrew does NOT symlink openjdk to avoid conflicts with system Java.
            # Print a hint; the user may need to run the caveats manually.
            warn "Please follow Homebrew's caveats to link OpenJDK if this is a fresh install."
        else
            error "Homebrew not found. Please install Java manually:"
            error "  brew install openjdk   # or download from https://adoptium.net"
            exit 1
        fi
    else
        error "Please install OpenJDK manually, e.g.:"
        error "  sudo apt-get install -y openjdk-17-jdk   # Debian/Ubuntu"
        error "  sudo dnf install -y java-17-openjdk      # Fedora/RHEL"
        exit 1
    fi
else
    info "Java found: $(java -version 2>&1 | head -n 1)"
fi

# ── ANDROID_HOME ────────────────────────────────────────────────────────────
if [[ -n "${ANDROID_HOME:-}" ]]; then
    ANDROID_SDK="$ANDROID_HOME"
elif [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
    ANDROID_SDK="$ANDROID_SDK_ROOT"
else
    if [[ "$OS" == "macos" ]]; then
        ANDROID_SDK="$HOME/Library/Android/sdk"
    else
        ANDROID_SDK="$HOME/Android/Sdk"
    fi
fi

export ANDROID_HOME="$ANDROID_SDK"
export ANDROID_SDK_ROOT="$ANDROID_SDK"
info "ANDROID_HOME set to: $ANDROID_HOME"

mkdir -p "$ANDROID_HOME"

# ── Command-line tools ──────────────────────────────────────────────────────
CMDLINE_DIR="$ANDROID_HOME/cmdline-tools"
LATEST_BIN="$CMDLINE_DIR/latest/bin"

if [[ -d "$LATEST_BIN" && -x "$LATEST_BIN/sdkmanager" ]]; then
    info "Android command-line tools already installed."
else
    info "Downloading Android command-line tools..."

    if [[ "$OS" == "macos" ]]; then
        CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-mac-11076708_latest.zip"
    else
        CMDLINE_URL="https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
    fi

    TEMP_ZIP="/tmp/cmdline-tools.zip"
    curl -L -o "$TEMP_ZIP" "$CMDLINE_URL"

    rm -rf "$CMDLINE_DIR/latest"
    mkdir -p "$CMDLINE_DIR"

    # Unzip; the archive contains a single "cmdline-tools" folder.
    unzip -q "$TEMP_ZIP" -d "$CMDLINE_DIR"
    mv "$CMDLINE_DIR/cmdline-tools" "$CMDLINE_DIR/latest"
    rm -f "$TEMP_ZIP"

    info "Command-line tools installed."
fi

# Add to PATH for this script
export PATH="$LATEST_BIN:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

# ── Accept licenses silently ────────────────────────────────────────────────
info "Accepting Android SDK licenses..."
yes | sdkmanager --licenses >/dev/null 2>&1 || true

# ── Required packages ───────────────────────────────────────────────────────
info "Checking / installing required SDK packages..."

REQUIRED_PKGS=(
    "platform-tools"
    "emulator"
    "system-images;android-34;google_apis;arm64-v8a"
)

for pkg in "${REQUIRED_PKGS[@]}"; do
    # sdkmanager --list_installed is slow; just install (idempotent)
    info "  -> $pkg"
    sdkmanager "$pkg" >/dev/null 2>&1 || sdkmanager "$pkg"
done

info "Required packages installed."

# ── Create default AVD ──────────────────────────────────────────────────────
AVD_NAME="Pixel_7_API_34"
if avdmanager list avd -c 2>/dev/null | grep -qx "$AVD_NAME"; then
    info "AVD '$AVD_NAME' already exists."
else
    info "Creating AVD: $AVD_NAME ..."
    echo "no" | avdmanager create avd \
        -n "$AVD_NAME" \
        -k "system-images;android-34;google_apis;arm64-v8a" \
        -d "pixel_7" \
        --force
    info "AVD '$AVD_NAME' created."
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Android Environment Ready"
echo "========================================"
echo ""
echo "Add the following to your shell profile (~/.zshrc, ~/.bashrc, etc.):"
echo ""
echo "  export ANDROID_HOME=\"$ANDROID_HOME\""
echo "  export ANDROID_SDK_ROOT=\"\$ANDROID_HOME\""
echo "  export PATH=\"\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$ANDROID_HOME/emulator:\$PATH\""
echo ""
echo "Then reload your shell:"
echo "  source ~/.zshrc   # or ~/.bashrc"
echo ""
echo "To start the emulator manually:"
echo "  emulator -avd $AVD_NAME -no-snapshot -no-audio"
echo ""
