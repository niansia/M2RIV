// Verify the portable M2RIV v1 content-identity profile using Node stdlib only.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const vectorsUrl = new URL("./golden-vectors.json", import.meta.url);
const document = JSON.parse(readFileSync(vectorsUrl, "utf8"));

function compareUnicodeScalar(left, right) {
  const a = Array.from(left, (character) => character.codePointAt(0));
  const b = Array.from(right, (character) => character.codePointAt(0));
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function canonicalJson(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("numbers must be finite");
    if (Object.is(value, -0)) return "-0.0";
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort(compareUnicodeScalar);
    return `{${keys
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  throw new TypeError(`unsupported value: ${typeof value}`);
}

for (const vector of document.vectors) {
  const payload = canonicalJson(vector.value);
  if (payload !== vector.canonical_json) {
    throw new Error(`canonical JSON mismatch: ${vector.name}`);
  }
  const domain = Buffer.from(`m2riv:${vector.namespace}:v1`, "utf8");
  const digest = createHash("sha256")
    .update(domain)
    .update(Buffer.from([0]))
    .update(Buffer.from(payload, "utf8"))
    .digest("hex");
  if (digest !== vector.sha256) {
    throw new Error(`fingerprint mismatch: ${vector.name}`);
  }
}

console.log(`verified ${document.vectors.length} M2RIV v1 identity vectors`);
