const { app, BrowserWindow, ipcMain, session, dialog } = require('electron')
const Sentry = require('@sentry/electron/main')
Sentry.init({
  dsn: 'https://76b824190eda7d3428b5cdb8743670a7@o4511618309357568.ingest.us.sentry.io/4511618336227328',
  tracesSampleRate: 1.0,
})
app.setName('TANNIS')
const path = require('path')
const os   = require('os')
const fs   = require('fs')
const { spawn } = require('child_process')
const https = require('https')

// ── TANNIS LOGGER ─────────────────────────────────────
const logDir  = path.join(os.homedir(), '.tannis', 'logs')
const logFile = path.join(os.homedir(), '.tannis', 'logs', 'tannis.log')

function log(level, msg) {
  const line = `[${new Date().toISOString()}] [${level}] ${msg}\n`
  process.stdout.write(line)
  try {
    const fs2 = require('fs')
    if (!fs2.existsSync(logDir)) fs2.mkdirSync(logDir, { recursive: true })
    fs2.appendFileSync(logFile, line)
  } catch(e) {}
}

log('INFO', '════════ TANNIS STARTED ════════')
log('INFO', `OS: ${require('os').platform()} ${require('os').release()}`)
log('INFO', `RAM: ${Math.round(require('os').totalmem() / 1073741824)}GB total | ${Math.round(require('os').freemem() / 1073741824)}GB free`)
log('INFO', `CPU: ${require('os').cpus()[0].model}`)
log('INFO', `TANNIS version: ${require('./package.json').version}`)


let ollamaProcess   = null
let whisperProcess  = null
let mainWindow      = null
let vizWindow       = null
let progressWindow  = null

// ── LICENSE ──────────────────────────────────────────
let licenseStatus = { valid: false, plan: 'free', checked: false }
const LICENSE_HOST = 'tannis-server-production.up.railway.app'

// Sends JSON to the TANNIS server and returns its JSON reply (never throws)
function postToServer(apiPath, bodyObj) {
  return new Promise((resolve) => {
    const body = JSON.stringify(bodyObj)
    const req = https.request({
      hostname: LICENSE_HOST,
      path: apiPath,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      timeout: 8000
    }, (res) => {
      let data = ''
      res.on('data', chunk => data += chunk)
      res.on('end', () => {
        try { resolve({ httpStatus: res.statusCode, ...JSON.parse(data) }) }
        catch(e) { resolve({ httpStatus: res.statusCode, error: 'Bad server response' }) }
      })
    })
    req.on('error', () => resolve({ error: 'No internet' }))
    req.on('timeout', () => { req.destroy(); resolve({ error: 'Timeout' }) })
    req.write(body)
    req.end()
  })
}

// The TANNIS drive's own ID (its volume serial number, like "1A2B-3C4D").
// Used to lock the license key to this exact drive.
function getDriveId() {
  try {
    if (process.platform === 'win32') {
      const root = path.parse(path.resolve(__dirname)).root   // e.g. "E:\"
      const letter = root.slice(0, 2)                           // e.g. "E:"
      if (!/^[A-Za-z]:$/.test(letter)) return null
      const out = require('child_process').execFileSync('cmd.exe', ['/c', 'vol', letter], { encoding: 'utf8', windowsHide: true, timeout: 5000 })
      const all = out.match(/[0-9A-F]{4}-[0-9A-F]{4}/gi)       // serial number is on the last line
      return all ? all[all.length - 1].toUpperCase() : null
    }
        const { execFileSync } = require('child_process')
    const here = path.resolve(__dirname)

    if (process.platform === 'linux') {
      // Same "1A2B-3C4D" number Windows shows for FAT/exFAT drives
      let uuid = ''
      try { uuid = execFileSync('findmnt', ['-n', '-o', 'UUID', '--target', here], { encoding: 'utf8', timeout: 5000 }).trim() } catch(e) {}
      if (!uuid) {
        try {
          const dev = execFileSync('findmnt', ['-n', '-o', 'SOURCE', '--target', here], { encoding: 'utf8', timeout: 5000 }).trim()
          if (dev) uuid = execFileSync('lsblk', ['-n', '-o', 'UUID', dev], { encoding: 'utf8', timeout: 5000 }).trim()
        } catch(e) {}
      }
      uuid = uuid.toUpperCase()
      if (/^[0-9A-F]{4}-[0-9A-F]{4}$/.test(uuid)) return uuid
      const clean = uuid.replace(/[^0-9A-F-]/g, '')
      return clean.length >= 8 ? 'LNX:' + clean.slice(0, 64) : null
    }

    if (process.platform === 'darwin') {
      // Macs report a different ID for the same drive, so it is stored separately on the server
      const df = execFileSync('/bin/df', ['-P', here], { encoding: 'utf8', timeout: 5000 }).trim().split('\n')
      const dev = (df[df.length - 1] || '').split(/\s+/)[0]
      if (!dev || !dev.startsWith('/dev/')) return null
      const info = execFileSync('/usr/sbin/diskutil', ['info', dev], { encoding: 'utf8', timeout: 8000 })
      const m = info.match(/Volume UUID:\s+([0-9A-Fa-f-]{36})/) || info.match(/Disk \/ Partition UUID:\s+([0-9A-Fa-f-]{36})/)
      if (!m) log('WARN', 'Mac drive info had no UUID to use as the drive ID')
      return m ? 'MAC:' + m[1].toUpperCase() : null
    }

    return null
  } catch(e) {
    log('WARN', `Could not read drive ID: ${e.message}`)
    return null
  }
}

