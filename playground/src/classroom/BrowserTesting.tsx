import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Check,
  Copy,
  Maximize2,
  Play,
  Plus,
  RotateCcw,
  Send,
  Square,
  Wrench,
} from "lucide-react";
import { course } from "./api";
import "./browser-testing.css";

type Step = {
  code: string;
  status: string;
  error: string;
  screenshot: string | null;
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
  status: string;
  cases: Case[];
  error: string;
  script: string;
};
type Message = {
  id: string;
  created_at: string;
  action: string;
  user: string;
  answer: string;
  reasoning: string;
  status: string;
  error: string;
  model: string;
  proposal: {
    summary: string;
    edits: {
      path: string;
      operation: string;
      old_content: string;
      new_content: string;
    }[];
  } | null;
  proposal_error: string;
  applied_revision: number | null;
};
type Session = {
  id: string;
  created_at: string;
  status: string;
  error: string;
  intent: string;
  html: string;
  script: string;
  revision: number;
  messages: Message[];
  executions: Execution[];
};
type History = Pick<Session, "id" | "created_at" | "revision" | "status">;
type Live = {
  execution_id: string;
  sequence: number;
  frame: string;
  status: string;
  step: string;
  case: string;
};
type Props = {
  modelId: string;
  thinking: boolean;
  effort: string;
  controls: HTMLElement | null;
  saveConnection: () => Promise<void>;
  onCallsChanged: () => Promise<void>;
};
const labels: Record<string, string> = {
  IDLE: "就绪",
  CHATTING: "正在回复",
  GENERATING: "正在生成",
  EXECUTING: "自动化运行中",
  REPAIRING: "正在修复",
  RUNNING: "进行中",
  PASSED: "通过",
  FAILED: "失败",
  INTERRUPTED: "已中断",
};
const previewPolicy =
  "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'";

function executionFeedback(execution: Execution) {
  const lines = [
    `测试结果：${labels[execution.status] || execution.status}`,
    `应用修订：${execution.revision}`,
  ];
  for (const item of execution.cases) {
    lines.push(`\n${item.name}：${labels[item.status] || item.status}`);
    for (const step of item.steps) {
      if (step.status === "FAILED") lines.push(`失败步骤：${step.code}`);
    }
    if (item.error) lines.push(item.error);
  }
  if (execution.error) lines.push(execution.error);
  return lines.join("\n");
}

function pythonCode(answer: string) {
  const block = answer.match(/```(?:python|py)\s*\n([\s\S]*?)```/i);
  if (block) return block[1].trim();
  if (/^\s*(?:from playwright|async def test_)/.test(answer))
    return answer.trim();
  return "";
}

