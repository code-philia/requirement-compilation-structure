import type { Node, Edge } from "@xyflow/react";
import type { Detail, RecordData, Selection } from "./types";

export const ZONES = [
  {
    id: "requirements",
    title: "需求档案站",
    en: "REQUIREMENTS",
    subtitle: "每一份承诺，从这里开始",
    color: "#6889ce",
    icon: "document",
    stage: "01",
  },
  {
    id: "database",
    title: "数据仓库",
    en: "DATA WAREHOUSE",
    subtitle: "实体、关系与读写义务",
    color: "#69a694",
    icon: "database",
    stage: "04",
  },
  {
    id: "backend",
    title: "API 工坊",
    en: "API WORKSHOP",
    subtitle: "把业务行为装配为契约",
    color: "#cb9a65",
    icon: "api",
    stage: "06",
  },
  {
    id: "frontend",
    title: "界面装配区",
    en: "INTERFACE STUDIO",
    subtitle: "组件与交互，在这里连接",
    color: "#a38ac6",
    icon: "ui",
    stage: "10",
  },
];
export type FactoryData = {
  label: string;
  kind: string;
  zone: number;
  record: RecordData;
  subtitle?: string;
  status?: string;
  count?: number;
  selection: Selection;
  [key: string]: unknown;
};
export type FactoryNode = Node<FactoryData>;

