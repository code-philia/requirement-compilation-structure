import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  Code2,
  Play,
  Plus,
  RotateCcw,
  Send,
  Square,
  Wrench,
} from "lucide-react";
import {
  course,
  money,
  number,
  seconds,
  statusText,
  type Detail,
  type Run,
} from "./api";
import "./browser-testing.css";

type Step = {
  code: string;
  status: string;
  error: string;
  screenshot: string | null;
  duration: number;
};
type Case = {
  name: string;
  status: string;
  steps: Step[];
  error: string;
  trace?: string;
};
type Execution = {
  id: string;
  started_at: string;
  revision: number;
  script: string;
  script_hash: string;
  status: string;
  cases: Case[];
  duration: number;
  error: string;
};
type Session = {
  id: string;
  created_at: string;
  status: string;
  error: string;
  intent: string;
  requirements: string;
  html: string;
  script: string;
  revision: number;
  calls: (Run & { action: string })[];
  executions: Execution[];
};
type History = Pick<Session, "id" | "created_at" | "revision" | "status">;
type Props = {
  modelId: string;
  thinking: boolean;
  effort: string;
  inspector: HTMLElement | null;
  saveConnection: () => Promise<void>;
  onCallsChanged: () => Promise<void>;
};
const labels: Record<string, string> = {
  IDLE: "就绪",
  GENERATING: "生成测试中",
  EXECUTING: "执行测试中",
  REPAIRING: "修复应用中",
  PASSED: "通过",
  FAILED: "失败",
  RUNNING: "进行中",
  INTERRUPTED: "已中断",
};
const previewPolicy =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'";

