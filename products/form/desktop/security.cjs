function localRequest(url, origin) {
  try {
    const parsed = new URL(url);
    return parsed.origin === origin && parsed.pathname.startsWith("/api/");
  } catch {
    return false;
  }
}
function environment(source, paths, data, web, token) {
  const env = {};
  for (const key of [
    "SystemRoot",
    "WINDIR",
    "PATH",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
  ])
    if (source[key]) env[key] = source[key];
  for (const key of [
    "FORM_GEMINI_API_KEY",
    "FORM_EXTERNAL_MODELS_ENABLED",
    "FORM_LOCAL_SHAPE_ENABLED",
    "FORM_SHAPE_LICENSE_ACCEPTED",
    "FORM_SHAPE_PYTHON",
    "FORM_SHAPE_SDK",
    "FORM_SHAPE_CHECKPOINT",
    "FORM_SHAPE_CONFIG",
    "FORM_OLLAMA_URL",
    "FORM_REASONING_PROVIDER",
    "FORM_REASONING_MODEL",
    "FORM_VISION_PROVIDER",
    "FORM_VISION_MODEL",
  ])
    if (source[key]) env[key] = source[key];
  return {
    ...env,
    PYTHONPATH: paths.join(require("node:path").delimiter),
    PYTHONUNBUFFERED: "1",
    FORM_DATA_DIR: data,
    FORM_WEB_DIR: web,
    FORM_RUNTIME_TOKEN: token,
  };
}
module.exports = { localRequest, environment };
