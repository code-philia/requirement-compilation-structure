# Button — Arco React 2.66.18

按钮动作、提交、取消、导航链接。Button, action, submit, cancel, link.

适用：用户明确触发操作或导航。

注意：不要把 Button.type 当成 HTML submit 类型；不要在按钮和 Form 重复提交。

关键属性：Button.type, Button.htmlType, Button.loading, Button.disabled, Link.href

- 表单提交使用 htmlType=submit，业务请求统一由 Form.onSubmit 负责。

回调（参数名为编译器约定）：
```json
{
  "onClick": [
    "event"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<Button type="primary" htmlType="submit" loading={pending}>保存</Button>
```

只读类型目录：references/arco/api/2.66.18/Button

官方参考：
- https://arco.design/react/components/button
- https://arco.design/react/components/link

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