async function checkLicense() {
  try {
    const licensePath = path.join(__dirname, '..', 'license.json')
    const driveId = getDriveId()
    log('INFO', `Drive ID: ${driveId || 'not available on this system'}`)

    let key = null
    if (fs.existsSync(licensePath)) {
      try { key = JSON.parse(fs.readFileSync(licensePath, 'utf8')).key || null }
      catch(e) { log('WARN', `license.json could not be read: ${e.message}`) }
    }

    // Brand new drive: ask the server for its key. This only ever happens once per drive.
    if (!key) {
      if (!driveId) {
        log('WARN', 'No license.json and no drive ID, cannot register this drive yet')
        licenseStatus = { valid: false, plan: 'free', checked: true, reason: 'No license yet' }
        return licenseStatus
      }
      log('INFO', 'No license on this drive yet, registering it...')
      const reg = await postToServer('/register-drive', { drive_id: driveId })
      if (!reg.key) {
        log('WARN', `Could not register drive: ${reg.error || reg.httpStatus}`)
        licenseStatus = { valid: false, plan: 'free', checked: true, reason: reg.error || 'Could not register drive' }
        return licenseStatus
      }
      key = reg.key
      try {
        fs.writeFileSync(licensePath, JSON.stringify({ key }, null, 2))
        log('INFO', `${reg.existing ? 'Restored' : 'Created'} license key ${key} for this drive`)
      } catch(e) {
        log('ERROR', `Could not save license.json to the drive: ${e.message}`)
      }
    }

    let backerEmail = null
    try { backerEmail = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config', 'config.json'), 'utf8')).backerEmail || null } catch(e) {}

    log('INFO', `Checking license key: ${key}`)
    const result = await postToServer('/validate-license', { key, email: backerEmail, drive_id: driveId })

    licenseStatus = { ...result, checked: true, key }
    log('INFO', `License: valid=${result.valid} plan=${result.plan || 'free'} balance=${result.balance ?? '-'} reason=${result.reason || result.error || 'ok'}`)
    return licenseStatus

  } catch(e) {
    log('ERROR', `License check failed: ${e.message}`)
    licenseStatus = { valid: false, plan: 'free', checked: true, reason: e.message }
    return licenseStatus
  }
}

// ── EXPOSE LICENSE STATUS TO RENDERER ────────────────
ipcMain.handle('get-license', () => licenseStatus)
// Re-checks with the server (used after buying credit so the new balance shows up)
ipcMain.handle('refresh-license', async () => { await checkLicense(); return licenseStatus })

// ── UPDATE CHECKER ───────────────────────────────────
function checkForUpdates() {
  return new Promise((resolve) => {
    const options = {
      hostname: 'api.github.com',
      path: '/repos/thetitangauntletsteam/tannis-releases/releases/latest',
      headers: { 'User-Agent': 'TANNIS-App' }
    }

    https.get(options, (res) => {
      let data = ''
      res.on('data', chunk => data += chunk)
      res.on('end', async () => {
        try {
          const release = JSON.parse(data)
          const latestVersion = release.tag_name.replace('v', '')
          const currentVersion = require('./package.json').version

          console.log(`[TANNIS] Current: ${currentVersion} | Latest: ${latestVersion}`)

          if (latestVersion === currentVersion) {
            console.log('[TANNIS] Already up to date.')
            resolve(false)
            return
          }

          const result = await dialog.showMessageBox({
            type: 'question',
            title: 'TANNIS Update Available',
            message: `A new version of TANNIS (v${latestVersion}) is available.\n\nWould you like to install it now?\n\nTANNIS will restart after the update.`,
            buttons: ['Install Update', 'Skip For Now'],
            defaultId: 0,
            cancelId: 1
          })

          if (result.response === 1) {
            resolve(false)
            return
          }

          // Find zip asset in release
          const zipAsset = release.assets.find(a => a.name.endsWith('.zip'))
          if (!zipAsset) {
            console.log('[TANNIS] No zip asset found in release.')
            resolve(false)
            return
          }

          // Show progress window
          progressWindow = new BrowserWindow({
  width: 420,
  height: 200,
  frame: false,
  alwaysOnTop: true,
  resizable: false,
  movable: true,
  backgroundColor: '#0a0a12',
  webPreferences: { nodeIntegration: true, contextIsolation: false }
})

          progressWindow.loadURL(`data:text/html,<!DOCTYPE html>
            <html>
            <body style="background:%230a0a12;color:%2300d4aa;font-family:'Courier New',monospace;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;margin:0;gap:16px;user-select:none;-webkit-app-region:drag">
  <style>button, input { -webkit-app-region: no-drag; }</style>
              <div style="font-size:13px;letter-spacing:6px">T.A.N.N.I.S</div>
              <div style="font-size:10px;letter-spacing:3px;color:%23ffffff88" id="status">DOWNLOADING UPDATE...</div>
              <div style="width:320px;height:4px;background:%23ffffff11;border-radius:2px;overflow:hidden">
                <div id="bar" style="width:0%;height:100%;background:%2300d4aa;border-radius:2px;transition:width 0.2s ease"></div>
              </div>
              <div style="font-size:10px;color:%23ffffff44;letter-spacing:2px" id="pct">0%</div>
              <div style="font-size:9px;color:%23ffffff22;letter-spacing:1px">DO NOT CLOSE TANNIS</div>
            </body>
            </html>`)

          const zipPath = path.join(__dirname, 'update.zip')
          const file = fs.createWriteStream(zipPath)

          // Follow redirects and track progress
          function downloadFile(url, dest, callback) {
            https.get(url, (response) => {
              if (response.statusCode === 302 || response.statusCode === 301) {
                downloadFile(response.headers.location, dest, callback)
                return
              }

              const totalSize = parseInt(response.headers['content-length'], 10)
              let downloaded = 0

              response.on('data', (chunk) => {
                downloaded += chunk.length
                if (totalSize && progressWindow && !progressWindow.isDestroyed()) {
                  const pct = Math.round((downloaded / totalSize) * 100)
                  progressWindow.webContents.executeJavaScript(`
                    document.getElementById('bar').style.width = '${pct}%';
                    document.getElementById('pct').textContent = '${pct}%';
                    document.getElementById('status').textContent = 'DOWNLOADING UPDATE... ${pct}%';
                  `).catch(() => {})
                }
              })

              response.pipe(dest)
              dest.on('finish', () => dest.close(callback))

            }).on('error', (err) => {
              fs.unlink(dest.path, () => {})
              console.error('[TANNIS] Download error:', err.message)
              if (progressWindow && !progressWindow.isDestroyed()) progressWindow.close()
              resolve(false)
            })
          }

          downloadFile(zipAsset.browser_download_url, file, () => {
            try {
              // Update progress to show extracting
              if (progressWindow && !progressWindow.isDestroyed()) {
                progressWindow.webContents.executeJavaScript(`
                  document.getElementById('status').textContent = 'INSTALLING UPDATE...';
                  document.getElementById('bar').style.width = '100%';
                  document.getElementById('pct').textContent = 'DONE';
                `).catch(() => {})
              }

              const AdmZip = require('adm-zip')
              const zip = new AdmZip(zipPath)
              zip.extractAllTo(__dirname, true)
              fs.unlinkSync(zipPath)

              console.log('[TANNIS] Update installed, restarting...')

              if (progressWindow && !progressWindow.isDestroyed()) progressWindow.close()

              app.relaunch()
              app.exit(0)

            } catch(e) {
              console.error('[TANNIS] Extract failed:', e.message)
              if (progressWindow && !progressWindow.isDestroyed()) progressWindow.close()
              resolve(false)
            }
          })

        } catch(e) {
          console.log('[TANNIS] Update check failed:', e.message)
          resolve(false)
        }
      })
    }).on('error', (e) => {
      console.log('[TANNIS] No internet or update server unreachable:', e.message)
      resolve(false)
    })
  })
}

// ── OLLAMA ───────────────────────────────────────────
// Is an AI engine already answering? (the launcher normally starts one before the app opens)
function isOllamaUp() {
  return new Promise(resolve => {
    const req = require('http').get({ hostname: '127.0.0.1', port: 11434, path: '/api/version', timeout: 2000 }, res => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.on('timeout', () => { req.destroy(); resolve(false) })
  })
}

async function startOllama() {
  // Never start a second copy. The launcher's engine is the up-to-date one; starting the
  // old copy on the drive next to it is what caused the version crashes before.
  if (await isOllamaUp()) {
    log('INFO', 'Ollama already running (started by launcher), not starting the drive copy')
    return
  }
  const platform = os.platform()
const ollamaPath = platform === 'win32'
  ? path.join(__dirname, '..', 'ollama', 'win', 'ollama.exe')
  : platform === 'darwin'
  ? path.join(__dirname, '..', 'ollama', 'mac', 'ollama')
  : path.join(__dirname, '..', 'ollama', 'linux', 'ollama')
  const modelDir = process.platform === 'darwin'
    ? path.join(__dirname, '..', '..', 'models')
    : path.join(__dirname, '..', 'models')

  log('INFO', `Starting Ollama from: ${ollamaPath}`)
ollamaProcess = spawn(ollamaPath, ['serve'], {
    env: { ...process.env, OLLAMA_MODELS: modelDir },
    detached: false
  })
  ollamaProcess.on('error', (err) => { log('ERROR', `Ollama failed to start: ${err.message}`); ollamaProcess = null })
}

// ── WHISPER ──────────────────────────────────────────
function startWhisperServer() {
  const platform = os.platform()

  let binaryPath
  if (platform === 'win32')       binaryPath = path.join(__dirname, '..', 'whisper', 'win',   'whisper-server.exe')
  else if (platform === 'darwin') binaryPath = path.join(__dirname, '..', 'whisper', 'mac',   'whisper-server')
  else                            binaryPath = path.join(__dirname, '..', 'whisper', 'linux', 'whisper-server')

  const modelPath = path.join(__dirname, '..', 'whisper', 'mac', 'models', 'ggml-base.en.bin')

  log('INFO', `Starting Whisper from: ${binaryPath}`)
console.log('[TANNIS] whisper-server starting on port 8178...')

  whisperProcess = spawn(binaryPath, [
    '--model',    modelPath,
    '--host',     '127.0.0.1',
    '--port',     '8178',
    '--language', 'en',
    '--threads',  '4'
  ], { detached: false })

  whisperProcess.stdout.on('data', (data) => console.log('[whisper]', data.toString().trim()))
  whisperProcess.stderr.on('data', (data) => console.log('[whisper]', data.toString().trim()))
  whisperProcess.on('error', (err) => { log('ERROR', `Whisper failed to start: ${err.message}`); whisperProcess = null })
  whisperProcess.on('exit', (code) => { console.log(`[TANNIS] whisper-server exited ${code}`); whisperProcess = null })
}

// ── MAIN WINDOW ──────────────────────────────────────
function createWindow() {
  console.log(' Launching TANNIS...')

  mainWindow = new BrowserWindow({
    icon: process.platform === 'darwin' ? path.join(__dirname, 'tannis.icns') : path.join(__dirname, 'tannis.ico'),
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    frame: false,
    backgroundColor: '#0a0a12',
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
      preload: path.join(__dirname, 'preload.js')
    }
  })

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowed = ['media', 'mediaKeySystem', 'geolocation', 'notifications']
    callback(allowed.includes(permission))
  })

  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    if (permission === 'media') return true
    return false
  })

  mainWindow.loadFile('index.html')

  mainWindow.on('closed', () => {
    if (vizWindow && !vizWindow.isDestroyed()) vizWindow.close()
    mainWindow = null
  })
}