export default function BrowserTesting(props: Props) {
  const [identity, setIdentity] = useState(
    () => sessionStorage.getItem("classroom-browser-session") || "",
  );
  const [session, setSession] = useState<Session | null>(null);
  const [history, setHistory] = useState<History[]>([]);
  const [intent, setIntent] = useState("");
  const [script, setScript] = useState("");
  const [tab, setTab] = useState("app");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(0);
  const [executionId, setExecutionId] = useState("");
  const [selectedStep, setSelectedStep] = useState<{
    caseIndex: number;
    stepIndex: number;
  } | null>(null);
  const [callId, setCallId] = useState("");
  const [call, setCall] = useState<Detail | null>(null);
  const [callTab, setCallTab] = useState("answer");

  useEffect(() => {
    let disposed = false;
    course<{ items: History[] }>("/browser/sessions")
      .then((data) => {
        if (!disposed) setHistory(data.items);
      })
      .catch((error) => {
        if (!disposed) setError(error.message);
      });
    return () => {
      disposed = true;
    };
  }, [identity]);

  useEffect(() => {
    if (!identity) return;
    sessionStorage.setItem("classroom-browser-session", identity);
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await course<Session>(`/browser/sessions/${identity}`);
        if (disposed) return;
        setSession(value);
      } catch (error) {
        if (!disposed) setError((error as Error).message);
      }
      if (!disposed) timer = setTimeout(poll, 1000);
    }
    poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [identity]);

  useEffect(() => {
    setIntent(session?.intent || "");
  }, [session?.id, session?.intent]);
  useEffect(() => {
    setScript(session?.script || "");
  }, [session?.id, session?.script]);
  useEffect(() => {
    setExecutionId("");
    setSelectedStep(null);
    setCallId("");
    setCall(null);
  }, [identity]);

  useEffect(() => {
    if (!callId) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await course<Detail>(`/runs/${callId}`);
        if (disposed) return;
        setCall(value);
        if (value.status === "RUNNING") timer = setTimeout(poll, 1000);
      } catch (error) {
        if (!disposed) setError((error as Error).message);
      }
    }
    poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [callId]);

  const working = busy || (!!session && session.status !== "IDLE");
  const execution =
    session?.executions.find((item) => item.id === executionId) ||
    session?.executions.at(-1);
  const lastExecution = session?.executions.at(-1);
  const steps = execution?.cases.flatMap((item) => item.steps) || [];
  const screenshot = selectedStep
    ? execution?.cases[selectedStep.caseIndex]?.steps[selectedStep.stepIndex]
    : steps.at(-1);
  const calls = session?.calls || [];
  const cost = calls.reduce((sum, item) => sum + (item.cost || 0), 0);
  const tokens = calls.reduce((sum, item) => sum + (item.usage.total || 0), 0);
  const elapsed = calls.reduce((sum, item) => sum + item.duration, 0);

  async function create() {
    if (working) return;
    setBusy(true);
    setError("");
    try {
      const value = await course<Session>("/browser/sessions", {});
      setSession(value);
      setIdentity(value.id);
      setTab("app");
      setPreview(0);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function act(action: string) {
    if (!session || working) return;
    setBusy(true);
    setError("");
    try {
      if (action !== "execute") await props.saveConnection();
      const value = await course<Session>(
        `/browser/sessions/${identity}/actions`,
        {
          action,
          model_id: props.modelId,
          thinking: props.thinking,
          effort: props.effort,
          intent,
          script,
        },
      );
      setSession(value);
      if (action === "execute") {
        setExecutionId("");
        setSelectedStep(null);
        setTab("execution");
      }
      if (action === "generate") setTab("script");
      if (action === "repair") setTab("app");
      await props.onCallsChanged();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function openCall(id: string) {
    setCallId(id);
    setCall(null);
    setCallTab("answer");
    setTab("model");
  }

  const inspector = (
    <>
      <section className="cr-bill bt-bill">
        <div className="cr-bill-heading">
          <h2>练习统计</h2>
          <span className={`bt-status ${working ? "running" : ""}`}>
            {labels[session?.status || "IDLE"]}
          </span>
        </div>
        <div className="cr-stat-grid">
          <div>
            <span>模型耗时</span>
            <b>{seconds(calls.length ? elapsed : null)}</b>
          </div>
          <div>
            <span>Token</span>
            <b>
              {calls.some((item) => item.usage.total != null)
                ? number(tokens)
                : "—"}
            </b>
          </div>
          <div>
            <span>金额</span>
            <b>
              {money(calls.some((item) => item.cost != null) ? cost : null)}
            </b>
          </div>
        </div>
        {calls.some(
          (item) => item.cost == null || item.usage.total == null,
        ) && <p className="cr-hint">仅累计已返回的用量与金额。</p>}
      </section>
      <section className="bt-inspector-section">
        <h3>测试结果</h3>
        {execution ? (
          <>
            <div className="bt-result-line">
              <span className={`bt-status ${execution.status.toLowerCase()}`}>
                {labels[execution.status]}
              </span>
              <span>{seconds(execution.duration)}</span>
            </div>
            <p>
              {
                execution.cases.filter((item) => item.status === "PASSED")
                  .length
              }{" "}
              / {execution.cases.length} 个用例通过 · 应用修订{" "}
              {execution.revision}
            </p>
            <p className="cr-hint">
              脚本指纹 {execution.script_hash.slice(0, 10)}
            </p>
            <button
              className="cr-text-button"
              onClick={() => setTab("execution")}
            >
              查看步骤与截图 →
            </button>
          </>
        ) : (
          <p className="cr-hint">执行后展示用例结果。</p>
        )}
      </section>
      <section className="bt-inspector-section bt-calls">
        <h3>
          模型调用 <small>{calls.length}</small>
        </h3>
        {calls.length === 0 && (
          <p className="cr-hint">生成测试与修复应用分别记录。</p>
        )}
        {[...calls].reverse().map((item) => (
          <button
            key={item.id}
            className="bt-call"
            onClick={() => openCall(item.id)}
          >
            <div>
              <strong>
                {item.action === "generate" ? "生成测试" : "修复应用"}
              </strong>
              <span
                className={`bt-status ${item.status === "COMPLETED" ? "passed" : item.status === "RUNNING" ? "running" : "failed"}`}
              >
                {statusText[item.status]}
              </span>
            </div>
            <p>
              {item.model_name} ·{" "}
              {item.thinking ? item.effort || "思考开启" : "思考关闭"}
            </p>
            <div className="bt-call-metrics">
              <span>{seconds(item.duration)}</span>
              <span>{number(item.usage.total)} Token</span>
              <span>{money(item.cost)}</span>
            </div>
          </button>
        ))}
      </section>
    </>
  );

  return (
    <div className="bt-workspace">
      {props.inspector && createPortal(inspector, props.inspector)}
      <header className="bt-heading">
        <div>
          <h2>浏览器测试</h2>
          <span>
            {session ? `报销清单 · 修订 ${session.revision}` : "报销清单"}
          </span>
        </div>
        <div className="bt-actions">
          <select
            aria-label="历史练习"
            value={identity}
            disabled={working}
            onChange={(event) => {
              setSession(null);
              setIdentity(event.target.value);
            }}
          >
            <option value="" disabled>
              历史练习
            </option>
            {history.map((item) => (
              <option value={item.id} key={item.id}>
                {new Date(item.created_at).toLocaleString()} ·{" "}
                {item.id.slice(0, 6)}
              </option>
            ))}
            {identity && !history.some((item) => item.id === identity) && (
              <option value={identity}>当前练习</option>
            )}
          </select>
          <button
            className="cr-button secondary"
            disabled={working}
            onClick={create}
          >
            <Plus size={14} />
            {session ? "重置为新练习" : "新建练习"}
          </button>
        </div>
      </header>
      <details className="bt-introduction">
        <summary>操作说明</summary>
        <p>
          浏览器自动化代替人填写、点击；测试通过断言检查结果。Playwright
          检查明确的功能规则，截图对比检查画面变化，视觉模型可辅助检查排版。本练习使用
          Playwright 功能测试。
        </p>
        <p>
          初始应用预置“合计只取最后一项”的缺陷。生成测试后执行，再将失败反馈交给模型修复应用，最后执行同一份测试。重置会保留旧记录，建立全新的缺陷应用。
        </p>
      </details>
      {(error || session?.error) && (
        <div className="bt-error" role="alert">
          {error || session?.error}
        </div>
      )}
      {!session ? (
        <div className="bt-empty">
          <Code2 size={32} />
          <h3>{identity ? "正在读取练习" : "报销清单测试"}</h3>
          <p>新建练习，输入测试步骤，生成并执行 Playwright 脚本。</p>
          <button
            className="cr-button primary"
            disabled={busy}
            onClick={create}
          >
            新建练习
          </button>
        </div>
      ) : (
        <>
          <section className="bt-composer">
            <label htmlFor="bt-intent">测试意图 / 操作步骤</label>
            <textarea
              id="bt-intent"
              value={intent}
              disabled={working}
              onChange={(event) => setIntent(event.target.value)}
              spellCheck={false}
            />
            <div className="bt-actions">
              <button
                className="cr-button primary"
                disabled={working || !intent.trim()}
                onClick={() => act("generate")}
              >
                <Send size={14} />
                生成测试
              </button>
              <button
                className="cr-button secondary"
                disabled={working || !script.trim()}
                onClick={() => act("execute")}
              >
                <Play size={14} />
                执行测试
              </button>
              <button
                className="cr-button secondary"
                disabled={
                  working ||
                  lastExecution?.status !== "FAILED" ||
                  lastExecution.script !== script ||
                  lastExecution.revision !== session.revision ||
                  !lastExecution.cases.some((item) => item.status === "FAILED")
                }
                onClick={() => act("repair")}
              >
                <Wrench size={14} />
                修复应用
              </button>
              {working && (
                <button
                  className="cr-button secondary"
                  onClick={async () => {
                    try {
                      setSession(
                        await course<Session>(
                          `/browser/sessions/${identity}/cancel`,
                          {},
                        ),
                      );
                    } catch (error) {
                      setError((error as Error).message);
                    }
                  }}
                >
                  <Square size={12} />
                  停止
                </button>
              )}
              <span className="bt-operation" role="status">
                {labels[session.status]}
              </span>
            </div>
          </section>
          <nav className="bt-tabs" aria-label="浏览器测试内容">
            {[
              ["app", "应用预览"],
              ["script", "测试脚本"],
              ["execution", "执行记录"],
              ["source", "应用源码"],
              ["model", "模型回复"],
            ].map(([id, name]) => (
              <button
                key={id}
                className={tab === id ? "active" : ""}
                onClick={() => setTab(id)}
              >
                {name}
              </button>
            ))}
          </nav>
          <section className="bt-content">
            {tab === "app" && (
              <>
                <div className="bt-content-heading">
                  <span>手动操作不会影响测试；每个用例使用全新页面。</span>
                  <button
                    className="cr-text-button"
                    onClick={() => setPreview((value) => value + 1)}
                  >
                    <RotateCcw size={13} />
                    清空预览
                  </button>
                </div>
                <iframe
                  key={`${session.id}-${session.revision}-${preview}`}
                  title="报销清单应用"
                  sandbox="allow-scripts"
                  referrerPolicy="no-referrer"
                  srcDoc={`<!doctype html><meta http-equiv="Content-Security-Policy" content="${previewPolicy}">${session.html.replace(/<!doctype[^>]*>/i, "")}`}
                />
              </>
            )}
            {tab === "script" && (
              <>
                <p className="cr-hint">
                  Python / Playwright ·
                  可编辑；修复应用时不会修改测试。每个用例从 APP_URL
                  开始，只支持页面定位、操作和 expect 断言。
                </p>
                <textarea
                  className="bt-script"
                  aria-label="Playwright 测试脚本"
                  value={script}
                  disabled={working}
                  onChange={(event) => setScript(event.target.value)}
                  placeholder="生成测试后在此查看脚本，也可自行输入支持的 Playwright 脚本。"
                  spellCheck={false}
                />
              </>
            )}
            {tab === "source" && <pre>{session.html}</pre>}
            {tab === "execution" && (
              <>
                <div className="bt-content-heading">
                  <select
                    aria-label="选择执行记录"
                    value={execution?.id || ""}
                    onChange={(event) => {
                      setExecutionId(event.target.value);
                      setSelectedStep(null);
                    }}
                  >
                    {!execution && <option>暂无执行记录</option>}
                    {[...session.executions].reverse().map((item, index) => (
                      <option key={item.id} value={item.id}>
                        {session.executions.length - index} ·{" "}
                        {labels[item.status]} · 修订 {item.revision} ·{" "}
                        {seconds(item.duration)}
                      </option>
                    ))}
                  </select>
                  {execution && (
                    <span>脚本 {execution.script_hash.slice(0, 10)}</span>
                  )}
                </div>
                {execution?.error && (
                  <div className="bt-error">{execution.error}</div>
                )}
                {!execution && (
                  <p className="cr-hint">点击执行测试，查看逐步结果。</p>
                )}
                <div className="bt-execution-grid">
                  <div>
                    {execution?.cases.map((item, caseIndex) => (
                      <details key={caseIndex} className="bt-case" open>
                        <summary>
                          <span
                            className={`bt-status ${item.status.toLowerCase()}`}
                          >
                            {labels[item.status]}
                          </span>
                          {item.name}
                        </summary>
                        {item.steps.map((step, stepIndex) => (
                          <button
                            className={`bt-step ${step.status.toLowerCase()}`}
                            key={stepIndex}
                            onClick={() =>
                              setSelectedStep({ caseIndex, stepIndex })
                            }
                          >
                            <span>
                              {step.status === "PASSED"
                                ? "✓"
                                : step.status === "FAILED"
                                  ? "×"
                                  : "·"}
                            </span>
                            <code>{step.code}</code>
                            <small>{seconds(step.duration)}</small>
                          </button>
                        ))}
                        {item.error && (
                          <pre className="bt-failure">{item.error}</pre>
                        )}
                        {item.trace && (
                          <a
                            className="bt-trace"
                            href={`/api/course/browser/sessions/${identity}/files/${item.trace}`}
                            download
                          >
                            下载执行轨迹（Trace Viewer）
                          </a>
                        )}
                      </details>
                    ))}
                  </div>
                  <div className="bt-screenshot">
                    {screenshot?.screenshot ? (
                      <>
                        <img
                          src={`/api/course/browser/sessions/${identity}/files/${screenshot.screenshot}`}
                          alt="所选测试步骤完成后的页面截图"
                        />
                        <p>{screenshot.code}</p>
                      </>
                    ) : (
                      <p className="cr-hint">执行后展示截图；点击步骤切换。</p>
                    )}
                  </div>
                </div>
                {execution && (
                  <details className="bt-snapshot">
                    <summary>本次执行的固定脚本</summary>
                    <pre>{execution.script}</pre>
                  </details>
                )}
              </>
            )}
            {tab === "model" && (
              <>
                <div className="bt-content-heading">
                  <select
                    aria-label="模型调用"
                    value={callId}
                    onChange={(event) => openCall(event.target.value)}
                  >
                    <option value="" disabled>
                      选择模型调用
                    </option>
                    {calls.map((item, index) => (
                      <option key={item.id} value={item.id}>
                        {index + 1} ·{" "}
                        {item.action === "generate" ? "生成测试" : "修复应用"} ·{" "}
                        {item.model_name}
                      </option>
                    ))}
                  </select>
                  <div className="bt-actions">
                    {[
                      ["answer", "原始回复"],
                      ["reasoning", "思考"],
                      ["prompt", "输入"],
                    ].map(([id, label]) => (
                      <button
                        className={`cr-text-button ${callTab === id ? "active" : ""}`}
                        key={id}
                        onClick={() => setCallTab(id)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                {call?.error && <div className="bt-error">{call.error}</div>}
                <pre>
                  {call
                    ? callTab === "reasoning"
                      ? call.reasoning || "没有返回思考内容"
                      : callTab === "prompt"
                        ? call.prompt
                        : call.answer || "等待回复…"
                    : "从右侧选择一次模型调用，查看输入、思考与原始回复。"}
                </pre>
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}
