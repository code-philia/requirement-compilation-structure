# Drawer — Arco React 2.66.18

模态对话框、侧边抽屉、危险操作确认、编辑弹窗。Dialog, modal, drawer, confirmation, approve.

适用：Modal 聚焦操作；Drawer 保留页面上下文；Popconfirm 确认简单操作。

注意：visible 不是 open；不同组件 onOk/onCancel 签名不完全相同。

关键属性：visible, onOk, onCancel, Modal.confirmLoading, Modal.footer, Modal.title, Drawer.title, Popconfirm.title

- Modal.onOk 可委托 form.submit，API 只由一个入口调用；失败保留输入。
- 弹层可挂载到 body，选择器应在真实可见内容中。

回调（参数名为编译器约定）：
```json
{
  "onOk": [
    "event"
  ],
  "onCancel": [
    "event"
  ],
  "afterOpen": [],
  "afterClose": []
}
```

同组用法示例（非生产数据）：
```tsx
<Modal visible={visible} onCancel={close} onOk={() => form.submit()} confirmLoading={pending}>{editForm}</Modal>
```

只读类型目录：references/arco/api/2.66.18/Drawer

官方参考：
- https://arco.design/react/components/modal
- https://arco.design/react/components/drawer
- https://arco.design/react/components/popconfirm

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