// ── APP READY ────────────────────────────────────────
app.whenReady().then(async () => {
  app.setName('TANNIS')
  if (process.platform === 'darwin') {
    app.dock.setIcon(path.join(__dirname, 'tannis_icon_new.png'))
  }

const FONT_MAP = {
    'courier':   "'Courier New', monospace",
    'jetbrains': "'JetBrains Mono', monospace",
    'sharetech': "'Share Tech Mono', monospace",
    'ibmplex':   "'IBM Plex Mono', monospace",
    'firacode':  "'Fira Code', monospace"
  }

  let cfg = {}
  try { cfg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config', 'config.json'), 'utf8')) } catch(e) {}

  const presets = JSON.parse(cfg.userPresets || "[]")
  const activePreset = presets.find(p => p.id === cfg.themeId)
  const theme = activePreset || cfg.themeCustom || {}
  const accent   = encodeURIComponent(theme.accent   || '#00d4aa')
  const bg       = encodeURIComponent(theme.bg       || '#0a0a12')
  const surface  = encodeURIComponent(theme.surface  || '#0d0d1a')
  const text     = encodeURIComponent(theme.text     || '#e0e0e0')
  const font     = encodeURIComponent(FONT_MAP[cfg.fontId] || "'Courier New', monospace")
  const fontSize = cfg.fontSize || 13

  let loadingWindow = new BrowserWindow({
    width: 480, height: 560,
    frame: false,
    backgroundColor: theme.bg || '#0a0a12',
    webPreferences: { nodeIntegration: true, contextIsolation: false }
  })
  loadingWindow.loadFile(path.join(__dirname, 'loading.html'), {
    query: { accent, bg, surface, text, font, fontSize }
  })

  function sendProgress(pct, label, dot) {
    if (loadingWindow && !loadingWindow.isDestroyed()) {
      loadingWindow.webContents.send('loading-progress', { pct, label, dot })
    }
  }

  loadingWindow.webContents.on('did-finish-load', () => {
    setTimeout(async () => {

      sendProgress(10, 'Checking license', 0)
      await checkLicense()
      await new Promise(r => setTimeout(r, 800))

      sendProgress(20, 'Starting Ollama',  1)
      await startOllama()
      await new Promise(r => setTimeout(r, 2000))

      sendProgress(40, 'Loading models',   2)
      await ensureDerivedModels(null)
      await new Promise(r => setTimeout(r, 1500))

      sendProgress(60, 'Starting Whisper', 3)
      startWhisperServer()
      await new Promise(r => setTimeout(r, 1500))

      sendProgress(80, 'Configuring audio', 3)
      await checkForUpdates()
      await new Promise(r => setTimeout(r, 600))

      sendProgress(95, 'Almost ready',     4)
      await new Promise(r => setTimeout(r, 800))

      sendProgress(100, 'Launching TANNIS', 4)
      await new Promise(r => setTimeout(r, 700))

      if (loadingWindow && !loadingWindow.isDestroyed()) loadingWindow.close()
      createWindow()

    }, 300)
  })
})

app.on('before-quit', () => {
  if (ollamaProcess)  ollamaProcess.kill()
  if (whisperProcess) whisperProcess.kill()
})

// ── WINDOW CONTROLS ──────────────────────────────────
ipcMain.on('minimize', (e) => BrowserWindow.fromWebContents(e.sender).minimize())
ipcMain.on('maximize', (e) => {
  const win = BrowserWindow.fromWebContents(e.sender)
  win.isMaximized() ? win.unmaximize() : win.maximize()
})
ipcMain.on('close', () => app.quit())

// ── VISUALIZER ───────────────────────────────────────
function createVizWindow() {
  if (vizWindow && !vizWindow.isDestroyed()) { vizWindow.focus(); return }

  vizWindow = new BrowserWindow({
    width: 320, height: 380, minWidth: 240, minHeight: 280,
    frame: false, transparent: true, backgroundColor: '#00000000',
    alwaysOnTop: true, resizable: true, skipTaskbar: false,
    title: 'TANNIS Visualizer',
    webPreferences: { nodeIntegration: true, contextIsolation: false }
  })

  vizWindow.loadFile('visualizer.html')

  vizWindow.on('closed', () => {
    vizWindow = null
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('viz-window-closed')
  })
}

ipcMain.on('open-viz-window', () => createVizWindow())
ipcMain.on('close-viz-window', () => { if (vizWindow && !vizWindow.isDestroyed()) vizWindow.close() })
ipcMain.on('viz-state', (e, data) => { if (vizWindow && !vizWindow.isDestroyed()) vizWindow.webContents.send('viz-state', data) })
ipcMain.on('viz-mic-toggle', () => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('viz-mic-toggle') })
ipcMain.on('viz-mic-state', (e, data) => { if (vizWindow && !vizWindow.isDestroyed()) vizWindow.webContents.send('viz-mic-state', data) })
ipcMain.on('viz-stop-speaking', () => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('viz-stop-speaking') })
ipcMain.on('viz-loop-toggle', () => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('viz-loop-toggle') })
ipcMain.on('viz-loop-state', (e, data) => { if (vizWindow && !vizWindow.isDestroyed()) vizWindow.webContents.send('viz-loop-state', data) })
ipcMain.on('viz-send-message', (e, data) => { if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('viz-send-message', data) })
ipcMain.on('viz-response', (e, data) => { if (vizWindow && !vizWindow.isDestroyed()) vizWindow.webContents.send('viz-response', data) })
ipcMain.on('tannis-log', (e, { level, msg }) => log(level, msg))

