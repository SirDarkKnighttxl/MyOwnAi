#!/bin/bash
# ============================================================
#  TANNIS launcher for Mac
#  Does the same job as launch.bat does on Windows:
#   - first time on a computer, asks: download the newest AI engine
#     and models from the internet (Y), or use the ones on the drive (N)
#   - tells you if you are offline, and uses the drive if so
#   - checks the AI files and the voice model for damage
#   - offers to save new downloads back to the drive
#   - starts the AI engine (retries in safe mode if it hangs)
#   - starts the voice engine and opens TANNIS
#  When TANNIS closes, the AI engine and voice engine are stopped too,
#  so the drive can be unplugged safely.
# ============================================================

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1
export COPYFILE_DISABLE=1   # stops the Mac from making "._" junk files on the drive

echo ""
echo "  Initializing TANNIS..."
echo ""

# ================= SETTINGS =================
# Raise SETUP_VER to make every Mac see the first-time question one more time
SETUP_VER=3
MODELS="llama3.2:1b llama3.2:3b qwen2.5-coder:7b llama3.1:8b"
# ============================================

TDATA="$HOME/Library/Application Support/TANNIS"
SETUP_MARKER="$TDATA/setup_done_$SETUP_VER.txt"
SAFE_MARKER="$TDATA/safe_mode.txt"
ENGINE_DIR="$TDATA/engine"
DRIVE_ENGINE="$HERE/ollama/mac/engine"
DRIVE_OLLAMA="$HERE/ollama/mac/ollama"
DRIVEMODELS="$HERE/models"
PCMODELS="$HOME/.ollama/models"
WHISPER_MODEL="$HERE/whisper/mac/models/ggml-base.en.bin"
WHISPER_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"

MODE="normal"
ASKAGAIN=""
NEWENGINE=""
DLFAILED=""
FOUNDBAD=""
DIDPULL=""
PULLFAILED=""
OFFLINE=""
OLLAMA_EXE=""
OLLAMA_PID=""
WHISPER_PID=""

mkdir -p "$TDATA" "$PCMODELS/blobs" "$PCMODELS/manifests"

# ================= HELPERS =================

pause() {
  if [ -t 0 ]; then read -r -p "  Press Enter to close..." _; fi
}

# Stop the AI engine and voice engine when this script ends (TANNIS closed, window closed, Ctrl+C)
cleanup() {
  if [ -n "$WHISPER_PID" ]; then kill "$WHISPER_PID" 2>/dev/null; fi
  if [ -n "$OLLAMA_PID" ]; then kill "$OLLAMA_PID" 2>/dev/null; fi
}
trap cleanup EXIT
trap 'exit 1' INT TERM HUP

is_online() {
  OFFLINE=""
  curl -s -o /dev/null -m 8 https://ollama.com || OFFLINE=1
}

file_size() {
  stat -f %z "$1" 2>/dev/null || echo -1
}

size_gb() {
  awk -v b="$1" 'BEGIN { printf "%.1f", b / 1073741824 }'
}

# Lists the files a model needs, written the way they are named in the blobs folder
digests_of() {
  grep -o 'sha256:[0-9a-f]\{64\}' "$1" 2>/dev/null | sed 's/:/-/' | sort -u
}

# $1 = models folder, $2 = model like llama3.2:1b
manifest_path() {
  echo "$1/manifests/registry.ollama.ai/library/${2%%:*}/${2#*:}"
}

# Copies to a .tmp file first so a half-finished copy never looks finished
safe_copy() {
  rm -f "$2.tmp"
  if cp -X "$1" "$2.tmp" 2>/dev/null && mv -f "$2.tmp" "$2"; then return 0; fi
  rm -f "$2.tmp"
  return 1
}

