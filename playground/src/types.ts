export type RecordData = Record<string, any>;
export type Metrics = {
  calls: number;
  input: number;
  output: number;
  cached: number;
  model_seconds: number;
  cost: number | null;
  priced_calls: number;
  usage_calls: number;
};
export type Run = {
  id: string;
  name: string;
  input?: string;
  output: string;
  started_at?: string;
  finished_at?: string;
  seconds?: number;
  status: string;
  settings: RecordData;
  legacy?: boolean;
  data_note?: string;
  error?: string;
  stages: RecordData;
};
export type Stage = {
  id: string;
  label: string;
  zone: string;
  status: string;
  seconds: number | null;
  started_at?: string;
  error?: string;
  metrics: Metrics;
};
export type Call = {
  id: string;
  stage: string;
  activity: string;
  status: string;
  model?: string;
  input: number | null;
  output: number | null;
  cached: number | null;
  seconds: number | null;
  started_at?: string;
  error?: string;
};
export type Detail = {
  run: Run;
  metrics: Metrics;
  seconds: number | null;
  stages: Stage[];
  calls: Call[];
  artifacts: RecordData;
};
export type Config = {
  prices?: RecordData;
  root: string;
  settings: RecordData;
  stages: { id: string; label: string; zone: string }[];
  active: string[];
};
export type Selection = {
  id: string;
  kind: string;
  label: string;
  record: RecordData;
  zone: number;
  relations?: string[];
};
export const statusLabel: Record<string, string> = {
  GREEN: "已完成",
  RUNNING: "运行中",
  PENDING: "未执行",
  FAILED: "失败",
  INTERRUPTED: "已停止",
  COMPLETED_WITH_FAILURES: "部分失败",
  HISTORICAL: "历史记录",
  RECORDED: "有调用记录",
  NO_APIS: "无需 API",
  NO_DIRECT_APIS: "无需 API",
  NO_TRIGGERS: "无需交互",
  NO_UI: "无需界面",
};
export function duration(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60
    ? `${minutes}m ${Math.floor(seconds % 60)}s`
    : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
export function compact(value: number | null | undefined) {
  return value == null
    ? "—"
    : Intl.NumberFormat("en", {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
}
export function money(value: number | null | undefined) {
  return value == null ? "未配置" : `$${value.toFixed(value < 0.01 ? 5 : 3)}`;
}
export async function api<T = any>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(
    "/api" + url,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data),
    );
  return data;
}
