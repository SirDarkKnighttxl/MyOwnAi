#!/bin/bash
# ═══════════════════════════════════════════════════
#   TANNIS DRIVE — PRE-SHIP TEST SCRIPT (MAC)
#   Run this from the root of the drive before shipping
#   Usage: bash tannis_test.sh
# ═══════════════════════════════════════════════════

cd "$(dirname "$0")"
PASS=0
FAIL=0
WARNINGS=0

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}[ PASS ]${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}[ FAIL ]${NC} $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}[ WARN ]${NC} $1"; ((WARNINGS++)); }
section() { echo ""; echo -e "${CYAN}${BOLD}── $1 ──${NC}"; }

echo ""
echo -e "${BOLD}  T.A.N.N.I.S — PRE-SHIP DRIVE TEST${NC}"
echo -e "  ${CYAN}Running on: $(uname -s) $(uname -r)${NC}"
echo -e "  ${CYAN}Drive path: $(pwd)${NC}"
echo ""

# ── LICENSE ──────────────────────────────────────────
section "LICENSE"

if [ -f "license.json" ]; then
  pass "license.json exists"
  KEY=$(python3 -c "import json; d=open('license.json').read(); print(json.loads(d).get('key',''))" 2>/dev/null)
  if [ -z "$KEY" ]; then
    fail "license.json has no key field"
  else
    pass "License key present: $KEY"
    if [[ "$KEY" == TIT-* ]]; then
      pass "License key format looks correct (TIT-...)"
    else
      warn "License key format unexpected — expected TIT-XXXX-XXXX-XXXX-XXXX"
    fi
  fi
else
  fail "license.json MISSING"
fi

# ── APP FILES ─────────────────────────────────────────
section "APP FILES"

[ -f "app/index.html" ]        && pass "app/index.html found"       || fail "app/index.html MISSING"
[ -f "app/main.js" ]           && pass "app/main.js found"          || fail "app/main.js MISSING"
[ -f "app/loading.html" ]      && pass "app/loading.html found"     || fail "app/loading.html MISSING"
[ -f "app/visualizer.html" ]   && pass "app/visualizer.html found"  || fail "app/visualizer.html MISSING"
[ -f "app/package.json" ]      && pass "app/package.json found"     || fail "app/package.json MISSING"
[ -f "app/preload.js" ]        && pass "app/preload.js found"       || fail "app/preload.js MISSING"

if [ -f "app/package.json" ]; then
  VER=$(python3 -c "import json; print(json.load(open('app/package.json')).get('version','unknown'))" 2>/dev/null)
  pass "App version: $VER"
fi

# ── ELECTRON ──────────────────────────────────────────
section "ELECTRON (MAC)"

if [ -f "app/node_modules_mac/electron/dist/TANNIS.app/Contents/MacOS/TANNIS" ]; then
  pass "Electron Mac binary found (TANNIS.app)"
else
  fail "Electron Mac binary MISSING — node_modules_mac not set up"
fi

if [ -d "app/node_modules_win" ]; then
  pass "node_modules_win present (for Windows users)"
else
  warn "node_modules_win not found — Windows users won't be able to run"
fi

# ── OLLAMA ────────────────────────────────────────────
section "OLLAMA"

if [ -f "ollama/mac/ollama" ]; then
  pass "Ollama Mac binary found"
  if [ -x "ollama/mac/ollama" ]; then
    pass "Ollama Mac binary is executable"
  else
    warn "Ollama Mac binary is NOT executable — run: chmod +x ollama/mac/ollama"
  fi
else
  fail "Ollama Mac binary MISSING at ollama/mac/ollama"
fi

if [ -f "ollama/win/ollama.exe" ]; then
  pass "Ollama Windows binary found"
else
  warn "Ollama Windows binary not found at ollama/win/ollama.exe"
fi

# ── WHISPER ───────────────────────────────────────────
section "WHISPER"

