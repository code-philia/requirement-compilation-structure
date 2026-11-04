import { AlertTriangle, Crosshair, MessageSquareText } from "lucide-react";
import { duration, type Call, type Detail, type Failure } from "../types";

const phases: Record<string, string> = {
  GENERATION: "测试生成",
  IMPLEMENTING: "代码实现",
  ACCEPTANCE: "验收检查",
  TESTING: "测试执行",
};

export function FailureList({
  failures,
  detail,
  onLocate,
  onCall,
}: {
  failures: Failure[];
  detail: Detail;
  onLocate?: (id: string) => void;
  onCall?: (call: Call) => void;
}) {
  if (!failures.length) return null;
  return (
    <div className="failure-list">
      {failures.map((failure) => (
        <details className="failure-entry" key={failure.id}>
          <summary>
            <AlertTriangle size={14} />
            <span>
              <b>
                {failure.label} · {failure.target}
              </b>
              <small>{failure.error}</small>
            </span>
            <span className="failure-expand">详情</span>
          </summary>
          <div className="failure-content">
            <p>
              <b>阶段</b> {failure.stage.slice(0, 2)} · {failure.stage_label}
            </p>
            <p>
              <b>失败环节</b> {phases[failure.phase] || failure.phase}
            </p>
            <p>
              <b>关联需求</b>{" "}
              {failure.requirement_ids.length
                ? failure.requirement_ids
                    .map((id) => id + " · " + failure.requirement_names[id])
                    .join("、")
                : "未记录具体需求归属"}
            </p>
            <pre className="failure-message">{failure.error}</pre>
            {failure.record.task && (
              <p>
                <b>原始任务标签</b> <code>{failure.record.task}</code>
              </p>
            )}
            {failure.record.turns != null && (
              <p>
                <b>模型轮数</b> {failure.record.turns}
              </p>
            )}
            {failure.record.test_path && (
              <p>
                <b>测试文件</b> <code>{failure.record.test_path}</code>
              </p>
            )}
            {failure.record.archive && (
              <p>
                <b>失败代码归档</b> <code>{failure.record.archive}</code>
              </p>
            )}
            <p>
              <b>证据来源</b> <code>{failure.source}</code>
            </p>
            {onLocate && failure.node_ids.length > 0 && (
              <div className="failure-locate">
                {failure.node_ids.map((id) => (
                  <button key={id} onClick={() => onLocate(id)}>
                    <Crosshair size={12} />
                    定位 {id}
                  </button>
                ))}
              </div>
            )}
            {onCall && (
              <details className="failure-calls">
                <summary>
                  <MessageSquareText size={12} />
                  关联模型调用 · {failure.call_ids.length}
                </summary>
                <div className="failure-call-list">
                  {detail.calls
                    .filter((call) => failure.call_ids.includes(call.id))
                    .map((call, index) => (
                      <button key={call.id} onClick={() => onCall(call)}>
                        <span>
                          {index + 1}. {call.activity || call.model || call.id}
                        </span>
                        <small>{duration(call.seconds)} · 查看输入／输出</small>
                      </button>
                    ))}
                  {!failure.call_ids.length && (
                    <p>
                      未保存可明确关联的模型调用，请查看原始证据和阶段日志。
                    </p>
                  )}
                </div>
              </details>
            )}
            <details className="failure-evidence">
              <summary>原始反馈与失败记录</summary>
              <pre>{JSON.stringify(failure.record, null, 2)}</pre>
            </details>
          </div>
        </details>
      ))}
    </div>
  );
}
