# Cascader — Arco React 2.66.18

下拉选择、远程搜索、组织树选择、层级级联。Select, searchable options, hierarchy, organization tree, cascader.

适用：Select 适合平面选项；TreeSelect 适合树节点；Cascader 适合路径层级。

注意：不要把所有选择器当成原生 select；不要把展示 label 当持久化 ID。

关键属性：value, options, onChange, allowClear, Select.showSearch, Select.filterOption, Select.onSearch, TreeSelect.treeData

- 远程搜索管理 loading 与响应顺序，后端限制的数据由后端筛选。
- 回调值与 option/extra 根据该组件类型声明读取。

回调（参数名为编译器约定）：
```json
{
  "onChange": [
    "value",
    "selectedOptions",
    "extra"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<Select value={selectedId} options={options} onChange={value => setSelectedId(value)} />
```

只读类型目录：references/arco/api/2.66.18/Cascader

官方参考：
- https://arco.design/react/components/select
- https://arco.design/react/components/tree-select
- https://arco.design/react/components/cascader

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
