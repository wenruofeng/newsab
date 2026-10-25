# TODO

Work queue for this clone. Keep only what is next; completed items link to their task report.

## 文档

- [x] 拆分核心规范：读者页面细节移至 `docs/reader_page.md`，内容文档 / 站点外观契约移至 `docs/artifact_versioning.md` §6.1 —— [报告](docs/reports/task_202610242255_spec-split.md)
- [ ] 上游同步：私有仓库应用此补丁时，`public_export.yaml` 已登记 `reader-page-spec`；需在上游重新导出 `export-manifest.json`（本 clone 中只刷新了被改文件的哈希与 contract 哈希）。
- [ ] 观察一次完整议题运行的 token 用量，确认拆分后主 agent 的上下文负担是否下降；若 `write` / `render-localize` 阶段确实需要页面模块细节，在其 SKILL.md 中按需引用 `docs/reader_page.md`，不要整篇加载。

## 下一个议题：东南亚烟霾

- [ ] **东南亚烟霾与新加坡对印尼企业的法律行动** —— 用户 2026-10-25 选定。在本地 clone 中运行（语料只存本地、不入库），不在云端会话中做。
  - 初步 A/B：印尼语媒体 vs 新加坡 / 马来西亚媒体（英语 / 马来语）。新马合成一组的理由需在 scope 中写明，或改为仅新加坡。
  - 大致窗口：2026-08-01（本季火情开始）至东盟峰会后约一周。节点：10/9 马来西亚停课；10/16、10/19 新加坡依《跨境烟霾污染法》向共 10 家印尼企业发出法律通知；印尼总统普拉博沃回应称印尼不会任人“羞辱”。
  - 可能的问题：责任在企业、印尼政府还是气候（厄尔尼诺）？新加坡的法律行动是否侵犯主权？应当如何应对（合作救火 / 追责 / 东盟机制）？引述谁的声音？
  - 首次运行前确认 `.newsab/operator_identity.json` 已配置。
  - 其他候选及理由见 [报告](docs/reports/task_202610242255_spec-split.md)「候选议题」一节。