export function buildGraph(
  detail: Detail | null,
  expanded: Set<string>,
): { nodes: FactoryNode[]; edges: Edge[]; selections: Map<string, Selection> } {
  const nodes: FactoryNode[] = [],
    edges: Edge[] = [],
    selections = new Map<string, Selection>();
  const a = detail?.artifacts || {};
  const edgeIds = new Set<string>();
  const dimensions: Record<string, [number, number]> = {
    zone: [460, 145],
    api: [290, 100],
    entity: [208, 129],
    trigger: [167, 66],
    page: [231, 90],
  };
  const add = (
    id: string,
    kind: string,
    label: string,
    zone: number,
    record: RecordData,
    x: number,
    y: number,
    subtitle?: string,
  ) => {
    if (selections.has(id)) return;
    const selection = { id, kind, label, zone, record };
    selections.set(id, selection);
    nodes.push({
      id,
      type: kind === "zone" ? "zone" : "factory",
      position: { x, y },
      initialWidth: dimensions[kind]?.[0] || 212,
      initialHeight: dimensions[kind]?.[1] || 90,
      data: {
        label,
        kind,
        zone,
        record,
        subtitle,
        selection,
        status:
          kind === "api"
            ? a.backend_tdd?.apis?.[id.slice(4)]?.status
            : kind === "entity" && !detail?.run.legacy
              ? detail?.stages.find((stage) => stage.id.startsWith("04"))
                  ?.status
              : kind === "requirement"
                ? a.independent_acceptance?.requirements?.[record.id]?.status
                : undefined,
      },
      draggable: kind !== "zone",
    });
  };
  const link = (
    source: string,
    target: string,
    kind: string,
    label?: string,
  ) => {
    if (!selections.has(source) || !selections.has(target)) return;
    const edgeId = `${kind}:${source}:${target}`;
    if (edgeIds.has(edgeId)) return;
    edgeIds.add(edgeId);
    edges.push({
      id: edgeId,
      source,
      target,
      label,
      type: "smoothstep",
      className: `edge-${kind}`,
      data: { kind },
      style: {
        stroke:
          kind === "write"
            ? "#c58b60"
            : kind === "read"
              ? "#67a28f"
              : "#a5afc2",
        strokeWidth: 1.2,
        strokeDasharray: kind === "association" ? "5 6" : undefined,
      },
    });
  };
  for (let zone = 0; zone < 4; zone++) {
    const info = ZONES[zone];
    add(
      "zone:" + zone,
      "zone",
      info.title,
      zone,
      {},
      zone * 540,
      0,
      info.subtitle,
    );
    nodes[nodes.length - 1].data.status =
      (!detail?.run.legacy
        ? detail?.stages.find((stage) => stage.id.startsWith(info.stage))
            ?.status
        : undefined) || "PENDING";
  }
  let requirementRow = 0;
  const visit = (node: RecordData, depth: number, parent?: string) => {
    if (!node?.id) return;
    const id = "req:" + node.id;
    add(
      id,
      "requirement",
      node.name || node.id,
      0,
      node,
      30 + Math.min(depth, 3) * 32,
      160 + requirementRow++ * 106,
      node.id,
    );
    if (parent) link(parent, id, "contain");
    if (expanded.has(id) || depth === 0)
      for (const child of node.children || []) visit(child, depth + 1, id);
  };
  visit(a.requirements || {}, 0);
  let index = 0;
  for (const [name, entity] of Object.entries(a.db_schema?.entities || {}) as [
    string,
    RecordData,
  ][]) {
    add(
      "db:" + name,
      "entity",
      name,
      1,
      entity,
      570 + (index % 2) * 230,
      160 + Math.floor(index / 2) * 160,
      `${Object.keys(entity.fields || {}).length} FIELDS`,
    );
    index++;
  }
  for (const [name, entity] of Object.entries(a.db_schema?.entities || {}) as [
    string,
    RecordData,
  ][]) {
    for (const field of Object.values(entity.fields || {}) as RecordData[]) {
      if (field.references)
        link("db:" + name, "db:" + field.references.split(".")[0], "foreign");
    }
  }
  index = 0;
  for (const [id, record] of Object.entries(a.backend_apis?.apis || {}) as [
    string,
    RecordData,
  ][]) {
    add(
      "api:" + id,
      "api",
      record.signature?.name || id,
      2,
      record,
      1110,
      160 + index++ * 132,
      `${record.signature?.method || "API"} ${record.signature?.path || id}`,
    );
  }
  const elements = a.ui_design?.elements || {};
  let uiRow = 0;
  const uiVisit = (
    id: string,
    depth: number,
    parent?: string,
    visited = new Set<string>(),
  ) => {
    if (visited.has(id) || depth > 12) return;
    visited.add(id);
    const record = elements[id];
    if (!record) return;
    const nodeId = "ui:" + id;
    add(
      nodeId,
      record.type === "page" ? "page" : "element",
      record.prop?.label || record.prop?.text || record.type || id,
      3,
      { ...record, id },
      1650 + Math.min(depth, 4) * 30,
      160 + uiRow++ * 102,
      record.type === "page"
        ? (Object.values(a.ui_design?.pages || {}) as RecordData[]).find(
            (p) => p.root === id,
          )?.route
        : record.type,
    );
    if (parent) link(parent, nodeId, "contain");
    if (expanded.has(nodeId) || record.type === "page") {
      for (const [childId, child] of Object.entries(elements) as [
        string,
        RecordData,
      ][]) {
        if (child.parent === id) uiVisit(childId, depth + 1, nodeId, visited);
      }
    }
  };
  for (const page of Object.values(a.ui_design?.pages || {}) as RecordData[])
    uiVisit(page.root, 0);
  for (const [id, trigger] of Object.entries(
    a.frontend_triggers?.triggers || {},
  ) as [string, RecordData][]) {
    const source = nodes.find((node) => node.id === "ui:" + trigger.source);
    if (!source || !expanded.has(source.id)) continue;
    add(
      "trigger:" + id,
      "trigger",
      trigger.event || id,
      3,
      trigger,
      source.position.x + 250,
      source.position.y + 12,
      id,
    );
    link(source.id, "trigger:" + id, "trigger");
    for (const action of trigger.action || [])
      if (action.kind === "api")
        link("trigger:" + id, "api:" + action.api, "call", "CALL");
  }
  // Associations come only from accepted IR records, never label matching.
  for (const [rid, fields] of Object.entries(
    a.db_schema?.requirements || {},
  ) as [string, string[]][]) {
    for (const entity of new Set(fields.map((field) => field.split(".")[0])))
      link("req:" + rid, "db:" + entity, "association");
  }
  for (const [rid, ids] of Object.entries(
    a.backend_apis?.requirements || {},
  ) as [string, string[]][]) {
    for (const id of ids) link("req:" + rid, "api:" + id, "association");
  }
  for (const [id, record] of Object.entries(a.backend_apis?.apis || {}) as [
    string,
    RecordData,
  ][]) {
    for (const mode of ["read", "write"]) {
      for (const entity of new Set(
        (record[mode] || []).map((field: string) => field.split(".")[0]),
      ))
        link("api:" + id, "db:" + entity, mode, mode === "read" ? "R" : "W");
    }
  }
  for (const [rid, ids] of Object.entries(a.ui_design?.requirements || {}) as [
    string,
    string[],
  ][]) {
    for (const id of ids) link("req:" + rid, "ui:" + id, "association");
  }
  return { nodes, edges, selections };
}
