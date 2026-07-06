from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from browser_service import BrowserService
from config_service import load_config
from excel_service import ExcelService


DEFAULT_NEEDLES = ["Pro2", "Ultra", "S6S", "星芒紫", "无尽黑", "玫瑰金", "香槟金", "Art"]


def parse_args():
    parser = argparse.ArgumentParser(description="Inspect DOM nodes around SKU-like labels.")
    parser.add_argument("--config", default="competitor_monitor/config_real_test.yaml")
    parser.add_argument("--url")
    parser.add_argument("--sheet")
    parser.add_argument("--row", type=int)
    parser.add_argument("--needle", action="append", dest="needles")
    parser.add_argument("--output")
    return parser.parse_args()


def resolve_url(config: dict, sheet: str | None, row: int | None, url: str | None) -> tuple[str, str]:
    if url:
        return url, ""
    if not sheet or not row:
        raise ValueError("Provide --url, or provide --sheet and --row.")
    excel_path = Path(config.get("excel_path", "竞品监控.xlsx"))
    workbook = ExcelService(excel_path).load_workbook()
    worksheet = workbook[sheet]
    model_cell = worksheet.cell(row=row, column=2)
    target = model_cell.hyperlink.target if model_cell.hyperlink and model_cell.hyperlink.target else str(model_cell.value or "")
    return target, str(model_cell.value or "")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    config = load_config(args.config)
    needles = args.needles or DEFAULT_NEEDLES
    url, model = resolve_url(config, args.sheet, args.row, args.url)

    script = """
    (body, needles) => {
        const out = [];
        const all = Array.from(body.querySelectorAll('*'));
        const normalize = (value) => String(value || '').trim().replace(/\\s+/g, ' ');
        const cssPath = (node) => {
            const parts = [];
            let current = node;
            while (current && current.nodeType === 1 && parts.length < 6) {
                let part = current.tagName.toLowerCase();
                if (current.id) part += '#' + current.id;
                const cls = normalize(current.className).split(' ').filter(Boolean).slice(0, 3);
                if (cls.length) part += '.' + cls.join('.');
                const parent = current.parentElement;
                if (parent) {
                    const siblings = Array.from(parent.children).filter((n) => n.tagName === current.tagName);
                    if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                }
                parts.unshift(part);
                current = current.parentElement;
            }
            return parts.join(' > ');
        };
        for (const node of all) {
            const text = normalize(node.innerText || node.textContent);
            if (!text || text.length > 180) continue;
            if (!needles.some((needle) => text.includes(needle))) continue;
            const rect = node.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            const parentText = normalize(node.parentElement && (node.parentElement.innerText || node.parentElement.textContent)).slice(0, 260);
            out.push({
                tag: node.tagName.toLowerCase(),
                text,
                className: normalize(node.className),
                role: node.getAttribute('role') || '',
                ariaLabel: node.getAttribute('aria-label') || '',
                title: node.getAttribute('title') || '',
                dataSkuId: node.getAttribute('data-sku-id') || node.getAttribute('data-skuid') || '',
                dataValue: node.getAttribute('data-value') || '',
                rect: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)},
                path: cssPath(node),
                parentText,
            });
        }
        return out;
    }
    """

    with BrowserService(
        headless=bool(config.get("headless", False)),
        timeout_ms=int(config.get("timeout_ms", 60000)),
        user_data_dir=config.get("browser_user_data_dir", "competitor_monitor/browser_profile"),
        context_config=config,
    ) as browser:
        page = browser._context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=int(config.get("timeout_ms", 60000)))
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        nodes = page.locator("body").evaluate(script, needles)
        title = page.title()
        page.close()

    output_dir = Path(config.get("log_dir", "competitor_monitor/logs"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output) if args.output else output_dir / "dom_probe.json"
    output_path.write_text(json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")

    print("model", model)
    print("url", url)
    print("title", title)
    print("node_count", len(nodes))
    print("output", output_path)
    for node in nodes[:40]:
        print("---")
        print(node["tag"], node["rect"], node["text"])
        print(node["className"])
        print(node["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
