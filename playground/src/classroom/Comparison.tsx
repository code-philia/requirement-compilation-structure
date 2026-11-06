import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { BarChart3 } from "lucide-react";
import { type Run, money, number, seconds, statusText } from "./api";
import "./comparison.css";

type Metric = "duration" | "tokens" | "cost";
type TokenMetric = "total" | "input" | "output" | "reasoning";
type TaskGroup = { id: string; name: string; runs: Run[] };
const colors = [
  "#5265ce",
  "#bc794b",
  "#34877d",
  "#9472c8",
  "#bb5a7c",
  "#5a91b5",
];
const metricNames: Record<Metric, string> = {
  duration: "完整耗时",
  tokens: "Token",
  cost: "金额",
};
const tokenNames: Record<TokenMetric, string> = {
  total: "输入 + 输出",
  input: "输入",
  output: "输出",
  reasoning: "思考（输出子项）",
};

function thinkingKey(run: Run) {
  if (!run.thinking) return "off";
  if (run.thinking_budget) return "budget-" + run.thinking_budget;
  return run.effort || "on";
}
function thinkingName(key: string) {
  if (key === "off") return "关闭思考";
  if (key === "on") return "开启 · 服务默认";
  if (key.startsWith("budget-")) return "思考预算 " + key.slice(7);
  return "思考 " + key;
}
function thinkingOrder(key: string) {
  const order = ["off", "on", "low", "medium", "high", "max"].indexOf(key);
  return order < 0 ? 10 : order;
}
function configuration(run: Run) {
  return JSON.stringify([run.actual_model, run.base_url, thinkingKey(run)]);
}
function configurationOrder(left: Run, right: Run) {
  const models = ["deepseek-flash", "deepseek-v4-pro", "qwen3.7-flash"];
  const leftOrder = models.indexOf(left.model_id);
  const rightOrder = models.indexOf(right.model_id);
  return (
    (leftOrder < 0 ? 10 : leftOrder) - (rightOrder < 0 ? 10 : rightOrder) ||
    left.actual_model.localeCompare(right.actual_model) ||
    left.base_url.localeCompare(right.base_url) ||
    thinkingOrder(thinkingKey(left)) - thinkingOrder(thinkingKey(right)) ||
    thinkingKey(left).localeCompare(thinkingKey(right))
  );
}
function metricValue(
  run: Run | null,
  metric: Metric,
  token: TokenMetric,
): number | null {
  if (!run) return null;
  const value = metric === "tokens" ? run.usage[token] : run[metric];
  return value != null && Number.isFinite(value) && value >= 0 ? value : null;
}
function formatValue(value: number | null, metric: Metric) {
  if (value == null) return "未知";
  if (metric === "cost") return money(value);
  if (metric === "duration") return seconds(value);
  return number(value);
}
function modelColor(run: Run) {
  const index = ["deepseek-flash", "deepseek-v4-pro", "qwen3.7-flash"].indexOf(
    run.model_id,
  );
  return colors[index < 0 ? 3 : index];
}
function Chart({
  option,
  onOpen,
  height,
}: {
  option: (width: number) => EChartsOption;
  onOpen: (id: string) => void;
  height: number;
}) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const open = useRef(onOpen);
  open.current = onOpen;
  const currentOption = useRef(option);
  currentOption.current = option;
  useEffect(() => {
    if (!element.current) return;
    const instance = echarts.init(element.current, undefined, {
      renderer: "canvas",
    });
    chart.current = instance;
    instance.on("click", (event) => {
      const datum = event.data as { runId?: string } | undefined;
      if (datum?.runId) open.current(datum.runId);
      else if (
        event.componentType === "yAxis" &&
        typeof event.value === "string"
      )
        open.current(event.value);
    });
    const observer = new ResizeObserver(() => {
      instance.resize();
      if (element.current)
        instance.setOption(currentOption.current(element.current.clientWidth), {
          notMerge: true,
        });
    });
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    if (element.current)
      chart.current?.setOption(option(element.current.clientWidth), {
        notMerge: true,
      });
  }, [option]);
  return <div className="cmp-chart" style={{ height }} ref={element} />;
}

