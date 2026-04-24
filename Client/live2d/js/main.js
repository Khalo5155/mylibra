const { app, BrowserWindow, screen } = require('electron');
const path = require('path');

let win;

function createWindow() {
  // 获取屏幕尺寸
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  win = new BrowserWindow({
    width: 300,        // 桌宠大小
    height: 400,
    x: width - 350,    // 初始位置（右下角）
    y: height - 450,
    transparent: true, // 关键：透明背景
    frame: false,      // 无边框
    alwaysOnTop: true, // 永远置顶
    skipTaskbar: true, // 不显示在任务栏
    resizable: false,
    hasShadow: false,
    webPreferences: {
      contextIsolation: false,
      nodeIntegration: true
    }
  });

  // 加载页面
  win.loadFile('index.html');

  // 允许拖动窗口
  win.setIgnoreMouseEvents(false);

  win.on('closed', () => {
    win = null;
  });
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  app.quit();
});