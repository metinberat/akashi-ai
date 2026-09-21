const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("akashiDesktop", {
  platform: process.platform,
  config: {
    load: () => ipcRenderer.invoke("akashi:config:load"),
    save: (value) => ipcRenderer.invoke("akashi:config:save", value),
  },
  provider: {
    load: () => ipcRenderer.invoke("akashi:provider:load"),
    save: (value) => ipcRenderer.invoke("akashi:provider:save", value),
  },
  windowControls: {
    minimize: () => ipcRenderer.invoke("akashi:window:minimize"),
    maximize: () => ipcRenderer.invoke("akashi:window:maximize"),
    close: () => ipcRenderer.invoke("akashi:window:close"),
    isMaximized: () => ipcRenderer.invoke("akashi:window:is-maximized"),
    onState: (callback) => {
      const listener = (_event, value) => callback(value);
      ipcRenderer.on("akashi:window:state", listener);
      return () => ipcRenderer.removeListener("akashi:window:state", listener);
    },
  },
  runtime: {
    status: () => ipcRenderer.invoke("akashi:runtime:status"),
    whenReady: () => ipcRenderer.invoke("akashi:runtime:ready"),
    recover: (component) => ipcRenderer.invoke("akashi:runtime:recover", component),
    onState: (callback) => {
      const listener = (_event, value) => callback(value);
      ipcRenderer.on("akashi:runtime:state", listener);
      return () => ipcRenderer.removeListener("akashi:runtime:state", listener);
    },
  },
  api: {
    fetch: (request) => ipcRenderer.invoke("akashi:api:fetch", request),
  },
  agent: {
    status: () => ipcRenderer.invoke("akashi:agent:status"),
    execute: (action, arguments_, approved) => ipcRenderer.invoke(
      "akashi:agent:execute",
      { action, arguments: arguments_, approved },
    ),
  },
  voice: {
    status: () => ipcRenderer.invoke("akashi:voice:status"),
    listen: (options) => ipcRenderer.invoke("akashi:voice:listen", options),
    stop: () => ipcRenderer.invoke("akashi:voice:stop"),
    onState: (callback) => {
      const listener = (_event, value) => callback(value);
      ipcRenderer.on("akashi:voice:state", listener);
      return () => ipcRenderer.removeListener("akashi:voice:state", listener);
    },
    live: {
      available: () => ipcRenderer.invoke("akashi:voice:live:available"),
      start: (options) => ipcRenderer.invoke("akashi:voice:live:start", options),
      stop: () => ipcRenderer.invoke("akashi:voice:live:stop"),
      interrupt: () => ipcRenderer.invoke("akashi:voice:live:interrupt"),
      sendText: (text) => ipcRenderer.invoke("akashi:voice:live:text", text),
      onEvent: (callback) => {
        const listener = (_event, value) => callback(value);
        ipcRenderer.on("akashi:voice:live:event", listener);
        return () => ipcRenderer.removeListener("akashi:voice:live:event", listener);
      },
    },
  },
  shell: {
    showDataFolder: () => ipcRenderer.invoke("akashi:shell:data-folder"),
    openExternal: (url) => ipcRenderer.invoke("akashi:shell:open-external", url),
  },
});
