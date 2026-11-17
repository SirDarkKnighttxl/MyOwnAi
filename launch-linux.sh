#!/bin/bash
cd "$(dirname "$0")"
echo ""
echo "  Initializing TANNIS..."
echo ""

# Kill any existing instances
pkill -f "ollama serve" 2>/dev/null
pkill -f "whisper-server" 2>/dev/null
sleep 1

# ── DETECT CPU TYPE ──
ARCH=$(uname -m)
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
  EARCH="arm64"   # Electron naming
  OARCH="arm64"   # Ollama naming
else
  EARCH="x64"
  OARCH="amd64"
fi

# ── MAKE SURE BASIC TOOLS EXIST ──
if ! command -v curl >/dev/null 2>&1 || ! command -v unzip >/dev/null 2>&1 || ! command -v zstd >/dev/null 2>&1; then
  echo ""
  echo "  This computer is missing 'curl', 'unzip', or 'zstd'."
  echo "  Please run ONE of these in a terminal, then run TANNIS again:"
  echo "    Mint / Ubuntu / Debian:   sudo apt install -y curl unzip zstd"
  echo "    Fedora / RHEL / Oracle:   sudo dnf install -y curl unzip zstd"
  echo ""
  read -p "  Press Enter to close..."
  exit 1
fi

# ── GET OLLAMA IF NOT ON THIS DRIVE (first time only, ~1-2 GB) ──
if [ ! -f "ollama/linux/ollama" ]; then
  echo "  Downloading AI engine (Ollama) — this is large and only happens once..."
  mkdir -p ollama/linux
  curl -L -o /tmp/ollama-linux.tar.zst "https://ollama.com/download/ollama-linux-${OARCH}.tar.zst"
  mkdir -p /tmp/ollama-extract
  tar --zstd -xf /tmp/ollama-linux.tar.zst -C /tmp/ollama-extract
  mv /tmp/ollama-extract/bin/ollama ollama/linux/ollama
  if [ -d /tmp/ollama-extract/lib ]; then
    cp -rL /tmp/ollama-extract/lib ollama/linux/ 2>/dev/null
  fi
  rm -rf /tmp/ollama-linux.tar.zst /tmp/ollama-extract
  if [ ! -f "ollama/linux/ollama" ]; then
    echo "  Could not download Ollama. Check your internet connection and try again."
    read -p "  Press Enter to close..."
    exit 1
  fi
  echo "  AI engine ready."
fi

# ── GET WHISPER IF NOT ON THIS DRIVE (first time only) ──
if [ ! -f "whisper/linux/whisper-server" ]; then
  echo "  Downloading voice engine (Whisper) — first time only..."
  mkdir -p whisper/linux
  curl -L -o whisper/linux/whisper-server "https://github.com/thetitangauntletsteam/tannis-releases/releases/download/v1.0.7/whisper-server-linux-x64"
  if [ ! -s "whisper/linux/whisper-server" ]; then
    echo "  Could not download the voice engine. TANNIS will still start, but voice may not work."
    rm -f whisper/linux/whisper-server
  fi
fi

# ── FIND A WORKING APP RUNTIME (self-healing) ──
DRIVE_DIR="$(pwd)"

# Prefer the runtime on the drive if it exists AND actually runs
chmod +x "$DRIVE_DIR/app/node_modules_linux/electron/dist/electron" 2>/dev/null
if [ -f "$DRIVE_DIR/app/node_modules_linux/electron/dist/electron" ] && "$DRIVE_DIR/app/node_modules_linux/electron/dist/electron" --version >/dev/null 2>&1; then
  NM="$DRIVE_DIR/app/node_modules_linux"
