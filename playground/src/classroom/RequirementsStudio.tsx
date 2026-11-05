import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileUp,
  Plus,
  Send,
  Square,
  Undo2,
  X,
} from "lucide-react";
import { course } from "./api";
import "./requirements-studio.css";

type Step = {
  id: string;
  Given: string;
  When: string;
  Then: string;
  references: string[];
};
type Scenario = { id: string; name: string; steps: Step[] };
type Requirement = {
  id: string;
  name: string;
  description: {
    text: string;
    image: { id: string; reference: string; page: string }[];
  };
  scenarios: Scenario[];
  children: Requirement[];
};
type Tool = {
  id: string;
  name: string;
  status: string;
  arguments: Record<string, unknown>;
  result: string;
};
type Turn = {
  id: string;
  user: string;
  answer: string;
  reasoning: string;
  status: string;
  error: string;
  model: string;
  tools: Tool[];
};
type Workspace = {
  id: string;
  name: string;
  tree: Requirement;
  revision: number;
  status: string;
  phase: string;
  error: string;
  turns: Turn[];
  can_undo: boolean;
  summary: string;
  context_chars: number;
  context_limit: number;
  compactions: {
    id: string;
    status: string;
    created_at: string;
    before_chars: number;
    after_chars?: number;
  }[];
  changes: {
    revision: number;
    action: string;
    node_id: string;
    source: string;
  }[];
  quality: {
    nodes: number;
    scenarios: number;
    steps: number;
    issues: { node_id: string; message: string }[];
  };
  markdown: string;
  yaml: string;
  input_path: string;
};
type History = { id: string; name: string; created_at: string };
type Props = {
  modelId: string;
  thinking: boolean;
  effort: string;
  controls: HTMLElement | null;
  saveConnection: () => Promise<void>;
};
type TreeData = {
  requirement: Requirement;
  collapsed: boolean;
  active: boolean;
  working: boolean;
  onAdd: (id: string) => void;
  onToggle: (id: string) => void;
};
type TreeNode = Node<TreeData>;
const toolNames: Record<string, string> = {
  read_document: "读取需求树",
  read_node: "读取节点",
  replace_document: "生成完整需求",
  add_node: "添加节点",
  update_node: "更新节点",
  move_node: "移动节点",
  delete_node: "删除节点",
};

function flatten(
  tree: Requirement,
  parent: string | null = null,
): { node: Requirement; parent: string | null }[] {
  const result = [{ node: tree, parent }];
  for (const child of tree.children) result.push(...flatten(child, tree.id));
  return result;
}

