import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceDir = path.join(root, "app", "static");
const outputDir = path.join(root, "frontend-dist");
const staticDir = path.join(outputDir, "static");
const scriptTag = '<script src="/static/app.js" defer></script>';

function reject(message) {
  console.error(message);
  process.exit(1);
}

function assertOrigin(value) {
  if (!value.startsWith("https://")) {
    reject("API_BASE must start with https://");
  }
  let url;
  try {
    url = new URL(value);
  } catch {
    reject("API_BASE must be an origin only, with no path");
  }
  if (url.origin !== value) {
    reject("API_BASE must be an origin only, with no path and no trailing slash");
  }
}

const apiBase = (process.env.API_BASE || "").trim();
if (apiBase) {
  assertOrigin(apiBase);
}

await mkdir(staticDir, { recursive: true });
await copyFile(path.join(sourceDir, "app.js"), path.join(staticDir, "app.js"));
await copyFile(path.join(sourceDir, "styles.css"), path.join(staticDir, "styles.css"));

let html = await readFile(path.join(sourceDir, "index.html"), "utf8");
if (!html.includes(scriptTag)) {
  reject('index.html is missing <script src="/static/app.js" defer></script>');
}
if (apiBase) {
  const injection = `<script>window.API_BASE = ${JSON.stringify(apiBase)};</script>\n  `;
  html = html.replace(scriptTag, `${injection}${scriptTag}`);
}
await writeFile(path.join(outputDir, "index.html"), html);

console.log(
  apiBase
    ? `Wrote frontend-dist with API_BASE ${apiBase}`
    : "Wrote frontend-dist for same-origin API calls"
);