// ── MODEL DOWNLOADS (Bonsai etc.) ────────────────────
const http = require('http')

function getModelDirs() {
  // Use the models folder next to the app folder when it exists (Windows, Linux, and Mac drives);
  // fall back to the old two-levels-up Mac path only if that folder is missing.
  const near = path.join(__dirname, '..', 'models')
  const drive = fs.existsSync(near) ? near : path.join(__dirname, '..', '..', 'models')
  const computer = path.join(os.homedir(), '.ollama', 'models')
  return { drive, computer, sameDir: path.resolve(drive) === path.resolve(computer) }
}

function freeGB(dir) {
  try {
    let p = dir
    while (!fs.existsSync(p)) p = path.dirname(p)
    const s = fs.statfsSync(p)
    return Math.round((s.bavail * s.bsize) / 1073741824 * 10) / 10
  } catch(e) { return -1 }
}

function ollamaGET(apiPath) {
  return new Promise((resolve, reject) => {
    http.get({ hostname: '127.0.0.1', port: 11434, path: apiPath }, res => {
      let out = ''
      res.on('data', c => out += c)
      res.on('end', () => { try { resolve(JSON.parse(out)) } catch(e) { reject(new Error('Bad Ollama response')) } })
    }).on('error', reject)
  })
}

// "MichelRosselli/bonsai-27b" -> manifests/registry.ollama.ai/MichelRosselli/bonsai-27b/latest
function manifestRelPath(model) {
  let name = model, tag = 'latest'
  const lastSlash = name.lastIndexOf('/')
  const colon = name.lastIndexOf(':')
  if (colon > lastSlash) { tag = name.slice(colon + 1); name = name.slice(0, colon) }
  const parts = name.split('/')
  let registry = 'registry.ollama.ai'
  if (parts.length > 1 && parts[0].includes('.')) registry = parts.shift()
  if (parts.length === 1) parts.unshift('library')
  return path.join('manifests', registry, ...parts, tag)
}