# ---------- first-time question ----------
ask_mode() {
  is_online
  echo "  =================================================="
  echo "   FIRST TIME ON THIS COMPUTER"
  echo ""
  if [ -z "$OFFLINE" ]; then
    echo "   You are ONLINE."
  else
    echo "   You are OFFLINE right now."
    echo "   Downloading needs internet, so for now TANNIS can only"
    echo "   use the AI engine and models already on this drive."
  fi
  echo ""
  echo "   Y = Download the newest AI engine and models from the internet."
  echo "       About 14 GB, can take a while on slow internet."
  echo "   N = Use the AI engine and models already on this TANNIS drive."
  echo "  =================================================="
  echo ""
  while true; do
    printf "  Download the newest from the internet? Press Y or N: "
    if ! read -r -n 1 ans; then
      echo ""
      MODE="drive"; ASKAGAIN=1
      return
    fi
    echo ""
    case "$ans" in
      [Yy])
        if [ -n "$OFFLINE" ]; then
          MODE="drive"; ASKAGAIN=1
          echo ""
          echo "  You are offline, so TANNIS cannot download anything right now."
          echo "  Using the files on this drive instead. You will be asked again"
          echo "  the next time you start TANNIS on this computer."
        else
          MODE="online"
          echo "  Got it. TANNIS will download the newest files."
        fi
        echo ""
        return ;;
      [Nn])
        MODE="drive"
        echo "  OK, using the files on this drive."
        echo ""
        return ;;
    esac
  done
}

# ---------- find / install the AI engine ----------
find_ollama() {
  OLLAMA_EXE=""
  if [ -d "$ENGINE_DIR" ]; then
    local found
    found="$(find "$ENGINE_DIR" -type f -name ollama 2>/dev/null | awk '{ print length, $0 }' | sort -n | head -n 1 | cut -d' ' -f2-)"
    if [ -n "$found" ] && [ -x "$found" ]; then OLLAMA_EXE="$found"; return; fi
  fi
  local c
  for c in "/Applications/Ollama.app/Contents/Resources/ollama" \
           "$HOME/Applications/Ollama.app/Contents/Resources/ollama" \
           "/opt/homebrew/bin/ollama" \
           "/usr/local/bin/ollama"; do
    if [ -x "$c" ]; then OLLAMA_EXE="$c"; return; fi
  done
}

# Moves a downloaded or copied engine folder ($1) into TANNIS's folder on this Mac
install_engine_folder() {
  local tmp="$1" exe
  exe="$(find "$tmp" -type f -name ollama 2>/dev/null | awk '{ print length, $0 }' | sort -n | head -n 1 | cut -d' ' -f2-)"
  if [ -z "$exe" ]; then rm -rf "$tmp"; return 1; fi
  chmod +x "$exe"
  xattr -dr com.apple.quarantine "$tmp" 2>/dev/null
  if ! "$exe" --help >/dev/null 2>&1; then rm -rf "$tmp"; return 1; fi
  rm -rf "$ENGINE_DIR.old"
  if [ -d "$ENGINE_DIR" ]; then mv "$ENGINE_DIR" "$ENGINE_DIR.old"; fi
  if mv "$tmp" "$ENGINE_DIR"; then
    rm -rf "$ENGINE_DIR.old"
    return 0
  fi
  rm -rf "$ENGINE_DIR" "$tmp"
  if [ -d "$ENGINE_DIR.old" ]; then mv "$ENGINE_DIR.old" "$ENGINE_DIR"; fi
  return 1
}

# Downloads the newest Ollama into TANNIS's own folder on this Mac (no password needed)
engine_online() {
  local tmp="$TDATA/engine.new" dl="$TDATA/engine-download"
  rm -rf "$tmp" "$dl"
  mkdir -p "$tmp" "$dl"
  echo "  Downloading the newest AI engine from ollama.com..."
  if curl -L -f --retry 2 --progress-bar -o "$dl/ollama-darwin.tgz" "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz" \
     && tar -xzf "$dl/ollama-darwin.tgz" -C "$tmp" 2>/dev/null; then
    :
  else
    rm -rf "$tmp"; mkdir -p "$tmp"
    if curl -L -f --retry 2 --progress-bar -o "$dl/Ollama-darwin.zip" "https://github.com/ollama/ollama/releases/latest/download/Ollama-darwin.zip" \
       && ditto -x -k "$dl/Ollama-darwin.zip" "$tmp" 2>/dev/null; then
      :
    else
      rm -rf "$tmp" "$dl"
      DLFAILED=1
      echo "  Could not download the newest AI engine."
      echo "  TANNIS will use the one already on this computer or on the drive."
      return
    fi
  fi
  rm -rf "$dl"
  echo "  Installing the AI engine..."
  if install_engine_folder "$tmp"; then
    NEWENGINE=1
    echo "  AI engine updated."
  else
    DLFAILED=1
    echo "  The downloaded AI engine did not work."
    echo "  TANNIS will use the one already on this computer or on the drive."
  fi
}

