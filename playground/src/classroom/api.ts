export type Profile = { model: string; base_url: string; key_set: boolean };
export type Model = {
  id: string;
  name: string;
  provider: string;
  description: string;
  input: number;
  cached: number | null;
  output: number;
  thinking_output: number;
  settings: Profile;
};
export type Task = {
  id: string;
  name: string;
  level: string;
  description: string;
  prompt: string;
  timeout: number;
  checks: string[];
  rubric?: { title: string; points: number; criteria: string }[];
  scenarios?: { action: string; expected: string }[];
};
export type Config = {
  models: Model[];
  tasks: Task[];
  sample_csv: string;
  active: string[];
};
export type Run = {
  id: string;
  model_id: string;
  model_name: string;
  actual_model: string;
  experiment: string;
  task_id: string;
  task_name: string;
  task_source: string;
  task_kind: "task" | "custom";
  returned_model: string | null;
  base_url: string;
  prompt_preview: string;
  thinking: boolean;
  effort: string | null;
  thinking_budget: number | null;
  max_tokens: number | null;
  timeout: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration: number;
  first_token: number | null;
  first_answer: number | null;
  finish_reason: string | null;
  usage: {
    input: number | null;
    output: number | null;
    cached: number | null;
    reasoning: number | null;
    total: number | null;
  };
  cost: number | null;
  error: string;
  price: {
    input: number;
    cached: number | null;
    output: number;
    period: string;
  };
};
export type Detail = Run & {
  prompt: string;
  csv?: string;
  answer: string;
  reasoning: string;
  request: Record<string, unknown>;
  raw_usage: Record<string, unknown>;
  html_available: boolean;
};
export type CsvReference = {
  total_rows: number;
  valid_rows: number;
  duplicate_rows: number;
  error_rows: number;
  error_items: number;
  valid_ids: string[];
  statuses: Record<string, number>;
  paid_orders: number;
  quantity: number;
  revenue: string;
  cities: { city: string; orders: number; revenue: string }[];
  errors: {
    row: number;
    order_id: string;
    issues: { column: string; reason: string }[];
  }[];
  duplicates: { row: number; order_id: string; first_row: number }[];
  changes: {
    row: number;
    changes: { column: string; from: string; to: string }[];
  }[];
};
export async function course<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch("/api/course" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data),
    );
  return data;
}
export const statusText: Record<string, string> = {
  RUNNING: "运行中",
  COMPLETED: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
  TRUNCATED: "输出截断",
  INTERRUPTED: "已中断",
};
export const number = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString("zh-CN");
export const money = (value: number | null | undefined) =>
  value == null ? "未知" : `¥${value.toFixed(6)}`;
export const seconds = (value: number | null | undefined) =>
  value == null ? "—" : `${value.toFixed(2)} s`;
export function mode(run: Run) {
  if (!run.thinking) return "关闭思考";
  return run.thinking_budget
    ? `思考预算 ${run.thinking_budget}`
    : run.effort
      ? `思考 ${run.effort}`
      : "开启思考";
}
