# News A/B 新闻对比报告生成器

[English](README.md) | 简体中文

![](title.png)

复制本代码库到本地、打开你的 AI agent（Codex / Claude Code），告诉它你感兴趣的新闻议题、以及两组需要对比的媒体——你的 agent 便可以使用库内的 skills 和 Python 脚本，在本地生成每个结论均可逐句审计、且经过统计检验的新闻对比报告网页。成品如下所示：

[news-ab.com](https://news-ab.com/)

本库分享的是 news-ab.com 网站背后的一套可复用、实验性质的 AI 工作流。Python 包与各种脚本仍包含 News A/B 或 `newsab` 字样，但本库与该网站没有运营关系，亦不包含网站数据。

## 报告生成流程

本流程把采集来的样本报道整理成共享的“问题 × 答案”模型：先将重复报道（转载）聚成独立报道组，再用同一组问题询问两侧媒体，比较回答率与答案，最终只报告能够追溯到报道原句且有一定统计支持的发现。

确定性工作（如校验与统计）由代码完成。采集、提问、标注、写作、自审中的语义部分由 AI 完成。最初的采集范围确认和最终的成品页各有一次人工审核。

流程并非线性：主 agent 会根据阶段产物和代码反馈，自行做出是否推进、返工、指派 subagent、请求额外人工审核等决策。

| 步骤 | 执行者 | 产出或决定 |
|---|---|---|
| 0. 输入需求 | 用户 | 大致的“议题 + A/B 媒体分组”范围 |
| 1. scope | AI | 制定采集计划与参考问题 |
| 1.5 人工触点一 | 用户 | 确认采集范围，审核参考问题 |
| 2. collect | AI/代码 | 分侧平衡采集、句子化语料、独立报道组 |
| 3. annotate | AI | 提出问题、subagent 标注答案与句级证据 |
| 3.5 normalize | AI/代码 | 跨两侧和批次的答案类别归一 |
| 4. analyze | 代码 | 回答率和答案比较、统计检验与置信区间 |
| 5. write | AI | 以统计结果为约束，撰写英文母版页面文案 |
| 6. render + localize | AI/代码 | 页面校验、subagent 自审，译成审核语言 |
| 7. 人工触点二 | 用户 | 检视候选成品页；意见可打回到对应步骤修正 |
| 8. publish | 代码 | 冻结静态报告（可选：多语言发行） |

### 单次运行成本

目前完成一整轮议题报告的平均成本估计：

| agent 活跃时长 | 模型请求 | token 总量 | 按 API 标价折算 |
|---|---|---|---|
| 约 3-4 小时 | 约 500-1300 次 | 约 1.6 亿 | 约 $100-150 |

“活跃时长”不计等待人工审核的时间。token 总量里绝大部分是输入。**推荐用订阅计划而不是 API key 来跑**。若使用最基本的订阅计划，中途等待额度限流可能会把实际时间拉长到2-3个五小时额度区间。

## 开始使用

用会读取 `AGENTS.md` 或 `CLAUDE.md` 的 agent 打开 clone，然后直接让它配置 workspace 并生成报告。例如：

> 先为我配置这个 News A/B workspace，然后生成一份关于 `<议题>` 的对比报告，对比 `<A 组媒体>`与 `<B 组媒体>` 的报道。

首次运行时，agent 会向你询问你的公开网站与联系邮箱，并写入你自己的本地文件`.newsab/operator_identity.json`（gitignore）。此信息仅用于你的 agent 用程序化网络浏览工具采集新闻时：代码会合规地向新闻网站展示访问者身份（应是你，而不是某大厂的 agent）。身份未配置前，采集工具会拒绝联网。首次运行时，agent 也会安装必要的依赖环境（python 3.10+）并运行离线验收 gate：

```sh
uv sync                  
uv run python tools/public_release_gate.py
```

## 打包已完成的报告

如果你希望 News A/B 网站考虑发布你自己生成的完整本地报告，可以让 agent 打包，然后在 news-ab.com 上投稿。你上传的稿件在通过人工审核后会发布。

投稿包会先在本机完成验证：

```sh
uv run python -m newsab_submission pack topics <topic_id> --out submission.tgz --json
uv run python -m newsab_submission inspect submission.tgz --json
uv run python -m newsab_submission verify submission.tgz --json
```

该数据包含新闻来源逐字快照，须保持私密；不要把它放进 GitHub issue、PR、release、邮件里。

## 数据与贡献边界

不要通过 GitHub issue、PR 或 release 上传文章 archive、凭据、个人资料或投稿。

你每次运行新闻报告的产物都会被 AI commit 进你自己的本地 clone——这份历史是 agent 跨会话协作的关键。新闻正文本身不会进 git，但那些小体积的运行记录会逐字引用来源句子。所以要么让 clone 只留在本机，要么 push 到一个你自己建立、自己掌握的私有仓库。想贡献代码时再从本库 fork 干净的版本。

代码与文档贡献规则见 [`CONTRIBUTING.zh-CN.md`](CONTRIBUTING.zh-CN.md)；许可边界见 [`LICENSE_SCOPE.md`](LICENSE_SCOPE.md)。