export default function BrowserTesting(props: Props) {
  const [identity, setIdentity] = useState(
    () => sessionStorage.getItem("classroom-browser-session") || "",
  );
  const [session, setSession] = useState<Session | null>(null);
  const [history, setHistory] = useState<History[]>([]);
  const [draft, setDraft] = useState("");
  const [script, setScript] = useState("");
  const [feedback, setFeedback] = useState("");
  const [editor, setEditor] = useState("script");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(0);
  const [previewMode, setPreviewMode] = useState("app");
  const [snapshot, setSnapshot] = useState("");
  const [live, setLive] = useState<Live | null>(null);
  const [connected, setConnected] = useState(false);
  const [copied, setCopied] = useState("");
  const [follow, setFollow] = useState(true);
  const chatArea = useRef<HTMLDivElement>(null);
  const previewArea = useRef<HTMLElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

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
      if (!disposed) timer = setTimeout(poll, 700);
    }
    poll();
    const source = new EventSource(
      `/api/course/browser/sessions/${identity}/live`,
    );
    source.onopen = () => {
      if (!disposed) setConnected(true);
    };
    source.onmessage = (event) => {
      if (disposed) return;
      const state: Live = JSON.parse(event.data);
      setLive(state);
    };
    source.onerror = () => {
      if (!disposed) setConnected(false);
    };
    return () => {
      disposed = true;
      clearTimeout(timer);
      source.close();
    };
  }, [identity]);

  useEffect(() => {
    setFeedback("");
    setLive(null);
    setConnected(false);
    setError("");
    setPreviewMode("app");
  }, [identity]);
  useEffect(() => {
    setDraft(session?.intent || "");
  }, [session?.id]);
  useEffect(() => {
    setScript(session?.script || "");
  }, [session?.id, session?.script]);
  useEffect(() => {
    setPreviewMode("app");
  }, [session?.id, session?.revision]);
  useEffect(() => {
    if (live?.status === "RUNNING") {
      setPreviewMode("live");
    } else if (live?.execution_id) {
      setPreviewMode((mode) => (mode === "live" ? "app" : mode));
    }
  }, [live?.execution_id, live?.status]);

  const messages = session?.messages || [];
  const executions = session?.executions || [];
  const latest = executions.at(-1);
  const working = busy || (!!session && session.status !== "IDLE");
  const progress =
    messages
      .map(
        (item) =>
          `${item.id}:${item.answer.length}:${item.reasoning.length}:${item.status}:${item.proposal?.edits.length}:${item.applied_revision}`,
      )
      .join("|") +
    executions.map((item) => `${item.id}:${item.status}`).join("|");
  useEffect(() => {
    const area = chatArea.current;
    if (follow && area) area.scrollTop = area.scrollHeight;
  }, [progress, follow]);

  async function copy(text: string, id: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
    } catch {
      setError("复制失败，请选中文字后复制。");
    }
  }

  async function create() {
    if (working) return;
    setBusy(true);
    setError("");
    try {
      const value = await course<Session>("/browser/sessions", {});
      setSession(value);
      setIdentity(value.id);
      setPreview(0);
      setFollow(true);
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
          intent: draft,
          message: draft,
          script,
          feedback,
        },
      );
      setSession(value);
      setFollow(true);
      if (action === "chat") setDraft("");
      if (action === "execute") {
        setLive(null);
        setPreviewMode("live");
      }
      if (action !== "execute") await props.onCallsChanged();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    try {
      setSession(
        await course<Session>(`/browser/sessions/${identity}/cancel`, {}),
      );
    } catch (error) {
      setError((error as Error).message);
    }
  }

  async function applyReply(replyId: string) {
    if (!session || working) return;
    setBusy(true);
    setError("");
    try {
      const value = await course<Session>(
        `/browser/sessions/${identity}/replies/${replyId}/apply`,
        {},
      );
      setSession(value);
      setPreviewMode("app");
      setPreview((value) => value + 1);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const timeline = [
    ...messages.map((message) => ({
      id: message.id,
      time: message.created_at,
      message,
      execution: null as Execution | null,
    })),
    ...executions.map((execution) => ({
      id: execution.id,
      time: execution.started_at,
      message: null as Message | null,
      execution,
    })),
  ].sort((left, right) => left.time.localeCompare(right.time));

  return (
    <div className="bt-workspace">
      {props.controls &&
        createPortal(
          <div className="cr-sidebar-action">
            <button
              className="cr-button primary"
              disabled={working}
              onClick={create}
            >
              <Plus size={18} />
              {session ? "新建练习 / 重置" : "新建练习"}
            </button>
          </div>,
          props.controls,
        )}
      <header className="bt-heading">
        <div>
          <h2>浏览器测试</h2>
          <span className={`bt-status ${working ? "running" : ""}`}>
            {labels[session?.status || "IDLE"]}
          </span>
        </div>
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
            <option key={item.id} value={item.id}>
              {new Date(item.created_at).toLocaleString()} ·{" "}
              {item.id.slice(0, 6)}
            </option>
          ))}
          {identity && !history.some((item) => item.id === identity) && (
            <option value={identity}>当前练习</option>
          )}
        </select>
      </header>
      <div className="bt-layout">
        <section className="bt-chat">
          <div
            className="bt-chat-messages"
            ref={chatArea}
            onScroll={(event) => {
              const area = event.currentTarget;
              setFollow(
                area.scrollHeight - area.scrollTop - area.clientHeight < 100,
              );
            }}
          >
            {!timeline.length && (
              <div className="bt-chat-welcome">
                <h3>与模型讨论测试</h3>
                <p>
                  描述操作步骤，让模型编写 Playwright
                  测试；将脚本填入右侧执行，查看自动化过程。
                </p>
                <p>初始应用的合计计算存在缺陷，可通过添加两项费用发现问题。</p>
                {!session && (
                  <button
                    className="cr-button primary"
                    disabled={busy}
                    onClick={create}
                  >
                    新建练习
                  </button>
                )}
              </div>
            )}
            {timeline.map((item) =>
              item.message ? (
                <div className="bt-turn" key={item.id}>
                  <article className="bt-message user">
                    <div className="bt-message-label">你</div>
                    <p>{item.message.user}</p>
                  </article>
                  <article className="bt-message assistant">
                    <div className="bt-message-label">
                      {item.message.model}
                      <span>
                        {item.message.status === "RUNNING"
                          ? "正在回复…"
                          : item.message.applied_revision != null
                            ? `已应用 · 修订 ${item.message.applied_revision}`
                            : item.message.proposal
                              ? "修改待应用"
                              : ""}
                      </span>
                    </div>
                    {item.message.reasoning && (
                      <details className="bt-reasoning">
                        <summary>思考过程</summary>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {item.message.reasoning}
                        </ReactMarkdown>
                      </details>
                    )}
                    {item.message.proposal ? (
                      <div className="bt-edit-proposal">
                        <p>{item.message.proposal.summary}</p>
                        {item.message.proposal.edits.map((edit, index) => (
                          <details key={index}>
                            <summary>
                              {index + 1}. {edit.path} · {edit.operation}
                            </summary>
                            <div className="bt-edit-before">
                              <span>替换前</span>
                              <pre>{edit.old_content}</pre>
                            </div>
                            <div className="bt-edit-after">
                              <span>替换后</span>
                              <pre>{edit.new_content || "（删除此片段）"}</pre>
                            </div>
                          </details>
                        ))}
                        <button
                          className="cr-button primary"
                          disabled={
                            working || item.message.applied_revision != null
                          }
                          onClick={() => applyReply(item.id)}
                        >
                          <Check size={13} />
                          {item.message.applied_revision != null
                            ? "已应用修改"
                            : `Apply · 应用 ${item.message.proposal.edits.length} 项修改`}
                        </button>
                      </div>
                    ) : (
                      <div className="bt-markdown">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {/^\s*(?:<!doctype|<html)/i.test(item.message.answer)
                            ? `\`\`\`html\n${item.message.answer}\n\`\`\``
                            : item.message.answer ||
                              (item.message.status === "RUNNING"
                                ? "等待回复…"
                                : "没有返回回复")}
                        </ReactMarkdown>
                      </div>
                    )}
                    {(item.message.error || item.message.proposal_error) && (
                      <div className="bt-error">
                        {item.message.error || item.message.proposal_error}
                      </div>
                    )}
                    <div className="bt-message-actions">
                      <button
                        onClick={() => copy(item.message!.answer, item.id)}
                      >
                        {copied === item.id ? (
                          <Check size={12} />
                        ) : (
                          <Copy size={12} />
                        )}
                        复制回复
                      </button>
                      {pythonCode(item.message.answer) && (
                        <button
                          disabled={working}
                          onClick={() => {
                            setScript(pythonCode(item.message!.answer));
                            setEditor("script");
                          }}
                        >
                          <Play size={12} />
                          填入测试区
                        </button>
                      )}
                    </div>
                  </article>
                </div>
              ) : item.execution ? (
                <article className="bt-test-message" key={item.id}>
                  <div className="bt-message-label">
                    <Play size={13} />
                    测试结果
                    <span
                      className={`bt-status ${item.execution.status.toLowerCase()}`}
                    >
                      {labels[item.execution.status]}
                    </span>
                  </div>
                  <p>
                    {
                      item.execution.cases.filter(
                        (test) => test.status === "PASSED",
                      ).length
                    }{" "}
                    / {item.execution.cases.length} 个用例通过 · 应用修订{" "}
                    {item.execution.revision}
                  </p>
                  <details>
                    <summary>查看测试反馈</summary>
                    <pre>{executionFeedback(item.execution)}</pre>
                  </details>
                  <div className="bt-message-actions">
                    <button
                      disabled={item.execution.status === "RUNNING"}
                      onClick={() => {
                        setFeedback(executionFeedback(item.execution!));
                        setEditor("feedback");
                      }}
                    >
                      <Wrench size={12} />
                      填入修复反馈
                    </button>
                    <button
                      onClick={() =>
                        copy(executionFeedback(item.execution!), item.id)
                      }
                    >
                      {copied === item.id ? (
                        <Check size={12} />
                      ) : (
                        <Copy size={12} />
                      )}
                      复制反馈
                    </button>
                    {item.execution.cases
                      .flatMap((test) => test.steps)
                      .some((step) => step.screenshot) && (
                      <button
                        onClick={() => {
                          const step = item
                            .execution!.cases.flatMap((test) => test.steps)
                            .filter((step) => step.screenshot)
                            .at(-1);
                          setSnapshot(
                            `/api/course/browser/sessions/${identity}/files/${step!.screenshot}`,
                          );
                          setPreviewMode("snapshot");
                        }}
                      >
                        查看画面
                      </button>
                    )}
                  </div>
                </article>
              ) : null,
            )}
          </div>
          {(error || session?.error) && (
            <div className="bt-error" role="alert">
              {error || session?.error}
            </div>
          )}
          <div className="bt-chat-composer">
            <textarea
              ref={input}
              aria-label="与模型对话"
              placeholder="输入测试意图、追问或修改要求…"
              value={draft}
              disabled={!session}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (
                  (event.ctrlKey || event.metaKey) &&
                  event.key === "Enter" &&
                  !event.nativeEvent.isComposing &&
                  !working &&
                  draft.trim()
                ) {
                  event.preventDefault();
                  act("chat");
                }
              }}
            />
            <div className="bt-actions">
              <span>Ctrl / ⌘ + Enter</span>
              {working ? (
                <button className="cr-button secondary" onClick={stop}>
                  <Square size={13} />
                  停止
                </button>
              ) : (
                <button
                  className="cr-button primary"
                  disabled={!session || !draft.trim()}
                  onClick={() => act("chat")}
                >
                  <Send size={14} />
                  发送
                </button>
              )}
            </div>
          </div>
        </section>
        <section className="bt-right">
          <section className="bt-editor">
            <nav className="bt-editor-tabs" aria-label="代码执行区">
              {[
                ["script", "Playwright 测试"],
                ["feedback", "修复反馈"],
                ["source", "应用源码"],
              ].map(([id, label]) => (
                <button
                  key={id}
                  className={editor === id ? "active" : ""}
                  onClick={() => setEditor(id)}
                >
                  {label}
                </button>
              ))}
            </nav>
            <textarea
              aria-label={
                editor === "script"
                  ? "Playwright 测试脚本"
                  : editor === "feedback"
                    ? "测试反馈"
                    : "应用源码"
              }
              className="bt-code"
              value={
                editor === "script"
                  ? script
                  : editor === "feedback"
                    ? feedback
                    : session?.html || ""
              }
              readOnly={editor === "source"}
              disabled={!session || working}
              onChange={(event) =>
                editor === "script"
                  ? setScript(event.target.value)
                  : setFeedback(event.target.value)
              }
              placeholder={
                editor === "script"
                  ? "粘贴 Python / Playwright 测试脚本，或从模型回复填入…"
                  : "粘贴测试反馈，或填入最近一次执行结果…"
              }
              spellCheck={false}
            />
            <div className="bt-editor-footer">
              {editor === "script" ? (
                <>
                  <span>每个用例从 APP_URL 开始</span>
                  <button
                    className="cr-button primary"
                    disabled={!session || working || !script.trim()}
                    onClick={() => act("execute")}
                  >
                    <Play size={13} />
                    执行测试
                  </button>
                </>
              ) : editor === "feedback" ? (
                <>
                  <button
                    className="cr-text-button"
                    disabled={!latest || working}
                    onClick={() => setFeedback(executionFeedback(latest!))}
                  >
                    填入最近结果
                  </button>
                  <button
                    className="cr-button primary"
                    disabled={!session || working || !feedback.trim()}
                    onClick={() => act("repair")}
                  >
                    <Wrench size={13} />
                    启动应用修复
                  </button>
                </>
              ) : (
                <>
                  <span>应用修订 {session?.revision || 0}</span>
                  <button
                    className="cr-text-button"
                    onClick={() => copy(session?.html || "", "source")}
                  >
                    <Copy size={12} />
                    复制源码
                  </button>
                </>
              )}
            </div>
          </section>
          <section className="bt-preview" ref={previewArea}>
            <header>
              <div>
                <strong>应用预览</strong>
                <span
                  className={`bt-status ${live?.status === "RUNNING" && previewMode === "live" ? "running" : ""}`}
                >
                  {previewMode === "live"
                    ? live?.status === "RUNNING"
                      ? "自动化运行中"
                      : "自动化结束"
                    : previewMode === "snapshot"
                      ? "执行截图"
                      : "手动预览"}
                </span>
              </div>
              <div className="bt-actions">
                {live?.frame && previewMode !== "live" && (
                  <button
                    title="查看自动化画面"
                    onClick={() => setPreviewMode("live")}
                  >
                    <Play size={13} />
                  </button>
                )}
                {previewMode !== "app" && (
                  <button
                    className="bt-manual-button"
                    onClick={() => {
                      setPreviewMode("app");
                      setPreview((value) => value + 1);
                    }}
                  >
                    手动操作
                  </button>
                )}
                <button
                  title="全屏预览"
                  aria-label="全屏预览"
                  onClick={async () => {
                    try {
                      if (document.fullscreenElement)
                        await document.exitFullscreen();
                      else await previewArea.current?.requestFullscreen();
                    } catch (error) {
                      setError((error as Error).message);
                    }
                  }}
                >
                  <Maximize2 size={14} />
                </button>
                <button
                  title="刷新应用预览"
                  aria-label="刷新应用预览"
                  disabled={!session}
                  onClick={() => {
                    setPreview((value) => value + 1);
                    setPreviewMode("app");
                  }}
                >
                  <RotateCcw size={14} />
                </button>
              </div>
            </header>
            <div className="bt-preview-stage">
              {previewMode === "app" && session ? (
                <iframe
                  key={`${session.id}-${session.revision}-${preview}`}
                  title="报销清单应用"
                  sandbox="allow-scripts"
                  referrerPolicy="no-referrer"
                  srcDoc={`<!doctype html><meta http-equiv="Content-Security-Policy" content="${previewPolicy}">${session.html.replace(/<!doctype[^>]*>/i, "")}`}
                />
              ) : previewMode === "snapshot" ? (
                <img src={snapshot} alt="测试执行截图" />
              ) : previewMode === "live" && live?.frame ? (
                <img src={live.frame} alt="Playwright 浏览器实时画面" />
              ) : (
                <div className="bt-preview-empty">
                  {previewMode === "live"
                    ? live && live.status !== "RUNNING"
                      ? "没有可用画面，请查看测试反馈或切换手动操作"
                      : connected
                        ? "正在等待浏览器画面…"
                        : "正在连接自动化画面…"
                    : "新建练习后预览应用"}
                </div>
              )}
            </div>
            {previewMode === "live" && (
              <div className="bt-live-step" role="status">
                <span>自动化画面只读；点击「手动操作」可操作应用。</span>
                <span>{live?.case}</span>
                <code>{live?.step || "正在启动浏览器"}</code>
                {!connected && <span>重新连接中…</span>}
              </div>
            )}
          </section>
        </section>
      </div>
    </div>
  );
}
