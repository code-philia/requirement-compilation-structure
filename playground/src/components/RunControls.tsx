import { useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleHelp,
  Cpu,
  Coins,
  FolderInput,
  FolderOutput,
  KeyRound,
  LoaderCircle,
  Play,
  RefreshCw,
  Settings2,
  Square,
  Terminal,
  WandSparkles,
} from "lucide-react";
import { api, type Config, type Detail, type RecordData } from "../types";

export function RunControls({
  config,
  activeId,
  detail,
  onStart,
  onError,
  onRefresh,
}: {
  config: Config | null;
  activeId: string | null;
  detail: Detail | null;
  onStart: (id: string) => void;
  onError: (message: string) => void;
  onRefresh: () => void;
}) {
  const [source, setSource] = useState("input");
  const [output, setOutput] = useState(
    "outputs/factory-" + new Date().toISOString().slice(0, 10),
  );
  const [stage, setStage] = useState("");
  const [settings, setSettings] = useState<RecordData>({
    base_url: "",
    api_key: "",
    model: "",
    reasoning: "low",
    visual_model: "",
    visual_base_url: "",
    visual_api_key: "",
  });
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [validation, setValidation] = useState<RecordData | null>(null);
  const [validationError, setValidationError] = useState("");
  const [inputPaths, setInputPaths] = useState<RecordData[]>([]);
  const [outputPaths, setOutputPaths] = useState<RecordData[]>([]);
  const [advanced, setAdvanced] = useState(false);
  const [prices, setPrices] = useState({ input: "", cached: "", output: "" });
  const [port, setPort] = useState(3000);
  const [priceSaved, setPriceSaved] = useState(false);
  useEffect(() => {
    if (config)
      setSettings((before) => ({
        ...before,
        ...config.settings,
        api_key: "",
        visual_api_key: "",
      }));
  }, [config?.root]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      fetch(
        `/api/validate?${new URLSearchParams({ input: source, output, stage })}`,
        { signal: controller.signal },
      )
        .then(async (response) => {
          const value = await response.json();
          if (!response.ok) throw new Error(value.detail);
          setValidation(value);
          setValidationError("");
        })
        .catch((error) => {
          if (error.name !== "AbortError") {
            setValidation(null);
            setValidationError(error.message);
          }
        });
    }, 450);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [source, output, stage]);
  useEffect(() => {
    const timer = setTimeout(() => {
      api("/directories?prefix=" + encodeURIComponent(source))
        .then((data) => setInputPaths(data.items))
        .catch(() => {});
    }, 250);
    return () => clearTimeout(timer);
  }, [source]);
  useEffect(() => {
    const timer = setTimeout(() => {
      api("/directories?prefix=" + encodeURIComponent(output))
        .then((data) => setOutputPaths(data.items))
        .catch(() => {});
    }, 250);
    return () => clearTimeout(timer);
  }, [output]);
  function change(name: string, value: string) {
    setSettings((before) => ({ ...before, [name]: value }));
  }
  useEffect(() => {
    const configured = config?.prices?.[settings.model];
    setPrices({
      input: configured?.input?.toString() ?? "",
      output: configured?.output?.toString() ?? "",
      cached: configured?.cached?.toString() ?? "",
    });
  }, [settings.model]);
  async function connect() {
    setConnecting(true);
    try {
      const data = await api("/models", settings);
      setModels(data.models);
      setSettings((before) => ({
        ...before,
        api_key: "",
        visual_api_key: "",
        key_set: true,
      }));
      if (!data.models.length) onError("服务未返回模型，可手动填写模型 ID。");
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setConnecting(false);
    }
  }
  async function savePrices() {
    try {
      if (prices.input === "" || prices.output === "") {
        onError("请填写输入和输出单价。");
        return;
      }
      await api("/prices", {
        [settings.model]: {
          input: Number(prices.input),
          output: Number(prices.output),
          ...(prices.cached !== "" ? { cached: Number(prices.cached) } : {}),
        },
      });
      setPriceSaved(true);
      onRefresh();
      setTimeout(() => setPriceSaved(false), 2000);
    } catch (error) {
      onError((error as Error).message);
    }
  }
  async function start() {
    setLoading(true);
    try {
      const priceMap: RecordData = {};
      if (prices.input !== "" && prices.output !== "")
        priceMap[settings.model] = {
          input: Number(prices.input),
          output: Number(prices.output),
          ...(prices.cached !== "" ? { cached: Number(prices.cached) } : {}),
        };
      const result = await api("/runs", {
        ...settings,
        input: source,
        output,
        stage,
        port,
        prices: priceMap,
      });
      setSettings((before) => ({
        ...before,
        api_key: "",
        visual_api_key: "",
        key_set: true,
      }));
      onStart(result.id);
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setLoading(false);
    }
  }
  async function stop() {
    setLoading(true);
    try {
      await api(`/runs/${activeId}/stop`, {});
      onRefresh();
    } catch (error) {
      onError((error as Error).message);
    } finally {
      setLoading(false);
    }
  }
  function reuse() {
    if (!detail) return;
    setSource(detail.run.input || "input");
    setOutput(detail.run.output);
    setStage(detail.run.settings.stage || "");
    setSettings((before) => ({
      ...before,
      ...detail.run.settings,
      api_key: "",
      visual_api_key: "",
    }));
    const price = detail.run.settings.prices?.[detail.run.settings.model];
    setPrices({
      input: price?.input?.toString() || "",
      output: price?.output?.toString() || "",
      cached: price?.cached?.toString() || "",
    });
    setPort(detail.run.settings.port || 3000);
  }
  return (
    <aside className="run-controls">
      <div className="sidebar-brand">
        <span className="brand-symbol">
          <WandSparkles size={19} />
        </span>
        <div>
          <b>编译控制台</b>
          <span>BUILD SOMETHING REAL</span>
        </div>
        <span className="local-badge">LOCAL</span>
      </div>
      <div className="controls-scroll">
        <div className="control-section">
          <div className="section-title">
            <span>01</span>
            <h3>工作目录</h3>
            <CircleHelp size={13}>
              <title>相对于 compiler 工作区</title>
            </CircleHelp>
          </div>
          <label className="field-label">
            <FolderInput size={14} />
            输入目录
          </label>
          <input
            className="field-input mono"
            list="input-paths"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            placeholder="input"
          />
          <datalist id="input-paths">
            {inputPaths.map((path) => (
              <option value={path.path} key={path.path}>
                {path.requirements ? "包含需求文档" : ""}
              </option>
            ))}
          </datalist>
          <label className="field-label">
            <FolderOutput size={14} />
            输出目录
          </label>
          <input
            className="field-input mono"
            list="output-paths"
            value={output}
            onChange={(event) => setOutput(event.target.value)}
            placeholder="outputs/my-project"
          />
          <datalist id="output-paths">
            {outputPaths.map((path) => (
              <option value={path.path} key={path.path} />
            ))}
          </datalist>
          <p className="field-hint">相对于 compiler/ · 每次执行独立归档</p>
          {validation && (
            <div className="validation-info">
              <Check size={12} />
              <span>
                {validation.exists
                  ? "将使用现有输出目录"
                  : "运行时创建输出目录"}
              </span>
            </div>
          )}
          {validationError && (
            <div className="validation-warning">
              <AlertCircle size={12} />
              {validationError}
            </div>
          )}
        </div>
        <div className="control-section">
          <div className="section-title">
            <span>02</span>
            <h3>模型连接</h3>
            <Cpu size={14} />
          </div>
          <label className="field-label">Base URL</label>
          <input
            className="field-input mono"
            value={settings.base_url}
            onChange={(event) => change("base_url", event.target.value)}
            placeholder="https://…/v1"
          />
          <label className="field-label">
            <KeyRound size={13} />
            API Key{" "}
            {settings.key_set && <span className="inline-note">已配置</span>}
          </label>
          <input
            className="field-input mono"
            type="password"
            autoComplete="off"
            value={settings.api_key}
            onChange={(event) => change("api_key", event.target.value)}
            placeholder={settings.key_set ? "保留当前服务中的密钥" : "sk-…"}
          />
          <div className="field-label model-label">
            <span>模型</span>
            <button
              className="text-link"
              disabled={connecting}
              onClick={connect}
            >
              {connecting ? (
                <LoaderCircle className="spin" size={11} />
              ) : (
                <RefreshCw size={11} />
              )}
              获取列表
            </button>
          </div>
          <input
            className="field-input mono"
            list="model-options"
            value={settings.model}
            onChange={(event) => change("model", event.target.value)}
            placeholder="选择或输入模型 ID"
          />
          <datalist id="model-options">
            {models.map((model) => (
              <option key={model} value={model} />
            ))}
          </datalist>
          <p className="field-hint">
            密钥仅在服务内存中保存，重启后清除。可沿用已有 .env 配置。
          </p>
          <button
            className="advanced-toggle"
            onClick={() => setAdvanced(!advanced)}
          >
            <Settings2 size={13} />
            高级设置
            <ChevronDown className={advanced ? "rotate" : ""} size={13} />
          </button>
          {advanced && (
            <div className="advanced-fields">
              <label className="field-label">Reasoning</label>
              <select
                className="field-input"
                value={settings.reasoning}
                onChange={(event) => change("reasoning", event.target.value)}
              >
                {["low", "high", "max", "none", "provider", "auto"].map(
                  (value) => (
                    <option key={value}>{value}</option>
                  ),
                )}
              </select>
              <label className="field-label">
                视觉模型（留空沿用文本模型）
              </label>
              <input
                className="field-input mono"
                value={settings.visual_model}
                onChange={(event) => change("visual_model", event.target.value)}
                placeholder="沿用文本模型"
              />
              <label className="field-label">视觉 Base URL</label>
              <input
                className="field-input mono"
                value={settings.visual_base_url}
                onChange={(event) =>
                  change("visual_base_url", event.target.value)
                }
                placeholder="沿用 Base URL"
              />
              <label className="field-label">视觉 API Key</label>
              <input
                type="password"
                className="field-input mono"
                autoComplete="off"
                value={settings.visual_api_key}
                onChange={(event) =>
                  change("visual_api_key", event.target.value)
                }
                placeholder="沿用文本密钥或服务现有配置"
              />
              <label className="field-label">
                文本模型价格 · USD / 1M tokens
              </label>
              <div className="price-fields">
                {(["input", "cached", "output"] as const).map((key, index) => (
                  <label key={key}>
                    <span>{["输入", "缓存输入", "输出"][index]}</span>
                    <input
                      className="field-input"
                      type="number"
                      min="0"
                      step="any"
                      value={prices[key]}
                      onChange={(event) =>
                        setPrices((before) => ({
                          ...before,
                          [key]: event.target.value,
                        }))
                      }
                      placeholder="—"
                    />
                  </label>
                ))}
              </div>
              <p className="field-hint">
                未配置模型显示未计价；不同视觉模型的费用不混用文本模型单价。
              </p>
              <button className="reuse-button" onClick={savePrices}>
                {priceSaved ? <Check size={12} /> : <Coins size={12} />}
                {priceSaved ? "已保存历史计价" : "保存单价，用于估算历史费用"}
              </button>
              <label className="field-label">生成应用端口</label>
              <input
                className="field-input"
                type="number"
                min="1"
                max="65535"
                value={port}
                onChange={(event) => setPort(Number(event.target.value))}
              />
            </div>
          )}
        </div>
        <div className="control-section">
          <div className="section-title">
            <span>03</span>
            <h3>编译任务</h3>
            <Terminal size={14} />
          </div>
          <label className="field-label">执行范围</label>
          <select
            className="field-input stage-select"
            value={stage}
            onChange={(event) => setStage(event.target.value)}
          >
            <option value="">完整流程 · 00 → 10</option>
            {config?.stages.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id.slice(0, 2)} · {item.label}
              </option>
            ))}
          </select>
          {!!validation?.missing?.length && (
            <div className="validation-warning">
              <AlertCircle size={13} />
              <span>缺少前置产物：{validation.missing.join("、")}</span>
            </div>
          )}
          <div className="execution-note">
            <span className="tiny-dot" />
            真实运行 · 一次一个任务
          </div>
          {detail && !detail.run.legacy && (
            <button className="reuse-button" onClick={reuse}>
              <RefreshCw size={12} />
              载入此运行的设置
              <ArrowUpRight size={12} />
            </button>
          )}
        </div>
      </div>
      <div className="controls-footer">
        {activeId ? (
          <button className="stop-button" disabled={loading} onClick={stop}>
            {loading ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Square size={13} />
            )}
            停止当前运行
          </button>
        ) : (
          <button
            className="start-button"
            disabled={
              loading ||
              !config ||
              !!validationError ||
              !!validation?.missing?.length ||
              !settings.model
            }
            onClick={start}
          >
            {loading ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <Play size={15} fill="currentColor" />
            )}
            开始编译<span>↗</span>
          </button>
        )}
        <p>
          {activeId
            ? "可自由浏览地图与历史，后台继续运行"
            : "从一个需求开始，构建完整应用"}
        </p>
      </div>
    </aside>
  );
}
