const fs = require("node:fs");
const path = require("node:path");

const appRoot = path.resolve(__dirname, "..");
const source = path.resolve(appRoot, "..", "..", "frontend", "out");
const destination = path.join(appRoot, "web");
const index = path.join(source, "index.html");

if (!fs.existsSync(index)) {
  throw new Error(`Static frontend is missing at ${index}. Run npm run build in frontend first.`);
}

fs.rmSync(destination, { recursive: true, force: true });
fs.cpSync(source, destination, { recursive: true });
console.log(`Copied AKASHI static frontend to ${destination}`);
