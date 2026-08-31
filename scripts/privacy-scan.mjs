import { readFile, readdir } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const ignored = new Set([
  ".git",
  ".next",
  ".pytest_cache",
  ".venv",
  ".vinext",
  ".wrangler",
  "__pycache__",
  "dist",
  "node_modules",
  "outputs",
  "work",
]);
const binaryExtensions = new Set([".db", ".gif", ".ico", ".jpeg", ".jpg", ".pdf", ".png", ".pyc", ".webp", ".zip"]);
const ignoredRuntimePaths = new Set(["backend/captures", "backend/data"]);
const findings = [];
const rules = [
  ["email address", /\b(?![^\s@]*@users\.noreply\.github\.com)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi],
  ["Windows home path", /[A-Z]:[\\/]Users[\\/][^\\/\s"']+/gi],
  ["macOS home path", /\/Users\/[^/\s"']+/g],
  ["Linux home path", /\/home\/[^/\s"']+/g],
  ["RV Whisper device ID", /\bRVM[23]-[A-Z0-9-]{4,}\b/gi],
  ["hard-coded credential", /\b(?:api[_-]?key|password|secret|token)\s*[=:]\s*["'][^"'\s]{8,}["']/gim],
];

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name)) continue;
    const path = join(directory, entry.name);
    if (ignoredRuntimePaths.has(relative(root, path).replaceAll("\\", "/"))) continue;
    if (entry.isDirectory()) await walk(path);
    else if (!binaryExtensions.has(extname(entry.name).toLowerCase())) {
      const content = await readFile(path, "utf8");
      for (const [label, pattern] of rules) {
        pattern.lastIndex = 0;
        if (pattern.test(content)) findings.push(`${relative(root, path)}: ${label}`);
      }
    }
  }
}

await walk(root);
if (findings.length) {
  console.error("Privacy scan failed:\n" + findings.join("\n"));
  process.exitCode = 1;
} else {
  console.log("Privacy scan passed.");
}
