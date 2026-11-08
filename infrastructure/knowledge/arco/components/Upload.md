# Upload — Arco React 2.66.18

附件、图片、文件上传及删除。File, attachment, upload, image upload.

适用：后端确实提供文件存储/上传接口。

注意：不能只凭 ER 文件字段发明上传端点；防止组件默认上传与自定义请求重复执行。

关键属性：fileList, onChange, onRemove, beforeUpload, customRequest, action, accept

- 上传认证、CSRF、文件引用及删除规则服从真实 API；UI 文件列表不等同持久化引用。

回调（参数名为编译器约定）：
```json
{
  "onChange": [
    "fileList",
    "file"
  ],
  "onRemove": [
    "file",
    "fileList"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<Upload fileList={files} customRequest={uploadViaContract} onChange={setFiles} />
```

只读类型目录：references/arco/api/2.66.18/Upload

官方参考：
- https://arco.design/react/components/upload

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
