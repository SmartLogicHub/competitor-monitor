const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

function readStyles() {
  return fs.readFileSync(path.join(__dirname, "styles.css"), "utf8");
}

function cssBlock(css, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\}`));
  assert.ok(match, `Expected to find ${selector}`);
  return match[1];
}

test("palette keeps a clean tech-blue primary action color", () => {
  const css = readStyles();

  assert.match(css, /--primary:\s*#3B82F6;/);
  assert.match(css, /--primary-hover:\s*#2563EB;/);
  assert.doesNotMatch(css, /--primary:\s*#c76f5f;/);
});

test("template collage chips use a thin fill rule instead of heavy spreadsheet blocks", () => {
  const css = readStyles();
  const cell = cssBlock(css, ".energy-cell");
  const fill = cssBlock(css, ".energy-cell span");

  assert.match(cell, /height:\s*10px;/);
  assert.doesNotMatch(fill, /repeating-linear-gradient/);
});

test("polling-refreshed rows and cards do not replay layout-shifting entry animations", () => {
  const css = readStyles();

  assert.doesNotMatch(
    css,
    /\.result-row,\s*\.log-item,\s*\.workflow-item,\s*\.pipeline-date-card\s*\{[^}]*animation:\s*entry-slide-up/s
  );
  assert.doesNotMatch(css, /\.pipeline-date-card\.complete\s*\{[^}]*animation:\s*complete-bounce/s);
});
