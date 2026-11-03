import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Panel,
  PanelGroup,
  PanelResizeHandle,
  type ImperativePanelHandle,
} from "react-resizable-panels";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import {
  Boxes,
  LoaderCircle,
  PanelLeftClose,
  PanelRightClose,
  X,
} from "lucide-react";
import {
  api,
  type Config,
  type Detail,
  type Run,
  type Selection,
} from "./types";
import { RunControls } from "./components/RunControls";
import { FactoryMap } from "./components/FactoryMap";
import { RunInspector } from "./components/RunInspector";
import { NodeDetails } from "./components/Details";
const CompareRuns = lazy(() => import("./components/CompareRuns"));

export default function App() {
  const [config, setConfig] = useState<Config | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [total, setTotal] = useState(0);
  const [identity, setIdentity] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get("run"),
  );
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(60);
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [compare, setCompare] = useState(false);
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const latest = useRef(0);
  const leftPanel = useRef<ImperativePanelHandle>(null);
  const rightPanel = useRef<ImperativePanelHandle>(null);
  const showError = useCallback((message: string) => setError(message), []);
  const refreshConfig = useCallback(
    () =>
      api<Config>("/config")
        .then(setConfig)
        .catch((error) => showError(error.message)),
    [showError],
  );
  const refreshRuns = useCallback(
    () =>
      api<{ items: Run[]; total: number }>(
        `/runs?limit=${limit}&search=${encodeURIComponent(search)}`,
      )
        .then((data) => {
          setRuns(data.items);
          setTotal(data.total);
        })
        .catch((error) => showError(error.message)),
    [search, limit, showError],
  );
  useEffect(() => {
    refreshConfig();
  }, [refreshConfig]);
  useEffect(() => {
    const timer = setTimeout(refreshRuns, 200);
    const interval = setInterval(() => {
      refreshRuns();
      refreshConfig();
    }, 6000);
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [refreshRuns, refreshConfig]);
  const refreshDetail = useCallback(async () => {
    if (!identity) return;
    const request = ++latest.current;
    setLoading(true);
    try {
      const value = await api<Detail>("/runs/" + identity);
      if (request === latest.current) setDetail(value);
    } catch (error) {
      if (request === latest.current) showError((error as Error).message);
    } finally {
      if (request === latest.current) setLoading(false);
    }
  }, [identity, showError]);
  useEffect(() => {
    setSelected(null);
    setDetail(null);
    const url = new URL(window.location.href);
    if (identity) url.searchParams.set("run", identity);
    else url.searchParams.delete("run");
    window.history.replaceState(null, "", url);
    refreshDetail();
  }, [identity]);
  useEffect(() => {
    if (!identity) {
      setConnected(false);
      return;
    }
    const source = new EventSource("/api/runs/" + identity + "/events");
    let debounce: ReturnType<typeof setTimeout>;
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("update", () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        refreshDetail();
        refreshConfig();
      }, 150);
    });
    return () => {
      latest.current++;
      clearTimeout(debounce);
      source.close();
    };
  }, [identity, refreshDetail, refreshConfig]);
  useEffect(() => {
    if (config?.active.length && !identity) setIdentity(config.active[0]);
  }, [config?.active, identity]);
  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => setError(""), 10000);
    return () => clearTimeout(timer);
  }, [error]);
  function start(id: string) {
    setIdentity(id);
    refreshRuns();
    refreshConfig();
    rightPanel.current?.expand();
  }
  const activeId = config?.active[0] || null;
  return (
    <MotionConfig reducedMotion="user">
      <div className="app-shell">
        <header className="app-header">
          <a
            className="app-logo"
            href="/"
            onClick={(event) => {
              event.preventDefault();
              setIdentity(null);
              setDetail(null);
            }}
          >
            <span className="logo-mark">
              <Boxes size={21} />
            </span>
            <div>
              <strong>
                REQUIREMENT <span>FACTORY</span>
              </strong>
              <small>需求编译工厂</small>
            </div>
          </a>
          <div className="header-center">
            <span className="header-divider" />
            <span className="workspace-title">
              {detail?.run.name || "你的下一座软件工厂"}
            </span>
            {activeId && (
              <span className="live-badge">
                <span className="pulse-dot" />
                COMPILING
              </span>
            )}
          </div>
          <div className="header-actions">
            <span className="local-indicator">
              <i />
              本地运行
            </span>
            <button
              className="icon-button"
              title={leftOpen ? "收起控制台" : "展开控制台"}
              onClick={() =>
                leftOpen
                  ? leftPanel.current?.collapse()
                  : leftPanel.current?.expand()
              }
            >
              <PanelLeftClose size={16} />
            </button>
            <button
              className="icon-button"
              title={rightOpen ? "收起运行观察" : "展开运行观察"}
              onClick={() =>
                rightOpen
                  ? rightPanel.current?.collapse()
                  : rightPanel.current?.expand()
              }
            >
              <PanelRightClose size={16} />
            </button>
          </div>
        </header>
        <div className="workspace">
          <PanelGroup direction="horizontal" autoSaveId="factory-panels">
            <Panel
              ref={leftPanel}
              collapsible
              collapsedSize={0}
              onCollapse={() => setLeftOpen(false)}
              onExpand={() => setLeftOpen(true)}
              id="controls"
              order={1}
              defaultSize={18}
              minSize={17}
              maxSize={30}
            >
              <RunControls
                config={config}
                activeId={activeId}
                detail={detail}
                onStart={start}
                onError={showError}
                onRefresh={() => {
                  refreshConfig();
                  refreshDetail();
                  refreshRuns();
                }}
              />
            </Panel>
            <PanelResizeHandle className="resize-handle" />
            <Panel id="canvas" order={2} defaultSize={56} minSize={28}>
              <FactoryMap
                detail={detail}
                selected={selected}
                onClear={() => setSelected(null)}
                onSelect={(selection) => {
                  setSelected(selection);
                  setDetailOpen(true);
                }}
              />
            </Panel>

            <PanelResizeHandle className="resize-handle" />
            <Panel
              ref={rightPanel}
              collapsible
              collapsedSize={0}
              onCollapse={() => setRightOpen(false)}
              onExpand={() => setRightOpen(true)}
              id="inspector"
              order={3}
              defaultSize={26}
              minSize={22}
              maxSize={42}
            >
              <RunInspector
                detail={detail}
                runs={runs}
                total={total}
                onChoose={setIdentity}
                search={search}
                onSearch={(value) => {
                  setSearch(value);
                  setLimit(60);
                }}
                onMore={() => setLimit(limit + 40)}
                onCompare={() => setCompare(true)}
                connected={connected}
                loading={loading}
                onError={showError}
              />
            </Panel>
          </PanelGroup>
        </div>
        <NodeDetails
          key={selected?.id}
          selection={detailOpen ? selected : null}
          detail={detail}
          onClose={() => setDetailOpen(false)}
          onNavigate={setSelected}
        />
        {compare && (
          <Suspense
            fallback={
              <div className="loading-overlay">
                <LoaderCircle className="spin" />
                正在打开运行对比…
              </div>
            }
          >
            <CompareRuns
              runs={runs}
              currentId={identity || undefined}
              onClose={() => setCompare(false)}
              onInspect={(id) => {
                setIdentity(id);
                setCompare(false);
              }}
            />
          </Suspense>
        )}
        <AnimatePresence>
          {error && (
            <motion.div
              className="toast-error"
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 10, opacity: 0 }}
              role="alert"
            >
              <span>{error}</span>
              <button aria-label="关闭提示" onClick={() => setError("")}>
                <X size={15} />
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}
