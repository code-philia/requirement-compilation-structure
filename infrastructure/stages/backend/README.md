# 后端证据编译与实现

生成流程为：需求及截图 → ER 设计 → **共享后端语义设计（02B）** → 数据读写义务
→ 数据库实现 → API/PQ 设计 → 业务实现。共享语义在所有业务模块分析之前确定，
避免每个接口自行解释角色、状态和团队边界。普通 CRUD、查询、导入导出、库存及财务
规则仍然按完整需求编译；权限和审批是这些业务操作的约束。

## 输入与中间产物

`evidence.py` 无模型读取标准路径下的 `reference/authorization/{catalog.json,
model.conf,policy.csv}` 和 `reference/bpmn/{index.json,coverage.json,*.bpmn}`。
XML 路径以实际 index.xml 为准，不要求扩展名。校验目录项、策略、组织层级、
BPMN 节点/连线/角色泳道和需求引用，保留源文件哈希及自然语言条件。
父级约束、依赖模块、场景、ER、策略和流程引用一起进入需求上下文。
需求依赖展开到叶子后排序；未知依赖和循环依赖明确失败。

`foundation.py` 统一产生 `.arc/backend_foundation.json`：

| 字段 | 含义 |
| --- | --- |
| `default_boundary` / `boundary_requirements` | 无边界、当前组织或组织子树，以及来源需求 |
| `additional_permissions` | 有来源依据的有效策略补充，原 CSV 保持不变 |
| `features` | 功能准入，与实体 CRUD 权限分开，例如明确的演示账号限制 |
| `machines` | 实体状态字段、初态、状态可用动作、事件与角色、前置条件及副作用字段 |
| `process_dispositions` | 每个源流程落实为状态机还是普通事务操作，及原因 |
| `schema_adjustments` | 仅用于有明确场景依据的生成关系 FK 可选化，必须引用对应 ER 关系 |
| `decisions` | 原始证据缺口/冲突、采用的行为及需求依据 |

原始策略、BPMN 图、场景和哈希另存 `.arc/backend_evidence.json`。自然语言网关条件
不直接执行。模型必须根据完整业务场景解释它们，再将可执行约束落实到 API 的 P/Q
和处理函数。源 BPMN 的 `isExecutable=false` 不阻止将其作为设计证据。

不硬编码 WMS 表名、流程名或角色清单。当前支持发布格式的域 RBAC 模型，范围为
`all/own/unit/unit_tree/assigned`，实体资源映射同名 ER 表，要求单主键。无证据输入保留
原流程；仅有 BPMN 而没有权限目录会明确报错。保留的基础设施表名发生业务冲突时
明确失败，不悄悄重命名。接入其他证据格式需扩展 importer。

## 生成应用中的库与职责