export default function Comparison({
  runs,
  tasks,
  onOpen,
}: {
  runs: Run[];
  tasks: { id: string; name: string }[];
  onOpen: (id: string) => void;
}) {
  const [task, setTask] = useState("");
  const [model, setModel] = useState("all");
  const [thinking, setThinking] = useState("all");
  const [status, setStatus] = useState("all");
  const [token, setToken] = useState<TokenMetric>("total");
  const [prompt, setPrompt] = useState("all");

  const groups = useMemo(() => {
    const map = new Map<string, TaskGroup>();
    for (const item of tasks)
      map.set(item.id, { id: item.id, name: item.name, runs: [] });
    for (const run of runs) {
      const id = run.task_kind === "custom" ? "custom-chat" : run.task_id;
      let group = map.get(id);
      if (!group) {
        group = {
          id,
          name: id === "custom-chat" ? "自定义对话" : run.task_name,
          runs: [],
        };
        map.set(id, group);
      }
      group.runs.push(run);
    }
    if (!map.has("custom-chat"))
      map.set("custom-chat", {
        id: "custom-chat",
        name: "自定义对话",
        runs: [],
      });
    const order = (id: string) =>
      id === "csv" ? 0 : id === "html" ? 1 : id === "custom-chat" ? 100 : 2;
    return [...map.values()].sort(
      (left, right) =>
        order(left.id) - order(right.id) || left.name.localeCompare(right.name),
    );
  }, [runs, tasks]);
  const group = groups.find((item) => item.id === task) || groups[0];
  const taskRuns = group?.runs || [];
  const versions = useMemo(() => {
    const map = new Map<string, string>();
    for (const run of taskRuns) {
      const previous = map.get(run.experiment);
      if (!previous || run.started_at < previous)
        map.set(run.experiment, run.started_at);
    }
    return [...map.entries()]
      .sort((left, right) => left[1].localeCompare(right[1]))
      .map(([id]) => id);
  }, [taskRuns]);
  const activePrompt = versions.includes(prompt) ? prompt : "all";
  const latest = useMemo(() => {
    const map = new Map<string, Run>();
    for (const run of taskRuns) {
      if (
        run.status === "RUNNING" ||
        (activePrompt !== "all" && run.experiment !== activePrompt)
      )
        continue;
      const key = configuration(run);
      const previous = map.get(key);
      if (
        !previous ||
        run.started_at > previous.started_at ||
        (run.started_at === previous.started_at && run.id > previous.id)
      )
        map.set(key, run);
    }
    return [...map.values()];
  }, [taskRuns, activePrompt]);
  const configurations = latest.filter(
    (run) =>
      (model === "all" || run.actual_model === model) &&
      (thinking === "all" || thinkingKey(run) === thinking),
  );
  const visible = configurations.filter(
    (run) => status === "all" || run.status === "COMPLETED",
  );
  const hidden = configurations.length - visible.length;
  const running = taskRuns.filter((run) => run.status === "RUNNING").length;
  const modelOptions = [
    ...new Set(taskRuns.map((run) => run.actual_model)),
  ].sort();
  const thinkingOptions = [...new Set(taskRuns.map(thinkingKey))].sort(
    (left, right) =>
      thinkingOrder(left) - thinkingOrder(right) || left.localeCompare(right),
  );

  function chartOption(
    rows: Run[],
    metric: Metric,
    width: number,
  ): EChartsOption {
    const compact = width < 520;
    const labels = new Map<string, string>();
    for (const run of rows) {
      const modelName =
        run.actual_model === run.model_id ? run.model_name : run.actual_model;
      const sameSetting = rows.filter(
        (item) =>
          item.actual_model === run.actual_model &&
          thinkingKey(item) === thinkingKey(run),
      );
      let label = modelName + "\n" + thinkingName(thinkingKey(run));
      if (sameSetting.length > 1)
        label += " · " + run.base_url.replace(/^https?:\/\//, "").split("/")[0];
      labels.set(run.id, label);
    }
    return {
      animationDuration: 250,
      tooltip: {
        trigger: "item",
        confine: true,
        renderMode: "richText",
        formatter: (parameters) => {
          const item = Array.isArray(parameters) ? parameters[0] : parameters;
          const run = rows[item.dataIndex];
          if (!run) return "";
          const lines = [
            run.actual_model,
            thinkingName(thinkingKey(run)),
            `所属：${run.task_name}`,
            `${metricNames[metric]}：${formatValue(metricValue(run, metric, token), metric)}`,
            `状态：${statusText[run.status]}`,
          ];
          if (metric === "duration")
            lines.push("首个正式回复：" + seconds(run.first_answer));
          if (metric === "tokens")
            lines.push(
              `输入 ${number(run.usage.input)} · 输出 ${number(run.usage.output)}`,
              `思考 ${number(run.usage.reasoning)}（输出子项）`,
            );
          lines.push(
            "提示词 " + run.experiment.slice(0, 8),
            run.base_url,
            "点击查看原始回复",
          );
          return lines.join("\n");
        },
      },
      grid: {
        left: compact ? 140 : 210,
        right: compact ? 82 : 110,
        top: 16,
        bottom: 38,
      },
      xAxis: {
        type: "value",
        min: 0,
        axisLabel: {
          fontSize: compact ? 9 : 11,
          color: "#91a0b6",
          formatter:
            metric === "cost"
              ? (value: number) =>
                  value === 0
                    ? "0"
                    : value < 0.01
                      ? value.toPrecision(2)
                      : value.toFixed(3)
              : undefined,
        },
        splitLine: { lineStyle: { color: "#edf1f7" } },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: rows.map((run) => run.id),
        triggerEvent: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          interval: 0,
          color: "#667c9c",
          fontSize: compact ? 10 : 12,
          lineHeight: compact ? 15 : 18,
          width: compact ? 122 : 190,
          overflow: "truncate",
          formatter: (id: string) => labels.get(id) || id,
        },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 22,
          showBackground: true,
          backgroundStyle: { color: "#f8fafd" },
          label: {
            show: true,
            position: "right",
            distance: 8,
            color: "#526b8e",
            fontSize: compact ? 10 : 12,
            formatter: (parameters) =>
              formatValue(
                metricValue(rows[parameters.dataIndex], metric, token),
                metric,
              ),
          },
          data: rows.map((run) => ({
            value: metricValue(run, metric, token),
            runId: run.id,
            name: labels.get(run.id),
            itemStyle: {
              color: modelColor(run),
              opacity: run.status === "COMPLETED" ? 0.85 : 0.4,
              borderRadius: [0, 3, 3, 0],
            },
          })),
        },
      ],
    };
  }

  return (
    <section className="cmp-workspace">
      <header className="cmp-heading">
        <div>
          <h2>实验对比</h2>
          <span>{visible.length} 个配置的最新结果</span>
        </div>
        <span className="cmp-ranking-description">
          <BarChart3 size={14} />
          全部运行记录自动参与比较
        </span>
      </header>
      <div className="cmp-filters">
        <label className="cmp-task-select">
          对比任务
          <select
            aria-label="选择对比任务"
            value={group?.id || ""}
            onChange={(event) => {
              setTask(event.target.value);
              setPrompt("all");
              setModel("all");
              setThinking("all");
            }}
          >
            {groups.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <select
          aria-label="筛选模型"
          value={model}
          onChange={(event) => setModel(event.target.value)}
        >
          <option value="all">全部模型</option>
          {modelOptions.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <select
          aria-label="筛选思考设置"
          value={thinking}
          onChange={(event) => setThinking(event.target.value)}
        >
          <option value="all">全部思考设置</option>
          {thinkingOptions.map((key) => (
            <option key={key} value={key}>
              {thinkingName(key)}
            </option>
          ))}
        </select>
        <select
          aria-label="筛选运行状态"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="all">全部已结束状态</option>
          <option value="completed">仅完整完成</option>
        </select>
        <select
          aria-label="Token 指标"
          value={token}
          onChange={(event) => setToken(event.target.value as TokenMetric)}
        >
          {Object.entries(tokenNames).map(([key, name]) => (
            <option key={key} value={key}>
              Token：{name}
            </option>
          ))}
        </select>
        {versions.length > 1 && (
          <select
            aria-label="提示词版本筛选"
            value={activePrompt}
            onChange={(event) => setPrompt(event.target.value)}
          >
            <option value="all">全部提示词 · 配置取最新</option>
            {[...versions].reverse().map((id) => (
              <option key={id} value={id}>
                提示词 V{versions.indexOf(id) + 1} · {id.slice(0, 6)}
              </option>
            ))}
          </select>
        )}
      </div>
      <p className="cmp-note">
        {group?.name}
        ：自动展示每个模型与有效思考设置最新的已结束结果；三张图分别从高到低排序。
        {hidden > 0 && ` ${hidden} 条最新记录被状态筛选隐藏。`}
        {running > 0 && ` ${running} 次请求运行中，结束后自动更新。`}
      </p>
      <div className="cmp-ranking-grid">
        {(["duration", "tokens", "cost"] as Metric[]).map((metric) => {
          const rows = [...visible].sort((left, right) => {
            const leftValue = metricValue(left, metric, token);
            const rightValue = metricValue(right, metric, token);
            if (leftValue == null && rightValue == null)
              return configurationOrder(left, right);
            if (leftValue == null) return 1;
            if (rightValue == null) return -1;
            return rightValue - leftValue || configurationOrder(left, right);
          });
          const missing = rows.filter(
            (run) => metricValue(run, metric, token) == null,
          ).length;
          return (
            <section className="cmp-ranking" key={metric}>
              <header>
                <strong>
                  {metricNames[metric]}
                  {metric === "tokens" ? ` · ${tokenNames[token]}` : ""}
                </strong>
                <span>
                  {metric === "duration"
                    ? "秒 / 次"
                    : metric === "cost"
                      ? "元 / 次"
                      : "Token / 次"}
                </span>
              </header>
              {rows.length ? (
                <Chart
                  option={(width) => chartOption(rows, metric, width)}
                  height={Math.max(280, rows.length * 46 + 62)}
                  onOpen={onOpen}
                />
              ) : (
                <div className="cmp-chart-empty">
                  当前任务在所选条件下暂无已结束的运行结果。
                </div>
              )}
              {missing > 0 && (
                <p className="cmp-missing">
                  {missing} 个配置未记录该指标，置于末尾，不计为零。
                </p>
              )}
            </section>
          );
        })}
      </div>
      <p className="cmp-panel-note">
        纵轴为模型与思考设置，柱末显示实际数值。点击柱条或配置名称查看回复；思考
        Token
        是输出子项，不重复相加。不同提示词的结果可通过提示词版本筛选单独查看。
      </p>
    </section>
  );
}
