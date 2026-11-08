# Arco React 生成参考

编译器使用 `@arco-design/web-react@2.66.18`，React 18。此文件是编译器整理的接入指南，
不是官网完整镜像。准确属性以该版本发布的类型声明为准。

## 参考来源与查询

- [快速上手](https://arco.design/react/docs/start)
- [官方源码与文档](https://github.com/arco-design/arco-design)
- [固定版本 npm 包](https://www.npmjs.com/package/@arco-design/web-react/v/2.66.18)
- [Form 接口](https://github.com/arco-design/arco-design/blob/main/components/Form/interface.tsx)
- [Table 接口](https://github.com/arco-design/arco-design/blob/main/components/Table/interface.tsx)
- [Modal 接口](https://github.com/arco-design/arco-design/blob/main/components/Modal/interface.ts)

安装依赖后，编译器将该版本 `es/**/*.d.ts` 复制到 `frontend/arco-api/`，文件工具可读取。
从 `frontend/arco-api/COMPONENT/interface.d.ts`、`index.d.ts` 或具体组件的声明入手。
按需查阅引用的其他声明；不要修改这些参考文件，也不要将其当作本地组件导入。
清单在 `.arc/arco_types.json`。升级版本时需同步调整编译器组件/事件目录和声明，不能只改包名。

## 组件检索与文件查阅

组件用途资料来自编译器的 `arco-components.json`，覆盖允许目录中的 58 个组件/子组件。
每项含用途、适用/不适用场景、关键属性、交互模式、简例和来源。生成项目的
`frontend/arco-components/index.json` 及每组件 Markdown 提供同一份只读资料。
它们不是完整官网镜像，也不取代固定版本的 API 声明。

第 07 阶段根据当前需求和已检索页面，用 BM25 选择用途候选；同组子组件候选去重，
保留组件之间的比较信息。已有页面/当前 UI 明确选定的组件始终带入，不受 top-k 限制。
第 09 阶段同样检索已选组件的交互资料。BM25 是词法匹配，不需要向量数据库；
没命中不等于库里没有合适组件。设计模型可通过已有 JSON 查询协议进一步搜索：

```json
{"context_request":{"kind":"component","query":"远程搜索 下拉选择"}}
```

查到 ID 后读取完整记录：

```json
{"context_request":{"kind":"component","ids":["Select","TreeSelect"]}}
```

第 08/10 阶段及前端修复显式启用只读文件发现工具。调用仍是普通模型 JSON，
由编译器执行，不依赖模型提供商的原生 function calling。先找文件：

```json
{"tool_calls":[{"tool":"list_files","glob":"frontend/arco-api/Select/**/*.d.ts","limit":20}]}
```

然后搜索具体属性：

```json
{"tool_calls":[{"tool":"search_files","query":"onChange","glob":"frontend/arco-api/Select/**/*.d.ts","context":2,"limit":10}]}
```

再按返回路径与行号使用 read_file。也可在 `frontend/arco-components/*.md` 搜索中文用途，
或在任务授权的应用源码中找已有组件用法。支持 next_offset 分页；搜索为不区分大小写
的字面字符串，不是正则或 shell 命令。`**` 匹配零层或多层目录。

文件发现受任务现有范围和排除规则约束，不能访问 node_modules、隐藏目录、越界路径
或符号链接。每次最多返回 100 项；内容搜索限制上下文、长行、总片段长度、扫描文件数
和字节数。看到 scan_truncated/skipped_files 时应缩小 glob，不能推断内容不存在。
大批只读参考路径不再全部注入 scope.existing_files，可通过 list_files 获取。
发现工具只返回路径/片段，文件写权限保持原来的限制。后端等其他智能体默认不增加这些工具。

初始检索结果保存在 `.arc/arco_retrieval.json`；设计阶段的 component 按需查询保存在
`.arc/arco_queries.jsonl`。`.arc/arco_knowledge.json` 记录知识库版本与哈希。

## 全局设置

```tsx
import { Button, Form, Input, Table, Modal } from '@arco-design/web-react';
import { IconPlus } from '@arco-design/web-react/icon';
```

应用根使用 `frontend/src/design-system.tsx` 的 `DesignSystemProvider`。
它加载全局 Arco CSS，默认简体中文。其他语言从 `@arco-design/web-react/es/locale/` 导入
对应 locale，传入 provider。业务标签严格采用需求原文，不以组件库语言替代业务文案。
Tailwind 保留布局工具类，移除 preflight，避免重置组件样式。优先用 Arco 默认设计、
全局 token 和局部页面样式；不要逐个覆盖内部类来模仿其他组件库。

## UI 设计与实现

保留 `element.type` 的语义类型（input/button/table 等），另记组件选择：

```json
{"type":"input","component":{"library":"arco","name":"Input"},"data":[],"prop":{"label":"名称"}}
```

布局、页壳、菜单优先采用 Layout/Menu/Breadcrumb/Space/Grid；表单采用 Form/Form.Item，
表格采用 Table，弹窗采用 Modal/Drawer，反馈采用 Alert/Empty/Spin/Message 等实际接口。
Message 是实现时调用的反馈 API，无须把函数调用伪装成页面元素。
原生 HTML 用于 main/section 等语义节点或可视化容器，需在 component.reason 说明。
表单、输入、选择、按钮和表格仍使用 Arco；没有需求的高级控件不必添加。

`Form.Item` 有 field 时由 Form 收集值，必须正确关联 label 与实际输入 id。使用
`Form.useForm()` 配合 setFieldsValue/resetFields 处理异步加载、切换对象、取消和重置。
明确选择 Form 管理字段或控件受控状态，避免两套值不同步。initialValues 不能替代重新加载。
Button 的 `type` 是视觉风格，提交按钮应使用 `htmlType="submit"`。

Table 使用 `data`、`rowKey`、`columns`，不是其他库的 dataSource。选择行用持久主键；
行操作从 columns.render 的 record 闭包取对象，不能从图标的 event.target 读取主键。
服务端分页用受控 pagination，过滤或分页变化调用对应读取 API。已分页数据不能再按前端
分页切片。汇总、导出和权限仍以服务器结果为准。

Modal/Drawer 使用 `visible`，不是 open。确认处理中使用适用的 loading/confirmLoading；
失败保留输入并显示错误。Modal.onOk 可委托 form.submit，但实际请求只在一个提交入口执行。
弹出内容可能通过 portal 挂载到 body；可见内容和稳定测试标记必须在真正渲染的弹窗里。
不创建空 div 或隐藏控件来满足元素存在性要求。重复行的控件必须按行定位。

InputNumber 默认处理 JS 数值；精确金额/数量文本优先使用 Input，再按后端契约校验，
不要通过 Number 破坏精度。日期回调包含字符串和 Dayjs 对象，按 API 的日期/时区协议转换。
上传文件必须确认后端接口，不依赖 Upload 默认自行请求一个不存在的地址。

## Trigger 设计与实现

语义事件和实际组件回调分开记录。例如：

```json
{"source":"UI-name","event":"change","binding":{"component":"Input","callback":"onChange","arguments":["value","event"]},"guard":null,"read":[],"write":["name"],"action":[{"kind":"ui","ui":"UI-name","description":"将 value 更新到 name"}]}
```

完整回调目录在模型输入的 frontend_stack.components 中。Input/Select/InputNumber 的
onChange 第一项是值，Checkbox/Switch 第一项是布尔值，Form.onSubmit 收到已校验的表单值。
不要套用所有控件都接收 DOM event 的假设。Table 的 onRow.onClick 是嵌套绑定，record 来自
onRow(record) 闭包。生命周期用 binding.callback=useEffect，arguments=[]，不伪装为组件属性。

第 08 阶段只实现布局、原生编辑和导航；第 10 阶段扩展同一提交/点击处理函数，不能再挂
独立监听器导致重复请求。实现包括 API 参数、校验、pending、成功/失败反馈、重载、取消、
异步竞争处理。后端要求的 Cookie、CSRF、幂等键必须沿用。UI 隐藏按钮不能替代后端鉴权。

## 浏览器定位

交互以实际可访问名称和角色定位。Arco Select 是自定义弹层，不对它调用原生 selectOption；
打开后定位实际选项。日期、菜单、Modal 等同样要考虑 portal，按可见弹层范围定位。
不依赖内部 CSS 类名、私有 DOM 层数或固定截图数据。单次提交只应产生一次业务变更。
只读/禁用/加载/错误状态必须符合需求及后端返回，不为组件库新增业务规则。
