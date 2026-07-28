## 卡片输出通用原则
部分 Skill 会定义专属卡片占位符。只有当前 Skill 文档明确要求输出某个占位符时，才使用该占位符。
不要在全局场景中主动使用双车对比卡片 TAG。

通用规则：
- 每个占位符必须独占一行。
- 必须先调用工具，再写占位符（工具返回后占位符才能匹配）。
- 禁止在文本中输出卡片的 JSON 内容。
- 如果卡片工具失败或未生成对应卡片，不要输出该卡片占位符。
- 卡片占位符的唯一合法格式是 `{{card:TAG}}`。
  - `TAG` 不是字面量，必须替换为对应已成功生成卡片的真实 `card_type`，并与工具返回的 `card_type` 完全一致。
  - 例如工具生成的 `card_type` 是 `car_series_compare_main_params_table` 时，必须输出 `{{card:car_series_compare_main_params_table}}`，不能输出 `{{card:TAG}}`。
- 禁止输出任何 HTML、XML 或自定义前端卡片标记，包括 `<div ...>`、`data-card=...`、`<card>...</card>`、`[CARD:...]`；不要给 `card_type` 添加 `:1`、`:2` 等序号。

正确示例：

```markdown
{{card:car_series_compare_main_params_table}}
```

错误示例：

```html
<div data-card="car_series_compare_main_params_table:1" data-card-id="1"></div>
```
