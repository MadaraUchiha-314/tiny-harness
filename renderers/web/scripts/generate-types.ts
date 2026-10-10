/**
 * Generates TypeScript types from the committed extension schemas (requirement 22.2):
 * docs/a2a/ext/task.json and channel.json are the source of truth; the output under
 * src/generated/ is rebuilt on every build and never committed.
 */
import { compileFromFile } from "json-schema-to-typescript";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../..");
const out = join(here, "../src/generated");

const schemas: Array<[string, string]> = [
  ["docs/a2a/ext/task.json", "task.ts"],
  ["docs/a2a/ext/channel.json", "channel.ts"],
];

await mkdir(out, { recursive: true });
for (const [source, target] of schemas) {
  const types = await compileFromFile(join(repo, source), {
    bannerComment: `/* Generated from ${source}; do not edit. */`,
    additionalProperties: false,
    strictIndexSignatures: true,
  });
  // The generator flattens the recursive JsonValue into a self-referencing alias that
  // TypeScript rejects; the schema's intent is plain JSON, so spell it out.
  const start = types.indexOf("export type JsonValue =");
  let fixed = types;
  if (start >= 0) {
    const rest = types.indexOf("\nexport ", start + 1);
    const end = rest >= 0 ? rest + 1 : types.length;
    fixed =
      types.slice(0, start) +
      "export type JsonValue = string | number | boolean | null | JsonValue[] | { [k: string]: JsonValue };\n" +
      types.slice(end);
  }
  await writeFile(join(out, target), fixed);
}
console.log(`generated ${schemas.length} type file(s) into src/generated/`);
