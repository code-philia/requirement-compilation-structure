import { useEffect, useState } from "react";
import { ArrowRight, Copy } from "lucide-react";
import { course, type Config, type CsvReference } from "./api";
export default function Tasks({
  config,
  onUse,
  onCopy,
  onError,
}: {
  config: Config;
  onUse: (prompt: string) => void;
  onCopy: (text: string) => void;
  onError: (message: string) => void;
}) {
  const [reference, setReference] = useState<CsvReference | null>(null);
  useEffect(() => {
    let disposed = false;
    course<CsvReference>("/reference", { csv: config.sample_csv })
      .then((value) => {
        if (!disposed) setReference(value);
      })
      .catch((error) => {
        if (!disposed) onError(error.message);
      });
    return () => {
      disposed = true;
    };
  }, [config.sample_csv, onError]);
  function promptFor(id: string, prompt: string) {
    return id === "csv" ? prompt + "\n\nCSV：\n" + config.sample_csv : prompt;
  }
  return (
    <section className="cr-tasks-page">
      <div className="cr-section-heading">
        <h2>任务</h2>
      </div>
      {config.tasks.map((task, index) => (
        <details
          className="cr-task-document"
          key={task.id}
          open={task.id === "csv"}
        >
          <summary>
            <span>任务{index === 0 ? "一" : "二"}</span>
            <h2>{task.name}</h2>
            <small>{task.level}</small>
          </summary>
          <div className="cr-task-document-body">
            <h3>任务说明</h3>
            <p>{task.description}</p>
            <div className="cr-task-actions">
              <button
                className="cr-button primary"
                onClick={() => onUse(promptFor(task.id, task.prompt))}
              >
                填入工作台
                <ArrowRight size={14} />
              </button>
              <button
                className="cr-button secondary"
                onClick={() => onCopy(promptFor(task.id, task.prompt))}
              >
                <Copy size={14} />
                复制提示词
              </button>
            </div>
            <details>
              <summary>原始提示词</summary>
              <pre>{promptFor(task.id, task.prompt)}</pre>
            </details>
            <details>
              <summary>验收标准</summary>
              <ul>
                {task.checks.map((check) => (
                  <li key={check}>{check}</li>
                ))}
              </ul>
              {task.rubric && (
                <>
                  <table className="cr-task-rubric">
                    <thead>
                      <tr>
                        <th>维度</th>
                        <th>分值</th>
                        <th>评价内容</th>
                      </tr>
                    </thead>
                    <tbody>
                      {task.rubric.map((item) => (
                        <tr key={item.title}>
                          <td>{item.title}</td>
                          <td>{item.points}</td>
                          <td>{item.criteria}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p>
                    一次交付按四个维度评满100分。基础功能或数据真实性存在关键错误时，不能用视觉分抵消。比较时隐藏模型名称，同一条件重复三次并保留全部结果。
                  </p>
                </>
              )}
            </details>
            {task.scenarios && (
              <details>
                <summary>连续验收流程</summary>
                <ol className="cr-task-scenarios">
                  {task.scenarios.map((item, index) => (
                    <li key={index}>
                      <strong>{item.action}</strong>
                      <p>{item.expected}</p>
                    </li>
                  ))}
                </ol>
              </details>
            )}
            {task.id === "csv" && (
              <section className="cr-standard-answer">
                <h3>标准答案</h3>
                {reference ? (
                  <div className="cr-reference-body">
                    <div className="cr-reference-totals">
                      {[
                        ["原始行", reference.total_rows],
                        ["有效行", reference.valid_rows],
                        ["重复行", reference.duplicate_rows],
                        ["错误行", reference.error_rows],
                        ["错误项", reference.error_items],
                      ].map(([label, value]) => (
                        <div key={label}>
                          <span>{label}</span>
                          <strong>{value}</strong>
                        </div>
                      ))}
                    </div>
                    <p>有效订单：{reference.valid_ids.join("、") || "无"}</p>
                    <p>
                      状态分布：
                      {Object.entries(reference.statuses)
                        .map(([key, value]) => `${key} ${value}`)
                        .join(" / ")}
                    </p>
                    <h3>
                      有效已支付：{reference.paid_orders} 单 ·{" "}
                      {reference.quantity} 件 · ¥{reference.revenue}
                    </h3>
                    <table>
                      <thead>
                        <tr>
                          <th>城市</th>
                          <th>订单数</th>
                          <th>销售额 / 元</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reference.cities.map((city) => (
                          <tr key={city.city}>
                            <td>{city.city}</td>
                            <td>{city.orders}</td>
                            <td>{city.revenue}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <h3>逐行异常</h3>
                    <table>
                      <thead>
                        <tr>
                          <th>数据行</th>
                          <th>订单</th>
                          <th>列与原因</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reference.errors.map((item) => (
                          <tr key={item.row}>
                            <td>{item.row}</td>
                            <td>{item.order_id}</td>
                            <td>
                              {item.issues
                                .map(
                                  (issue) => `${issue.column}：${issue.reason}`,
                                )
                                .join("；")}
                            </td>
                          </tr>
                        ))}
                        {reference.duplicates.map((item) => (
                          <tr key={item.row}>
                            <td>{item.row}</td>
                            <td>{item.order_id}</td>
                            <td>重复，首次出现在第 {item.first_row} 行</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <details open>
                      <summary>格式清洗明细</summary>
                      <table>
                        <thead>
                          <tr>
                            <th>数据行</th>
                            <th>列</th>
                            <th>原始值</th>
                            <th>整理后</th>
                          </tr>
                        </thead>
                        <tbody>
                          {reference.changes.flatMap((item) =>
                            item.changes.map((change) => (
                              <tr key={`${item.row}-${change.column}`}>
                                <td>{item.row}</td>
                                <td>{change.column}</td>
                                <td>
                                  <code>{JSON.stringify(change.from)}</code>
                                </td>
                                <td>{change.to}</td>
                              </tr>
                            )),
                          )}
                        </tbody>
                      </table>
                    </details>
                  </div>
                ) : (
                  <p>正在计算标准答案…</p>
                )}
              </section>
            )}
          </div>
        </details>
      ))}
    </section>
  );
}
