# Input.Search — Arco React 2.66.18

文本、密码、多行备注、搜索、数值输入。Text, password, textarea, search, number, decimal.

适用：按字段语义选择输入形式。精确十进制文本可用 Input 保留原始字符串。

注意：Input.onChange 第一项是 value，不是 DOM event；精确金额不要经 JS Number 损失精度。

关键属性：value, onChange, placeholder, allowClear, InputNumber.min, InputNumber.precision, Input.Search.onSearch

- Input.Search 将编辑与发起检索分开，避免 onChange/onSearch 重复请求。
- Number 控件按后端类型转换，空值不要静默视为零。

回调（参数名为编译器约定）：
```json
{
  "onChange": [
    "value",
    "event"
  ],
  "onSearch": [
    "value"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<Input value={name} onChange={value => setName(value)} />
```

只读类型目录：references/arco/api/2.66.18/Input

官方参考：
- https://arco.design/react/components/input
- https://arco.design/react/components/input-number

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
