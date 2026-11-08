# Arco 组件知识库

本目录属于 **plusplus 编译器**，供生成前端时检索和只读查阅，不复制到目标应用。

```text
arco/
├── components.json       # 组件用途源数据
├── guide.md              # 接入及检索指南
├── components/           # 按组件展开的用途资料
└── api/2.66.18/          # 固定版本的官方 TypeScript 声明、许可及清单
```

智能体通过只读虚拟路径 `references/arco/` 访问这里。这个路径由编译器文件工具解析，
不是目标应用里的文件夹。list_files/search_files/read_file 均可访问；edit_file 不可修改。
例如 `references/arco/components/Table.md` 或
`references/arco/api/2.66.18/Table/interface.d.ts`。

UI/Trigger 设计从 components.json 检索用途资料，实现和修复查阅同一知识库。
目标应用只安装 Arco 依赖并使用实际组件、Provider 和样式；`.arc` 可保存版本、
哈希和检索命中 ID，不承担知识库分发。

用途文档是编译器整理的资料，不是官网镜像。API 声明来自
[@arco-design/web-react 2.66.18](https://www.npmjs.com/package/@arco-design/web-react/v/2.66.18)，
保留原包许可。manifest.json 记录来源及逐文件 SHA256，运行生成阶段不改写本目录。
维护 components.json 后，在 plusplus 根目录执行
`python -m infrastructure.stages.frontend.arco_knowledge --rebuild-guides` 更新展开文档。
升级 Arco 时应同时更新依赖版本、组件/回调目录和本目录中的 API 快照。
