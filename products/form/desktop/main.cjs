const { app, BrowserWindow, session, dialog } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");
const { localRequest, environment } = require("./security.cjs");
let child,
  window,
  origin,
  token,
  quitting = false;
if (process.env.FORM_DATA_DIR)
  app.setPath("userData", path.resolve(process.env.FORM_DATA_DIR));
const owned = app.requestSingleInstanceLock();
if (!owned) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      window.restore();
      window.show();
      window.focus();
    }
  });
  app
    .whenReady()
    .then(start)
    .catch(() => {
      dialog.showErrorBox(
        "FORM startup failed",
        "Runtime could not initialize. Configure FORM_PYTHON to a Python 3.11+ environment with the product dependencies.",
      );
      app.quit();
    });
}
async function start() {
  const root = path.resolve(__dirname, "..");
  const repository = path.resolve(root, "../..");
  const resources = app.isPackaged ? process.resourcesPath : root;
  const userEnvironment = configuredEnvironment(root);
  const settingsPath = path.join(
    app.getPath("userData"),
    "runtime-settings.json",
  );
  let saved = {};
  try {
    saved = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  } catch {}
  let python =
    userEnvironment.FORM_PYTHON ||
    saved.python ||
    (!app.isPackaged
      ? path.join(repository, "backend/.venv/Scripts/python.exe")
      : "");
  if (!python || !path.isAbsolute(python) || !fs.existsSync(python)) {
    const selection = await dialog.showOpenDialog({
      title: "FORM: select installed Python with product dependencies",
      properties: ["openFile"],
      filters: [{ name: "Python interpreter", extensions: ["exe"] }],
    });
    if (selection.canceled) throw new Error("Interpreter not configured");
    python = selection.filePaths[0];
    if (
      !["python.exe", "pythonw.exe"].includes(
        path.basename(python).toLowerCase(),
      )
    )
      throw new Error("Expected Python interpreter");
    fs.writeFileSync(settingsPath, JSON.stringify({ python }));
  }
  token = crypto.randomBytes(32).toString("hex");
  const paths = app.isPackaged
    ? [
        path.join(resources, "server"),
        path.join(resources, "engine"),
        path.join(resources, "dcc"),
      ]
    : [
        path.join(root, "server"),
        path.join(repository, "backend"),
        path.join(repository, "desktop/agent"),
      ];
  child = spawn(python, ["-m", "form_studio.runtime"], {
    shell: false,
    windowsHide: true,
    cwd: app.getPath("userData"),
    env: environment(
      userEnvironment,
      paths,
      app.getPath("userData"),
      app.isPackaged
        ? path.join(resources, "web")
        : path.join(root, "web-dist"),
      token,
    ),
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stderr.on("data", () => {}); // Drain, never copy arbitrary DCC/source output or credentials to renderer/logs.
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Startup timeout")), 30000);
    let buffer = "";
    child.stdout.on("data", (chunk) => {
      buffer = (buffer + chunk.toString()).slice(-8192);
      for (const line of buffer.split("\n")) {
        try {
          const value = JSON.parse(line);
          if (
            value.product === "FORM" &&
            Number.isInteger(value.port) &&
            value.port > 1024
          ) {
            clearTimeout(timer);
            resolve(value.port);
          }
        } catch {}
      }
    });
    child.on("error", () => {
      clearTimeout(timer);
      reject(new Error("Runtime launch failed"));
    });
    child.once("exit", () => {
      clearTimeout(timer);
      reject(new Error("Runtime exited"));
    });
  });
  // Python static serving cannot read ASAR; use an unpacked resource copy in packaged builds.
  origin = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i++) {
    try {
      const response = await fetch(origin + "/api/health", {
        headers: { Authorization: "Bearer " + token },
      });
      if (response.ok) break;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
    if (i === 99) throw new Error("Health timeout");
  }
  const partition = session.fromPartition("form-workspace");
  partition.setPermissionRequestHandler((_wc, _permission, callback) =>
    callback(false),
  );
  partition.webRequest.onBeforeSendHeaders((details, callback) => {
    if (localRequest(details.url, origin))
      details.requestHeaders.Authorization = "Bearer " + token;
    callback({ requestHeaders: details.requestHeaders });
  });
  partition.on("will-download", (_event, item) => {
    if (!localRequest(item.getURL(), origin)) item.cancel();
  });
  window = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1000,
    minHeight: 700,
    backgroundColor: "#111416",
    title: "FORM · Character Studio",
    autoHideMenuBar: true,
    webPreferences: {
      partition: "form-workspace",
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin !== origin) event.preventDefault();
  });
  child.once("exit", () => {
    if (!quitting && window)
      dialog.showErrorBox(
        "FORM runtime offline",
        "The local engine stopped. Saved work is retained. Relaunch FORM to inspect and resume interrupted versions.",
      );
  });
  await window.loadURL(origin);
}
function configuredEnvironment(root) {
  const env = { ...process.env };
  // Private runtime configuration is outside the application resources and renderer.
  for (const file of [
    !app.isPackaged ? path.join(root, ".env") : null,
    path.join(app.getPath("userData"), "form.env"),
  ]) {
    if (!file || !fs.existsSync(file)) continue;
    for (const [key, value] of Object.entries(
      require("node:util").parseEnv(fs.readFileSync(file, "utf8")),
    ))
      if (key.startsWith("FORM_") && !env[key]) env[key] = value;
  }
  return env;
}
app.on("window-all-closed", () => app.quit());
app.on("before-quit", (event) => {
  if (quitting || !child || child.exitCode !== null) return;
  event.preventDefault();
  quitting = true;
  if (window) window.hide();
  const finish = () => app.exit(0);
  child.once("exit", finish);
  // Do not kill Blender during a save. Runtime waits for its current fixed, timed DCC operation.
  if (origin)
    fetch(origin + "/api/shutdown", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
    }).catch(() => {
      child.kill();
    });
  else child.kill();
});
