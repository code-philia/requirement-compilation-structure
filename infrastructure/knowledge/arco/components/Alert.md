# Alert — Arco React 2.66.18

错误、成功、警告、空数据、加载状态、结果页、操作提示。Error, feedback, empty, loading, result, tooltip.

适用：区分加载中、无记录、请求失败及业务拒绝。

注意：不能用空态掩盖请求错误，不能用 Tooltip 替代唯一可访问名称。

关键属性：Alert.type, Alert.content, Empty.description, Spin.loading, Result.status, Tooltip.content

- 反馈与提交 pending 由真实结果驱动，不制造成功。
- 瞬时反馈可调用 Message/Notification；它们不是 element.component 组件。

回调（参数名为编译器约定）：
```json
{}
```

同组用法示例（非生产数据）：
```tsx
<Spin loading={loading}>{error ? <Alert type="error" content={error} /> : content}</Spin>
```

只读类型目录：references/arco/api/2.66.18/Alert

官方参考：
- https://arco.design/react/components/alert
- https://arco.design/react/components/empty
- https://arco.design/react/components/spin

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
