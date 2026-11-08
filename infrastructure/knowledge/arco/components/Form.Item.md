# Form.Item — Arco React 2.66.18

表单编辑、必填与校验、提交、重置、异步回填。Validated form, submit, reset, edit.

适用：多个字段共同校验、创建、编辑、登录表单。

注意：initialValues 不替代异步回填；避免 Form store 与独立受控状态竞争。

关键属性：Form.form, Form.onSubmit, Form.onValuesChange, Form.Item.field, Form.Item.rules, Form.Item.label

- Form.useForm；编辑对象切换后 setFieldsValue/resetFields。
- Form.Item 的字段控件与可见 label 正确关联。

回调（参数名为编译器约定）：
```json
{}
```

同组用法示例（非生产数据）：
```tsx
<Form form={form} onSubmit={save}><Form.Item field="name" label="名称" rules={[{required:true}]}><Input id="name" /></Form.Item><Button htmlType="submit">保存</Button></Form>
```

只读类型目录：references/arco/api/2.66.18/Form

官方参考：
- https://arco.design/react/components/form

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