# Uses the AI engine saved on the drive
engine_from_drive() {
  local tmp="$TDATA/engine.new"
  if [ -d "$DRIVE_ENGINE" ]; then
    echo "  Installing the AI engine from the drive..."
    rm -rf "$tmp"
    if ditto "$DRIVE_ENGINE" "$tmp" 2>/dev/null && install_engine_folder "$tmp"; then
      find_ollama
      if [ -n "$OLLAMA_EXE" ]; then return; fi
    fi
    rm -rf "$tmp"
  fi
  if [ -f "$DRIVE_OLLAMA" ]; then
    chmod +x "$DRIVE_OLLAMA" 2>/dev/null
    xattr -d com.apple.quarantine "$DRIVE_OLLAMA" 2>/dev/null
    OLLAMA_EXE="$DRIVE_OLLAMA"
    echo "  Using the backup AI engine on the drive."
  fi
}

# ---------- start the AI engine ----------
# $1 = log file. Returns 0 when the engine answers.
launch_engine() {
  "$OLLAMA_EXE" serve >"$1" 2>&1 &
  OLLAMA_PID=$!
  local tries=0
  printf "  Starting AI engine, this can take up to a minute "
  until curl -s -f -m 3 -o /dev/null http://127.0.0.1:11434/api/version; do
    tries=$((tries + 1))
    if [ "$tries" -ge 45 ]; then
      echo ""
      return 1
    fi
    printf "."
    sleep 1
  done
  echo ""
  echo "  AI engine is running."
  return 0
}

start_engine() {
  pkill -x Ollama 2>/dev/null
  unset OLLAMA_MODELS
  export OLLAMA_HOST=127.0.0.1:11434
  if [ -f "$SAFE_MARKER" ]; then
    echo "  Safe mode is ON."
    export OLLAMA_FLASH_ATTENTION=0
  fi
  if launch_engine "$TDATA/ollama.log"; then return 0; fi
  if [ -f "$SAFE_MARKER" ]; then return 1; fi
  echo "  The AI engine is not answering. Trying again in safe mode..."
  kill "$OLLAMA_PID" 2>/dev/null
  pkill -f "ollama serve" 2>/dev/null
  sleep 2
  echo "safe" > "$SAFE_MARKER"
  export OLLAMA_FLASH_ATTENTION=0
  launch_engine "$TDATA/ollama-safe.log"
}

# ---------- voice model ----------
check_whisper() {
  local sz
  sz="$(file_size "$WHISPER_MODEL")"
  if [ "$sz" -ge 140000000 ] 2>/dev/null; then return; fi
  echo "  The voice model on the drive is missing or damaged."
  is_online
  if [ -n "$OFFLINE" ]; then
    echo "  You are offline, so voice may not work until you start TANNIS online."
    return
  fi
  echo "  Downloading a fresh voice model, about 150 MB..."
  mkdir -p "$(dirname "$WHISPER_MODEL")"
  rm -f "$WHISPER_MODEL.tmp"
  if curl -L -f --retry 2 --progress-bar -o "$WHISPER_MODEL.tmp" "$WHISPER_URL" && mv -f "$WHISPER_MODEL.tmp" "$WHISPER_MODEL"; then
    echo "  Voice model fixed."
  else
    rm -f "$WHISPER_MODEL.tmp"
    echo "  Could not download the voice model. Voice may not work this time."
  fi
}

