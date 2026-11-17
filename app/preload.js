const { ipcRenderer } = require('electron')

window.minimizeWindow = () => ipcRenderer.send('minimize')
window.maximizeWindow = () => ipcRenderer.send('maximize')
window.closeWindow = () => ipcRenderer.send('close')