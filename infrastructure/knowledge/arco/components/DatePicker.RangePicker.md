# DatePicker.RangePicker — Arco React 2.66.18

日期、起止日期范围、时间筛选。Date, range, time, timezone.

适用：日期字段或日期范围过滤。

注意：不要将 Dayjs 对象直接作为 API 的业务日期；不要擅自把本地日期转换成 UTC 时间。

关键属性：value, onChange, format, allowClear, DatePicker.showTime, disabledDate

- 回调提供日期字符串与 Dayjs；以 API 格式及时区契约为准。
- 范围与单值形状不同，清空值单独处理。

回调（参数名为编译器约定）：
```json
{
  "onChange": [
    "dateStrings",
    "dates"
  ]
}
```

同组用法示例（非生产数据）：
```tsx
<DatePicker onChange={(dateString) => setBusinessDate(dateString)} />
```

只读类型目录：references/arco/api/2.66.18/DatePicker

官方参考：
- https://arco.design/react/components/date-picker
- https://arco.design/react/components/time-picker

本文件是编译器整理的用途指南；准确属性以固定版本类型声明为准。