- [node-casbin](https://github.com/apache/casbin-node-casbin/blob/master/README.md)
  **5.51.1**：持久化用户/组织角色绑定，执行资源动作及记录范围策略。
  使用[带域的 RBAC](https://casbin.apache.org/docs/rbac-with-domains/)。源策略全部
  `all` 时，需求规定的团队隔离仍作为额外边界。管理员身份只由数据库角色确定，
  拥有所有应用权限；状态合法性和业务前置条件仍然适用。
- [XState](https://stately.ai/docs/pure-transitions) **5.33.3**：以纯转换计算合法目标状态，
  SQLite 持久化状态，数据库比较旧状态后更新。BPMN 是业务证据，当前不是完整 BPMN 引擎。
- [decimal.js](https://mikemcl.github.io/decimal.js/) **10.6.0**：供生成业务代码处理 ER 中
  精确十进制文本字段，金额、数量汇总不能直接依赖 JS Number/SQLite 浮点 SUM。

共享表包括 `users/org_units/roles/user_ou_roles/auth_sessions/record_access/
command_receipts/workflow_audit/platform_meta`。已有辅助用户/组织表会扩展为基础设施表。
账号使用 scrypt 哈希，源 `test account` 的 SEED 记录用于初始化，不覆盖已有密码。
缺省管理员账号为 `admin`，缺省密码为 `admin123456`；源中已有 admin 时采用源配置。
单组织已有业务记录可初始化归属；多组织旧记录不会猜测归属，普通用户访问无归属
记录时拒绝，必须明确完成数据迁移。当前面向新输出目录，没有自动迁移既有应用数据库。

## API 契约与业务实现

`contracts.py` 为每个业务 API 要求 `security`、`process_refs` 和 `workflow`：

- `security` 声明资源、动作、主记录选择器、操作类型和功能准入。
- `workflow` 绑定全局状态机/转换，将每个 guard/effect 映射到 API 的 P/Q。
  涉及其他单据的复合操作可声明 `related_transitions`，在同一事务内调用
  `await request.access.advance(machine, transition, recordId)`。
- 校验规范 ID、状态字段、角色动作、流程覆盖和副作用写字段，保留原有读写义务覆盖。
  库存、金额、关联单据、撤销补偿等都必须按场景明确设计并实现，不能只切换审批状态。

编译器固定生成路由、认证、鉴权、事务及状态更新代码。生成模型只实现业务 `handle`，
不能通过文件工具修改这些基础设施。API 到文件的映射保存在
`.arc/backend_implementation_files.json`，共享 API 使用全部关联需求作为上下文。

处理函数从 `request.access.principal` 获取可信身份；列表、统计、导出和关联查询
使用 `request.access.scope(resource, action, 'alias.id')` 的参数化 SQL 片段。
通过 `request.access.assign` 进行显式授权的任务分配。客户端传入的角色、组织和
owner 字段不能替代持久化身份及归属。SQL 连接外观禁止处理函数控制事务、DDL 或连接生命周期。

权限检查后，事务包含业务校验/副作用、关联转换、主状态 CAS、审计和幂等回执。
失败返回或异常全部回滚。事务结束检查业务写字段、数据边界、关联记录及基础设施改动；
审计只能由平台写入。流程及批量命令要求幂等键，同键不同请求拒绝，成功重放返回原结果。

## HTTP 与后续生成

固定端点为 `POST /api/auth/login`（username/password，可选已分配的 unit）、
`GET /api/auth/me`、`POST /api/auth/logout`。登录及 me 返回 `user` 与 `csrfToken`，
会话使用 HttpOnly、SameSite=Lax Cookie，HTTPS 时加 Secure。后续变更请求发送
`X-CSRF-Token`，流程/批量请求还发送 `Idempotency-Key`。业务路由都要求登录。
前端实现上下文同步携带这些协议及统一语义。

生成算法原有的业务验收阶段补充真实角色拒绝、跨组织查询/变更、流程非法状态、
失败无副作用、幂等及撤销场景的生成指令；范围依据需求，不强行增加多级审批。
身份端点属于编译器基础设施，不让模型为每个系统重新生成认证协议。

## 当前边界

支持每个实体一个扁平持久状态机、角色与当前经办人约束，以及同一数据库事务内的多个记录转换。
业务 guards/effects 仍由生成代码执行；引用校验本身不能证明业务逻辑正确。
完整并行会签、计时器、外部事件和跨服务事务未实现，遇到这类需求需要扩展运行时。

当前写入保护以事务前后数据快照校验，SQLite 请求通过进程内队列串行执行，
适合首版生成应用；大数据量应改为更细粒度的数据库约束/变更跟踪。
读取侧能检查声明的资源是否请求过 scope，但不能静态证明任意生成 SQL 正确使用了
该片段；跨组织列表、统计及导出隔离仍须通过生成应用的行为验收确认。

WMS 输入已做无模型解析检查，共 299 条策略、7 个流程、33 个需求节点。
生成的基础设施已通过 TypeScript 构建，尚未执行完整 WMS 模型生成及端到端验收。
根节点的 8 条业务观察数据仍缺少规范实体绑定；账号初始化不意味着这些业务数据
已完成导入，也不代表输入已经通过完整 producer-spec 校验。
