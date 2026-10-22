import { describe, expect, it } from "vitest";
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";
import ElementPlus, { ID_INJECTION_KEY, ZINDEX_INJECTION_KEY } from "element-plus";
import { readFileSync } from "node:fs";
import LogPanel from "./LogPanel.vue";
import SettingsPanel from "./SettingsPanel.vue";
import type { Settings } from "../types";

async function render(component: any, props: any) {
  const app = createSSRApp({ render: () => h(component, props) });
  app.use(ElementPlus);
  app.provide(ID_INJECTION_KEY, { prefix: 1, current: 0 });
  app.provide(ZINDEX_INJECTION_KEY, { current: 0 });
  return renderToString(app);
}

describe("desktop usability regressions", () => {
  it("shares responsive column and scrollbar sizing between workspace and footer", () => {
    const css = readFileSync(new URL("../style.css", import.meta.url), "utf-8");
    expect(css.match(/grid-template-columns: var\(--workspace-columns\)/g)).toHaveLength(2);
    expect(css).not.toContain("max-width: 760px;");
    expect(css).toContain("@media (max-width: 760px)");
    expect(css).toContain("--workspace-columns: minmax(0, 1fr);");
    expect(css).toContain("scrollbar-gutter: stable;");
  });
  it("offers full log view and copy instead of unsupported browser downloads", async () => {
    const html = await render(LogPanel, { lines: ["ERROR: 中文诊断"], zh: true, copying: false });
    expect(html).toContain("复制完整日志");
    expect(html).toContain("查看完整日志");
    expect(html).not.toContain("导出完整日志");
    expect(html).toContain('role="log"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain("ERROR: 中文诊断");
  });

  it("places recursive scanning in Output, not inside Advanced", async () => {
    const html = await render(SettingsPanel, { settings: { recursive: true } as Settings, disabled: false, zh: true });
    expect(html.indexOf("递归扫描子目录")).toBeGreaterThan(html.indexOf(">输出</h3>"));
    expect(html.indexOf("递归扫描子目录")).toBeLessThan(html.indexOf("高级设置"));
    expect(html.match(/递归扫描子目录/g)).toHaveLength(1);
  });

  it("uses the existing application image for branding", () => {
    const app = readFileSync(new URL("../App.vue", import.meta.url), "utf-8");
    expect(app).toContain('import appIcon from "../../assets/icons/VideoMergingTool.png"');
    expect(app).toContain(':src="appIcon"');
    expect(app).not.toContain("VideoCamera");
    const main = readFileSync(new URL("../main.ts", import.meta.url), "utf-8");
    expect(main.match(/\bElDialog\b/g)).toHaveLength(2);
  });
});
