import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Coins,
  FileBox,
  History,
  LoaderCircle,
  MessageSquareText,
  Search,
  Terminal,
  Workflow,
  X,
} from "lucide-react";
import {
  api,
  compact,
  duration,
  money,
  statusLabel,
  type Call,
  type Detail,
  type RecordData,
  type Run,
  type Stage,
} from "../types";
import { JsonView, Modal } from "./Details";

export function RunInspector({
  detail,
  runs,
  total,
  onChoose,
  onSearch,
  search,
  onMore,
  onCompare,
  connected,
  loading,
  onError,
}: {
  detail: Detail | null;
  runs: Run[];
  total: number;
  onChoose: (id: string) => void;
  onSearch: (query: string) => void;
  search: string;
  onMore: () => void;
  onCompare: () => void;
  connected: boolean;
  loading: boolean;
  onError: (message: string) => void;
}) {
  const [tab, setTab] = useState("current");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [call, setCall] = useState<Call | null>(null);
  const [callData, setCallData] = useState<RecordData[] | null>(null);
  const [callError, setCallError] = useState("");
  const [callTab, setCallTab] = useState("input");
  const [clock, setClock] = useState(Date.now());
  const activeStage = detail?.stages.find(
    (stage) => stage.status === "RUNNING",
  );
  useEffect(() => {
    if (activeStage) setExpanded(activeStage.id);
  }, [activeStage?.id, detail?.run.id]);
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setCall(null);
    setExpanded(
      detail?.stages.find((stage) => stage.status === "RUNNING")?.id || null,
    );
    setTab("current");
  }, [detail?.run.id]);
  useEffect(() => {
    if (!call || !detail) return;
    setCallData(null);
    setCallError("");
    let cancelled = false;
    api(`/runs/${detail.run.id}/calls/${call.id}`)
      .then((data) => {
        if (!cancelled) setCallData(data);
      })
      .catch((error) => {
        if (!cancelled) setCallError(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, [call?.id, detail?.run.id]);
  const seconds =
    detail?.run.status === "RUNNING" && detail.run.started_at
      ? (clock - Date.parse(detail.run.started_at)) / 1000
      : detail?.seconds;
  const input = callData?.find((record) => record.event === "request");
  const output = callData?.find((record) => record.event === "response");
  const failure = callData?.find((record) => record.event === "error");
  const summaryRecord = callData?.find((record) => record.event === "summary");
  return (
    <aside className="run-inspector">
      <div className="inspector-tabs">
        <button
          className={tab === "current" ? "active" : ""}
          onClick={() => setTab("current")}
        >
          <Activity size={14} />
          运行观察
        </button>
        <button
          className={tab === "history" ? "active" : ""}
          onClick={() => setTab("history")}
        >
          <History size={14} />
          历史<span>{total}</span>
        </button>
        <button
          className="icon-button compare-trigger"
          title="对比运行"
          onClick={onCompare}
        >
          <ChartNoAxesCombined size={16} />
        </button>
      </div>
      {tab === "history" ? (
        <>
          <div className="history-search">
            <Search size={14} />
            <input
              value={search}
              placeholder="搜索项目、模型或输出目录"
              onChange={(event) => onSearch(event.target.value)}
            />
          </div>
          <div className="history-list">
            {runs.map((run) => (
              <button
                className={`history-card ${run.id === detail?.run.id ? "chosen" : ""}`}
                key={run.id}
                onClick={() => onChoose(run.id)}
              >
                <div className="history-card-top">
                  <span className="history-project">
                    <FileBox size={15} />
                    {run.name}
                  </span>
                  <span className={`status-chip status-${run.status}`}>
                    {statusLabel[run.status] || run.status}
                  </span>
                </div>
                <span className="history-path mono">{run.output}</span>
                <div className="history-meta">
                  <span>
                    {run.legacy
                      ? "历史工作目录"
                      : run.started_at
                        ? new Date(run.started_at).toLocaleString("zh-CN", {
                            month: "2-digit",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                  </span>
                  <span>{run.settings.model || "模型待解析"}</span>
                </div>
                {!run.legacy && (
                  <div className="history-bottom">
                    <span>
                      <Clock3 size={11} />
                      {duration(run.seconds)}
                    </span>
                    <span>
                      {run.settings.stage
                        ? run.settings.stage.slice(0, 2) + " 单阶段"
                        : "全流程"}
                      <ArrowRight size={12} />
                    </span>
                  </div>
                )}
              </button>
            ))}
            {!runs.length && (
              <div className="inspector-empty">
                <History size={24} />
                <h3>还没有运行记录</h3>
                <p>已有 outputs 会自动出现在这里。</p>
              </div>
            )}
            {runs.length < total && (
              <button className="load-more" onClick={onMore}>
                加载更多 · {runs.length} / {total}
              </button>
            )}
          </div>
        </>
      ) : (
        <>
          {!detail ? (
            <div className="inspector-empty">
              <Workflow size={30} />
              <h3>等待第一份编译任务</h3>
              <p>
                运行状态、模型调用和产物摘要
                <br />
                将在这里实时更新。
              </p>
              <button
                className="secondary-button"
                onClick={() => setTab("history")}
              >
                浏览历史记录
                <ArrowRight size={13} />
              </button>
            </div>
          ) : (
            <div className="inspector-scroll">
              <div className="run-overview">
                <div className="run-title">
                  <span className="overline">CURRENT WORKSPACE</span>
                  <span className={`connection ${connected ? "online" : ""}`}>
                    <i />
                    {connected ? "已连接" : "重连中"}
                  </span>
                </div>
                <h2>{detail.run.name}</h2>
                <div className="run-id">
                  <span className={`status-chip status-${detail.run.status}`}>
                    {statusLabel[detail.run.status] || detail.run.status}
                  </span>
                  <code>{detail.run.id.slice(0, 22)}</code>
                  {loading && <LoaderCircle size={12} className="spin" />}
                </div>
                <div className="metrics-grid">
                  <div>
                    <span>
                      <Clock3 size={12} />
                      总耗时
                    </span>
                    <b>{duration(seconds)}</b>
                  </div>
                  <div>
                    <span>
                      <MessageSquareText size={12} />
                      Token
                    </span>
                    <b>
                      {compact(
                        detail.metrics.usage_calls || detail.metrics.calls === 0
                          ? detail.metrics.input + detail.metrics.output
                          : null,
                      )}
                    </b>
                  </div>
                  <div>
                    <span>
                      <Coins size={12} />
                      估算 CNY
                    </span>
                    <b
                      className={detail.metrics.cost == null ? "unpriced" : ""}
                    >
                      {money(detail.metrics.cost)}
                    </b>
                  </div>
                </div>
                {detail.metrics.calls > 0 &&
                  detail.metrics.usage_calls < detail.metrics.calls && (
                    <p className="metric-note">
                      Usage 已报告 {detail.metrics.usage_calls}/
                      {detail.metrics.calls} 次，统计可能不完整。
                    </p>
                  )}
                {detail.metrics.cost != null &&
                  detail.metrics.priced_calls < detail.metrics.calls && (
                    <p className="metric-note">
                      部分估算 · 已计价 {detail.metrics.priced_calls}/
                      {detail.metrics.calls} 次调用
                    </p>
                  )}
                <details className="run-settings">
                  <summary>
                    运行设置
                    <span>{detail.run.settings.model || "未知模型"}</span>
                    <ChevronDown size={12} />
                  </summary>
                  <dl>
                    <dt>模型</dt>
                    <dd>{detail.run.settings.model || "未记录"}</dd>
                    <dt>URL</dt>
                    <dd>{detail.run.settings.base_url || "未记录"}</dd>
                    <dt>视觉模型</dt>
                    <dd>{detail.run.settings.visual_model || "未记录"}</dd>
                    <dt>输入</dt>
                    <dd>{detail.run.input || "未记录"}</dd>
                    <dt>输出</dt>
                    <dd>{detail.run.output}</dd>
                  </dl>
                </details>
                {detail.run.data_note && (
                  <div className="data-note">{detail.run.data_note}</div>
                )}
                {detail.run.error && (
                  <div className="error-box">{detail.run.error}</div>
                )}
              </div>
              <div className="pipeline-section">
                <div className="inspector-section-title">
                  <h3>编译流水线</h3>
                  <span>
                    {
                      detail.stages.filter((stage) => stage.status === "GREEN")
                        .length
                    }{" "}
                    / {detail.run.settings.stage ? "1" : detail.stages.length}
                  </span>
                </div>
                <div className="stage-track">
                  {detail.stages.map((stage) => (
                    <button
                      key={stage.id}
                      className={`stage-track-item status-${stage.status} ${detail.run.settings.stage && stage.id !== detail.run.settings.stage ? "not-selected" : ""}`}
                      title={`${stage.label} · ${statusLabel[stage.status] || stage.status}`}
                      onClick={() => {
                        setExpanded(stage.id);
                        setTimeout(
                          () =>
                            document
                              .getElementById("stage-" + stage.id)
                              ?.scrollIntoView({
                                behavior: "smooth",
                                block: "nearest",
                              }),
                          50,
                        );
                      }}
                    >
                      <i />
                      {stage.id.slice(0, 2)}
                    </button>
                  ))}
                </div>
              </div>
              <div className="stage-list">
                {detail.stages.map((stage) => (
                  <StageCard
                    key={stage.id}
                    stage={stage}
                    detail={detail}
                    open={expanded === stage.id}
                    onToggle={() =>
                      setExpanded(expanded === stage.id ? null : stage.id)
                    }
                    onCall={(value) => {
                      setCall(value);
                      setCallTab("input");
                    }}
                    clock={clock}
                  />
                ))}
              </div>
              <LogPanel
                identity={detail.run.id}
                active={detail.run.status === "RUNNING"}
                onError={onError}
              />
            </div>
          )}
        </>
      )}
      <div className="inspector-footer">
        <span>
          <span className="tiny-dot" />
          本地工作区
        </span>
        <button onClick={onCompare}>
          <ChartNoAxesCombined size={12} />
          运行对比
        </button>
      </div>
      <Modal
        open={!!call}
        onClose={() => setCall(null)}
        title="模型调用详情"
        eyebrow={call?.id}
        wide
      >
        <div className="call-meta">
          <span>{call?.model}</span>
          <span>{duration(call?.seconds)}</span>
          <span>
            输入 {compact(call?.input)} / 输出 {compact(call?.output)}
          </span>
        </div>
        <div className="detail-tabs">
          {[
            ["input", "模型输入"],
            ["output", "模型输出"],
            ["envelope", "完整记录"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={callTab === id ? "active" : ""}
              onClick={() => setCallTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="modal-body">
          {callError ? (
            <div className="error-box">{callError}</div>
          ) : !callData ? (
            <div className="loading-state">
              <LoaderCircle className="spin" />
              正在读取完整调用…
            </div>
          ) : summaryRecord ? (
            <>
              <p className="data-note">{summaryRecord.note}</p>
              <JsonView value={summaryRecord.summary} />
            </>
          ) : callTab === "input" ? (
            <>
              {(input?.arguments?.messages || []).map(
                (message: RecordData, index: number) => (
                  <div className="message-block" key={index}>
                    <span className="overline">{message.role}</span>
                    <JsonView value={message.content} />
                  </div>
                ),
              )}
            </>
          ) : callTab === "output" ? (
            <>
              {output ? (
                <>
                  {(output.response?.choices || []).map(
                    (choice: RecordData, index: number) => (
                      <div key={index}>
                        {choice.message?.reasoning_content && (
                          <details>
                            <summary>推理内容</summary>
                            <JsonView
                              value={choice.message.reasoning_content}
                            />
                          </details>
                        )}
                        <JsonView value={choice.message?.content || choice} />
                      </div>
                    ),
                  )}
                </>
              ) : (
                <JsonView value={failure || "调用尚未返回"} />
              )}
            </>
          ) : (
            <JsonView value={callData} />
          )}
        </div>
      </Modal>
    </aside>
  );
}
function StageCard({
  stage,
  detail,
  open,
  onToggle,
  onCall,
  clock,
}: {
  stage: Stage;
  detail: Detail;
  open: boolean;
  onToggle: () => void;
  onCall: (call: Call) => void;
  clock: number;
}) {
  const [limit, setLimit] = useState(35);
  const calls = detail.calls.filter(
    (call) => call.stage === stage.id.slice(0, 2),
  );
  const tasks =
    detail.tasks?.filter((task) => task.stage === stage.id.slice(0, 2)) || [];
  const seconds =
    stage.status === "RUNNING" && stage.started_at
      ? (clock - Date.parse(stage.started_at)) / 1000
      : stage.seconds;
  const summary = stage.id.endsWith("_recorded")
    ? null
    : artifactSummary(stage.id, detail.artifacts);
  return (
    <section
      className={`stage-card ${open ? "expanded" : ""}`}
      id={"stage-" + stage.id}
    >
      <button className="stage-header" onClick={onToggle}>
        <span className={`stage-number status-${stage.status}`}>
          {stage.status === "GREEN" ? (
            <Check size={12} />
          ) : stage.status === "RUNNING" ? (
            <LoaderCircle size={12} className="spin" />
          ) : (
            stage.id.slice(0, 2)
          )}
        </span>
        <div>
          <b title={stage.label}>{stage.label}</b>
          <small>{statusLabel[stage.status] || stage.status}</small>
        </div>
        <span className="stage-duration">{duration(seconds)}</span>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>
      {open && (
        <div className="stage-body">
          <div className="stage-metrics">
            <span>
              输入{" "}
              <b>
                {compact(
                  stage.metrics.usage_calls || stage.metrics.calls === 0
                    ? stage.metrics.input
                    : null,
                )}
              </b>
            </span>
            <span>
              输出{" "}
              <b>
                {compact(
                  stage.metrics.usage_calls || stage.metrics.calls === 0
                    ? stage.metrics.output
                    : null,
                )}
              </b>
            </span>
            <span>
              估算 <b>{money(stage.metrics.cost)}</b>
            </span>
          </div>
          <div className="model-latency">
            模型耗时 {duration(stage.metrics.model_seconds)} · {calls.length}{" "}
            次调用
          </div>
          {stage.error && <div className="error-box">{stage.error}</div>}
          {summary && (
            <div className="artifact-summary">
              <FileBox size={13} />
              <span>{summary}</span>
            </div>
          )}
          {tasks.slice(0, limit).map((task) => (
            <details
              className="task-group"
              key={task.id}
              open={tasks.length <= 2}
            >
              <summary>
                <span>{task.task_id}</span>
                <small>{task.metrics.calls}</small>
              </summary>
              <div className="task-totals">
                <span>
                  {task.seconds == null && task.status !== "RUNNING"
                    ? "模型耗时"
                    : "任务耗时"}{" "}
                  {duration(
                    task.seconds ??
                      (task.status === "RUNNING" && task.started_at
                        ? (clock - Date.parse(task.started_at)) / 1000
                        : task.metrics.model_seconds),
                  )}
                </span>
                <span>
                  输入 {compact(task.metrics.input)} / 输出{" "}
                  {compact(task.metrics.output)}
                </span>
                <span>{money(task.metrics.cost)}</span>
              </div>
              {task.requirement_ids.length > 0 && (
                <p className="fine-print">
                  {task.requirement_ids.length > 1 ? "共享任务 · " : "需求 · "}
                  {task.requirement_ids.join("、")}
                </p>
              )}
              {detail.actions?.some(
                (action) => action.task_span_id === task.id,
              ) && (
                <details className="action-metrics">
                  <summary>动作明细</summary>
                  {detail.actions
                    .filter((action) => action.task_span_id === task.id)
                    .map((action) => (
                      <div key={action.id}>
                        <span>{action.action}</span>
                        <small>
                          {duration(action.seconds)} ·{" "}
                          {money(action.metrics.cost)}
                        </small>
                      </div>
                    ))}
                </details>
              )}
              {calls
                .filter((call) => call.task_span_id === task.id)
                .map((call, index) => (
                  <button
                    className="call-row"
                    key={call.id}
                    onClick={() => onCall(call)}
                  >
                    <span className={`call-dot status-${call.status}`} />
                    <span>
                      调用 {index + 1}
                      <small>{call.model}</small>
                    </span>
                    <span>
                      {duration(call.seconds)}
                      <small>
                        {compact((call.input || 0) + (call.output || 0))} tok
                      </small>
                    </span>
                    <ChevronRight size={12} />
                  </button>
                ))}
            </details>
          ))}
          {tasks.length > limit && (
            <button className="load-more" onClick={() => setLimit(limit + 35)}>
              展开更多任务
            </button>
          )}
          {!calls.length && (
            <p className="fine-print">此阶段暂无模型调用记录。</p>
          )}
        </div>
      )}
    </section>
  );
}
function artifactSummary(stage: string, a: RecordData) {
  const id = stage.slice(0, 2);
  if (id === "01")
    return a.requirements?.id ? "已读取需求文档与参考信息" : null;
  if (id === "02")
    return a.db_schema?.entities
      ? `${Object.keys(a.db_schema.entities).length} 个实体 · ${Object.values(a.db_schema.entities).reduce((sum: number, item: any) => sum + Object.keys(item.fields || {}).length, 0)} 个字段`
      : null;
  if (id === "03")
    return a.db_obligations?.requirements
      ? `${Object.keys(a.db_obligations.requirements).length} 份需求读写义务`
      : null;
  if (id === "05")
    return a.backend_apis?.apis
      ? `${Object.keys(a.backend_apis.apis).length} 个 API 契约`
      : null;
  if (id === "07")
    return a.ui_design?.pages
      ? `${Object.keys(a.ui_design.pages).length} 个页面 · ${Object.keys(a.ui_design.elements || {}).length} 个 UI 元素`
      : null;
  if (id === "09")
    return a.frontend_triggers?.triggers
      ? `${Object.keys(a.frontend_triggers.triggers).length} 个交互 Trigger`
      : null;
  const report =
    id === "06"
      ? a.backend_tdd
      : id === "08"
        ? a.ui_checks
        : id === "10"
          ? a.independent_acceptance
          : null;
  return report?.status
    ? `检查结果：${statusLabel[report.status] || report.status}`
    : null;
}
function LogPanel({
  identity,
  active,
  onError,
}: {
  identity: string;
  active: boolean;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const offset = useRef(0);
  const follow = useRef(true);
  const box = useRef<HTMLPreElement>(null);
  useEffect(() => {
    offset.current = 0;
    setText("");
    setPending(false);
  }, [identity]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const data = await api(
          `/runs/${identity}/log?offset=${offset.current}`,
        );
        if (cancelled) return;
        offset.current = data.offset;
        if (data.text) {
          setText((before) => (before + data.text).slice(-250000));
          if (data.truncated) setTruncated(true);
          if (follow.current)
            setTimeout(() => {
              if (box.current) box.current.scrollTop = box.current.scrollHeight;
            }, 30);
          else setPending(true);
        }
      } catch (error) {
        if (!cancelled) onError((error as Error).message);
      } finally {
        if (!cancelled && active) timer = setTimeout(load, 1800);
      }
    }
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [identity, active, open]);
  return (
    <section className="log-section">
      <button className="log-toggle" onClick={() => setOpen(!open)}>
        <Terminal size={14} />
        原始运行日志
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>
      {open && (
        <>
          <p className="fine-print">
            {truncated ? "展示最近日志 · " : ""}完整记录保存在输出目录中。
          </p>
          <pre
            className="console-log"
            ref={box}
            onScroll={() => {
              if (box.current)
                follow.current =
                  box.current.scrollHeight -
                    box.current.scrollTop -
                    box.current.clientHeight <
                  40;
            }}
          >
            {text || "等待日志…"}
          </pre>
          {pending && (
            <button
              className="new-logs"
              onClick={() => {
                follow.current = true;
                setPending(false);
                if (box.current)
                  box.current.scrollTop = box.current.scrollHeight;
              }}
            >
              <ArrowDown size={12} />
              有新日志，返回底部
            </button>
          )}
        </>
      )}
    </section>
  );
}
