import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Clock3,
  Coins,
  MessageSquareText,
  Maximize2,
  Download,
  FlaskConical,
  LoaderCircle,
  MonitorPlay,
  Orbit,
  Plus,
  RotateCcw,
  Send,
  Settings2,
  Square,
  Trash2,
  X,
} from "lucide-react";
import {
  course,
  type Config,
  type Detail,
  type Profile,
  type Run,
  mode,
  money,
  number,
  seconds,
  statusText,
} from "./api";
import Tasks from "./Tasks";
import BrowserTesting from "./BrowserTesting";
import RequirementsStudio from "./RequirementsStudio";
import { compact, duration } from "../types";
import "./classroom.css";
const Comparison = lazy(() => import("./Comparison"));
type Draft = { prompt: string; task_id?: string; task_name?: string };
type Connection = Profile & { api_key: string };
type Screen = "workbench" | "compare" | "tasks" | "browser" | "requirements";
type OutputTab = "reasoning" | "answer" | "rendered" | "preview" | "request";
function initialDraft(): Draft {
  try {
    const value = JSON.parse(
      sessionStorage.getItem("classroom-input") || "null",
    );
    if (value && typeof value.prompt === "string")
      return {
        prompt: value.prompt,
        task_id: value.task_id,
        task_name: value.task_name,
      };
  } catch {
    /* Use an empty input when browser storage is unavailable. */
  }
  return { prompt: "" };
}
export default function Classroom() {
  const [config, setConfig] = useState<Config | null>(null);
  const [connections, setConnections] = useState<Record<string, Connection>>(
    {},
  );
  const [modelId, setModelId] = useState("deepseek-flash");
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [thinking, setThinking] = useState(false);
  const [effort, setEffort] = useState("low");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    new URLSearchParams(location.search).get("attempt"),
  );
  const [detail, setDetail] = useState<Detail | null>(null);
  const [screen, setScreen] = useState<Screen>(() => {
    const requested = new URLSearchParams(location.search).get("screen");
    if (
      requested === "browser" ||
      requested === "requirements" ||
      requested === "compare"
    )
      return requested;
    return "tasks";
  });
  const [browserControls, setBrowserControls] = useState<HTMLElement | null>(
    null,
  );
  const [outputTab, setOutputTab] = useState<OutputTab>("rendered");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clock, setClock] = useState(Date.now());
  const [search, setSearch] = useState("");
  const [follow, setFollow] = useState(true);
  const [streamConnected, setStreamConnected] = useState(false);
  const [previewVersion, setPreviewVersion] = useState(0);
  const [phonePreview, setPhonePreview] = useState(false);
  const [previewHeight, setPreviewHeight] = useState(900);
  const previewFrame = useRef<HTMLIFrameElement>(null);
  const outputArea = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const model = config?.models.find((item) => item.id === modelId);
  const connection = connections[modelId];
  const compactModel = screen === "browser" || screen === "requirements";
  const activeCount = runs.filter((run) => run.status === "RUNNING").length;
  const refreshRuns = useCallback(async () => {
    try {
      const data = await course<{ items: Run[] }>("/runs");
      setRuns(data.items);
    } catch (error) {
      setError((error as Error).message);
    }
  }, []);
  useEffect(() => {
    document.title = "课堂练习室";
    let disposed = false;
    course<Config>("/config")
      .then((value) => {
        if (disposed) return;
        setConfig(value);
        const next: Record<string, Connection> = {};
        for (const item of value.models)
          next[item.id] = { ...item.settings, api_key: "" };
        setConnections(next);
        if (
          !new URLSearchParams(location.search).has("attempt") &&
          value.active.length
        )
          setSelectedId(value.active[0]);
      })
      .catch((error) => setError(error.message));
    refreshRuns();
    const poll = setInterval(refreshRuns, 5000);
    const timer = setInterval(() => setClock(Date.now()), 250);
    return () => {
      disposed = true;
      clearInterval(poll);
      clearInterval(timer);
    };
  }, [refreshRuns]);
  useEffect(() => {
    try {
      sessionStorage.setItem("classroom-input", JSON.stringify(draft));
    } catch {
      /* Keep the draft in memory. */
    }
  }, [draft]);
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let disposed = false;
    let source: EventSource | undefined;
    const url = new URL(location.href);
    url.searchParams.set("attempt", selectedId);
    history.replaceState(null, "", url);
    setLoading(true);
    setDetail(null);
    setStreamConnected(false);
    setOutputTab("rendered");
    setFollow(true);
    course<Detail>("/runs/" + selectedId)
      .then((record) => {
        if (disposed) return;
        setDetail(record);
        if (record.status !== "RUNNING") return;
        source = new EventSource(`/api/course/runs/${selectedId}/events`);
        source.onopen = () => setStreamConnected(true);
        source.onerror = () => setStreamConnected(false);
        source.onmessage = (event) => {
          if (disposed) return;
          const value = JSON.parse(event.data) as Detail;
          setDetail(value);
          setRuns((current) =>
            current.map((item) =>
              item.id === value.id ? { ...item, ...value } : item,
            ),
          );
          if (value.status !== "RUNNING") {
            source?.close();
            setStreamConnected(false);
            refreshRuns();
          }
        };
      })
      .catch((error) => {
        if (!disposed) setError(error.message);
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
      source?.close();
    };
  }, [selectedId, refreshRuns]);
  useEffect(() => {
    if (follow && outputTab !== "preview" && outputArea.current)
      outputArea.current.scrollTop = outputArea.current.scrollHeight;
  }, [detail?.answer, detail?.reasoning, outputTab, follow]);
  useEffect(() => {
    if (detail?.html_available) setOutputTab("preview");
  }, [detail?.id, detail?.html_available]);
  useEffect(() => {
    setPreviewHeight(phonePreview ? 844 : 900);
  }, [detail?.id, phonePreview, previewVersion]);
  useEffect(() => {
    function resize(event: MessageEvent) {
      const message = event.data;
      if (
        event.source !== previewFrame.current?.contentWindow ||
        message?.type !== "classroom-preview-size" ||
        message.runId !== detail?.id ||
        !Number.isFinite(message.height)
      )
        return;
      setPreviewHeight(
        Math.max(
          phonePreview ? 844 : 900,
          Math.min(16000, Math.ceil(message.height)),
        ),
      );
    }
    window.addEventListener("message", resize);
    return () => window.removeEventListener("message", resize);
  }, [detail?.id, phonePreview]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  function editDraft(change: Partial<Draft>) {
    setDraft((current) => ({ ...current, ...change }));
  }
  function editConnection(change: Partial<Connection>) {
    setConnections((current) => ({
      ...current,
      [modelId]: { ...current[modelId], ...change },
    }));
  }
  async function saveConnection() {
    const value = await course<Profile>("/connections/" + modelId, connection);
    setConnections((current) => ({
      ...current,
      [modelId]: { ...value, api_key: "" },
    }));
  }
  async function start() {
    if (busy || !draft.prompt.trim()) return;
    setBusy(true);
    setError("");
    try {
      await saveConnection();
      const result = await course<{ id: string }>("/runs", {
        model_id: modelId,
        prompt: draft.prompt,
        task_id: draft.task_id || "",
        task_name: draft.task_name || "",
        thinking,
        effort,
      });
      await refreshRuns();
      setSelectedId(result.id);
      setScreen("workbench");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel(run: Run) {
    try {
      await course("/runs/" + run.id + "/cancel", {});
      await refreshRuns();
      const value = await course<Detail>("/runs/" + run.id);
      setDetail((current) => (current?.id === value.id ? value : current));
    } catch (error) {
      setError((error as Error).message);
    }
  }
  async function remove(run: Run) {
    try {
      await course("/runs/" + run.id, undefined, "DELETE");
      setRuns((current) => current.filter((item) => item.id !== run.id));
      if (selectedId === run.id) {
        setSelectedId(null);
        setDetail(null);
        history.replaceState(null, "", "/classroom");
      }
    } catch (error) {
      setError((error as Error).message);
    }
  }
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice("已复制");
    } catch {
      setError("复制失败，请选中文字手动复制");
    }
  }
  function reuse() {
    if (!detail) return;
    setModelId(detail.model_id);
    setThinking(detail.thinking);
    setEffort(detail.effort || "low");
    setDraft({
      prompt: detail.prompt + (detail.csv ? "\n\nCSV：\n" + detail.csv : ""),
      task_id: detail.task_id,
      task_name: detail.task_name,
    });
    input.current?.focus();
  }
  const elapsed =
    detail?.status === "RUNNING"
      ? Math.max(
          detail.duration,
          (clock - Date.parse(detail.started_at)) / 1000,
        )
      : detail?.duration;
  const visibleRuns = runs.filter((run) =>
    `${run.model_name} ${run.actual_model} ${mode(run)} ${statusText[run.status]} ${run.id}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <div className="classroom-shell">
      <header className="cr-header">
        <a className="cr-back" href="/" title="返回需求工厂">
          <ArrowLeft size={18} />
          <span>需求工厂</span>
        </a>
        <div className="cr-brand">
          <span>
            <FlaskConical size={21} />
          </span>
          <div>
            <strong>课堂练习室</strong>
          </div>
        </div>
        <nav className="cr-top-tabs" aria-label="练习室页面">
          {(
            [
              ["tasks", "任务"],
              ["workbench", "实验工作台"],
              ["compare", "对比看板"],
              ["browser", "GUI 测试"],
              ["requirements", "需求沉淀"],
            ] as const
          ).map(([id, title]) => (
            <button
              key={id}
              className={screen === id ? "active" : ""}
              onClick={() => setScreen(id)}
            >
              {title}
            </button>
          ))}
        </nav>
        <a
          className="cr-lesson-link"
          href="/api/course/lesson"
          target="_blank"
          rel="noreferrer"
        >
          <BookOpen size={16} />
          <span>教案</span>
        </a>
      </header>
      {error && (
        <div className="cr-error" role="alert">
          <span>{error}</span>
          <button onClick={() => setError("")} aria-label="关闭错误">
            <X size={16} />
          </button>
        </div>
      )}
      {notice && (
        <div className="cr-toast" role="status">
          <Check size={16} />
          {notice}
        </div>
      )}
      <div
        className={`cr-layout ${screen === "browser" ? "cr-browser-layout" : ""} ${screen === "requirements" ? "cr-requirements-layout" : ""} ${screen === "compare" ? "cr-compare-layout" : ""}`}
      >
        <aside className="cr-controls">
          {(screen === "browser" || screen === "requirements") && (
            <div ref={setBrowserControls} />
          )}
          {screen === "workbench" && (
            <div className="cr-sidebar-action">
              <button
                className="cr-button primary"
                onClick={() => {
                  setSelectedId(null);
                  editDraft({ task_id: "", task_name: "" });
                  history.replaceState(null, "", "/classroom");
                  input.current?.focus();
                }}
              >
                <Plus size={18} />
                新建
              </button>
            </div>
          )}
          <div className="cr-sidebar-title">
            <h2>模型</h2>
          </div>
          {compactModel ? (
            <select
              className="cr-model-select"
              aria-label="选择模型"
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
            >
              {config?.models.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          ) : (
            <>
              <div className="cr-model-list">
                {config?.models.map((item, index) => (
                  <button
                    key={item.id}
                    className={`cr-model ${modelId === item.id ? "selected" : ""}`}
                    onClick={() => setModelId(item.id)}
                    aria-pressed={modelId === item.id}
                  >
                    <div className="cr-model-name">
                      <span className={`cr-model-symbol model-${index}`}>
                        <Orbit size={20} />
                      </span>
                      <strong>{item.name}</strong>
                      {modelId === item.id && <Check size={15} />}
                    </div>

                    <div className="cr-price-pair">
                      <span>
                        输入 <b>¥{item.input.toFixed(2)}</b>
                      </span>
                      <span>
                        输出{" "}
                        <b>
                          ¥
                          {(thinking
                            ? item.thinking_output
                            : item.output
                          ).toFixed(2)}
                        </b>
                      </span>
                    </div>
                  </button>
                ))}
              </div>
              <p className="cr-price-note">
                元 / 百万 Token · 输入按未缓存
                <br />
                DeepSeek 闲时；千问北京标准价
              </p>
              {model && (
                <div className="cr-model-footnote">
                  {model.cached == null
                    ? "缓存输入按普通输入计费"
                    : `缓存输入 ¥${model.cached.toFixed(2)} / 百万`}
                  {model.output !== model.thinking_output && (
                    <>
                      <br />
                      千问思考输出 ¥{model.thinking_output.toFixed(2)} / 百万
                    </>
                  )}
                </div>
              )}
            </>
          )}

          <section className="cr-setting-section">
            <button
              className="cr-disclosure"
              onClick={() => setSettingsOpen(!settingsOpen)}
              aria-expanded={settingsOpen}
            >
              <Settings2 size={15} />
              <strong>模型连接</strong>
              <span
                className={`cr-key-dot ${connection?.key_set ? "set" : ""}`}
              />
              {settingsOpen ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
            </button>
            {settingsOpen && connection && (
              <div className="cr-connection-form">
                <label>
                  实际模型 ID
                  <input
                    value={connection.model}
                    onChange={(e) => editConnection({ model: e.target.value })}
                  />
                </label>
                <label>
                  Base URL
                  <input
                    value={connection.base_url}
                    onChange={(e) =>
                      editConnection({ base_url: e.target.value })
                    }
                    placeholder="https://…/v1"
                  />
                </label>
                <label>
                  API Key
                  <input
                    type="password"
                    autoComplete="off"
                    value={connection.api_key}
                    onChange={(e) =>
                      editConnection({ api_key: e.target.value })
                    }
                    placeholder={
                      connection.key_set ? "已加载，留空继续使用" : "粘贴密钥"
                    }
                  />
                </label>
                <p className="cr-hint">
                  默认读取 .env；保存后仅本次服务进程持有密钥。
                </p>
                <button
                  className="cr-button secondary"
                  onClick={async () => {
                    try {
                      await saveConnection();
                      setNotice("连接设置已保存");
                    } catch (error) {
                      setError((error as Error).message);
                    }
                  }}
                >
                  保存连接
                </button>
              </div>
            )}
            {!settingsOpen && (
              <p className="cr-connection-status">
                {connection?.key_set ? "密钥已就绪" : "尚未设置密钥"} ·
                点击展开设置
              </p>
            )}
          </section>

          <section className="cr-setting-section">
            <div className="cr-toggle-row">
              <div>
                <strong>思考模式</strong>
              </div>
              <button
                className={`cr-switch ${thinking ? "on" : ""}`}
                role="switch"
                aria-checked={thinking}
                aria-label="开启思考模式"
                onClick={() => setThinking(!thinking)}
              >
                <span />
              </button>
            </div>
            {thinking && model?.provider === "deepseek" && (
              <label className="cr-field">
                思考强度
                <div className="cr-segment">
                  {["low", "high", "max"].map((value) => (
                    <button
                      key={value}
                      className={effort === value ? "active" : ""}
                      onClick={() => setEffort(value)}
                    >
                      {value}
                    </button>
                  ))}
                </div>
              </label>
            )}
            <p className="cr-hint">
              DeepSeek 使用服务最大输出长度，输出用量包含思考。
            </p>
          </section>

          <section className="cr-setting-section">
            <p className="cr-hint">请求时限：10 分钟</p>
          </section>
        </aside>
        <main
          className={`cr-main ${screen === "browser" ? "cr-browser-main" : ""} ${screen === "requirements" ? "cr-requirements-main" : ""} ${screen === "workbench" ? "cr-chat-main" : ""} ${screen === "workbench" && outputTab === "preview" ? "cr-preview-mode" : ""}`}
        >
          {screen === "tasks" && config ? (
            <Tasks
              config={config}
              onUse={(prompt, task_id, task_name) => {
                editDraft({ prompt, task_id, task_name });
                setScreen("workbench");
                setTimeout(() => input.current?.focus(), 0);
              }}
              onCopy={copy}
              onError={setError}
            />
          ) : screen === "requirements" ? (
            <RequirementsStudio
              modelId={modelId}
              thinking={thinking}
              effort={effort}
              controls={browserControls}
              saveConnection={saveConnection}
            />
          ) : screen === "browser" ? (
            <BrowserTesting
              modelId={modelId}
              thinking={thinking}
              effort={effort}
              controls={browserControls}
              saveConnection={saveConnection}
              onCallsChanged={refreshRuns}
            />
          ) : screen === "compare" ? (
            <Suspense
              fallback={
                <div className="cr-empty">
                  <LoaderCircle className="cr-spin" />
                  加载对比图…
                </div>
              }
            >
              <Comparison
                runs={runs}
                tasks={config?.tasks || []}
                onOpen={(id) => {
                  setSelectedId(id);
                  setScreen("workbench");
                  if (id === selectedId) {
                    course<Detail>("/runs/" + id)
                      .then(setDetail)
                      .catch((error) => setError(error.message));
                  }
                }}
              />
            </Suspense>
          ) : (
            <>
              <section className="cr-chat-composer">
                <label htmlFor="cr-free-prompt">提示词</label>
                <span className="cr-prompt-task">
                  {draft.task_id && draft.task_id !== "custom-chat"
                    ? draft.task_name
                    : "自定义对话"}
                  {draft.task_id && draft.task_id !== "custom-chat" && (
                    <button
                      title="切换为自定义对话"
                      onClick={() => editDraft({ task_id: "", task_name: "" })}
                    >
                      <X size={11} />
                    </button>
                  )}
                </span>
                <textarea
                  ref={input}
                  id="cr-free-prompt"
                  value={draft.prompt}
                  onChange={(e) => editDraft({ prompt: e.target.value })}
                  placeholder="输入提示词…"
                  spellCheck={false}
                  onKeyDown={(e) => {
                    if (
                      (e.ctrlKey || e.metaKey) &&
                      e.key === "Enter" &&
                      !e.nativeEvent.isComposing &&
                      activeCount < 3
                    ) {
                      e.preventDefault();
                      start();
                    }
                  }}
                />
                <div className="cr-chat-send-row">
                  <span>Ctrl / ⌘ + Enter</span>
                  <button
                    className="cr-button primary"
                    disabled={
                      busy ||
                      !draft.prompt.trim() ||
                      activeCount >= 3 ||
                      !config
                    }
                    onClick={start}
                  >
                    {busy ? (
                      <LoaderCircle size={15} className="cr-spin" />
                    ) : (
                      <Send size={15} />
                    )}
                    发送
                  </button>
                </div>
              </section>
              <section className="cr-chat-output">
                {loading ? (
                  <div className="cr-empty">
                    <LoaderCircle className="cr-spin" />
                    读取记录…
                  </div>
                ) : !detail ? (
                  <div className="cr-empty">
                    <FlaskConical size={32} strokeWidth={1.2} />
                    <h3>暂无输出</h3>
                  </div>
                ) : (
                  <>
                    <div className="cr-chat-record">
                      <div>
                        <strong>{detail.model_name}</strong>
                        <span>{mode(detail)}</span>
                        <span
                          className={`cr-state state-${detail.status.toLowerCase()}`}
                        >
                          {statusText[detail.status]}
                        </span>
                      </div>
                      <button className="cr-text-button" onClick={reuse}>
                        复用输入
                      </button>
                    </div>
                    <details className="cr-sent-prompt">
                      <summary>本次输入</summary>
                      <pre>
                        {detail.prompt}
                        {detail.csv ? "\n\nCSV：\n" + detail.csv : ""}
                      </pre>
                    </details>
                    {detail.error && (
                      <div className="cr-inline-error">{detail.error}</div>
                    )}
                    <div className="cr-output-tabs">
                      <div>
                        {(
                          [
                            ["reasoning", "思考"],
                            ["answer", "原始输出"],
                            ["rendered", "渲染"],
                            ["preview", "应用预览"],
                            ["request", "请求"],
                          ] as const
                        ).map(([id, title]) => (
                          <button
                            key={id}
                            className={outputTab === id ? "active" : ""}
                            onClick={() => setOutputTab(id)}
                            disabled={
                              id === "preview" && !detail.html_available
                            }
                            title={
                              id === "preview" && !detail.html_available
                                ? "回复完成且包含 HTML 时可预览"
                                : title
                            }
                          >
                            {title}
                          </button>
                        ))}
                      </div>
                      <div>
                        <button
                          className="cr-text-button"
                          title="复制原始输出"
                          onClick={() =>
                            copy(
                              outputTab === "reasoning"
                                ? detail.reasoning
                                : detail.answer,
                            )
                          }
                        >
                          <Copy size={14} />
                        </button>
                        <a
                          title="下载记录"
                          href={`/api/course/runs/${detail.id}/download`}
                        >
                          <Download size={14} />
                        </a>
                      </div>
                    </div>
                    <div
                      className="cr-chat-content"
                      ref={outputArea}
                      onScroll={(e) => {
                        const node = e.currentTarget;
                        setFollow(
                          node.scrollHeight -
                            node.scrollTop -
                            node.clientHeight <
                            40,
                        );
                      }}
                    >
                      {outputTab === "reasoning" && (
                        <pre className="cr-raw-output">
                          {detail.reasoning ||
                            (!detail.thinking
                              ? "未开启思考"
                              : detail.status === "RUNNING"
                                ? "等待思考内容…"
                                : "服务未返回可见思考内容")}
                        </pre>
                      )}
                      {outputTab === "answer" && (
                        <pre className="cr-raw-output">
                          {detail.answer ||
                            (detail.status === "RUNNING"
                              ? "等待输出…"
                              : "无输出")}
                        </pre>
                      )}
                      {outputTab === "rendered" && (
                        <div className="cr-markdown">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            skipHtml
                            components={{
                              a: ({ children, href }) => (
                                <a href={href} target="_blank" rel="noreferrer">
                                  {children}
                                </a>
                              ),
                              img: ({ alt }) => (
                                <span className="cr-markdown-image">
                                  [图片：{alt || "未加载"}]
                                </span>
                              ),
                            }}
                          >
                            {detail.answer ||
                              (detail.status === "RUNNING"
                                ? "等待输出…"
                                : "无输出")}
                          </ReactMarkdown>
                        </div>
                      )}
                      {outputTab === "request" && (
                        <pre className="cr-raw-output">
                          {JSON.stringify(
                            {
                              request: detail.request,
                              returned_model: detail.returned_model,
                              finish_reason: detail.finish_reason,
                              raw_usage: detail.raw_usage,
                              price_snapshot: detail.price,
                            },
                            null,
                            2,
                          )}
                        </pre>
                      )}
                      {outputTab === "preview" && (
                        <div
                          className={`cr-preview ${phonePreview ? "phone-preview" : ""}`}
                        >
                          <div>
                            <button
                              className="cr-text-button"
                              onClick={async (event) => {
                                const preview =
                                  event.currentTarget.closest<HTMLElement>(
                                    ".cr-preview",
                                  );
                                try {
                                  if (document.fullscreenElement)
                                    await document.exitFullscreen();
                                  else await preview?.requestFullscreen();
                                } catch (error) {
                                  setError((error as Error).message);
                                }
                              }}
                            >
                              <Maximize2 size={13} />
                              全屏预览
                            </button>
                            <button
                              className="cr-text-button"
                              onClick={() => setPhonePreview((value) => !value)}
                            >
                              <MonitorPlay size={13} />
                              {phonePreview ? "宽屏" : "手机宽度"}
                            </button>
                            <button
                              className="cr-text-button"
                              onClick={() =>
                                setPreviewVersion((value) => value + 1)
                              }
                            >
                              <RotateCcw size={13} />
                              重新载入
                            </button>
                            <a
                              href={`/api/course/runs/${detail.id}/download?format=html`}
                              title="下载 HTML 与本地 Three.js，解压后打开 index.html"
                            >
                              <Download size={13} />
                              下载应用 ZIP
                            </a>
                          </div>
                          <iframe
                            ref={previewFrame}
                            style={{ height: previewHeight }}
                            key={`${detail.id}-${previewVersion}`}
                            src={`/api/course/runs/${detail.id}/preview`}
                            sandbox="allow-scripts"
                            referrerPolicy="no-referrer"
                            title="应用预览"
                          />
                        </div>
                      )}
                    </div>
                    {detail.status === "RUNNING" && (
                      <div className="cr-stream-footer">
                        <span>
                          <i className={streamConnected ? "connected" : ""} />
                          {streamConnected ? "接收中" : "重新连接中"}
                        </span>
                        <button
                          className="cr-text-button"
                          onClick={() => setFollow(true)}
                        >
                          回到最新
                        </button>
                      </div>
                    )}
                  </>
                )}
              </section>
            </>
          )}
        </main>
        {screen !== "browser" &&
          screen !== "requirements" &&
          screen !== "compare" && (
            <aside className="cr-inspector">
              <section className="cr-bill">
                <div className="cr-bill-heading">
                  <h2>调用统计</h2>
                  {detail?.status === "RUNNING" && (
                    <button onClick={() => cancel(detail)}>
                      <Square size={11} />
                      取消
                    </button>
                  )}
                </div>
                <div className="cr-stat-grid">
                  <div>
                    <span>
                      <Clock3 size={12} />
                      耗时
                    </span>
                    <b title={seconds(elapsed)}>{duration(elapsed)}</b>
                  </div>
                  <div>
                    <span>
                      <MessageSquareText size={12} />
                      Token
                    </span>
                    <b title={number(detail?.usage.total)}>
                      {compact(detail?.usage.total)}
                    </b>
                    <small>
                      入 {compact(detail?.usage.input)} / 出{" "}
                      {compact(detail?.usage.output)}
                    </small>
                  </div>
                  <div>
                    <span>
                      <Coins size={12} />
                      估算 CNY
                    </span>
                    <b
                      className="cr-stat-price"
                      title={detail ? money(detail.cost) : ""}
                    >
                      {detail ? money(detail.cost) : "—"}
                    </b>
                  </div>
                </div>
              </section>
              {detail && (
                <details className="cr-bill-details">
                  <summary>
                    时延与计费明细
                    <ChevronDown size={13} />
                  </summary>
                  <dl>
                    <dt>缓存输入 / 思考 Token</dt>
                    <dd>
                      {number(detail.usage.cached)} /{" "}
                      {number(detail.usage.reasoning)}
                    </dd>
                    <dt>首个可见内容</dt>
                    <dd>{seconds(detail.first_token)}</dd>
                    <dt>首个正式回复</dt>
                    <dd>{seconds(detail.first_answer)}</dd>
                    <dt>输入 / 输出单价</dt>
                    <dd>
                      ¥{detail.price.input} / ¥{detail.price.output}
                    </dd>
                    <dt>缓存输入单价</dt>
                    <dd>
                      {detail.price.cached == null
                        ? "按普通输入"
                        : `¥${detail.price.cached}`}
                    </dd>
                    <dt>口径</dt>
                    <dd>
                      {detail.price.period === "off_peak"
                        ? "闲时教学估算价"
                        : "北京标准价"}
                    </dd>
                  </dl>
                  <p>
                    单价单位：元 / 百万
                    Token。网络和排队包含在往返时延中；未返回的缓存或思考用量不猜测为零。
                  </p>
                </details>
              )}
              <section className="cr-history">
                <div className="cr-history-heading">
                  <div>
                    <h2>调用记录</h2>
                  </div>
                  <span>{runs.length}</span>
                </div>
                <input
                  className="cr-search"
                  placeholder="筛选模型、思考设置…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <div className="cr-history-actions">
                  <button
                    className="cr-text-button"
                    onClick={() => setScreen("compare")}
                  >
                    查看任务对比
                    <ArrowRight size={12} />
                  </button>
                </div>
                {visibleRuns.length === 0 && (
                  <p className="cr-history-empty">
                    还没有记录。
                    <br />
                    发送后自动保存记录。
                  </p>
                )}
                <div className="cr-run-list">
                  {visibleRuns.map((run) => (
                    <article
                      key={run.id}
                      className={`cr-history-run ${run.id === selectedId ? "selected" : ""}`}
                    >
                      <button
                        className="cr-run-select"
                        onClick={() => {
                          setSelectedId(run.id);
                          setScreen("workbench");
                        }}
                      >
                        <div>
                          <strong>{run.model_name}</strong>
                          <span
                            className={`cr-call-status state-${run.status.toLowerCase()}`}
                            title={statusText[run.status]}
                          >
                            {run.status === "RUNNING"
                              ? "进行中"
                              : run.status === "COMPLETED"
                                ? "已完成"
                                : "失败"}
                          </span>
                        </div>
                        <p>
                          <span
                            className="cr-record-task"
                            title={
                              run.task_kind === "custom"
                                ? "自定义对话"
                                : `所属任务：${run.task_name}`
                            }
                          >
                            {run.task_name}
                          </span>{" "}
                          · {mode(run)}
                        </p>
                        <div className="cr-run-numbers">
                          <span title="估算金额">
                            <Coins size={10} />
                            {money(run.cost)}
                          </span>
                          <span title={`Token：${number(run.usage.total)}`}>
                            <MessageSquareText size={10} />
                            {compact(run.usage.total)}
                          </span>
                          <span title="耗时">
                            <Clock3 size={10} />
                            {duration(run.duration)}
                          </span>
                        </div>
                      </button>
                      <button
                        className="cr-run-delete"
                        aria-label={
                          run.status === "RUNNING"
                            ? "取消此次尝试"
                            : "删除此次尝试"
                        }
                        title={
                          run.status === "RUNNING"
                            ? "取消此次尝试"
                            : "删除此次尝试"
                        }
                        onClick={() =>
                          run.status === "RUNNING" ? cancel(run) : remove(run)
                        }
                      >
                        {run.status === "RUNNING" ? (
                          <Square size={12} />
                        ) : (
                          <Trash2 size={13} />
                        )}
                      </button>
                    </article>
                  ))}
                </div>
              </section>
            </aside>
          )}
      </div>

      {!config && !error && (
        <div className="cr-loading">
          <LoaderCircle className="cr-spin" />
          加载练习室…
        </div>
      )}
    </div>
  );
}
