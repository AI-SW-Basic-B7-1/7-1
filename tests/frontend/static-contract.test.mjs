import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(testDirectory, "..", "..");

const requiredFiles = [
  "static/index.html",
  "static/css/style.css",
  "static/js/api.js",
  "static/js/auth.js",
  "static/js/app.js",
  "static/js/keyboard.js",
];

async function readRepositoryFile(relativePath) {
  return readFile(path.join(repositoryRoot, relativePath), "utf8");
}

test("필수 프론트 파일은 static 경계 안에 존재하고 비어 있지 않다", async () => {
  for (const relativePath of requiredFiles) {
    const content = await readRepositoryFile(relativePath);
    assert.ok(content.trim().length > 0, `${relativePath} 파일이 비어 있습니다.`);
  }
});

test("HTML 정적 자원은 동일 출처의 /static 경로만 사용한다", async () => {
  const html = await readRepositoryFile("static/index.html");
  const resourcePaths = [...html.matchAll(/(?:href|src)="([^"]+)"/g)].map((match) => match[1]);

  assert.ok(resourcePaths.length >= 3);
  assert.ok(resourcePaths.every((resourcePath) => resourcePath.startsWith("/static/")));
  assert.doesNotMatch(html, /(?:file|https?):\/\//i);
});

test("fetch와 팀 API 경로는 api.js 한 곳에만 모여 있다", async () => {
  const [apiSource, authSource, appSource, keyboardSource] = await Promise.all([
    readRepositoryFile("static/js/api.js"),
    readRepositoryFile("static/js/auth.js"),
    readRepositoryFile("static/js/app.js"),
    readRepositoryFile("static/js/keyboard.js"),
  ]);

  assert.match(apiSource, /const API_BASE = "\/api"/);
  for (const endpoint of ["/health", "/auth/register", "/auth/login", "/chat", "/me/chats"]) {
    assert.ok(apiSource.includes(`"${endpoint}"`), `${endpoint} 계약이 없습니다.`);
  }
  assert.match(apiSource, /\bfetch\s*\(/);
  assert.doesNotMatch(`${authSource}\n${appSource}\n${keyboardSource}`, /\bfetch\s*\(/);
  assert.doesNotMatch(`${apiSource}\n${authSource}\n${appSource}\n${keyboardSource}`, /(?:file|https?):\/\//i);
});

test("대화 내용은 HTML 실행 없이 textContent로 렌더링한다", async () => {
  const appSource = await readRepositoryFile("static/js/app.js");

  assert.match(appSource, /content\.textContent = text/);
  assert.doesNotMatch(appSource, /\.innerHTML\s*=/);
  assert.doesNotMatch(appSource, /insertAdjacentHTML/);
});
