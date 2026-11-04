import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Handle,
  Position,
  useReactFlow,
  type NodeProps,
} from "@xyflow/react";
import {
  Check,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Crosshair,
  Expand,
  Focus,
  GitBranch,
  Hand,
  Layers3,
  Search,
  Sparkles,
  Zap,
  X,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { buildGraph, ZONES, type FactoryNode } from "../graph";
import type { Detail, Selection } from "../types";
import { FactoryArt } from "./FactoryArt";
import "@xyflow/react/dist/style.css";

const FactoryNodeView = memo(function FactoryNodeView({
  data,
  selected,
}: NodeProps<FactoryNode>) {
  const expandable = !!data.expandable;
  return (
    <motion.div
      initial={{ opacity: 0, y: 14, scale: 0.94 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35 }}
      className={`factory-node kind-${data.kind} ${data.zone === 0 || data.zone === 3 ? "is-tree" : ""} ${data.failureCount ? "has-failure" : ""} ${selected ? "is-selected" : ""}`}
      style={{ "--zone-color": ZONES[data.zone].color } as React.CSSProperties}
    >
      <Handle id="in" type="target" position={Position.Left} />
      <Handle id="out" type="source" position={Position.Right} />
      <div className="node-illustration">
        {data.kind === "group" ? (
          <Layers3 size={27} />
        ) : (
          <FactoryArt kind={data.kind} color={ZONES[data.zone].color} />
        )}
      </div>
      <div className="node-caption">
        <span className="node-eyebrow">{data.subtitle || data.kind}</span>
        <strong title={data.label}>{data.label}</strong>
      </div>
      {expandable && (
        <span className="node-child-count">{String(data.childCount)} 项</span>
      )}
      {!!data.failureCount && (
        <span
          className="node-failure-badge"
          title={`${data.failureCount} 处失败（含折叠子节点）`}
        >
          <AlertTriangle size={11} />
          {String(data.failureCount)}
        </span>
      )}
      {data.status === "GREEN" && (
        <span
          className="node-verified"
          title={data.kind === "requirement" ? "需求验收通过" : "实现检查通过"}
        >
          <Check size={12} />
        </span>
      )}
      {expandable && (
        <button
          className="node-expand nodrag"
          title="展开或折叠子节点与交互"
          aria-label="展开或折叠子节点"
          aria-expanded={!!data.expanded}
          onClick={(event) => {
            event.stopPropagation();
            (data.onExpand as () => void)?.();
          }}
        >
          {data.expanded ? (
            <ChevronDown size={13} />
          ) : (
            <ChevronRight size={13} />
          )}
        </button>
      )}
      {data.kind === "trigger" && (
        <span className="trigger-badge">
          <Zap size={11} />
        </span>
      )}
    </motion.div>
  );
});
const ZoneNode = memo(function ZoneNode({ data }: NodeProps<FactoryNode>) {
  const info = ZONES[data.zone];
  return (
    <div
      className={`zone-heading zone-${data.zone}`}
      style={{ "--zone-color": info.color } as React.CSSProperties}
    >
      <div className="zone-title-row">
        <span className="zone-number">0{data.zone + 1}</span>
        <span className={`zone-status status-${data.status}`} />
        <span className="zone-count">{data.count || 0} 个产物</span>
      </div>
      <span className="overline">{info.en}</span>
      <h2>{data.label}</h2>
      <p>{data.subtitle}</p>
      <div className="zone-rule" />
    </div>
  );
});
const nodeTypes = { factory: FactoryNodeView, zone: ZoneNode };

function MapContent({
  detail,
  onSelect,
  selected,
  onClear,
  locateTarget,
  onFocus,
}: {
  detail: Detail | null;
  onSelect: (selection: Selection) => void;
  selected: Selection | null;
  onClear: () => void;
  locateTarget: { id: string; request: number } | null;
  onFocus: (selection: Selection) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState(-1);
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const [relatedOnly, setRelatedOnly] = useState(false);
  const [allLinks, setAllLinks] = useState(false);
  const [pendingFocus, setPendingFocus] = useState("");
  const { fitView, setCenter } = useReactFlow();
  const reduce = useReducedMotion();
  const positions = useRef(new Map<string, { x: number; y: number }>());
  const fitted = useRef("");
  const [zoomed, setZoomed] = useState(false);
  const [, updatePositions] = useState(0);
  useEffect(() => {
    setExpanded(new Set());
    positions.current.clear();
    fitted.current = "";
    setTab(-1);
    setRelatedOnly(false);
    setQuery("");
    setPendingFocus("");
  }, [detail?.run.id]);
  const graph = useMemo(
    () => buildGraph(detail, expanded),
    [detail?.artifacts, detail?.failures, expanded],
  );
  const related = useMemo(() => {
    const ids = new Set<string>();
    if (!selected) return ids;
    ids.add(selected.id);
    for (let pass = 0; pass < 3; pass++) {
      for (const edge of graph.edges) {
        if (ids.has(edge.source) && !edge.target.startsWith("req:"))
          ids.add(edge.target);
        if (ids.has(edge.target) && !edge.source.startsWith("req:"))
          ids.add(edge.source);
        if (
          pass === 0 &&
          (edge.source === selected.id || edge.target === selected.id)
        ) {
          ids.add(edge.source);
          ids.add(edge.target);
        }
      }
    }
    return ids;
  }, [selected, graph.edges]);
  const filteredNodes = graph.nodes.map((node) => {
    const isMatch =
      !query ||
      `${node.data.label} ${node.id}`
        .toLowerCase()
        .includes(query.toLowerCase());
    const hidden =
      node.data.kind !== "zone" &&
      relatedOnly &&
      selected &&
      !related.has(node.id);
    const position = positions.current.get(node.id) || node.position;
    return {
      ...node,
      position,
      hidden: !!hidden,
      selected: node.id === selected?.id,
      className: `${selected && node.data.kind !== "zone" && !related.has(node.id) ? "node-muted" : ""} ${!isMatch && node.data.kind !== "zone" ? "search-muted" : ""}`,
      data: {
        ...node.data,
        expanded: expanded.has(node.id),
        onExpand: () => {
          positions.current.clear();
          setFollow(false);
          setPendingFocus(node.id);
          setExpanded((before) => {
            const next = new Set(before);
            if (next.has(node.id)) next.delete(node.id);
            else next.add(node.id);
            return next;
          });
        },
      },
    };
  });
  const filteredEdges = graph.edges
    .filter(
      (edge) =>
        allLinks ||
        (selected
          ? related.has(edge.source) && related.has(edge.target)
          : edge.data?.kind === "contain"),
    )
    .map((edge) => ({
      ...edge,
      animated:
        !!selected &&
        related.has(edge.source) &&
        related.has(edge.target) &&
        !reduce,
    }));
  const activeStage = detail?.stages.find(
    (stage) => stage.status === "RUNNING",
  );
  const activeZone = activeStage
    ? Number(activeStage.id.slice(0, 2)) <= 1
      ? 0
      : Number(activeStage.id.slice(0, 2)) <= 4
        ? 1
        : Number(activeStage.id.slice(0, 2)) <= 6
          ? 2
          : 3
    : -1;
  useEffect(() => {
    if (graph.nodes.length <= 4 || fitted.current === detail?.run.id) return;
    const timer = setTimeout(() => {
      fitView({
        nodes: graph.nodes,
        padding: 0.13,
        duration: reduce ? 0 : 650,
        maxZoom: 0.9,
      });
      fitted.current = detail?.run.id || "";
    }, 250);
    return () => clearTimeout(timer);
  }, [graph.nodes.length, detail?.run.id, fitView, reduce]);
  function focusZone(zone: number) {
    setTab(zone);
    setFollow(false);
    fitView({
      nodes: graph.nodes.filter((node) => zone < 0 || node.data.zone === zone),
      padding: 0.18,
      duration: reduce ? 0 : 550,
      maxZoom: zone < 0 ? 0.9 : 1.15,
    });
  }
  useEffect(() => {
    if (!follow || activeZone < 0) return;
    setTab(activeZone);
    fitView({
      nodes: graph.nodes.filter((node) => node.data.zone === activeZone),
      padding: 0.2,
      maxZoom: 1.05,
      duration: reduce ? 0 : 650,
    });
  }, [follow, activeZone, fitView, reduce]);
  useEffect(() => {
    if (!pendingFocus) return;
    const timer = setTimeout(() => {
      if (pendingFocus === "overview") {
        focusZone(-1);
      } else if (pendingFocus.startsWith("search:")) {
        const node = graph.nodes.find(
          (node) => node.id === pendingFocus.slice(7),
        );
        if (node)
          setCenter(node.position.x + 88, node.position.y + 34, {
            zoom: 1.2,
            duration: reduce ? 0 : 550,
          });
      } else {
        const children = new Set(
          graph.edges
            .filter(
              (edge) =>
                edge.source === pendingFocus &&
                (edge.data?.kind === "contain" ||
                  edge.data?.kind === "trigger"),
            )
            .map((edge) => edge.target),
        );
        children.add(pendingFocus);
        fitView({
          nodes: graph.nodes.filter((node) => children.has(node.id)),
          padding: 0.3,
          maxZoom: 1.1,
          duration: reduce ? 0 : 500,
        });
      }
      setPendingFocus("");
    }, 80);
    return () => clearTimeout(timer);
  }, [pendingFocus, graph, fitView, setCenter, reduce]);
  const matches = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return [];
    return graph.catalog
      .filter(({ selection }) =>
        `${selection.label} ${selection.id} ${selection.record.signature?.path || ""}`
          .toLowerCase()
          .includes(term),
      )
      .slice(0, 8);
  }, [graph.catalog, query]);
  function locate(match: (typeof graph.catalog)[number], showDetails = true) {
    positions.current.clear();
    setExpanded((before) => new Set([...before, ...match.ancestors]));
    setFollow(false);
    setRelatedOnly(false);
    setTab(match.selection.zone);
    setPendingFocus("search:" + match.selection.id);
    setQuery("");
    if (showDetails) onSelect(match.selection);
    else onFocus(match.selection);
  }
  useEffect(() => {
    if (!locateTarget) return;
    const match = graph.catalog.find(
      (item) => item.selection.id === locateTarget.id,
    );
    if (match) locate(match, false);
  }, [locateTarget?.request]);
  function search() {
    if (matches[0]) locate(matches[0]);
  }
  return (
    <div className="factory-map">
      <div className="map-topbar">
        <div className="map-tabs">
          <button
            className={tab === -1 ? "active" : ""}
            onClick={() => focusZone(-1)}
          >
            <Layers3 size={14} />
            工厂总览
          </button>
          {ZONES.map((zone, index) => (
            <button
              key={zone.id}
              className={tab === index ? "active" : ""}
              onClick={() => focusZone(index)}
            >
              {zone.title}
            </button>
          ))}
        </div>
        <span className="map-view-label">LIVE WORKSPACE</span>
      </div>
      <div className="map-search">
        <Search size={15} />
        <input
          placeholder="查找需求、实体、API…"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") search();
          }}
        />
        <kbd>↵</kbd>
        {query.trim() && (
          <div className="map-search-results">
            {matches.map((match) => (
              <button key={match.selection.id} onClick={() => locate(match)}>
                <span>{match.selection.label}</span>
                <small>
                  {match.selection.id} · {ZONES[match.selection.zone].title}
                </small>
              </button>
            ))}
            {!matches.length && <p>没有匹配的节点</p>}
          </div>
        )}
      </div>
      {detail && (
        <div className="map-disclosure-toolbar">
          <span>
            {
              graph.nodes.filter(
                (node) =>
                  node.data.kind !== "zone" && node.data.kind !== "group",
              ).length
            }{" "}
            / {graph.catalog.length} 个节点可见
          </span>
          <button
            onClick={() => {
              positions.current.clear();
              setExpanded(new Set());
              setFollow(false);
              onClear();
              setPendingFocus("overview");
            }}
          >
            收起全部
          </button>
          <small>点击数量按钮逐层展开 · 搜索可定位折叠节点</small>
        </div>
      )}
      <div className="map-canvas">
        <ReactFlow
          nodes={filteredNodes}
          edges={filteredEdges}
          nodeTypes={nodeTypes}
          minZoom={0.04}
          maxZoom={1.8}
          defaultViewport={{ x: 55, y: 190, zoom: 0.53 }}
          nodesConnectable={false}
          elementsSelectable
          onNodesChange={(changes) => {
            let moved = false;
            for (const change of changes) {
              if (change.type === "position" && change.position) {
                positions.current.set(change.id, change.position);
                moved = true;
              }
            }
            if (moved) updatePositions((value) => value + 1);
          }}
          onNodeClick={(_, node) => {
            if (node.data.kind === "zone") focusZone(node.data.zone);
            else if (node.data.kind === "group")
              (node.data.onExpand as () => void)?.();
            else onSelect(node.data.selection);
          }}
          onNodeDragStop={(_, node) =>
            positions.current.set(node.id, node.position)
          }
          onMoveStart={(event) => {
            if (event) setFollow(false);
          }}
          onMoveEnd={(_, viewport) => setZoomed(viewport.zoom > 0.65)}
          fitView={false}
          proOptions={{ hideAttribution: true }}
          className={zoomed ? "detail-zoom" : ""}
        >
          <Background
            variant={BackgroundVariant.Lines}
            gap={52}
            color="#dfe5ec"
            lineWidth={0.5}
          />
          <Controls showInteractive={false} showFitView={false} />
          <MiniMap
            style={{ width: 115, height: 75 }}
            nodeColor={(node) => ZONES[(node.data as any).zone || 0].color}
            maskColor="rgba(238,242,245,.75)"
            zoomable
            pannable
          />
        </ReactFlow>
      </div>
      {selected && (
        <div className="map-selection">
          <span>关联追踪</span>
          <b>{selected.label}</b>
          <button onClick={() => onSelect(selected)}>查看详情</button>
          <button aria-label="清除关联高亮" onClick={onClear}>
            <X size={13} />
          </button>
        </div>
      )}
      {!detail && (
        <div className="map-welcome">
          <span className="welcome-icon">
            <FactoryArt kind="api" color="#7183ae" />
          </span>
          <span className="overline">FROM INTENT TO SOFTWARE</span>
          <h1>让需求，成为软件。</h1>
          <p>
            开始一次编译，或打开历史记录。
            <br />
            看见每个需求如何连接数据、接口与界面。
          </p>
          <div className="welcome-steps">
            <span>文档</span>
            <i>→</i>
            <span>数据</span>
            <i>→</i>
            <span>契约</span>
            <i>→</i>
            <span>应用</span>
          </div>
        </div>
      )}
      {detail && graph.nodes.length === 4 && (
        <div className="map-welcome compact-welcome">
          <Sparkles size={28} />
          <h2>工厂正在准备中</h2>
          <p>接受第一份编译产物后，它会出现在这里。</p>
        </div>
      )}
      <div className="map-bottom">
        <div className="map-legend">
          <span>
            <i className="legend-dot" />
            已生成的设计产物
          </span>
          <span>
            <Hand size={12} />
            拖拽 · 滚轮缩放 · 点击查看
          </span>
        </div>
        <div className="map-actions">
          <button
            className={allLinks ? "toggled" : ""}
            onClick={() => setAllLinks(!allLinks)}
            title="显示全部已声明关联"
          >
            <GitBranch size={14} />
          </button>
          <button
            className={relatedOnly ? "toggled" : ""}
            disabled={!selected}
            onClick={() => setRelatedOnly(!relatedOnly)}
            title="只看选中对象的关联"
          >
            <Focus size={14} />
          </button>
          <button
            className={follow ? "toggled" : ""}
            onClick={() => setFollow(!follow)}
            title="跟随当前阶段"
          >
            <Crosshair size={14} />
            <span>跟随</span>
          </button>
          <button onClick={() => focusZone(-1)} title="返回工厂总览">
            <Expand size={14} />
          </button>
        </div>
      </div>
      {activeStage && (
        <div className="current-work">
          <span className="pulse-dot" />
          正在编译 · {activeStage.label}
        </div>
      )}
    </div>
  );
}
export function FactoryMap(props: {
  detail: Detail | null;
  locateTarget: { id: string; request: number } | null;
  onFocus: (selection: Selection) => void;
  onSelect: (selection: Selection) => void;
  selected: Selection | null;
  onClear: () => void;
}) {
  return (
    <ReactFlowProvider>
      <MapContent {...props} />
    </ReactFlowProvider>
  );
}
