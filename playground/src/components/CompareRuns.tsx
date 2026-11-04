import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import {
  ArrowLeft,
  ChartNoAxesCombined,
  ChevronDown,
  LoaderCircle,
  Plus,
  X,
} from "lucide-react";
import {
  api,
  compact,
  duration,
  money,
  type Call,
  type Detail,
  type Run,
} from "../types";
import { Modal } from "./Details";
echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  CanvasRenderer,
]);
const colors = [
  "#5872d9",
  "#62a593",
  "#cc9562",
  "#a18ac3",
  "#d17d89",
  "#57a4bc",
];

type Metric = "seconds" | "tokens" | "cost" | "calls";
function callRequirementPoints(call: Call): string[] {
  if (call.requirement_ids?.length) return [...new Set(call.requirement_ids)];
  return [call.task_id ? "任务 · " + call.task_id : "未关联需求"];
}
export default function CompareRuns({
  runs,
  currentId,
  onClose,
  onInspect,
}: {
  runs: Run[];
  currentId?: string;
  onClose: () => void;
  onInspect: (id: string, stage?: string) => void;
}) {
  const [ids, setIds] = useState<string[]>(currentId ? [currentId] : []);
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [stage, setStage] = useState("");
  const [cumulative, setCumulative] = useState(false);
  const [chartType, setChartType] = useState<"line" | "bar">("line");
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState(runs);
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      api("/runs?limit=100&search=" + encodeURIComponent(search)).then(
        (data) => {
          if (!cancelled) setOptions(data.items);
        },
      );
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [search]);
  useEffect(() => {
    for (const id of ids) {
      if (details[id] || errors[id]) continue;
      api<Detail>("/runs/" + id)
        .then((detail) => setDetails((before) => ({ ...before, [id]: detail })))
        .catch((error) =>
          setErrors((before) => ({ ...before, [id]: error.message })),
        );
    }
  }, [ids]);
  const selected = useMemo(
    () => ids.map((id) => details[id]).filter(Boolean),
    [ids, details],
  );
  const stages = selected[0]?.stages || [];
  const taskNames = useMemo(() => {
    const names = new Set<string>();
    for (const detail of selected)
      for (const task of detail.tasks || [])
        if (task.stage === stage.slice(0, 2) && !task.parent_id)
          names.add(task.task_id);
    return [...names];
  }, [selected, stage]);
  const labels = useMemo(
    () =>
      stage
        ? taskNames
        : stages.map((item) => item.id.slice(0, 2) + " " + item.label),
    [stage, taskNames, stages],
  );
  const callLabels = useMemo(() => {
    if (!stage) return labels;
    const points = new Set<string>();
    for (const detail of selected) {
      for (const call of detail.calls) {
        if (call.stage !== stage.slice(0, 2)) continue;
        for (const point of callRequirementPoints(call)) points.add(point);
      }
    }
    return [...points];
  }, [selected, stage, labels]);
  function values(detail: Detail, metric: Metric) {
    let sum = 0;
    const metricLabels = metric === "calls" ? callLabels : labels;
    return metricLabels.map((label, index) => {
      let value: number | null = null;
      if (!stage) {
        const entry = detail.stages.find(
          (item) => item.id === stages[index].id,
        );
        if (entry && entry.status !== "PENDING") {
          value =
            metric === "seconds"
              ? entry.seconds
              : metric === "tokens"
                ? entry.metrics.usage_calls || entry.metrics.calls === 0
                  ? entry.metrics.input + entry.metrics.output
                  : null
                : metric === "calls"
                  ? entry.metrics.calls
                  : entry.metrics.cost;
        }
      } else if (metric === "calls") {
        const stageEntry = detail.stages.find((item) => item.id === stage);
        if (stageEntry && stageEntry.status !== "PENDING") {
          value = detail.calls.filter(
            (call) =>
              call.stage === stage.slice(0, 2) &&
              callRequirementPoints(call).includes(label),
          ).length;
        }
      } else {
        const tasks = (detail.tasks || []).filter(
          (task) =>
            task.stage === stage.slice(0, 2) &&
            task.task_id === label &&
            !task.parent_id,
        );
        if (tasks.length) {
          if (metric === "seconds") {
            value = tasks.reduce(
              (total, task) =>
                total + (task.seconds ?? task.metrics.model_seconds),
              0,
            );
          } else if (metric === "tokens") {
            value = tasks.reduce(
              (total, task) => total + task.metrics.input + task.metrics.output,
              0,
            );
          } else {
            const priced = tasks.filter((task) => task.metrics.cost != null);
            value = priced.length
              ? priced.reduce((total, task) => total + task.metrics.cost!, 0)
              : null;
          }
        }
      }
      if (value == null) return null;
      sum += value;
      return cumulative ? sum : value;
    });
  }
  const chartData = useMemo(() => {
    const result = {} as Record<
      Metric,
      { id: string; name: string; color: string; values: (number | null)[] }[]
    >;
    for (const metric of ["seconds", "tokens", "cost", "calls"] as Metric[]) {
      result[metric] = selected.map((detail) => ({
        id: detail.run.id,
        name: detail.run.name + " · " + detail.run.id.slice(-6),
        color: colors[ids.indexOf(detail.run.id) % colors.length],
        values: values(detail, metric),
      }));
    }
    return result;
  }, [selected, ids, stage, labels, callLabels, cumulative]);
  return (
    <Modal open onClose={onClose} title="运行对比" eyebrow="RUN ANALYTICS" wide>
      <div className="compare-controls">
        <div className="selected-runs">
          {ids.map((id, index) => (
            <span
              className="selected-run"
              key={id}
              style={
                {
                  "--run-color": colors[index % colors.length],
                } as React.CSSProperties
              }
            >
              <i />
              {details[id]?.run.name ||
                runs.find((run) => run.id === id)?.name ||
                "读取中…"}
              <button
                title="移除此运行"
                onClick={() =>
                  setIds((before) => before.filter((value) => value !== id))
                }
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
        <div className="compare-add">
          <input
            value={search}
            placeholder="搜索更多历史运行"
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            aria-label="添加运行"
            value=""
            onChange={(event) => {
              if (event.target.value && !ids.includes(event.target.value))
                setIds([...ids, event.target.value]);
            }}
          >
            <option value="">＋ 添加运行</option>
            {options.map((run) => (
              <option
                value={run.id}
                key={run.id}
                disabled={ids.includes(run.id)}
              >
                {run.name} · {run.started_at?.slice(0, 16) || "历史目录"} ·{" "}
                {run.settings.model || run.output}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="compare-toolbar">
        <div>
          <ChartNoAxesCombined size={15} />
          <span>横轴粒度</span>
          <select
            value={stage}
            onChange={(event) => setStage(event.target.value)}
          >
            <option value="">所有阶段</option>
            {stages.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id.slice(0, 2)} · {item.label} / 执行任务
              </option>
            ))}
          </select>
        </div>
        <div className="chart-type-controls">
          <div className="chart-type-switch" role="group" aria-label="图表类型">
            <button
              aria-pressed={chartType === "line"}
              onClick={() => setChartType("line")}
            >
              折线图
            </button>
            <button
              aria-pressed={chartType === "bar"}
              onClick={() => setChartType("bar")}
            >
              柱状图
            </button>
          </div>
          <label>
            <input
              type="checkbox"
              checked={cumulative}
              onChange={(event) => setCumulative(event.target.checked)}
            />
            累计值
          </label>
        </div>
      </div>
      <div className="modal-body compare-body">
        {ids.filter((id) => !details[id] && !errors[id]).length > 0 && (
          <div className="loading-state">
            <LoaderCircle size={18} className="spin" />
            读取运行统计…
          </div>
        )}
        {Object.entries(errors)
          .filter(([id]) => ids.includes(id))
          .map(([id, error]) => (
            <div className="error-box" key={id}>
              {error}
            </div>
          ))}
        {selected.length === 0 ? (
          <div className="compare-empty">
            <ChartNoAxesCombined size={36} />
            <h3>选择两次运行，开始比较</h3>
            <p>也可以继续添加运行，每次运行对应一种颜色。</p>
          </div>
        ) : (
          <>
            <div className="comparison-table">
              <table>
                <thead>
                  <tr>
                    <th>运行 / 输入</th>
                    <th>状态</th>
                    <th>墙钟耗时</th>
                    <th>Token</th>
                    <th>模型调用次数</th>
                    <th>估算金额</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.map((detail, index) => (
                    <tr key={detail.run.id}>
                      <td>
                        <span
                          className="table-run-dot"
                          style={{
                            background:
                              colors[
                                ids.indexOf(detail.run.id) % colors.length
                              ],
                          }}
                        />
                        <button
                          className="text-link"
                          onClick={() => onInspect(detail.run.id)}
                        >
                          {detail.run.name}
                        </button>
                        <small>
                          {detail.run.input || "输入未记录"} ·{" "}
                          {detail.run.id.slice(0, 20)}
                        </small>
                      </td>
                      <td>{detail.run.status}</td>
                      <td>{duration(detail.seconds)}</td>
                      <td>
                        {compact(
                          detail.metrics.usage_calls ||
                            detail.metrics.calls === 0
                            ? detail.metrics.input + detail.metrics.output
                            : null,
                        )}
                      </td>
                      <td>{detail.metrics.calls.toLocaleString("zh-CN")}</td>
                      <td>
                        {money(detail.metrics.cost)}
                        {detail.metrics.cost != null &&
                        detail.metrics.priced_calls < detail.metrics.calls
                          ? " *"
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {new Set(
              selected.map((detail) => detail.run.input || detail.run.output),
            ).size > 1 && (
              <div className="data-note">
                运行使用了不同或未记录的需求输入，比较时请结合任务规模。
              </div>
            )}
            <p className="chart-note">
              {stage
                ? "结构化记录显示任务实际耗时；历史记录缺少任务计时时显示模型耗时之和。共享 API 按实际任务统计。"
                : "阶段时间为实际墙钟耗时；历史记录缺失的数据留空。点击图表中的阶段可下钻到执行任务。"}{" "}
              ＊
              表示部分计价。阶段内的调用次数按需求点归集，共享调用会计入每个关联需求点，不宜直接相加；缺少关联时按任务展示。
            </p>
            {(["seconds", "tokens", "cost", "calls"] as Metric[]).map(
              (metric) => (
                <Chart
                  key={metric}
                  title={
                    metric === "seconds"
                      ? stage
                        ? "任务耗时"
                        : "阶段耗时"
                      : metric === "tokens"
                        ? "Token 使用量"
                        : metric === "calls"
                          ? "模型调用次数"
                          : "估算费用 · CNY"
                  }
                  labels={metric === "calls" ? callLabels : labels}
                  series={chartData[metric]}
                  line={chartType === "line"}
                  metric={metric}
                  onClick={(index) => {
                    if (!stage) setStage(stages[index].id);
                  }}
                />
              ),
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
function Chart({
  title,
  labels,
  series,
  line,
  metric,
  onClick,
}: {
  title: string;
  labels: string[];
  series: {
    id: string;
    name: string;
    color: string;
    values: (number | null)[];
  }[];
  line: boolean;
  metric: Metric;
  onClick: (index: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.EChartsType | null>(null);
  const clickHandler = useRef(onClick);
  clickHandler.current = onClick;
  const hasLabels = labels.length > 0;
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current);
    instance.current = chart;
    chart.on("click", (params: any) => clickHandler.current(params.dataIndex));
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, [hasLabels]);
  useEffect(() => {
    if (!instance.current) return;
    instance.current.setOption({
      animationDuration: 350,
      color: series.map((item) => item.color),
      textStyle: { fontFamily: "Inter, system-ui, sans-serif" },
      grid: { left: 55, right: 24, top: 45, bottom: 70 },
      tooltip: { trigger: "axis", confine: true },
      legend: {
        top: 0,
        type: "scroll",
        textStyle: { fontSize: 11, color: "#768196" },
      },
      xAxis: {
        type: "category",
        data: labels,
        axisLine: { lineStyle: { color: "#dce3ec" } },
        axisLabel: {
          color: "#8993a3",
          fontSize: 10,
          width: 95,
          overflow: "truncate",
          interval: 0,
          rotate: labels.length > 8 ? 20 : 0,
        },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        minInterval: metric === "calls" ? 1 : 0,
        splitLine: { lineStyle: { color: "#edf0f4" } },
        axisLabel: {
          color: "#8993a3",
          fontSize: 10,
          formatter: (value: number) =>
            metric === "cost" ? "¥" + value.toFixed(3) : compact(value),
        },
      },
      dataZoom: [
        {
          type: "inside",
          start: 0,
          end:
            labels.length > 20
              ? Math.min(100, (20 / labels.length) * 100)
              : 100,
        },
        {
          type: "slider",
          height: 13,
          bottom: 8,
          borderColor: "transparent",
          backgroundColor: "#f1f4f8",
          fillerColor: "#dce3f5",
          handleSize: "80%",
          showDetail: false,
        },
      ],
      series: series.map((item) => ({
        name: item.name,
        type: line ? "line" : "bar",
        data: item.values,
        smooth: false,
        connectNulls: false,
        symbolSize: 6,
        barMaxWidth: 24,
        itemStyle: { borderRadius: line ? 0 : [4, 4, 0, 0] },
        lineStyle: { width: 2.2 },
      })),
    });
  }, [labels, series, line, metric]);
  return (
    <section className="chart-panel">
      <h3>{title}</h3>
      {labels.length ? (
        <div ref={host} className="chart-host" />
      ) : (
        <p className="muted">此阶段没有可比较的模型任务。</p>
      )}
    </section>
  );
}
