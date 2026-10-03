const fs = require("node:fs");
const path = require("node:path");
const esbuild = require("esbuild");
const root = path.resolve(__dirname, "..");
async function main() {
  fs.mkdirSync(path.join(root, "web-dist"), { recursive: true });
  for (const name of ["index.html", "style.css"])
    fs.copyFileSync(
      path.join(root, "web", name),
      path.join(root, "web-dist", name),
    );
  await esbuild.build({
    entryPoints: [path.join(root, "web/app.js")],
    outfile: path.join(root, "web-dist/app.js"),
    bundle: true,
    minify: true,
    format: "esm",
    target: "chrome140",
    legalComments: "linked",
  });
}
main().catch(() => {
  process.exitCode = 1;
});
