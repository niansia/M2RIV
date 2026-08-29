// Verify the portable M2RIV v1 content-identity profile using Node stdlib only.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const vectorsUrl = new URL("./golden-vectors.json", import.meta.url);
const document = JSON.parse(readFileSync(vectorsUrl, "utf8"));
const floatVectorsUrl = new URL("./float-vectors.json", import.meta.url);
const floatDocument = JSON.parse(readFileSync(floatVectorsUrl, "utf8"));

class Float64Value {
  constructor(value) {
    this.value = value;
  }
}

function compareUnicodeScalar(left, right) {
  const a = Array.from(left, (character) => character.codePointAt(0));
  const b = Array.from(right, (character) => character.codePointAt(0));
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function pythonFloat(value) {
  if (!Number.isFinite(value)) throw new TypeError("numbers must be finite");
  if (Object.is(value, -0)) return "-0.0";
  if (value === 0) return "0.0";

  const sign = value < 0 ? "-" : "";
  const raw = Math.abs(value).toString().toLowerCase();
  const [coefficient, exponentText = "0"] = raw.split("e");
  const explicitExponent = Number.parseInt(exponentText, 10);
  const point = coefficient.indexOf(".");
  const decimalPosition = point === -1 ? coefficient.length : point;
  const allDigits = coefficient.replace(".", "");
  const firstSignificant = allDigits.search(/[1-9]/);
  const firstExponent = decimalPosition - firstSignificant - 1 + explicitExponent;
  const significant = allDigits.slice(firstSignificant).replace(/0+$/, "");

  if (firstExponent >= -4 && firstExponent < 16) {
    if (firstExponent < 0) {
      return `${sign}0.${"0".repeat(-firstExponent - 1)}${significant}`;
    }
    const integerDigits = firstExponent + 1;
    if (significant.length <= integerDigits) {
      return `${sign}${significant}${"0".repeat(integerDigits - significant.length)}.0`;
    }
    return `${sign}${significant.slice(0, integerDigits)}.${significant.slice(integerDigits)}`;
  }

  const mantissa =
    significant.length === 1 ? significant : `${significant[0]}.${significant.slice(1)}`;
  const exponentSign = firstExponent < 0 ? "-" : "+";
  const exponent = Math.abs(firstExponent).toString().padStart(2, "0");
  return `${sign}${mantissa}e${exponentSign}${exponent}`;
}

function materializeTypedValue(value) {
  if (Array.isArray(value)) return value.map(materializeTypedValue);
  if (value === null || typeof value !== "object") return value;
  const keys = Object.keys(value);
  if (keys.length === 1 && keys[0] === "$float64") {
    if (!/^[0-9a-fA-F]{16}$/.test(value.$float64)) {
      throw new TypeError("$float64 must contain exactly 16 hexadecimal digits");
    }
    const bytes = Buffer.from(value.$float64, "hex");
    return new Float64Value(bytes.readDoubleBE(0));
  }
  if (keys.length === 1 && keys[0] === "$integer") {
    return BigInt(value.$integer);
  }
  if (keys.length === 1 && keys[0] === "$datetime") {
    const timestamp = value.$datetime;
    if (typeof timestamp !== "string" || !/(Z|[+-]\d\d:\d\d)$/.test(timestamp)) {
      throw new TypeError("$datetime must contain an offset-aware RFC 3339 string");
    }
    return timestamp.endsWith("Z") ? `${timestamp.slice(0, -1)}+00:00` : timestamp;
  }
  if (keys.length === 1 && keys[0] === "$path") {
    return value.$path.replaceAll("\\", "/");
  }
  if (keys.length === 1 && keys[0] === "$set") {
    if (!Array.isArray(value.$set) || !value.$set.every((item) => typeof item === "string")) {
      throw new TypeError("$set must contain only strings in the portable v1 profile");
    }
    return [...new Set(value.$set)].sort(compareUnicodeScalar);
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, materializeTypedValue(item)]),
  );
}

function canonicalJson(value) {
  if (value instanceof Float64Value) return pythonFloat(value.value);
  if (typeof value === "bigint") return value.toString();
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("numbers must be finite");
    if (Object.is(value, -0)) return "-0.0";
    return Number.isInteger(value) ? value.toString() : pythonFloat(value);
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
  const payload = canonicalJson(materializeTypedValue(vector.typed_value ?? vector.value));
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

for (const vector of floatDocument.vectors) {
  const bytes = Buffer.from(vector.bits, "hex");
  const payload = canonicalJson({ value: new Float64Value(bytes.readDoubleBE(0)) });
  if (payload !== vector.canonical_json) {
    throw new Error(`float canonical JSON mismatch: ${vector.bits}`);
  }
  const digest = createHash("sha256")
    .update(Buffer.from("m2riv:float-spelling-corpus:v1", "utf8"))
    .update(Buffer.from([0]))
    .update(Buffer.from(payload, "utf8"))
    .digest("hex");
  if (digest !== vector.sha256) {
    throw new Error(`float fingerprint mismatch: ${vector.bits}`);
  }
}

console.log(`verified ${floatDocument.vectors.length} binary64 spelling vectors`);
