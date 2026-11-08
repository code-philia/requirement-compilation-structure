# Table — Arco React 2.66.18

数据表格、列、行操作、分页、排序、筛选、多行选择。Table, row action, pagination, sorting, filters, selection.

适用：结构化数据集合及服务端分页；需稳定行标识。

注意：Table 使用 data 而非 dataSource；不要再次分页已由服务器分页的数据。

关键属性：Table.data, Table.columns, Table.rowKey, Table.pagination, Table.loading, Table.rowSelection, Table.onChange, Pagination.current, Pagination.total

- columns.render 的 record 闭包携带行 ID；onRow.onClick 的 record 来自 onRow(record)。
- 分页/排序/过滤变更组合成真实读取 API 参数；清除失效选择。

回调（参数名为编译器约定）：
```json
{
  "onChange": [
    "pagination",
    "sorter",
    "filters",
    "extra"
  ],
  "rowSelection.onChange": [
    "selectedRowKeys",
    "selectedRows"
  ],
  "onRow.onClick": [
    "event"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<Table rowKey="id" data={rows} columns={columns} pagination={{current,pageSize,total}} onChange={reloadPage} />
```

只读类型目录：references/arco/api/2.66.18/Table

官方参考：
- https://arco.design/react/components/table
- https://arco.design/react/components/pagination

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