// After a pull, copy the model so BOTH the computer and the TANNIS drive have it
async function syncModelBetweenDirs(model, send) {
  const { drive, computer, sameDir } = getModelDirs()
  if (sameDir) return
  const rel = manifestRelPath(model)
  let src, dst
  if (fs.existsSync(path.join(computer, rel)))    { src = computer; dst = drive }
  else if (fs.existsSync(path.join(drive, rel)))  { src = drive;    dst = computer }
  else throw new Error('Downloaded model manifest not found')
  const manifest = JSON.parse(fs.readFileSync(path.join(src, rel), 'utf8'))
  const digests = [manifest.config?.digest, ...(manifest.layers || []).map(l => l.digest)].filter(Boolean)
  fs.mkdirSync(path.join(dst, 'blobs'), { recursive: true })
  let i = 0
  for (const d of digests) {
    i++
    const file = d.replace(':', '-')
    const from = path.join(src, 'blobs', file), to = path.join(dst, 'blobs', file)
    if (fs.existsSync(to) && fs.statSync(to).size === fs.statSync(from).size) continue
    send({ status: `Copying model files (${i}/${digests.length})...`, pct: Math.round(i / digests.length * 100) })
    await fs.promises.copyFile(from, to + '.part')
    await fs.promises.rename(to + '.part', to)
  }
  fs.mkdirSync(path.dirname(path.join(dst, rel)), { recursive: true })
  fs.copyFileSync(path.join(src, rel), path.join(dst, rel))
  log('INFO', `Model ${model} synced: ${src} -> ${dst}`)
}

