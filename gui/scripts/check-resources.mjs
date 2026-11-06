// Complements the official CLI: existing-but-empty values are not translations.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
const root = new URL("../src/i18n/locales/", import.meta.url);
const problems = [];
function leaves(value, prefix = "") {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof child === "object" && child !== null ? leaves(child, path) : [[path, child]];
  });
}
function read(language, namespace) {
  return new Map(leaves(JSON.parse(readFileSync(new URL(`${language}/${namespace}`, root), "utf8"))));
}
for (const namespace of readdirSync(new URL("en-US/", root))) {
  const source = read("en-US", namespace);
  const bases = new Set([...source.keys()].map((key) => key.replace(/_(zero|one|two|few|many|other)$/, "")));
  const pluralBases = new Set([...source.keys()].filter((key) => key.endsWith("_other")).map((key) => key.slice(0, -6)));
  for (const language of ["en-US", "zh-CN"]) {
    const target = read(language, namespace);
    const categories = new Intl.PluralRules(language).resolvedOptions().pluralCategories;
    for (const base of bases) {
      const required = pluralBases.has(base) ? categories.map((category) => `${base}_${category}`) : [base];
      for (const key of required) {
        const value = target.get(key);
        if (typeof value !== "string" || !value.trim()) problems.push(`${language}/${namespace}:${key}: missing or empty translation`);
      }
    }
    for (const [key, value] of target) {
      if (typeof value !== "string" || !value.trim()) problems.push(`${language}/${namespace}:${key}: invalid translation`);
    }
  }
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`Translation resources complete and nonempty: ${fileURLToPath(root)}`);
}

// i18next-cli 1.85.1's call-site interpolation loader only reads common/default/
// translation, and TS currently permits t(key) without options. Cover that narrow
// gap for literal calls; normal key/parameter types and CLI placeholder checks
// remain authoritative. No replacement translation API or generated key list.
const { default: ts } = await import("typescript");
const { join } = await import("node:path");
const messages = new Map();
for (const namespace of readdirSync(new URL("en-US/", root))) {
  for (const [key, value] of read("en-US", namespace)) {
    const name = `${namespace.slice(0, -5)}:${key}`;
    messages.set(name, value);
    if (key.endsWith("_other")) messages.set(name.slice(0, -6), value);
  }
}
function inspectFile(path) {
  const source = ts.createSourceFile(path, readFileSync(path, "utf8"), ts.ScriptTarget.Latest, true);
  function visit(node) {
    if (ts.isCallExpression(node) && node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0])) {
      const callee = node.expression;
      const isT = ts.isIdentifier(callee) ? callee.text === "t" : ts.isPropertyAccessExpression(callee) && callee.name.text === "t";
      const key = node.arguments[0].text;
      const candidates = key.includes(":") ? [messages.get(key)] : [...messages].filter(([name]) => name.endsWith(`:${key}`)).map(([, value]) => value);
      if (isT && candidates.some((value) => typeof value === "string" && value.includes("{{"))) {
        const line = source.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        console.error(`${path}:${line}: ${key} requires interpolation options`);
        process.exitCode = 1;
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
function inspectDirectory(directory) {
  for (const item of readdirSync(directory, { withFileTypes: true })) {
    if (["generated", "client", "locales"].includes(item.name)) continue;
    const path = join(directory, item.name);
    if (item.isDirectory()) inspectDirectory(path);
    else if (/\.tsx?$/.test(item.name) && !item.name.endsWith(".d.ts")) inspectFile(path);
  }
}
inspectDirectory(fileURLToPath(new URL("../src/", import.meta.url)));