# ---------- copy models from the drive to this Mac ----------
copy_drive_to_pc() {
  local f name dest sz
  if [ -d "$DRIVEMODELS/blobs" ]; then
    for f in "$DRIVEMODELS/blobs"/sha256-*; do
      [ -f "$f" ] || continue
      name="$(basename "$f")"
      case "$name" in *.tmp|*.part|*partial*) continue ;; esac
      dest="$PCMODELS/blobs/$name"
      sz="$(file_size "$f")"
      if [ "$sz" != "$(file_size "$dest")" ]; then
        echo "    Copying $(size_gb "$sz") GB of model data, please wait..."
        safe_copy "$f" "$dest"
      fi
    done
  fi
  if [ -d "$DRIVEMODELS/manifests" ]; then
    while IFS= read -r f; do
      dest="$PCMODELS/manifests/${f#"$DRIVEMODELS/manifests/"}"
      if ! cmp -s "$f" "$dest"; then
        mkdir -p "$(dirname "$dest")"
        safe_copy "$f" "$dest"
      fi
    done < <(find "$DRIVEMODELS/manifests" -type f ! -name '._*' ! -name '.DS_Store' ! -name '*.tmp')
  fi
}

# $1 = from models folder, $2 = to models folder, $3 = model like llama3.2:1b
copy_model() {
  local man dst d fail=""
  man="$(manifest_path "$1" "$3")"
  dst="$(manifest_path "$2" "$3")"
  [ -f "$man" ] || return 1
  echo "    Copying $3, please wait..."
  mkdir -p "$2/blobs" "$(dirname "$dst")"
  for d in $(digests_of "$man"); do
    if [ ! -f "$1/blobs/$d" ]; then fail=1; continue; fi
    if [ "$(file_size "$1/blobs/$d")" = "$(file_size "$2/blobs/$d")" ]; then continue; fi
    safe_copy "$1/blobs/$d" "$2/blobs/$d" || fail=1
  done
  if [ -n "$fail" ]; then return 1; fi
  safe_copy "$man" "$dst"
}

# ---------- damage check ----------
blob_ok() {
  [ -f "$1" ] && [ "$(shasum -a 256 "$1" 2>/dev/null | awk '{ print $1 }')" = "$2" ]
}

# $1 = file to check   $2 = its name   $3 = backup copy to fix it from (optional)
check_blob() {
  local want="${2#sha256-}"
  if blob_ok "$1" "$want"; then return 0; fi
  if [ -f "$1" ]; then
    echo "    Found a damaged file - fixing it..."
    rm -f "$1"
  fi
  if [ -n "$3" ] && [ -f "$3" ]; then
    if blob_ok "$3" "$want"; then
      if safe_copy "$3" "$1"; then
        echo "    Fixed using the good copy."
        return 0
      fi
    else
      rm -f "$3"
    fi
  fi
  FOUNDBAD=1
}

verify_model() {
  local man d
  man="$(manifest_path "$PCMODELS" "$1")"
  [ -f "$man" ] || man="$(manifest_path "$DRIVEMODELS" "$1")"
  [ -f "$man" ] || return
  echo "    Checking $1..."
  for d in $(digests_of "$man"); do
    check_blob "$PCMODELS/blobs/$d" "$d" "$DRIVEMODELS/blobs/$d"
  done
}

models_from_drive() {
  echo "  Copying the AI models from the drive to this computer."
  echo "  This can take a few minutes. Please do not unplug the drive."
  copy_drive_to_pc
  echo "  Checking the AI files for damage. This can take a few minutes..."
  local m
  for m in $MODELS; do verify_model "$m"; done
  if [ -n "$FOUNDBAD" ]; then
    echo "  Some files could not be fixed from the drive. They will be downloaded."
  else
    echo "  AI files look good."
  fi
}

# ---------- downloads ----------
pull_one() {
  echo "    Downloading $1..."
  if "$OLLAMA_EXE" pull "$1"; then DIDPULL=1; else PULLFAILED=1; fi
}

pull_all() {
  is_online
  if [ -n "$OFFLINE" ]; then PULLFAILED=1; return; fi
  echo ""
  echo "  Downloading the AI models. Please do not unplug the drive."
  local m
  for m in $MODELS; do pull_one "$m"; done
}

check_model() {
  if "$OLLAMA_EXE" show "$1" >/dev/null 2>&1; then return; fi
  echo "  $1 is missing on this computer - fixing it..."
  copy_model "$DRIVEMODELS" "$PCMODELS" "$1"
  if "$OLLAMA_EXE" show "$1" >/dev/null 2>&1; then return; fi
  is_online
  if [ -n "$OFFLINE" ]; then PULLFAILED=1; return; fi
  pull_one "$1"
}