// ── DERIVED MODELS ───────────────────────────────────
// Some community model uploads ship a chat template that prefills an empty
// "<think></think>" block on every turn. That silently disables reasoning:
// Ollama accepts think:true, the model has nowhere to reason, and the thinking
// field comes back empty. We rebuild those models locally with a corrected
// template. No re-download — the new model reuses the blobs already on disk.

const QWEN3_THINK_TEMPLATE = `{{- if or .System .Tools }}<|im_start|>system
{{- if .System }}
{{ .System }}
{{- end }}
{{- if .Tools }}

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{{- range .Tools }}
{"type": "function", "function": {{ .Function }}}
{{- end }}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>
{{- end }}<|im_end|>
{{ end }}
{{- range $i, $_ := .Messages }}
{{- $last := eq (len (slice $.Messages $i)) 1 }}
{{- if eq .Role "user" }}<|im_start|>user
{{ .Content }}<|im_end|>
{{ else if eq .Role "assistant" }}<|im_start|>assistant
{{ if .Thinking }}<think>{{ .Thinking }}</think>
{{ end }}{{ if .Content }}{{ .Content }}
{{- else if .ToolCalls }}<tool_call>
{{ range .ToolCalls }}{"name": "{{ .Function.Name }}", "arguments": {{ .Function.Arguments }}}
{{ end }}</tool_call>
{{- end }}{{ if not $last }}<|im_end|>
{{ end }}
{{- else if eq .Role "tool" }}<|im_start|>user
<tool_response>
{{ .Content }}
</tool_response><|im_end|>
{{ end }}
{{- if and (ne .Role "assistant") $last }}<|im_start|>assistant
{{ end }}
{{- end }}`

