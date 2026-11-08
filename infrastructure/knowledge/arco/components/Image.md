# Image — Arco React 2.66.18

图片预览、非表格列表、条目、树形浏览与选择。Image preview, list, item, tree browsing.

适用：图像或松散列表，树形结构导航；多列记录比较优先 Table。

注意：不要将截图数据当生产记录；普通 List 不自动提供后端分页或权限过滤。

关键属性：Image.src, Image.alt, List.dataSource, List.render, Tree.treeData, Tree.selectedKeys, Tree.onSelect

- List 的数据属性是 dataSource，与 Table.data 区分。
- 树节点保留真实 ID，选择结果不能代替服务端权限判断。

回调（参数名为编译器约定）：
```json
{}
```

同组用法示例（非生产数据）：
```tsx
<List dataSource={rows} render={row => <List.Item key={row.id}>{row.name}</List.Item>} />
```

只读类型目录：references/arco/api/2.66.18/Image

官方参考：
- https://arco.design/react/components/list
- https://arco.design/react/components/tree
- https://arco.design/react/components/image

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