else
  # Otherwise use a runtime stored on this computer, building it if needed
  NM="$HOME/.tannis/node_modules_linux"
  chmod +x "$NM/electron/dist/electron" 2>/dev/null
  if ! "$NM/electron/dist/electron" --version >/dev/null 2>&1; then
    echo "  Setting up TANNIS on this computer — first time only, this takes a few minutes..."
    rm -rf "$NM"
    mkdir -p "$HOME/.tannis"
    cp -r "$DRIVE_DIR/app/node_modules_win" "$NM"

    VER=$(grep -m1 '"version"' "$NM/electron/package.json" | cut -d'"' -f4)
    [ -z "$VER" ] && VER="36.9.5"

    echo "  Downloading Electron for Linux..."
    rm -rf "$NM/electron/dist"
    mkdir -p "$NM/electron/dist"
    curl -L -o /tmp/electron-linux.zip "https://github.com/electron/electron/releases/download/v${VER}/electron-v${VER}-linux-${EARCH}.zip"
    unzip -q -o /tmp/electron-linux.zip -d "$NM/electron/dist"
    rm -f /tmp/electron-linux.zip
    printf "electron" > "$NM/electron/path.txt"
    chmod +x "$NM/electron/dist/electron" 2>/dev/null
    if ! "$NM/electron/dist/electron" --version >/dev/null 2>&1; then
      echo "  Could not set up the app engine. Check your internet connection and try again."
      read -p "  Press Enter to close..."
      exit 1
    fi
    echo "  Setup complete."
  fi
  # Quietly sweep away broken leftovers from older setups on the drive
  rm -rf "$DRIVE_DIR/app/node_modules_linux" 2>/dev/null
fi

# ── FIX PERMISSIONS ──
chmod +x "ollama/linux/ollama" 2>/dev/null
chmod +x "whisper/linux/whisper-server" 2>/dev/null
chmod +x "$NM/electron/dist/chrome-sandbox" 2>/dev/null

# ── COPY MODELS (first time only) ──
mkdir -p "$HOME/.ollama/models/blobs"
mkdir -p "$HOME/.ollama/models/manifests/registry.ollama.ai/library"

if [ ! -d "$HOME/.ollama/models/manifests/registry.ollama.ai/library/llama3.2" ]; then
  echo "  Copying Llama 3.2 — first time only..."
  mkdir -p "$HOME/.ollama/models/manifests/registry.ollama.ai/library/llama3.2"
  cp -n ./models/manifests/registry.ollama.ai/library/llama3.2/* "$HOME/.ollama/models/manifests/registry.ollama.ai/library/llama3.2/" 2>/dev/null
fi

if [ ! -d "$HOME/.ollama/models/manifests/registry.ollama.ai/library/qwen2.5-coder" ]; then
  echo "  Copying Qwen 2.5 Coder — first time only..."
  mkdir -p "$HOME/.ollama/models/manifests/registry.ollama.ai/library/qwen2.5-coder"
  cp -n ./models/manifests/registry.ollama.ai/library/qwen2.5-coder/* "$HOME/.ollama/models/manifests/registry.ollama.ai/library/qwen2.5-coder/" 2>/dev/null
fi

if [ ! -d "$HOME/.ollama/models/manifests/registry.ollama.ai/library/llama3.1" ]; then
  echo "  Copying Llama 3.1 — first time only..."
  mkdir -p "$HOME/.ollama/models/manifests/registry.ollama.ai/library/llama3.1"
  cp -n ./models/manifests/registry.ollama.ai/library/llama3.1/* "$HOME/.ollama/models/manifests/registry.ollama.ai/library/llama3.1/" 2>/dev/null
fi

LOCAL_COUNT=$(ls "$HOME/.ollama/models/blobs/" 2>/dev/null | wc -l | tr -d ' ')
USB_COUNT=$(ls ./models/blobs/ 2>/dev/null | wc -l | tr -d ' ')
if [ "$LOCAL_COUNT" -lt "$USB_COUNT" ]; then
  NEEDED_KB=$(du -sk ./models/blobs 2>/dev/null | cut -f1)
  AVAIL_KB=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2{print $4}')
  if [ -n "$NEEDED_KB" ] && [ -n "$AVAIL_KB" ] && [ "$AVAIL_KB" -gt "$NEEDED_KB" ]; then
    echo "  Copying model data — first time only..."
    rsync -a --ignore-existing ./models/blobs/ "$HOME/.ollama/models/blobs/" 2>/dev/null || cp -rn ./models/blobs/. "$HOME/.ollama/models/blobs/" 2>/dev/null
  else
    echo "  Not enough disk space to copy models — TANNIS will run them directly from the drive."
  fi
fi

# ── START OLLAMA ──
echo "  Starting AI engine..."
OLLAMA_MODELS="$(pwd)/models" "./ollama/linux/ollama" serve &
sleep 6

# ── START WHISPER ──
if [ -f "whisper/linux/whisper-server" ]; then
  echo "  Starting voice engine..."
  "./whisper/linux/whisper-server" --port 8178 --model "./whisper/mac/models/ggml-base.en.bin" &
  sleep 2
fi

# ── LAUNCH TANNIS ──
echo "  Launching TANNIS..."
cd app
"$NM/electron/dist/electron" . --no-sandbox
