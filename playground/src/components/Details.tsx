import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowRight,
  Braces,
  Check,
  Copy,
  Database,
  FileText,
  KeyRound,
  Link2,
  X,
  Zap,
} from "lucide-react";
import { useState } from "react";
import {
  duration,
  compact,
  money,
  type Detail,
  type Selection,
  type RecordData,
} from "../types";
import { ZONES } from "../graph";

export function JsonView({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false);
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="json-view">
      <button
        className="copy-button"
        title="复制"
        onClick={() => {
          navigator.clipboard.writeText(text || "").then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
      </button>
      <pre>{text}</pre>
    </div>
  );
}
export function Modal({
  open,
  onClose,
  title,
  eyebrow,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  eyebrow?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content
          className={`modal-content ${wide ? "modal-wide" : ""}`}
          aria-describedby={undefined}
        >
          <div className="modal-header">
            <div>
              {eyebrow && <span className="overline">{eyebrow}</span>}
              <Dialog.Title>{title}</Dialog.Title>
            </div>
            <Dialog.Close className="icon-button" aria-label="关闭">
              <X size={18} />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function NodeDetails({
  selection,
  detail,
  onClose,
  onNavigate,
}: {
  selection: Selection | null;
  detail: Detail | null;
  onClose: () => void;
  onNavigate: (selection: Selection) => void;
}) {
  const [tab, setTab] = useState("detail");
  if (!selection) return null;
  const { record, kind, label } = selection;
  const a = detail?.artifacts || {};
  const stats = detail?.requirements?.[record.id];
  const requirementIds: string[] = [];
  if (kind === "entity")
    for (const [rid, fields] of Object.entries(
      a.db_schema?.requirements || {},
    ) as [string, string[]][]) {
      if (fields.some((field) => field.startsWith(label + ".")))
        requirementIds.push(rid);
    }
  if (kind === "api")
    for (const [rid, ids] of Object.entries(
      a.backend_apis?.requirements || {},
    ) as [string, string[]][]) {
      if (ids.includes(selection.id.slice(4))) requirementIds.push(rid);
    }
  if (kind === "element" || kind === "page")
    for (const [rid, ids] of Object.entries(
      a.ui_design?.requirements || {},
    ) as [string, string[]][]) {
      if (ids.includes(record.id)) requirementIds.push(rid);
    }
  const triggers = Object.entries(a.frontend_triggers?.triggers || {}).filter(
    ([, trigger]) => (trigger as RecordData).source === record.id,
  ) as [string, RecordData][];
  return (
    <Modal
      open
      onClose={onClose}
      title={label}
      eyebrow={`${ZONES[selection.zone].en} / ${selection.id}`}
    >
      <div className="detail-tabs">
        <button
          className={tab === "detail" ? "active" : ""}
          onClick={() => setTab("detail")}
        >
          <FileText size={14} />
          详情
        </button>
        <button
          className={tab === "source" ? "active" : ""}
          onClick={() => setTab("source")}
        >
          <Braces size={14} />
          原始产物
        </button>
      </div>
      <div className="modal-body">
        {tab === "source" ? (
          <JsonView value={record} />
        ) : (
          <>
            {record.description && (
              <p className="description">
                {typeof record.description === "string"
                  ? record.description
                  : record.description.text}
              </p>
            )}
            {kind === "requirement" && (
              <>
                {record.description?.image?.length > 0 && (
                  <div className="reference-images">
                    {record.description.image.map((image: RecordData) => (
                      <figure key={image.id || image.reference}>
                        {detail?.run.input ? (
                          <img
                            loading="lazy"
                            src={`/api/runs/${detail.run.id}/reference?path=${encodeURIComponent(image.reference)}`}
                            alt={image.id || "需求参考图片"}
                          />
                        ) : (
                          <p className="fine-print">
                            历史记录未保存输入目录，无法定位参考图片。
                          </p>
                        )}
                        <figcaption>
                          {image.id} · {image.reference}
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                )}
                <div className="detail-info-grid">
                  <div>
                    <span>子需求</span>
                    <strong>{record.children?.length || 0}</strong>
                  </div>
                  <div>
                    <span>业务场景</span>
                    <strong>{record.scenarios?.length || 0}</strong>
                  </div>
                </div>
                {stats && (
                  <section className="requirement-stats">
                    <h3>需求编译统计</h3>
                    <div className="detail-info-grid">
                      <div>
                        <span>任务耗时</span>
                        <strong>{duration(stats.seconds)}</strong>
                      </div>
                      <div>
                        <span>模型耗时</span>
                        <strong>{duration(stats.metrics.model_seconds)}</strong>
                      </div>
                      <div>
                        <span>输入 / 输出 Token</span>
                        <strong>
                          {compact(stats.metrics.input)} /{" "}
                          {compact(stats.metrics.output)}
                        </strong>
                      </div>
                      <div>
                        <span>可归属费用 · CNY</span>
                        <strong>{money(stats.metrics.cost)}</strong>
                      </div>
                    </div>
                    <p className="fine-print">
                      父需求包含子需求的统计。仅计入可明确归属的调用；关联共享调用{" "}
                      {stats.shared_calls}{" "}
                      次，不重复分摊费用。历史记录缺少任务计时时保留为空。
                    </p>
                  </section>
                )}
                {(record.scenarios || []).map((scenario: RecordData) => (
                  <section className="scenario" key={scenario.id}>
                    <h3>{scenario.name || scenario.id}</h3>
                    {(scenario.steps || []).map((step: RecordData) => (
                      <div className="step-card" key={step.id}>
                        <span className="mono muted">{step.id}</span>
                        {["Given", "When", "Then"].map((key) => (
                          <div className="gwt" key={key}>
                            <b>{key}</b>
                            <p>{step[key] || step[key.toLowerCase()] || "—"}</p>
                          </div>
                        ))}
                      </div>
                    ))}
                  </section>
                ))}
                <Effects
                  read={a.db_obligations?.requirements?.[record.id]?.read}
                  write={a.db_obligations?.requirements?.[record.id]?.write}
                />
              </>
            )}
            {kind === "entity" && (
              <>
                <h3 className="section-label">
                  <Database size={14} />
                  实体字段
                </h3>
                <table className="fields-table">
                  <thead>
                    <tr>
                      <th>字段</th>
                      <th>类型</th>
                      <th>约束 / 关系</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(record.fields || {}).map(
                      ([name, field]: [string, any]) => (
                        <tr key={name}>
                          <td>
                            <strong>{name}</strong>
                            <small>{field.description}</small>
                          </td>
                          <td>
                            <code>{field.type}</code>
                          </td>
                          <td>
                            <div className="field-flags">
                              {field.primary_key && (
                                <span>
                                  <KeyRound size={10} />
                                  PK
                                </span>
                              )}
                              {field.unique && <span>UNIQUE</span>}
                              {field.nullable === false && (
                                <span>NOT NULL</span>
                              )}
                            </div>
                            {field.references && (
                              <button
                                className="text-link"
                                onClick={() => {
                                  const entity = field.references.split(".")[0];
                                  onNavigate({
                                    id: "db:" + entity,
                                    kind: "entity",
                                    label: entity,
                                    zone: 1,
                                    record: a.db_schema.entities[entity],
                                  });
                                }}
                              >
                                <Link2 size={11} />
                                {field.references}
                              </button>
                            )}
                            {(field.constraints || []).map(
                              (value: string, index: number) => (
                                <small key={index}>{value}</small>
                              ),
                            )}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </>
            )}
            {kind === "api" && (
              <>
                <div className="api-route">
                  <span>{record.signature?.method}</span>
                  <code>{record.signature?.path}</code>
                </div>
                <details open>
                  <summary>输入契约 · Request</summary>
                  <JsonView value={record.request} />
                </details>
                <details>
                  <summary>输出契约 · Response</summary>
                  <JsonView value={record.response} />
                </details>
                <Conditions title="前置条件 P" values={record.precondition} />
                <Conditions title="后置条件 Q" values={record.postcondition} />
                <Effects read={record.read} write={record.write} />
                <p className="fine-print">
                  R/W 为设计声明；实际行为的保证来自实现检查和验收结果。
                </p>
              </>
            )}
            {(kind === "page" || kind === "element") && (
              <>
                <div className="pill-row">
                  <span className="pill">{record.type}</span>
                  {record.mode?.map((mode: string) => (
                    <span className="pill" key={mode}>
                      {mode === "user_write" ? "用户可写" : "用户可读"}
                    </span>
                  ))}
                </div>
                <h3>静态属性</h3>
                <JsonView value={record.prop} />
                <h3>前端变量声明</h3>
                {record.data?.length ? (
                  <JsonView value={record.data} />
                ) : (
                  <p className="muted">没有动态变量。</p>
                )}
                <h3>
                  <Zap size={14} />
                  关联 Trigger · {triggers.length}
                </h3>
                {triggers.map(([id, trigger]) => (
                  <button
                    className="relation-card"
                    key={id}
                    onClick={() =>
                      onNavigate({
                        id: "trigger:" + id,
                        kind: "trigger",
                        label: trigger.event || id,
                        zone: 3,
                        record: trigger,
                      })
                    }
                  >
                    <Zap size={14} />
                    <span>
                      {trigger.event}
                      <small>{id}</small>
                    </span>
                    <ArrowRight size={14} />
                  </button>
                ))}
              </>
            )}
            {kind === "trigger" && (
              <>
                <div className="pill-row">
                  <span className="pill">{record.event}</span>
                  <span className="pill">{record.source}</span>
                </div>
                {record.guard && (
                  <p className="description">执行条件：{record.guard}</p>
                )}
                <Effects read={record.read} write={record.write} />
                <h3>有序动作</h3>
                {(record.action || []).map(
                  (action: RecordData, index: number) => (
                    <div className="action-card" key={index}>
                      <span className="action-number">{index + 1}</span>
                      <div>
                        <b>{action.kind === "api" ? "调用 API" : "界面动作"}</b>
                        <p>{action.description}</p>
                        {action.api && (
                          <button
                            className="text-link"
                            onClick={() =>
                              onNavigate({
                                id: "api:" + action.api,
                                kind: "api",
                                label:
                                  a.backend_apis?.apis?.[action.api]?.signature
                                    ?.name || action.api,
                                record:
                                  a.backend_apis?.apis?.[action.api] || {},
                                zone: 2,
                              })
                            }
                          >
                            {action.api}
                            <ArrowRight size={12} />
                          </button>
                        )}
                      </div>
                    </div>
                  ),
                )}
              </>
            )}
            {requirementIds.length > 0 && (
              <>
                <h3>关联需求</h3>
                <div className="pill-row">
                  {requirementIds.map((id) => (
                    <span className="pill mono" key={id}>
                      {id}
                    </span>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
function Effects({ read, write }: { read?: string[]; write?: string[] }) {
  if (!read && !write) return null;
  return (
    <div className="effects">
      {[
        ["READ", read],
        ["WRITE", write],
      ].map(([title, values]) => (
        <div key={title as string}>
          <span className={`effect-label ${title === "WRITE" ? "write" : ""}`}>
            {title as string}
          </span>
          <div className="pill-row">
            {((values as string[]) || []).map((value) => (
              <code className="effect-field" key={value}>
                {value}
              </code>
            ))}
            {!((values as string[]) || []).length && (
              <span className="muted">无</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
function Conditions({
  title,
  values,
}: {
  title: string;
  values?: RecordData[];
}) {
  return (
    <section className="conditions">
      <h3>{title}</h3>
      {values?.length ? (
        values.map((value, index) => (
          <p key={index}>
            <span className="condition-dot" />
            {value.description}
          </p>
        ))
      ) : (
        <p className="muted">无</p>
      )}
    </section>
  );
}
