import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import type { EChartsOption } from "echarts";
import { BarChart3, ChartNoAxesCombined } from "lucide-react";
import { type Run, mode, money, number, seconds, statusText } from "./api";

const colors = [
  "#5265ce",
  "#bc794b",
  "#34877d",
  "#9472c8",
  "#bb5a7c",
  "#5a91b5",
  "#9a843c",
  "#6e778c",
];

function Chart({ option }: { option: EChartsOption }) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!element.current) return;
    chart.current = echarts.init(element.current, undefined, {
      renderer: "canvas",
    });
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true });
  }, [option]);
  return <div className="cr-chart" ref={element} />;
}

export default function Comparison({
  runs,
  selected,
  onOpen,
}: {
  runs: Run[];
  selected: string[];
  onOpen: (id: string) => void;
}) {
  const [kind, setKind] = useState<"line" | "bar">("line");
  const [model, setModel] = useState("all");
  const [thinking, setThinking] = useState("all");
  const [tokens, setTokens] = useState<
    "total" | "input" | "output" | "reasoning"
  >("total");
  const chosen = useMemo(
    () =>
      runs.filter(
        (run) =>
          selected.includes(run.id) &&
          run.status !== "RUNNING" &&
          (model === "all" || run.model_id === model) &&
          (thinking === "all" || run.thinking === (thinking === "on")),
      ),
    [runs, selected, model, thinking],
  );
  const experiments = useMemo(() => {
    const latest = new Map<string, Run>();
    for (const run of chosen) {
      const key = JSON.stringify([
        run.actual_model,
        run.thinking ? run.effort || "on" : "off",
        run.thinking ? run.thinking_budget : null,
      ]);
      const previous = latest.get(key);
      if (!previous || run.started_at > previous.started_at)
        latest.set(key, run);
    }
    return [...latest.values()].sort((a, b) =>
      a.started_at.localeCompare(b.started_at),
    );
  }, [chosen]);
  function setting(run: Run) {
    if (!run.thinking) return "关";
    return run.thinking_budget
      ? `预算 ${run.thinking_budget}`
      : run.effort || "开";
  }
  function option(metric: "tokens" | "cost" | "duration"): EChartsOption {
    const value = (run: Run) =>
      metric === "tokens" ? run.usage[tokens] : run[metric];

    return {
      animationDuration: 250,
      color: colors,
      tooltip: {
        trigger: "axis",
        confine: true,
        valueFormatter: (v) =>
          v == null
            ? "未知"
            : metric === "cost"
              ? `¥${Number(v).toFixed(6)}`
              : String(v),
      },

      grid: {
        left: 12,
        right: 18,
        top: 18,
        bottom: 16,
        containLabel: true,
      },
      xAxis: {
        type: "category",
        data: experiments.map(
          (run, index) =>
            `${index + 1}. ${run.actual_model}\n思考：${setting(run)}`,
        ),
        axisLine: { lineStyle: { color: "#cdd4df" } },
        axisLabel: {
          color: "#7c8595",
          interval: 0,
          hideOverlap: false,
          showMinLabel: true,
          showMaxLabel: true,
          rotate: experiments.length > 5 ? 60 : 0,
          fontSize: experiments.length > 5 ? 9 : 10,
          lineHeight: 14,
          width: 110,
          overflow: "break",
        },
      },
      yAxis: {
        type: "value",
        min: 0,
        axisLabel: {
          color: "#7c8595",
          formatter:
            metric === "cost"
              ? (v: number) =>
                  v === 0 ? "0" : v < 0.01 ? v.toPrecision(2) : v.toFixed(3)
              : undefined,
        },
        splitLine: { lineStyle: { color: "#edf0f4" } },
      },
      series: [
        {
          name:
            metric === "tokens" ? "Token" : metric === "cost" ? "金额" : "时延",
          type: kind,
          smooth: false,
          connectNulls: false,
          symbolSize: 9,
          barMaxWidth: 38,
          data: experiments.map((run) => ({
            value: value(run),
            itemStyle: {
              color:
                colors[
                  Math.max(
                    0,
                    [
                      "deepseek-flash",
                      "deepseek-v4-pro",
                      "qwen3.7-flash",
                    ].indexOf(run.model_id),
                  )
                ],
            },
          })),
        },
      ],
    };
  }

  return (
    <section
      className={`cr-comparison ${experiments.length > 5 ? "cr-dense-charts" : ""}`}
    >
      <div className="cr-section-heading">
        <div>
          <span className="cr-eyebrow">COMPARE EXPERIMENTS</span>
          <h2>调用对比</h2>
        </div>
        <div className="cr-segment">
          <button
            className={kind === "line" ? "active" : ""}
            onClick={() => setKind("line")}
          >
            <ChartNoAxesCombined size={15} />
            折线
          </button>
          <button
            className={kind === "bar" ? "active" : ""}
            onClick={() => setKind("bar")}
          >
            <BarChart3 size={15} />
            柱状
          </button>
        </div>
      </div>
      <div className="cr-chart-filters">
        <select
          aria-label="筛选模型"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        >
          <option value="all">全部模型</option>
          {Array.from(
            new Map(
              runs.map((run) => [run.model_id, run.model_name]),
            ).entries(),
          ).map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <select
          aria-label="筛选思考模式"
          value={thinking}
          onChange={(e) => setThinking(e.target.value)}
        >
          <option value="all">全部思考设置</option>
          <option value="off">关闭思考</option>
          <option value="on">开启思考</option>
        </select>
        <span>{experiments.length} 个配置</span>
      </div>
      <p className="cr-hint">
        选中记录按模型和思考配置保留最新结果，图表与列表同步。未知用量留空。
      </p>
      {chosen.length === 0 ? (
        <div className="cr-empty">
          <ChartNoAxesCombined size={36} />
          <h3>未选择记录</h3>
        </div>
      ) : (
        <>
          <div className="cr-chart-block">
            <div className="cr-chart-title">
              <h3>Token 消耗</h3>
              <select
                aria-label="Token 指标"
                value={tokens}
                onChange={(e) => setTokens(e.target.value as typeof tokens)}
              >
                <option value="total">输入 + 输出</option>
                <option value="input">输入 Token</option>
                <option value="output">输出 Token</option>
                <option value="reasoning">思考 Token（输出子项）</option>
              </select>
            </div>
            <Chart option={option("tokens")} />
          </div>
          <div className="cr-chart-block">
            <h3>
              估算金额 <small>CNY / 次</small>
            </h3>
            <Chart option={option("cost")} />
          </div>
          <div className="cr-chart-block">
            <h3>
              完整往返时延 <small>秒 / 次</small>
            </h3>
            <Chart option={option("duration")} />
          </div>
          <div className="cr-table-scroll">
            <table>
              <thead>
                <tr>
                  <th>尝试 / 配置</th>
                  <th>状态</th>
                  <th>Token</th>
                  <th>时延</th>
                  <th>金额</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <button
                        className="cr-text-button"
                        onClick={() => onOpen(run.id)}
                      >
                        {run.model_name} · {run.id.slice(0, 6)}
                      </button>
                      <small>
                        {mode(run)} · {run.prompt_preview}
                      </small>
                    </td>
                    <td>{statusText[run.status]}</td>
                    <td>{number(run.usage.total)}</td>
                    <td>{seconds(run.duration)}</td>
                    <td>{money(run.cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