// base model on the drive  ->  name the app actually chats with
const DERIVED_MODELS = [
  { from: 'digitsflow/bonsai-8b', name: 'bonsai-8b-think', template: QWEN3_THINK_TEMPLATE }
]

function ollamaPOST(apiPath, bodyObj) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(bodyObj)
    const req = http.request({ hostname: '127.0.0.1', port: 11434, path: apiPath, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, res => {
      let out = ''
      res.on('data', c => out += c)
      res.on('end', () => {
        // /api/create may answer with one JSON object or a stream of them — take the last
        let parsed = null
        for (const line of out.split('\n')) {
          if (!line.trim()) continue
          try { parsed = JSON.parse(line) } catch(_) {}
        }
        if (res.statusCode >= 400 || (parsed && parsed.error)) {
          return reject(new Error((parsed && parsed.error) || `HTTP ${res.statusCode}`))
        }
        resolve(parsed || {})
      })
    })
    req.on('error', reject)
    req.write(body); req.end()
  })
}

async function createDerivedModel(d) {
  // Newer Ollama takes structured fields; older builds only understand a raw Modelfile.
  try {
    await ollamaPOST('/api/create', { model: d.name, from: d.from, template: d.template, stream: false })
  } catch(err) {
    log('WARN', `Structured create failed for ${d.name} (${err.message}) — trying Modelfile form`)
    const modelfile = `FROM ${d.from}\nTEMPLATE """${d.template}"""\n`
    await ollamaPOST('/api/create', { name: d.name, modelfile, stream: false })
  }
  log('INFO', `Derived model created: ${d.name} (from ${d.from})`)
}

