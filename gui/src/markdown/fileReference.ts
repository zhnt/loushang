export interface FileReference {
  readonly path: string;
  readonly line?: number;
}

const explicitRelativePath = /^\.\.?[\\/]/;
const fileName = /(?:^|[\\/])(?:README|LICENSE|CHANGELOG|Dockerfile|Makefile|\.gitignore|\.editorconfig)$/;
const fileExtension = /\.(?:md|markdown|mdx|txt|log|rst|adoc|html?|css|scss|jsonc?|ya?ml|toml|ini|cfg|xml|csv|tsv|[cm]?[jt]sx?|pyi?|rs|go|java|kt|swift|[ch](?:pp|xx)?|cs|rb|php|sql|sh|bash|zsh|fish|ps1|bat|vue|svelte|pdf|png|jpe?g|webp)$/i;

function relativePath(path: string): boolean {
  return path.length > 0 && path.length <= 4096 && path.trim() === path
    && !/^[\\/]|[:\p{Cc}]/u.test(path);
}

function withLine(path: string, line: string | undefined): FileReference {
  const number = line ? Number(line) : 0;
  return number > 0 && Number.isSafeInteger(number) ? { path, line: number } : { path };
}

export function markdownFileReference(url: string): FileReference | undefined {
  const [target, fragment] = url.split("#", 2);
  if (!target || target.includes("?")) return undefined;
  try {
    const path = decodeURIComponent(target);
    if (!relativePath(path)) return undefined;
    return withLine(path, fragment?.match(/^L([1-9]\d*)(?:-L?\d+)?$/i)?.[1]);
  } catch {
    return undefined;
  }
}

export function inlineFileReference(value: string): FileReference | undefined {
  const location = value.match(/(?::|#L)([1-9]\d*)(?:-L?\d+)?$/);
  const path = location ? value.slice(0, location.index) : value;
  if (!relativePath(path) || !/^[\p{L}\p{N}._/\\ -]+$/u.test(path)) return undefined;
  if (!explicitRelativePath.test(path)
    && (path.includes(" ") || !fileName.test(path) && !fileExtension.test(path) && !/[\\/]$/.test(path))) return undefined;
  return withLine(path, location?.[1]);
}
