# Switch — Arco React 2.66.18

布尔开关、多选框、单选选项、多选组。Boolean, checked, multiple choices, radio, toggle.

适用：Checkbox/Switch 控制布尔状态；Radio.Group 表达互斥选项；Checkbox.Group 表达集合。

注意：checked 和 value 含义不同；不要从事件 target 推断 Arco 回调的第一项。

关键属性：Checkbox.checked, Switch.checked, Radio.Group.value, Checkbox.Group.value, options, onChange, disabled

- Form 内布尔字段按实际 triggerPropName 绑定 checked，参考 Form.Item 声明。

回调（参数名为编译器约定）：
```json
{
  "onChange": [
    "checked",
    "event"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<Switch checked={enabled} onChange={checked => setEnabled(checked)} />
```

只读类型目录：references/arco/api/2.66.18/Switch

官方参考：
- https://arco.design/react/components/checkbox
- https://arco.design/react/components/radio
- https://arco.design/react/components/switch

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
