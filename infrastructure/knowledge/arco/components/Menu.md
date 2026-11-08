# Menu — Arco React 2.66.18

导航菜单、子菜单、面包屑、标签页。Navigation, route, menu, breadcrumb, tabs.

适用：应用导航层级或同一页面的内容分类。

注意：不要只更新选中菜单却不导航；权限隐藏不能替代后端鉴权。

关键属性：Menu.selectedKeys, Menu.openKeys, Menu.onClickMenuItem, Tabs.activeTab, Tabs.onChange, Tabs.TabPane.key

- 从实际路由恢复选中状态，支持直达/刷新/前进后退。
- Tabs 与弹窗状态区分，截图状态不必独立生成路由。

回调（参数名为编译器约定）：
```json
{
  "onClickMenuItem": [
    "key",
    "event",
    "keyPath"
  ],
  "onClickSubMenu": [
    "key",
    "openKeys",
    "keyPath"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<Menu selectedKeys={[activeKey]} onClickMenuItem={navigateByKey}>{items}</Menu>
```

只读类型目录：references/arco/api/2.66.18/Menu

官方参考：
- https://arco.design/react/components/menu
- https://arco.design/react/components/tabs
- https://arco.design/react/components/breadcrumb

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