// Build any derived model whose base is installed but whose derived copy is missing.
// Safe to call repeatedly — it skips anything that already exists.
async function ensureDerivedModels(send) {
  let tags
  try {
    tags = await ollamaGET('/api/tags')
  } catch(err) {
    log('WARN', `Could not list models to check derived builds: ${err.message}`)
    return
  }
  const have = (tags.models || []).map(m => m.name)
  const has = (n) => have.some(x => x === n || x === n + ':latest')

  for (const d of DERIVED_MODELS) {
    if (has(d.name)) continue
    if (!has(d.from)) continue   // base not installed yet — nothing to derive from
    try {
      if (send) send({ status: 'Preparing thinking mode...', pct: null })
      await createDerivedModel(d)
      try { await syncModelBetweenDirs(d.name, send || (() => {})) } catch(e) {
        log('WARN', `Derived model ${d.name} built but not copied to the other drive: ${e.message}`)
      }
    } catch(err) {
      log('ERROR', `Could not build derived model ${d.name}: ${err.message}`)
    }
  }
}

ipcMain.handle('model-check', async (e, { model }) => {
  const { drive, computer, sameDir } = getModelDirs()
  let installed = false
  try {
    const tags = await ollamaGET('/api/tags')
    installed = (tags.models || []).some(m => m.name === model || m.name === model + ':latest')
  } catch(err) {}
  const onDrive = !sameDir && fs.existsSync(path.join(drive, manifestRelPath(model)))
  const totalRamGB = Math.round(os.totalmem() / 1073741824)
  return { installed, onDrive, sameDir, totalRamGB, freeComputerGB: freeGB(computer), freeDriveGB: freeGB(drive) }
})

ipcMain.handle('model-pull', async (e, { model }) => {
  const send = (d) => { if (!e.sender.isDestroyed()) e.sender.send('model-pull-progress', d) }
  try {
    const { drive, sameDir } = getModelDirs()
    const alreadyOnDrive = !sameDir && fs.existsSync(path.join(drive, manifestRelPath(model)))
    log('INFO', `Model pull started: ${model}${alreadyOnDrive ? ' (found on drive, skipping download)' : ''}`)
    if (!alreadyOnDrive) await new Promise((resolve, reject) => {
      const body = JSON.stringify({ name: model, model: model, stream: true })
      const req = http.request({ hostname: '127.0.0.1', port: 11434, path: '/api/pull', method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) } }, res => {
        let buf = ''
        res.on('data', chunk => {
          buf += chunk
          const lines = buf.split('\n'); buf = lines.pop()
          for (const line of lines) {
            if (!line.trim()) continue
            try {
              const j = JSON.parse(line)
              if (j.error) return reject(new Error(j.error))
              const pct = j.total ? Math.round((j.completed || 0) / j.total * 100) : null
              send({ status: j.status || 'Downloading...', pct })
            } catch(_) {}
          }
        })
        res.on('end', resolve)
      })
      req.on('error', reject)
      req.write(body); req.end()
    })
    send({ status: 'Copying model files...', pct: 0 })
    await syncModelBetweenDirs(model, send)
    await ensureDerivedModels(send)
    send({ status: 'Ready', pct: 100, done: true })
    log('INFO', `Model pull finished: ${model}`)
    return { ok: true }
  } catch(err) {
    log('ERROR', `Model pull failed (${model}): ${err.message}`)
    send({ status: 'Failed: ' + err.message, pct: null, error: true })
    return { ok: false, error: err.message }
  }
})