pull_warning() {
  echo ""
  echo "  WARNING: Some AI files could not be downloaded because this computer"
  echo "  is offline or the download failed. TANNIS will use the copies on the"
  echo "  drive where it can. Connect to the internet and start TANNIS again"
  echo "  to finish setting up."
  echo ""
  pause
}

# ---------- save new downloads back to the drive ----------
sync_all() {
  echo "  Saving the AI models to the TANNIS drive..."
  local m bad=""
  for m in $MODELS; do
    copy_model "$PCMODELS" "$DRIVEMODELS" "$m" || bad=1
  done
  if [ -n "$bad" ]; then
    echo "    Some models could not be saved. The drive may be full."
  else
    clean_drive
  fi
}

# Deletes old model files on the drive that no model uses anymore
clean_drive() {
  echo "  Cleaning up old AI files on the TANNIS drive..."
  [ -d "$DRIVEMODELS/manifests" ] || return
  local keep="$TDATA/keep.txt" bad="" f n freed=0 sz list
  : > "$keep"
  while IFS= read -r f; do
    list="$(digests_of "$f")"
    if [ -z "$list" ]; then bad=1; else echo "$list" >> "$keep"; fi
  done < <(find "$DRIVEMODELS/manifests" -type f ! -name '._*' ! -name '.DS_Store' ! -name '*.tmp')
  if [ -n "$bad" ] || [ ! -s "$keep" ]; then
    echo "    Skipped cleanup to keep your files safe."
    rm -f "$keep"
    return
  fi
  for f in "$DRIVEMODELS/blobs"/sha256-*; do
    [ -f "$f" ] || continue
    n="$(basename "$f")"
    if ! grep -qxF "$n" "$keep"; then
      sz="$(file_size "$f")"
      if [ "$sz" -gt 0 ] 2>/dev/null; then freed=$((freed + sz)); fi
      rm -f "$f"
    fi
  done
  rm -f "$keep"
  echo "    Freed $(size_gb "$freed") GB on the TANNIS drive."
}

save_engine() {
  [ -d "$ENGINE_DIR" ] || return
  echo "  Saving the new AI engine to the drive..."
  mkdir -p "$HERE/ollama/mac"
  rm -rf "$DRIVE_ENGINE.tmp"
  if ditto --norsrc --noextattr "$ENGINE_DIR" "$DRIVE_ENGINE.tmp" 2>/dev/null; then
    rm -rf "$DRIVE_ENGINE"
    mv "$DRIVE_ENGINE.tmp" "$DRIVE_ENGINE"
  else
    rm -rf "$DRIVE_ENGINE.tmp"
    echo "    Could not save the AI engine to the drive. It may be full."
  fi
}

ask_save() {
  [ -t 0 ] || return
  echo ""
  echo "  =================================================="
  echo "   TANNIS downloaded new AI files to this computer."
  echo "   Save them to your TANNIS drive too? Then the drive is"
  echo "   up to date for the next computer. This can take a while."
  echo "  =================================================="
  echo ""
  while true; do
    printf "  Save the new files to the drive? Press Y or N: "
    read -r -n 1 ans || return
    echo ""
    case "$ans" in
      [Yy])
        if [ -n "$DIDPULL" ]; then sync_all; fi
        if [ -n "$NEWENGINE" ]; then save_engine; fi
        echo "  Done saving to the drive."
        echo ""
        return ;;
      [Nn])
        echo "  OK, the drive was not changed."
        echo ""
        return ;;
    esac
  done
}

# ================= MAIN =================

# First time on this Mac: ask where to get the AI files from
if [ ! -f "$SETUP_MARKER" ] && [ -t 0 ]; then ask_mode; fi

# Close any running Ollama and voice engine
pkill -x Ollama 2>/dev/null
pkill -f "ollama serve" 2>/dev/null
pkill -x ollama 2>/dev/null
pkill -f "whisper-server" 2>/dev/null
sleep 2

# Use the runtime on the drive
export PATH="$HERE/runtime/mac/bin:$PATH"

