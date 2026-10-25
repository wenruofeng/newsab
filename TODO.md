# TODO

Work queue for this clone. Keep only what is next; completed items link to their task report.

## 文档

- [x] 拆分核心规范：读者页面细节移至 `docs/reader_page.md`，内容文档 / 站点外观契约移至 `docs/artifact_versioning.md` §6.1 —— [报告](docs/reports/task_202610242255_spec-split.md)
- [ ] 上游同步：私有仓库应用此补丁时，`public_export.yaml` 已登记 `reader-page-spec`；需在上游重新导出 `export-manifest.json`（本 clone 中只刷新了被改文件的哈希与 contract 哈希）。
- [ ] 观察一次完整议题运行的 token 用量，确认拆分后主 agent 的上下文负担是否下降；若 `write` / `render-localize` 阶段确实需要页面模块细节，在其 SKILL.md 中按需引用 `docs/reader_page.md`，不要整篇加载。

## 候选议题（待用户选定后进入 scope）

候选清单及理由见 [报告](docs/reports/task_202610242255_spec-split.md)「候选议题」一节。首选：中美第八轮经贸磋商成果；东南亚烟霾与新加坡起诉印尼企业；希伯伦军事行动（希伯来语 vs 阿拉伯语）。
