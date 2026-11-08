# Steps — Arco React 2.66.18

流程进度、详情键值、状态标签、数量徽标。Steps, process progress, descriptions, status, badge.

适用：展示真实后端状态、详情字段或计数。

注意：Steps 不是审批执行引擎；标签颜色不决定业务状态。

关键属性：Steps.current, Steps.status, Descriptions.data, Tag.color, Badge.count, Badge.status

- 状态值和可用动作来自后端契约，页面只展示或发起允许的命令。

回调（参数名为编译器约定）：
```json
{}
```

同组用法示例（非生产数据）：
```tsx
<Descriptions data={detailFields} />
```

只读类型目录：references/arco/api/2.66.18/Steps

官方参考：
- https://arco.design/react/components/steps
- https://arco.design/react/components/descriptions
- https://arco.design/react/components/tag

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
