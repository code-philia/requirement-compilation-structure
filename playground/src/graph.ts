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

export function buildGraph(detail: Detail | null, expanded: Set<string>) {
  const nodes: FactoryNode[] = [],
    edges: Edge[] = [],
    selections = new Map<string, Selection>();
  const a = detail?.artifacts || {};
  const edgeIds = new Set<string>();
  const dimensions: Record<string, [number, number]> = {
    zone: [360, 125],
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
      initialWidth: dimensions[kind]?.[0] || 176,
      initialHeight: dimensions[kind]?.[1] || 68,
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
                ? a.frontend_e2e?.requirements?.[record.id]?.status
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
      sourceHandle: "out",
      targetHandle: "in",
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
  type Item = {
    id: string;
    kind: string;
    label: string;
    record: RecordData;
    subtitle?: string;
    children: Item[];
    count?: number;
  };
  const catalog: { selection: Selection; ancestors: string[] }[] = [];
  const elements = a.ui_design?.elements || {};
  const childrenByParent = new Map<string, string[]>();
  const triggersBySource = new Map<string, Item[]>();
  for (const [id, trigger] of Object.entries(
    a.frontend_triggers?.triggers || {},
  ) as [string, RecordData][]) {
    const triggers = triggersBySource.get(trigger.source) || [];
    triggers.push({
      id: "trigger:" + id,
      kind: "trigger",
      label: trigger.event || id,
      record: trigger,
      subtitle: id,
      children: [],
    });
    triggersBySource.set(trigger.source, triggers);
  }
  for (const [id, record] of Object.entries(elements) as [
    string,
    RecordData,
  ][]) {
    const children = childrenByParent.get(record.parent) || [];
    children.push(id);
    childrenByParent.set(record.parent, children);
  }
  function requirementItem(
    record: RecordData,
    seen = new Set<string>(),
  ): Item[] {
    if (!record?.id || seen.has(record.id)) return [];
    const path = new Set(seen).add(record.id);
    return [
      {
        id: "req:" + record.id,
        kind: "requirement",
        label: record.name || record.id,
        record,
        subtitle: record.id,
        children: (record.children || []).flatMap((child: RecordData) =>
          requirementItem(child, path),
        ),
      },
    ];
  }
  function uiItem(id: string, seen = new Set<string>()): Item[] {
    const record = elements[id];
    if (!record || seen.has(id)) return [];
    const path = new Set(seen).add(id);
    const children = (childrenByParent.get(id) || []).flatMap((child) =>
      uiItem(child, path),
    );
    children.push(...(triggersBySource.get(id) || []));
    return [
      {
        id: "ui:" + id,
        kind: record.type === "page" ? "page" : "element",
        label: record.prop?.label || record.prop?.text || record.type || id,
        record: { ...record, id },
        subtitle:
          record.type === "page"
            ? (Object.values(a.ui_design?.pages || {}) as RecordData[]).find(
                (page) => page.root === id,
              )?.route
            : record.type,
        children,
      },
    ];
  }
  const trees: Item[][] = [
    requirementItem(a.requirements || {}),
    Object.entries(a.db_schema?.entities || {}).map(([name, entity]) => ({
      id: "db:" + name,
      kind: "entity",
      label: name,
      record: entity as RecordData,
      subtitle: `${Object.keys((entity as RecordData).fields || {}).length} FIELDS`,
      children: [],
    })),
    Object.entries(a.backend_apis?.apis || {}).map(([id, value]) => {
      const record = value as RecordData;
      return {
        id: "api:" + id,
        kind: "api",
        label: record.signature?.name || id,
        record,
        subtitle: `${record.signature?.method || "API"} ${record.signature?.path || id}`,
        children: [],
      };
    }),
    (Object.values(a.ui_design?.pages || {}) as RecordData[]).flatMap((page) =>
      uiItem(page.root),
    ),
  ];
  // Every level has at most eight cards, including very broad requirement/UI trees.
  function groupItems(items: Item[], parent: string): Item[] {
    if (items.length <= 8) return items;
    const size = 8 ** Math.floor(Math.log(items.length - 1) / Math.log(8));
    const groups: Item[] = [];
    for (let offset = 0; offset < items.length; offset += size) {
      const members = items.slice(offset, offset + size);
      const id = `${parent}:group:${offset}`;
      groups.push({
        id,
        kind: "group",
        label: `${members[0].label} 等 ${members.length} 项`,
        subtitle: `第 ${offset + 1}–${offset + members.length} 项 · 点击展开`,
        record: {},
        count: members.length,
        children: groupItems(members, id),
      });
    }
    return groups;
  }
  const totalCounts = [0, 0, 0, 0];
  function prepare(
    items: Item[],
    parent: string,
    zone: number,
    ancestors: string[],
  ): Item[] {
    const grouped = groupItems(items, parent);
    for (const item of grouped) {
      if (item.kind !== "group") {
        totalCounts[zone]++;
        item.count = item.children.length;
        catalog.push({
          selection: {
            id: item.id,
            kind: item.kind,
            label: item.label,
            zone,
            record: item.record,
          },
          ancestors,
        });
      }
      item.children = prepare(item.children, item.id, zone, [
        ...ancestors,
        item.id,
      ]);
    }
    return grouped;
  }
  function render(items: Item[], zone: number, parent?: string) {
    for (const item of items) {
      if (selections.has(item.id)) {
        if (parent) link(parent, item.id, "contain");
        continue;
      }
      add(
        item.id,
        item.kind,
        item.label,
        zone,
        item.record,
        0,
        0,
        item.subtitle,
      );
      const node = nodes[nodes.length - 1];
      node.data.childCount = item.count || item.children.length;
      node.data.expandable = item.children.length > 0;
      if (parent)
        link(parent, item.id, item.kind === "trigger" ? "trigger" : "contain");
      if (expanded.has(item.id)) render(item.children, zone, item.id);
    }
  }
  for (let zone = 0; zone < 4; zone++) {
    const info = ZONES[zone];
    const items = prepare(trees[zone], "zone:" + zone, zone, []);
    add("zone:" + zone, "zone", info.title, zone, {}, 0, 0, info.subtitle);
    const heading = nodes[nodes.length - 1];
    heading.data.count = totalCounts[zone];
    heading.data.status =
      (!detail?.run.legacy
        ? detail?.stages.find((stage) => stage.id.startsWith(info.stage))
            ?.status
        : undefined) || "PENDING";
    render(items, zone);
  }
  // Retain earlier stage failures even when a later frontend check passed.
  // Badges propagate to collapsed ancestors so hidden failures stay discoverable.
  for (const failure of detail?.failures || []) {
    const affected = new Set<string>();
    for (const id of failure.node_ids) {
      affected.add(id);
      for (const ancestor of catalog.find((item) => item.selection.id === id)
        ?.ancestors || [])
        affected.add(ancestor);
    }
    for (const node of nodes) {
      if (!affected.has(node.id)) continue;
      node.data.failureCount = Number(node.data.failureCount || 0) + 1;
      node.data.status = failure.node_ids.includes(node.id)
        ? "FAILED"
        : "COMPLETED_WITH_FAILURES";
    }
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
  for (const [id, trigger] of Object.entries(
    a.frontend_triggers?.triggers || {},
  ) as [string, RecordData][]) {
    for (const action of trigger.action || []) {
      if (action.kind === "api")
        link("trigger:" + id, "api:" + action.api, "call", "CALL");
    }
  }
  // Keep requirement/UI hierarchies in left-to-right trees. Flat registries use
  // a compact grid; both layouts reserve the full bounds of expanded branches.
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const childNodes = new Map<string, FactoryNode[]>();
  const parented = new Set<string>();
  for (const edge of edges) {
    if (edge.data?.kind !== "contain" && edge.data?.kind !== "trigger")
      continue;
    const child = nodesById.get(edge.target)!;
    if (parented.has(child.id)) continue;
    parented.add(child.id);
    const children = childNodes.get(edge.source) || [];
    children.push(child);
    childNodes.set(edge.source, children);
  }
  function pack(items: FactoryNode[]): { width: number; height: number } {
    if (!items.length) return { width: 0, height: 0 };
    const blocks = items.map((node) => {
      const children = childNodes.get(node.id) || [];
      const bounds = pack(children);
      const width = Math.max(176, bounds.width);
      const height = 68 + (children.length ? 38 + bounds.height : 0);
      return { node, children, width, height };
    });
    const columns = Math.min(3, Math.ceil(Math.sqrt(items.length)));
    const columnWidths = Array(columns).fill(0);
    for (let i = 0; i < blocks.length; i++)
      columnWidths[i % columns] = Math.max(
        columnWidths[i % columns],
        blocks[i].width,
      );
    let y = 0;
    for (let start = 0; start < blocks.length; start += columns) {
      const row = blocks.slice(start, start + columns);
      let x = 0;
      for (let col = 0; col < row.length; col++) {
        const block = row[col];
        block.node.position = { x: x + (columnWidths[col] - 176) / 2, y };
        const shift = (node: FactoryNode) => {
          node.position.x += x + (columnWidths[col] - block.width) / 2;
          node.position.y += y + 106;
          for (const child of childNodes.get(node.id) || []) shift(child);
        };
        for (const child of block.children) shift(child);
        x += columnWidths[col] + 28;
      }
      y += Math.max(...row.map((block) => block.height)) + 28;
    }
    return {
      width:
        columnWidths.reduce((sum, value) => sum + value, 0) +
        (columns - 1) * 28,
      height: y - 28,
    };
  }
  function layoutTree(roots: FactoryNode[]): { width: number; height: number } {
    const heights = new Map<string, number>();
    const siblingGap = 24;
    const levelWidth = 256;
    function measure(node: FactoryNode): number {
      const children = childNodes.get(node.id) || [];
      let childrenHeight = 0;
      for (const child of children) childrenHeight += measure(child);
      childrenHeight += Math.max(0, children.length - 1) * siblingGap;
      const height = Math.max(68, childrenHeight);
      heights.set(node.id, height);
      return height;
    }
    let width = 0;
    function place(node: FactoryNode, depth: number, top: number) {
      const height = heights.get(node.id)!;
      node.position = { x: depth * levelWidth, y: top + (height - 68) / 2 };
      width = Math.max(width, node.position.x + 176);
      let childTop = top;
      for (const child of childNodes.get(node.id) || []) {
        place(child, depth + 1, childTop);
        childTop += heights.get(child.id)! + siblingGap;
      }
    }
    let top = 0;
    for (const root of roots) {
      const height = measure(root);
      place(root, 0, top);
      top += height + siblingGap;
    }
    return { width, height: Math.max(0, top - siblingGap) };
  }
  let zoneX = 0;
  for (let zone = 0; zone < 4; zone++) {
    const members = nodes.filter(
      (node) => node.data.zone === zone && node.data.kind !== "zone",
    );
    const roots = members.filter((node) => !parented.has(node.id));
    const bounds = zone === 0 || zone === 3 ? layoutTree(roots) : pack(roots);
    const width = Math.max(360, bounds.width + 32);
    const heading = nodes.find((node) => node.id === "zone:" + zone)!;
    heading.position = { x: zoneX, y: 0 };
    heading.style = { width };
    heading.initialWidth = width;
    for (const node of members) {
      node.position.x += zoneX + 16;
      node.position.y += 145;
    }
    zoneX += width + 70;
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
  return { nodes, edges, selections, catalog };
}