# ── FIRST TIME SETUP: Download Electron for Mac if missing ──
if [ ! -f "app/node_modules_mac/electron/dist/TANNIS.app/Contents/MacOS/TANNIS" ]; then
  echo "  Setting up TANNIS for first time..."
  cd app
  npm install 2>/dev/null
  npm approve-scripts electron 2>/dev/null
  npm install 2>/dev/null
  VER=$(node -e "console.log(require('./node_modules/electron/package.json').version)" 2>/dev/null || echo "36.9.5")
  echo "  Downloading Electron for Mac..."
  cd node_modules/electron/dist
  curl -L -o electron-mac.zip "https://github.com/electron/electron/releases/download/v${VER}/electron-v${VER}-darwin-arm64.zip" 2>/dev/null
  unzip -q -o electron-mac.zip 2>/dev/null
  rm -f electron-mac.zip
  cd ../../..
  # Save as node_modules_mac - never touch node_modules_win
  cp -r node_modules node_modules_mac
  rm -rf node_modules
  cd ..
fi

# ── FIX PERMISSIONS ──
chmod +x "ollama/mac/ollama" 2>/dev/null
chmod +x "whisper/mac/whisper-server" 2>/dev/null
xattr -rd com.apple.quarantine "ollama/mac/ollama" 2>/dev/null
xattr -rd com.apple.quarantine "whisper/mac/whisper-server" 2>/dev/null
xattr -rd com.apple.quarantine "app/node_modules_mac/electron/dist/TANNIS.app" 2>/dev/null

# ── AI ENGINE ──
if [ "$MODE" = "online" ]; then engine_online; fi
find_ollama
if [ -z "$OLLAMA_EXE" ]; then engine_from_drive; fi
if [ -z "$OLLAMA_EXE" ]; then
  echo ""
  echo "  Could not find or install the AI engine."
  echo "  Connect to the internet and try again."
  pause
  exit 1
fi

# ── AI MODELS FROM THE DRIVE (first time, when N was picked) ──
if [ "$MODE" = "drive" ]; then models_from_drive; fi

# ── VOICE MODEL ──
check_whisper

# ── START OLLAMA (uses the models on this Mac, same as Windows) ──
if ! start_engine; then
  echo ""
  echo "  The AI engine did not start. Restart the computer and try again."
  echo "  Details are saved in: $TDATA"
  pause
  exit 1
fi

# ── DOWNLOAD OR REPAIR AI MODELS ──
if [ "$MODE" = "online" ] || [ -n "$FOUNDBAD" ]; then pull_all; fi
for m in $MODELS; do check_model "$m"; done

# ── OFFER TO SAVE NEW DOWNLOADS TO THE DRIVE ──
if [ -n "$DIDPULL" ] || [ -n "$NEWENGINE" ]; then ask_save; fi
if [ -n "$PULLFAILED" ]; then pull_warning; fi

# ── REMEMBER THIS MAC IS SET UP ──
if [ "$MODE" != "normal" ] && [ -z "$ASKAGAIN$PULLFAILED$DLFAILED" ]; then
  echo "done" > "$SETUP_MARKER"
fi

# ── START WHISPER ──
echo "  Starting voice engine..."
if [ -f "$HERE/whisper/mac/whisper-server" ]; then
  "$HERE/whisper/mac/whisper-server" --port 8178 --model "$WHISPER_MODEL" >"$TDATA/whisper.log" 2>&1 &
  WHISPER_PID=$!
  sleep 2
fi

# ── LAUNCH TANNIS (directly from node_modules_mac - no swapping) ──
APPBIN="$HERE/app/node_modules_mac/electron/dist/TANNIS.app/Contents/MacOS/TANNIS"
if [ ! -f "$APPBIN" ]; then
  echo ""
  echo "  The TANNIS app files on this drive are missing or damaged."
  echo "  Please contact Titan Gauntlets support."
  pause
  exit 1
fi

echo "  Launching TANNIS..."
printf "TANNIS.app/Contents/MacOS/TANNIS" > "$HERE/app/node_modules_mac/electron/path.txt"
cd "$HERE/app"
"$APPBIN" .
rm -f "$HERE/app/node_modules_mac/electron/path.txt"

echo "  TANNIS closed. Stopping the AI engine and voice engine..."
# cleanup() runs automatically here
