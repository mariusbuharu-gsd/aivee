// Builds the static site into dist/: copies src/ and the brand files from docs/brand,
// then fails if any local href/src in the HTML points at a file that does not exist.
// No dependencies, so CI can run it with plain Node.
import { cpSync, existsSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "src");
const dist = join(here, "dist");
const brand = resolve(here, "../../docs/brand");

rmSync(dist, { recursive: true, force: true });
cpSync(src, dist, { recursive: true });
cpSync(brand, join(dist, "brand"), {
  recursive: true,
  filter: (path) => path === brand || path.endsWith(".svg"),
});

const missing = [];
for (const page of readdirSync(dist).filter((f) => f.endsWith(".html"))) {
  const html = readFileSync(join(dist, page), "utf8");
  for (const [, ref] of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    if (/^(https?:|mailto:|tel:|#|data:)/.test(ref)) continue;
    const path = join(dist, ref.split(/[?#]/)[0]);
    if (!existsSync(path)) missing.push(`${page}: ${ref}`);
  }
}

if (missing.length) {
  console.error(`Broken local references:\n  ${missing.join("\n  ")}`);
  process.exit(1);
}
console.log(`Site built in ${dist}`);
