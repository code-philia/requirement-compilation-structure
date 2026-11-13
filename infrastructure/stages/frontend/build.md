# 前端逐需求设计、测试与实现

入口 `build_frontend`，替代独立前端 outline 和旧 UI/trigger 实现阶段。
按依赖顺序仅遍历叶节点；每个叶节点使用一个 `FrontendBuildAgent(BaseAgent)`，
共享客户端、对话和工具日志，先设计，再生成测试，最后实现和修复。

| 步骤 | 工具 | 行为 |
| --- | --- | --- |
| 设计 | `save_design`、`get_ui_design`、`get_backend_apis` | 简述页面/组件/公共逻辑、路由、主要状态、API 与实现文件职责 |
| 生成测试 | `begin_tests`、`write_test`、`begin_tdd` | 先写源场景的 Playwright 测试，编译测试后保留断言并开放实现 |
| 实现 | `edit_file`、`run_tests`、`finish_requirement` | 实现 React/Arco 和真实 HTTP，验收当前及已接受需求，失败则在原对话修复 |

设计是协调信息，不生成组件树、触发器 DSL、props 契约或 UI 解释器。提示词要求
`App.tsx` 主要负责路由/组合，按功能拆分页面；有独立职责的表格、编辑表单、弹窗
分别落到组件文件，跨页面的 shell/session、HTTP client、hooks 和类型复用现有模块。
不要求为每个按钮创建文件，也不规定行数门槛或机械的层级目录。

启动仅提供关联需求与父节点规则、图片分析和 UI 状态证据、相关 schema、后端接口
摘要、少量已有 UI 设计、Arco 参考与固定测试说明。UI 设计以 BM25 选取复用候选，
实际后端契约按 API ID 批量获取，重复且未变化的完整定义返回上下文引用。
阶段切换不重复展开全部文件和设计，通过测试只返回简短计数；完整证据留在日志和报告。

测试期的初始检查仅验证测试可编译，明确标记 `TESTS_COMPILED`，不代表行为通过；
避免在 UI 尚不存在时逐场景等待浏览器超时。实际完成必须经过真实浏览器、真实
后端及独立临时数据库验收，包含累计回归、源场景覆盖和最终构建。
后端、schema、种子与已有验收测试始终只读；缺失接口或上游错误报告具体修复项，
不在浏览器伪造结果。注册、身份、权限和流程采用真实后端契约，不预设业务表或登录协议。

只有一个实现修复预算：每叶默认 10 次，配置 `[clone] frontend_test_iterations`，
环境覆盖 `ARC_FRONTEND_TEST_ITERATIONS`，直接编译器变量 `FRONTEND_TEST_ITERATIONS`。
不设置独立探索/读取/模型调用硬上限，重复读取和连续无进展只给软提醒。未变化的
通过结果可复用；失败重试复用诊断并消耗重试次数。重复同类错误提示改变策略或报告
具体阻塞。最终集成修复沿用最后节点的剩余预算，不重启一个额外预算的 Agent。

当前测试默认只读；有源证据的机制缺陷可通过 `repair_test_mechanics` 临时授权
`write_test` 连续局部修正，下一次验收收回授权，禁止削弱业务断言。旧测试、固定
runner/fixture 和所有后端文件不可编辑。失败节点归档并回滚源码/依赖变化，其他节点
继续；失败草稿不进入已接受设计。重启复用已验收且输入未变化的需求与组件。

产物：`.arc/frontend_plan.json`、`.arc/frontend_implementation_files.json`、
`.arc/frontend_node_drafts/`、`.arc/frontend_e2e.json`、`.arc/incremental_frontend.json`。
沿用 `frontend_e2e.json` 与最终 build 结果接入 dashboard。调试命令：

```bash
uv run main.py /path/to/requirements -o /path/to/app --stage build_frontend --model-log
```

该命令先恢复 `build_backend` 成功结束的 Git 检查点，再执行前端阶段。

阶段号已统一为 00–06。旧 `07_build_frontend` 及旧前端子阶段名仍可作为 CLI 别名，
但会执行整个 `build_frontend`。历史 Git 检查点保留，兼容查找仅认可对应实现阶段
的成功记录，不把旧设计阶段的 GREEN 当作整个构建阶段已完成。

## smoke 运行后的通用优化

- `save_design` 接受 ID 映射、带 ID 的列表、单条记录。清理单个文件名后的
  `(existing)`、`(new)` 或职责附注，附注移到 `location_note`；拒绝多文件歧义和
  不安全路径。错误反馈一次列出有问题的条目、已知 ID 和最小可用示例，不逐项猜格式。
  `uses` 中可识别的文件引用转为 UI ID，Arco 引用单独记录；无法绑定的引用保留诊断，
  不作为新业务需求，也不阻塞整份设计。旧计划在检索/恢复前进行相同的路径清理。
  实现文件映射只发布真实存在的文件，未落地的提示另行记录，防止形成虚假文件索引。
- 固定的 `frontend/src/components/accessibility.tsx` 提供 `selectAriaLabel` 和
  `requiredLabel`。提示词要求复用而非重新发明标签包装，不同时命名外层 combobox
  与内部输入框。它不含业务字段或 fixture；阶段开始提供其源码摘要，前端 Agent 只读。
- 固定浏览器 helper `navigateAndAssert` 接收实际触发控件、目标 URL 和页面标识，
  可检查刷新、后退、前进，并记录已执行的导航证据。`chooseNamedOption` 验证唯一
  named combobox 后选择真实选项。路径、名称、数据全部由源需求提供，不固化某类应用。
  fixture 同时导出 `NavigationCheck` 和 `BrowserSession` 类型，减少测试导入错误。
  最终 `frontend_e2e.json.navigation_evidence` 展示点击证据和未记录证据的声明路由；
  它是诊断信息，不新增静态阻断门槛，也不把菜单存在/直接 goto 当作连通性证明。
- 原生 Agent 在 SDK 重试之后，对连接错误、408/409/429/5xx 最多额外重试两次，
  保留对话且不重复执行工具；401/403 等配置/权限错误不盲目重试。重试耗尽保留原有
  节点归档机制。前端准备步骤（Node、runtime、依赖、Arco 类型、Chromium）在
  `.arc/frontend_preparation.json` 记录进度，对运行时/系统错误最多重试一次；仍失败
  明确发布 FAILED 与恢复位置，不伪造通过或继续执行缺少环境的浏览器验收。
- 没有增加读取/探索硬预算，没有放开整文件替换保护，没有改变异步请求的竞态、
  取消、会话或退出登录逻辑。完整行为仍由真实应用验收判定。
