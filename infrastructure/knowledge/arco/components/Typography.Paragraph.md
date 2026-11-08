# Typography.Paragraph — Arco React 2.66.18

信息分组、页标题、文本、说明、详情块。Card, title, text, paragraph.

适用：详情、表单分组、统计区域或原文说明。

注意：不要将示例业务记录写成固定文本，标题文案服从需求。

关键属性：Card.title, Card.extra, Typography.Title.heading, Typography.Text.type

- 动态业务名称来自真实数据；保留标题层级和可访问名称。

回调（参数名为编译器约定）：
```json
{}
```

同组用法示例（非生产数据）：
```tsx
<Card title={title}><Typography.Paragraph>{description}</Typography.Paragraph></Card>
```

只读类型目录：references/arco/api/2.66.18/Typography

官方参考：
- https://arco.design/react/components/card
- https://arco.design/react/components/typography

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