function RequirementCard({ data }: NodeProps<TreeNode>) {
  const node = data.requirement;
  return (
    <div className={`rs-tree-node ${data.active ? "active" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="rs-node-label">
        <span>{node.id}</span>
        <button
          className="nodrag nopan"
          title="添加子节点"
          disabled={data.working}
          onClick={(event) => {
            event.stopPropagation();
            data.onAdd(node.id);
          }}
        >
          <Plus size={13} />
        </button>
      </div>
      <strong title={node.name}>{node.name}</strong>
      <footer>
        <span>{node.scenarios.length} 个场景</span>
        {node.children.length > 0 && (
          <button
            className="nodrag nopan"
            onClick={(event) => {
              event.stopPropagation();
              data.onToggle(node.id);
            }}
          >
            {data.collapsed ? (
              <ChevronRight size={12} />
            ) : (
              <ChevronDown size={12} />
            )}
            {node.children.length} 个子项
          </button>
        )}
      </footer>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { requirement: RequirementCard };

function NodeEditor({
  node,
  revision,
  nodes,
  working,
  onSave,
  onMove,
  onDelete,
  onClose,
}: {
  node: Requirement;
  revision: number;
  nodes: { node: Requirement; parent: string | null }[];
  working: boolean;
  onSave: (id: string, patch: object, revision: number) => Promise<boolean>;
  onMove: (id: string, parent: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(() => structuredClone(node));
  const [baseRevision, setBaseRevision] = useState(revision);
  const [dirty, setDirty] = useState(false);
  const [parent, setParent] = useState(
    nodes.find((item) => item.node.id === node.id)?.parent || "",
  );
  const currentParent =
    nodes.find((item) => item.node.id === node.id)?.parent || "";
  useEffect(() => setParent(currentParent), [currentParent]);
  useEffect(() => {
    if (!dirty) {
      setDraft(structuredClone(node));
      setBaseRevision(revision);
    }
  }, [node, revision, dirty]);
  const descendants = new Set(flatten(node).map((item) => item.node.id));
  function change(next: Requirement) {
    setDirty(true);
    setDraft(next);
  }
  function scenarioName(index: number, value: string) {
    const next = structuredClone(draft);
    next.scenarios[index].name = value;
    change(next);
  }
  function stepField(
    scenario: number,
    step: number,
    key: "Given" | "When" | "Then",
    value: string,
  ) {
    const next = structuredClone(draft);
    next.scenarios[scenario].steps[step][key] = value;
    change(next);
  }
  function newStep(): Step {
    return {
      id: "STEP-" + crypto.randomUUID().slice(0, 8),
      Given: "",
      When: "",
      Then: "",
      references: [],
    };
  }
  return (
    <section className="rs-node-editor">
      <header>
        <strong>编辑节点 · {node.id}</strong>
        <button title="关闭编辑" onClick={onClose}>
          <X size={15} />
        </button>
      </header>
      {dirty && baseRevision !== revision && (
        <p className="rs-error">
          文档已变化，草稿仍保留。请复制草稿后重新载入再保存。
        </p>
      )}
      <fieldset disabled={working}>
        <label>
          名称
          <input
            value={draft.name}
            onChange={(event) => change({ ...draft, name: event.target.value })}
          />
        </label>
        <label>
          描述
          <textarea
            value={draft.description.text}
            onChange={(event) =>
              change({
                ...draft,
                description: { ...draft.description, text: event.target.value },
              })
            }
            placeholder="用户、输入、业务规则、结果、边界与不做什么"
          />
        </label>
        {draft.description.image.length > 0 && (
          <p className="rs-hint">
            已有 {draft.description.image.length}{" "}
            张参考图关联，编辑文字会保留关联。
          </p>
        )}
        <div className="rs-editor-heading">
          <strong>验收场景</strong>
          <button
            className="cr-text-button"
            onClick={() =>
              change({
                ...draft,
                scenarios: [
                  ...draft.scenarios,
                  {
                    id: "SCN-" + crypto.randomUUID().slice(0, 8),
                    name: "新场景",
                    steps: [newStep()],
                  },
                ],
              })
            }
          >
            <Plus size={12} />
            场景
          </button>
        </div>
        {draft.scenarios.map((scenario, index) => (
          <div className="rs-scenario" key={scenario.id}>
            <div className="rs-editor-heading">
              <input
                aria-label="场景名称"
                value={scenario.name}
                onChange={(event) => scenarioName(index, event.target.value)}
              />
              <button
                title="删除场景"
                onClick={() =>
                  change({
                    ...draft,
                    scenarios: draft.scenarios.filter((_, i) => i !== index),
                  })
                }
              >
                <X size={12} />
              </button>
            </div>
            {scenario.steps.map((step, stepIndex) => (
              <div key={step.id} className="rs-step-fields">
                {(
                  [
                    ["Given", "前置条件"],
                    ["When", "用户操作"],
                    ["Then", "预期结果"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    {label} · {key}
                    <textarea
                      value={step[key]}
                      onChange={(event) =>
                        stepField(index, stepIndex, key, event.target.value)
                      }
                    />
                  </label>
                ))}
                {scenario.steps.length > 1 && (
                  <button
                    className="cr-text-button"
                    onClick={() => {
                      const next = structuredClone(draft);
                      next.scenarios[index].steps.splice(stepIndex, 1);
                      change(next);
                    }}
                  >
                    删除此步
                  </button>
                )}
              </div>
            ))}
            <button
              className="cr-text-button"
              onClick={() => {
                const next = structuredClone(draft);
                next.scenarios[index].steps.push(newStep());
                change(next);
              }}
            >
              ＋ 添加步骤
            </button>
          </div>
        ))}
        <div className="rs-actions">
          <button
            className="cr-button primary"
            disabled={!dirty}
            onClick={async () => {
              if (
                await onSave(
                  node.id,
                  {
                    name: draft.name,
                    description: draft.description,
                    scenarios: draft.scenarios,
                  },
                  baseRevision,
                )
              )
                setDirty(false);
            }}
          >
            保存节点
          </button>
          <button
            className="cr-button secondary"
            onClick={() => {
              setDraft(structuredClone(node));
              setDirty(false);
              setBaseRevision(revision);
            }}
          >
            重新载入
          </button>
        </div>
        {nodes.find((item) => item.node.id === node.id)?.parent && (
          <div className="rs-node-structure">
            <label>
              移动到父节点
              <select
                value={parent}
                onChange={(event) => setParent(event.target.value)}
              >
                {nodes
                  .filter((item) => !descendants.has(item.node.id))
                  .map((item) => (
                    <option key={item.node.id} value={item.node.id}>
                      {item.node.id} · {item.node.name}
                    </option>
                  ))}
              </select>
            </label>
            <div className="rs-actions">
              <button
                className="cr-button secondary"
                disabled={dirty}
                onClick={() => onMove(node.id, parent)}
              >
                移动节点
              </button>
              <button
                className="cr-text-button rs-danger"
                onClick={() => {
                  if (
                    window.confirm(
                      `删除“${node.name}”及其子节点？可通过撤销恢复。`,
                    )
                  )
                    onDelete(node.id);
                }}
              >
                删除子树
              </button>
            </div>
          </div>
        )}
      </fieldset>
    </section>
  );
}

export default function RequirementsStudio(props: Props) {
  const [identity, setIdentity] = useState(
    () => sessionStorage.getItem("requirements-workspace") || "",
  );
  const [session, setSession] = useState<Workspace | null>(null);
  const [history, setHistory] = useState<History[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("tree");
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [showChecks, setShowChecks] = useState(false);
  const [focus, setFocus] = useState("");
  const [autoFrame, setAutoFrame] = useState(true);
  const [follow, setFollow] = useState(true);
  const [notice, setNotice] = useState("");
  const chatArea = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const flow = useRef<ReactFlowInstance<TreeNode, Edge> | null>(null);
  const working = busy || (!!session && session.status !== "IDLE");
  const nodes = useMemo(
    () => (session ? flatten(session.tree) : []),
    [session?.tree],
  );
  const selectedNode = nodes.find((item) => item.node.id === selected)?.node;

  useEffect(() => {
    let disposed = false;
    course<{ items: History[] }>("/requirements/sessions")
      .then((value) => {
        if (!disposed) setHistory(value.items);
      })
      .catch((error) => {
        if (!disposed) setError(error.message);
      });
    return () => {
      disposed = true;
    };
  }, [identity]);
  useEffect(() => {
    if (!session) return;
    setHistory((current) =>
      current.map((item) =>
        item.id === session.id ? { ...item, name: session.name } : item,
      ),
    );
  }, [session?.id, session?.name]);
  useEffect(() => {
    if (!identity) return;
    sessionStorage.setItem("requirements-workspace", identity);
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await course<Workspace>(
          `/requirements/sessions/${identity}`,
        );
        if (!disposed)
          setSession((current) =>
            current?.id === value.id && current.revision > value.revision
              ? current
              : value,
          );
      } catch (error) {
        if (!disposed) setError((error as Error).message);
      }
      if (!disposed) timer = setTimeout(poll, 900);
    }
    poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [identity]);
  useEffect(() => {
    setSelected("");
    setEditing(false);
    setCollapsed(new Set());
    setError("");
    setNotice("");
    setFollow(true);
    setAutoFrame(true);
  }, [identity]);
  useEffect(() => {
    if (!session || nodes.some((item) => item.node.id === selected)) return;
    setSelected(session.tree.id);
    if (nodes.length > 20)
      setCollapsed(
        new Set(
          session.tree.children
            .filter((node) => node.children.length)
            .map((node) => node.id),
        ),
      );
  }, [session?.id, nodes.length, selected]);
  const progress = session?.turns
    .map(
      (turn) =>
        `${turn.id}:${turn.answer.length}:${turn.reasoning.length}:${turn.tools.length}:${turn.status}`,
    )
    .join("|");
  useEffect(() => {
    if (follow && chatArea.current)
      chatArea.current.scrollTop = chatArea.current.scrollHeight;
  }, [progress, follow]);

  async function create(template: string) {
    if (working) return;
    setBusy(true);
    setError("");
    try {
      const value = await course<Workspace>("/requirements/sessions", {
        template,
      });
      setSession(value);
      setIdentity(value.id);
      setTab("tree");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function mutate(
    operation: string,
    arguments_: object,
    revision = session?.revision,
  ): Promise<Workspace | null> {
    if (!session || working) return null;
    setBusy(true);
    setError("");
    try {
      const value = await course<Workspace>(
        `/requirements/sessions/${identity}/mutations`,
        { operation, arguments: arguments_, revision },
      );
      setSession(value);
      return value;
    } catch (error) {
      setError((error as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  async function add(parent: string) {
    const value = await mutate("add_node", {
      parent_id: parent,
      node: {
        name: "新需求",
        description: { text: "" },
        scenarios: [],
        children: [],
      },
    });
    if (value) {
      setCollapsed((current) => {
        const next = new Set(current);
        next.delete(parent);
        return next;
      });
      const id = value.changes.at(-1)?.node_id || parent;
      setSelected(id);
      setEditing(true);
      setFocus(id);
    }
  }
  async function send(compact = false) {
    if (!session || working || (!compact && !draft.trim())) return;
    setBusy(true);
    setError("");
    setFollow(true);
    try {
      await props.saveConnection();
      setSession(
        await course<Workspace>(`/requirements/sessions/${identity}/chat`, {
          model_id: props.modelId,
          thinking: props.thinking,
          effort: props.effort,
          message: draft,
          compact,
          node_id: selected,
        }),
      );
      if (!compact) setDraft("");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice("已复制");
    } catch {
      setError("复制失败，请选中文字复制。");
    }
  }
  function selectNode(id: string, focusNode = false) {
    const ancestors = new Set<string>();
    let parent = nodes.find((item) => item.node.id === id)?.parent;
    while (parent) {
      ancestors.add(parent);
      parent = nodes.find((item) => item.node.id === parent)?.parent;
    }
    setCollapsed(
      (current) => new Set([...current].filter((item) => !ancestors.has(item))),
    );
    setSelected(id);
    setEditing(true);
    setShowChecks(false);
    setTab("tree");
    if (focusNode) setFocus(id);
  }
  const graph = useMemo(() => {
    const graphNodes: TreeNode[] = [];
    const edges: Edge[] = [];
    if (!session) return { nodes: graphNodes, edges };
    function height(node: Requirement): number {
      if (collapsed.has(node.id) || !node.children.length) return 1;
      return node.children.reduce((sum, child) => sum + height(child), 0);
    }
    function visit(node: Requirement, depth: number, top: number) {
      const size = height(node);
      graphNodes.push({
        id: node.id,
        type: "requirement",
        position: { x: depth * 265, y: (top + size / 2) * 112 },
        data: {
          requirement: node,
          collapsed: collapsed.has(node.id),
          active: selected === node.id,
          working,
          onAdd: add,
          onToggle: (id) =>
            setCollapsed((current) => {
              const next = new Set(current);
              if (next.has(id)) next.delete(id);
              else next.add(id);
              return next;
            }),
        },
      });
      if (collapsed.has(node.id)) return;
      let offset = top;
      for (const child of node.children) {
        visit(child, depth + 1, offset);
        offset += height(child);
        edges.push({
          id: `${node.id}-${child.id}`,
          source: node.id,
          target: child.id,
          type: "smoothstep",
          style: { stroke: "#afbdd5", strokeWidth: 1.4 },
        });
      }
    }
    visit(session.tree, 0, 0);
    return { nodes: graphNodes, edges };
  }, [session?.tree, collapsed, selected, working]);
  useEffect(() => {
    if (!focus || !graph.nodes.some((node) => node.id === focus)) return;
    const timer = setTimeout(() => {
      flow.current?.fitView({
        nodes: [{ id: focus }],
        duration: 250,
        maxZoom: 1,
      });
      setFocus("");
    }, 80);
    return () => clearTimeout(timer);
  }, [focus, graph.nodes]);
  useEffect(() => {
    if (!autoFrame || editing || tab !== "tree") return;
    const timer = setTimeout(
      () => flow.current?.fitView({ duration: 250, maxZoom: 1, padding: 0.2 }),
      100,
    );
    return () => clearTimeout(timer);
  }, [graph.nodes.length, autoFrame, editing, tab]);

  const hints = [
    [
      "先生成大纲",
      "我想做一个【你的业务应用】，使用者是【谁】，目标是【解决什么问题】。请先问我必要的问题，再生成模块大纲；这一轮先不要展开所有细节，不确定的内容标记待确认。",
    ],
    [
      "完善选中节点",
      `请完善 ${selected || "选中节点"}：先核对用户、输入、业务规则、输出、边界和不做什么，再补充正常、异常与适用的边界验收场景。缺少信息先提问。保留其他节点与已有 ID。`,
    ],
    [
      "检查遗漏矛盾",
      "请审阅当前需求树：检查范围遗漏、重复职责、规则矛盾、含糊表达、无法验收的描述及待确认事项。先列问题和建议，不要直接修改。",
    ],
  ];

  return (
    <div className="rs-workspace">
      {props.controls &&
        createPortal(
          <>
            <header className="rs-heading">
              <div>
                <strong>需求沉淀</strong>
                <span>{session?.name || "从想法到可验收的需求"}</span>
              </div>
              <select
                aria-label="需求项目"
                value={identity}
                disabled={working}
                onChange={(event) => {
                  setSession(null);
                  setIdentity(event.target.value);
                }}
              >
                <option value="" disabled>
                  项目历史
                </option>
                {history.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.id.slice(0, 6)}
                  </option>
                ))}
                {identity && !history.some((item) => item.id === identity) && (
                  <option value={identity}>当前项目</option>
                )}
              </select>
            </header>
            <div className="cr-sidebar-action rs-project-buttons">
              <button
                className="cr-button primary"
                disabled={working}
                onClick={() => create("blank")}
              >
                <Plus size={15} />
                新建需求项目
              </button>
              <button
                className="cr-button secondary"
                disabled={working}
                onClick={() => create("input")}
              >
                从 input 新建
              </button>
            </div>
          </>,
          props.controls,
        )}

      <div className="rs-layout">
        <section className="rs-chat">
          <div
            className="rs-chat-messages"
            ref={chatArea}
            onScroll={(event) => {
              const element = event.currentTarget;
              setFollow(
                element.scrollHeight -
                  element.scrollTop -
                  element.clientHeight <
                  80,
              );
            }}
          >
            {!session?.turns.length && (
              <div className="rs-welcome">
                <h3>先说清楚，你想解决什么问题</h3>
                <p>
                  可以先让模型生成大纲，再逐个完善模块。选中树中的节点，可以直接讨论“这个节点”。
                </p>
                <p>
                  每个叶子需求写清规则，并用前置条件、操作和预期结果描述如何验收。
                </p>
                {!session && (
                  <div className="rs-actions">
                    <button
                      className="cr-button primary"
                      disabled={working}
                      onClick={() => create("blank")}
                    >
                      空白项目
                    </button>
                    <button
                      className="cr-button secondary"
                      disabled={working}
                      onClick={() => create("input")}
                    >
                      从当前 input 开始
                    </button>
                  </div>
                )}
              </div>
            )}
            {session?.turns.map((turn) => (
              <div className="rs-turn" key={turn.id}>
                <article className="rs-user">
                  <small>你</small>
                  <p>{turn.user}</p>
                </article>
                <article className="rs-assistant">
                  <div className="rs-turn-label">
                    {turn.model}
                    <span>
                      {turn.status === "RUNNING"
                        ? "正在处理…"
                        : turn.status === "COMPLETED"
                          ? ""
                          : "未完成"}
                    </span>
                  </div>
                  {turn.reasoning && (
                    <details className="rs-reasoning">
                      <summary>思考过程</summary>
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {turn.reasoning}
                      </ReactMarkdown>
                    </details>
                  )}
                  {turn.tools.length > 0 && (
                    <details
                      className="rs-tools"
                      open={turn.status === "RUNNING"}
                    >
                      <summary>需求工具 · {turn.tools.length} 次操作</summary>
                      {turn.tools.map((tool) => (
                        <div key={tool.id}>
                          <span
                            className={
                              tool.status === "FAILED" ? "rs-danger" : ""
                            }
                          >
                            {tool.status === "COMPLETED"
                              ? "✓"
                              : tool.status === "FAILED"
                                ? "×"
                                : "·"}{" "}
                            {toolNames[tool.name] || tool.name}
                          </span>
                          <small>
                            {String(
                              tool.arguments.node_id ||
                                tool.arguments.parent_id ||
                                "",
                            )}
                          </small>
                          <p>{tool.result}</p>
                        </div>
                      ))}
                    </details>
                  )}
                  <div className="rs-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {turn.answer ||
                        (turn.status === "RUNNING" ? session.phase : "")}
                    </ReactMarkdown>
                  </div>
                  {turn.error && <p className="rs-error">{turn.error}</p>}
                </article>
              </div>
            ))}
          </div>
          {(error || session?.error) && (
            <div className="rs-error" role="alert">
              {error || session?.error}
            </div>
          )}
          <div className="rs-prompts">
            {hints.map(([label, text]) => (
              <button
                key={label}
                disabled={!session || working}
                onClick={() => setDraft(text)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="rs-composer">
            <textarea
              aria-label="需求对话"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="告诉模型你的目标，或让它完善选中节点…"
              disabled={!session}
              onKeyDown={(event) => {
                if (
                  (event.ctrlKey || event.metaKey) &&
                  event.key === "Enter" &&
                  !event.nativeEvent.isComposing &&
                  !working &&
                  draft.trim()
                ) {
                  event.preventDefault();
                  send();
                }
              }}
            />
            <div className="rs-actions">
              <span>
                {session?.phase ||
                  (session
                    ? `选中 ${selected} · 会话自动保存`
                    : "请先新建或选择项目")}
              </span>
              {working ? (
                <button
                  className="cr-button secondary"
                  onClick={async () => {
                    try {
                      setSession(
                        await course<Workspace>(
                          `/requirements/sessions/${identity}/cancel`,
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
              ) : (
                <button
                  className="cr-button primary"
                  disabled={!session || !draft.trim()}
                  onClick={() => send()}
                >
                  <Send size={13} />
                  发送
                </button>
              )}
            </div>
          </div>
          {session && (
            <details className="rs-context">
              <summary>
                会话上下文 · 约 {session.context_chars.toLocaleString()} 字符
                {session.compactions.some((item) => item.status === "COMPLETED")
                  ? " · 已压缩"
                  : ""}
              </summary>
              <p>
                约超过 {session.context_limit.toLocaleString()}{" "}
                字符时，在下一次发送前自动压缩旧上下文；原对话与当前需求树保留。
              </p>
              {session.summary && <pre>{session.summary}</pre>}
              <button
                className="cr-text-button"
                disabled={working || !session.turns.length}
                onClick={() => send(true)}
              >
                现在压缩历史
              </button>
            </details>
          )}
        </section>
        <section className="rs-document">
          <nav className="rs-document-toolbar">
            <div>
              {[
                ["tree", "需求树"],
                ["markdown", "文档预览"],
                ["yaml", "YAML"],
              ].map(([id, title]) => (
                <button
                  className={tab === id ? "active" : ""}
                  key={id}
                  onClick={() => setTab(id)}
                >
                  {title}
                </button>
              ))}
            </div>
            <div>
              <button
                disabled={!session || working || !session.can_undo}
                title="撤销上一次文档修改"
                onClick={() => mutate("undo", {})}
              >
                <Undo2 size={13} />
              </button>
              <button
                disabled={!session || working}
                title="导入 YAML / JSON"
                onClick={() => fileInput.current?.click()}
              >
                <FileUp size={14} />
              </button>
              {session && (
                <a
                  title="导出编译输入包"
                  href={`/api/course/requirements/sessions/${identity}/export/zip`}
                >
                  <Download size={14} />
                </a>
              )}
            </div>
          </nav>
          <input
            ref={fileInput}
            type="file"
            accept=".yaml,.yml,.json"
            hidden
            onChange={async (event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file || !session || working) return;
              setBusy(true);
              setError("");
              try {
                if (file.size > 1000000) throw new Error("文档不能超过 1MB");
                const value = await course<Workspace>(
                  `/requirements/sessions/${identity}/import`,
                  { revision: session.revision, text: await file.text() },
                );
                setSession(value);
                setSelected(value.tree.id);
                setCollapsed(new Set());
                setNotice("已导入，可撤销");
              } catch (error) {
                setError((error as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          />
          {session && (
            <div className="rs-document-summary">
              <span>
                {session.quality.nodes} 个节点 · {session.quality.scenarios}{" "}
                个场景 · 修订 {session.revision}
              </span>
              <button
                className={session.quality.issues.length ? "rs-warning" : ""}
                onClick={() => setShowChecks((value) => !value)}
              >
                {session.quality.issues.length
                  ? `${session.quality.issues.length} 项待完善`
                  : "结构检查通过"}
              </button>
            </div>
          )}
          {showChecks && session && (
            <section className="rs-checks">
              <header>
                <strong>待完善项</strong>
                <button onClick={() => setShowChecks(false)}>
                  <X size={13} />
                </button>
              </header>
              {!session.quality.issues.length && (
                <p>当前结构检查通过；业务正确性与完整性仍需人工核对。</p>
              )}
              {session.quality.issues.map((issue, index) => (
                <button
                  key={index}
                  onClick={() => selectNode(issue.node_id, true)}
                >
                  <strong>{issue.node_id}</strong>
                  {issue.message}
                </button>
              ))}
            </section>
          )}
          <div className="rs-document-content">
            {!session ? (
              <div className="rs-document-empty">
                新建项目后，在这里查看与编辑需求树。
              </div>
            ) : tab === "tree" ? (
              <>
                <div className="rs-tree-toolbar">
                  <input
                    aria-label="查找需求节点"
                    placeholder="按名称或 ID 查找…"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                  <button
                    onClick={() => {
                      setAutoFrame(true);
                      flow.current?.fitView({ duration: 250, maxZoom: 1 });
                    }}
                  >
                    居中
                  </button>
                  <button onClick={() => setCollapsed(new Set())}>展开</button>
                  <button
                    onClick={() =>
                      setCollapsed(
                        new Set(
                          session.tree.children
                            .filter((node) => node.children.length)
                            .map((node) => node.id),
                        ),
                      )
                    }
                  >
                    大纲
                  </button>
                  <button
                    disabled={working}
                    onClick={() => add(selected || session.tree.id)}
                  >
                    <Plus size={12} />
                    节点
                  </button>
                </div>
                {query && (
                  <div className="rs-search-results">
                    {nodes
                      .filter((item) =>
                        `${item.node.id} ${item.node.name}`
                          .toLowerCase()
                          .includes(query.toLowerCase()),
                      )
                      .slice(0, 15)
                      .map((item) => (
                        <button
                          key={item.node.id}
                          onClick={() => {
                            selectNode(item.node.id, true);
                            setQuery("");
                          }}
                        >
                          {item.node.id} · {item.node.name}
                        </button>
                      ))}
                  </div>
                )}
                <div className="rs-canvas">
                  <ReactFlow<TreeNode, Edge>
                    nodes={graph.nodes}
                    edges={graph.edges}
                    nodeTypes={nodeTypes}
                    nodesDraggable={false}
                    nodesConnectable={false}
                    fitView
                    fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
                    minZoom={0.08}
                    maxZoom={1.6}
                    onInit={(instance) => {
                      flow.current = instance;
                    }}
                    onMoveStart={(event) => {
                      if (event) setAutoFrame(false);
                    }}
                    onNodeClick={(_, node) => {
                      setSelected(node.id);
                      setEditing(true);
                    }}
                    proOptions={{ hideAttribution: true }}
                  >
                    <Background gap={20} size={1} color="#dfe6f1" />
                    <Controls showInteractive={false} />
                  </ReactFlow>
                </div>
                {editing && selectedNode && (
                  <NodeEditor
                    key={`${identity}-${selectedNode.id}`}
                    node={selectedNode}
                    revision={session.revision}
                    nodes={nodes}
                    working={working}
                    onClose={() => setEditing(false)}
                    onSave={async (id, patch, revision) =>
                      !!(await mutate(
                        "update_node",
                        { node_id: id, patch },
                        revision,
                      ))
                    }
                    onMove={async (id, parent) => {
                      const value = await mutate("move_node", {
                        node_id: id,
                        parent_id: parent,
                      });
                      if (value) {
                        setCollapsed((current) => {
                          const next = new Set(current);
                          next.delete(parent);
                          return next;
                        });
                        setFocus(id);
                      }
                    }}
                    onDelete={async (id) => {
                      const value = await mutate("delete_node", {
                        node_id: id,
                      });
                      if (value) {
                        setSelected(
                          value.changes.at(-1)?.node_id || value.tree.id,
                        );
                        setEditing(false);
                      }
                    }}
                  />
                )}
              </>
            ) : tab === "markdown" ? (
              <div className="rs-preview rs-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {session.markdown}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="rs-yaml">
                <div className="rs-actions">
                  <button onClick={() => copy(session.yaml)}>
                    <Copy size={12} />
                    复制 YAML
                  </button>
                  <a
                    href={`/api/course/requirements/sessions/${identity}/export/yaml`}
                  >
                    下载 requirements.yaml
                  </a>
                  <a
                    href={`/api/course/requirements/sessions/${identity}/export/markdown`}
                  >
                    下载 Markdown
                  </a>
                </div>
                <pre>{session.yaml}</pre>
              </div>
            )}
          </div>
          {session && (
            <footer className="rs-handoff">
              <div>
                <span>编译输入目录</span>
                <code title={session.input_path}>{session.input_path}</code>
              </div>
              <button
                title="复制路径后在需求工厂输入目录中粘贴"
                onClick={() => copy(session.input_path)}
              >
                <Copy size={12} />
                路径
              </button>
              <a href="/" target="_blank" rel="noreferrer">
                需求工厂 ↗
              </a>
            </footer>
          )}
          {notice && (
            <button className="rs-notice" onClick={() => setNotice("")}>
              <Check size={12} />
              {notice}
            </button>
          )}
        </section>
      </div>
    </div>
  );
}
