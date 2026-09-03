# 贡献指南

[English](CONTRIBUTING.md) | 简体中文

感谢你改进 News A/B toolkit。

公开仓库接收 bug/功能 issue，以及小型 PR。它不接收任何新闻议题相关数据，包括建议和投稿（它们应走 news-ab.com 的网页表单渠道）。

请从本库 fork 一份干净的版本再提 PR。生成自己的新闻报告是另一条路径：直接 clone，那份 Git 历史应仅留在你自己手里（见 README）。

## 提交前

1. 新测试应使用完全 synthetic 的 outlet、URL、句子、topic/publication/run id；不要从已发布议题删字段后充当 fixture。
2. 行为变化同步更新对应 package/skill 文档；不要把一次性运行记录写成永久方法合同。
3. 从仓库根目录运行：

   ```sh
   uv sync          # 每个 checkout 一次；按根目录 pyproject.toml 建 ./.venv
   uv run pytest    # 全套（packages + tests）
   ```

## DCO 与许可

本项目采用 inbound=outbound：你提交的原创改动按仓库的 MIT 条款提供。每个 commit 必须带
Developer Certificate of Origin 1.1 的 sign-off：

```text
Signed-off-by: Your Name <your.email@example.com>
```

可用 `git commit -s` 添加。sign-off 表示你有权按该许可提交这些改动；不要把第三方代码、图片、
字体、数据或文本标成自己的原创内容。确需引入第三方材料时，PR 必须说明来源、许可与所需 notice，
并同步更新 `THIRD_PARTY_NOTICES.md`。

## one-way contribution bridge

早期阶段，公开仓库由私有运营仓库的 `public_export.yaml` 确定性生成。maintainer 审核通过公开 PR
后，会把该 patch 应用到私有仓库的同路径，保留作者和 PR URL，运行完整测试，再重新 export；只有
导出结果与 PR 合并后的公开树一致时才合并。请勿依赖只存在于导出产物、无法回到定义源的手工修改。

安全问题请使用 repository 的 private security-reporting channel，不要在公开 issue 中粘贴 secret
或可利用的私有数据。
