import type { UserChoicePromptV1 } from "./generated/bridge.ts";

function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).length !== fields.length || fields.some((field) => !Object.prototype.hasOwnProperty.call(value, field))) {
    throw new Error("Invalid user choice fields");
  }
  return value as Record<string, unknown>;
}

function identifier(value: unknown, maximum: number): string {
  if (typeof value !== "string" || value.length > maximum
    || !/^[A-Za-z0-9]/.test(value) || /[^A-Za-z0-9._~-]/.test(value)) {
    throw new Error("Invalid user choice identifier");
  }
  return value;
}

function text(value: unknown, maximum: number): string {
  if (typeof value !== "string" || !value.trim() || [...value].length > maximum) {
    throw new Error("Invalid user choice text");
  }
  return value;
}

export function validateUserChoice(value: unknown): UserChoicePromptV1 {
  const prompt = object(value, ["questionId", "question", "options"]);
  if (!Array.isArray(prompt.options) || prompt.options.length < 2 || prompt.options.length > 5) {
    throw new Error("Invalid user choice option count");
  }
  const ids = new Set<string>();
  const options = prompt.options.map((raw: unknown) => {
    const option = object(raw, ["id", "label", "description"]);
    const id = identifier(option.id, 64);
    if (ids.has(id)) throw new Error("Duplicate user choice option");
    ids.add(id);
    return {
      id, label: text(option.label, 160),
      description: option.description === null ? null : text(option.description, 512),
    };
  });
  return { questionId: identifier(prompt.questionId, 512), question: text(prompt.question, 1024), options };
}