if [ -f "whisper/mac/whisper-server" ]; then
  pass "Whisper Mac binary found"
  if [ -x "whisper/mac/whisper-server" ]; then
    pass "Whisper Mac binary is executable"
  else
    warn "Whisper Mac binary is NOT executable — run: chmod +x whisper/mac/whisper-server"
  fi
else
  fail "Whisper Mac binary MISSING at whisper/mac/whisper-server"
fi

if [ -f "whisper/mac/models/ggml-base.en.bin" ]; then
  SIZE=$(du -sh "whisper/mac/models/ggml-base.en.bin" | cut -f1)
  pass "Whisper model found (ggml-base.en.bin) — $SIZE"
else
  fail "Whisper model MISSING at whisper/mac/models/ggml-base.en.bin"
fi

if [ -f "whisper/win/whisper-server.exe" ]; then
  pass "Whisper Windows binary found"
else
  warn "Whisper Windows binary not found at whisper/win/whisper-server.exe"
fi

# ── MODELS ────────────────────────────────────────────
section "AI MODELS"

if [ -d "models/blobs" ]; then
  BLOB_COUNT=$(ls "models/blobs/" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$BLOB_COUNT" -gt 0 ]; then
    pass "Model blobs present — $BLOB_COUNT files"
  else
    fail "models/blobs folder is EMPTY"
  fi
else
  fail "models/blobs folder MISSING"
fi

[ -d "models/manifests/registry.ollama.ai/library/llama3.2" ]      && pass "Llama 3.2 manifest found"      || fail "Llama 3.2 manifest MISSING"
[ -d "models/manifests/registry.ollama.ai/library/qwen2.5-coder" ] && pass "Qwen 2.5 Coder manifest found" || fail "Qwen 2.5 Coder manifest MISSING"
[ -d "models/manifests/registry.ollama.ai/library/llama3.1" ]      && pass "Llama 3.1 manifest found"      || fail "Llama 3.1 manifest MISSING"

# ── CONFIG ────────────────────────────────────────────
section "CONFIG"

if [ -d "config" ]; then
  pass "config folder exists"
else
  warn "config folder not found — will be created on first launch"
fi

# ── LAUNCH SCRIPTS ────────────────────────────────────
section "LAUNCH SCRIPTS"

if [ -f "launch.sh" ]; then
  pass "launch.sh found"
  if [ -x "launch.sh" ]; then
    pass "launch.sh is executable"
  else
    warn "launch.sh is NOT executable — run: chmod +x launch.sh"
  fi
else
  fail "launch.sh MISSING"
fi

[ -f "launch.bat" ] && pass "launch.bat found (for Windows)" || warn "launch.bat not found"

# ── LICENSE SERVER PING ───────────────────────────────
section "LICENSE SERVER CONNECTIVITY"

if curl -s --max-time 5 "https://tannis-server-production.up.railway.app/health" > /dev/null 2>&1; then
  pass "Railway license server is reachable"
else
  warn "Railway license server did not respond — check internet or server status"
fi

# ── DISK SPACE ────────────────────────────────────────
section "DRIVE SIZE"

DRIVE_SIZE=$(df -h . | awk 'NR==2{print $2}')
DRIVE_USED=$(df -h . | awk 'NR==2{print $3}')
DRIVE_FREE=$(df -h . | awk 'NR==2{print $4}')
pass "Drive: $DRIVE_USED used of $DRIVE_SIZE total | $DRIVE_FREE free"

# ── RESULT ────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
if [ "$FAIL" -eq 0 ]; then
  echo -e "  ${GREEN}${BOLD}ALL CHECKS PASSED — DRIVE READY TO SHIP${NC}"
else
  echo -e "  ${RED}${BOLD}$FAIL CHECK(S) FAILED — DO NOT SHIP${NC}"
fi
if [ "$WARNINGS" -gt 0 ]; then
  echo -e "  ${YELLOW}$WARNINGS WARNING(S) — review before shipping${NC}"
fi
echo -e "  ${CYAN}$PASS passed · $FAIL failed · $WARNINGS warnings${NC}"
echo "═══════════════════════════════════════════"
echo ""
