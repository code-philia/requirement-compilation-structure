# Divider — Arco React 2.66.18

页面壳、顶部导航、侧边菜单、内容区域及响应式布局。Application shell, header, sidebar, spacing, grid.

适用：多个页面共用 shell，工具栏按钮间距，表单分栏布局。

注意：不把布局组件当成数据加载或路由引擎；不要为每个截图复制页面壳。

关键属性：Layout.Sider.collapsed, Space.direction, Space.size, Grid.Row.gutter, Grid.Col.span

- 菜单选择与实际路由同步；折叠状态与业务记录分开。

回调（参数名为编译器约定）：
```json
{}
```

同组用法示例（非生产数据）：
```tsx
<Layout><Layout.Sider>{menu}</Layout.Sider><Layout.Content>{page}</Layout.Content></Layout>
```

只读类型目录：references/arco/api/2.66.18/Divider

官方参考：
- https://arco.design/react/components/layout
- https://arco.design/react/components/grid

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
