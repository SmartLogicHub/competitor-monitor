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

test("palette uses a restrained local-tool primary color", () => {
  const css = readStyles();

  assert.match(css, /--primary:\s*#1F3A5F;/);
  assert.match(css, /--primary-hover:\s*#172A45;/);
  assert.doesNotMatch(css, /--primary:\s*#c76f5f;/);
});

test("C-scheme surfaces avoid AI-template gradients and glow", () => {
  const css = readStyles();
  const primaryButton = cssBlock(css, ".btn.primary");
  const gradientCount = (css.match(/gradient\(/g) || []).length;

  assert.doesNotMatch(primaryButton, /linear-gradient/);
  assert.ok(gradientCount <= 12, `Expected restrained gradient usage, found ${gradientCount}`);
  assert.doesNotMatch(css, /#(?:3B82F6|06B6D4|10B981|EF4444|F59E0B)\b/i);
  assert.doesNotMatch(css, /box-shadow:\s*0\s+0\s+8px\s+rgba\(59,\s*130,\s*246,\s*0\.6\)/);
  assert.doesNotMatch(css, /aurora-flow/);
});

test("configuration save controls use a calm shared hierarchy", () => {
  const css = readStyles();
  const primaryButton = cssBlock(css, ".btn.primary");

  assert.match(css, /\.config-save-state/);
  assert.match(css, /\.account-save-hint/);
  assert.match(css, /\.config-actions/);
  assert.doesNotMatch(primaryButton, /box-shadow:\s*0\s+6px\s+16px/);
  assert.doesNotMatch(css, /button-sheen|status-breathe|energy-cell-scan/);
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

test("dashboard surfaces avoid decorative glow and whole-card hover lift", () => {
  const css = readStyles();

  assert.doesNotMatch(css, /bg-glow-pink|bg-glow-blue/);
  assert.doesNotMatch(css, /glow-float-a|glow-float-b/);
  assert.doesNotMatch(css, /radar-pulse/);
  assert.doesNotMatch(css, /active-step-breathe/);
  assert.doesNotMatch(css, /pipeline-flow-line/);
  assert.doesNotMatch(css, /\.kpi-card:hover\s*\{[\s\S]*?transform:\s*translateY/s);
  assert.doesNotMatch(css, /\.task-card:hover,\s*\.panel:hover\s*\{[\s\S]*?transform:\s*translateY/s);
});

test("running task state uses inline notice instead of a blurred blocking overlay", () => {
  const css = readStyles();
  const note = cssBlock(css, ".task-running-note");

  assert.match(note, /display:\s*grid;/);
  assert.match(note, /grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto;/);
  assert.doesNotMatch(css, /\.card-overlay/);
  assert.doesNotMatch(css, /\/\*\s*卡片运行中遮罩蒙版\s*\*\//);
  assert.doesNotMatch(note, /position:\s*absolute/);
  assert.doesNotMatch(note, /backdrop-filter/);
});

test("mobile layout constrains navigation and hidden drawer to viewport", () => {
  const css = readStyles();

  assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*\.side-nav\s*\{[\s\S]*max-width:\s*100vw;[\s\S]*overflow:\s*hidden;/);
  assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*\.main-area\s*\{[\s\S]*max-width:\s*100vw;/);
  assert.match(css, /\.detail-drawer\[aria-hidden="true"\]\s*\{[\s\S]*visibility:\s*hidden;/);
});
