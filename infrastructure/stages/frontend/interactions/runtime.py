"""Step 12 lowering: bind DOM triggers to model-selected event functions.

Compiler-owned TypeScript strings provide UI state, guarded API calls, navigation,
and event registration. The model implements each event's business logic; the
compiler activates only the events accepted or currently being implemented."""

import json

from infrastructure.stages.frontend.ui.design import owners
from infrastructure.stages.frontend.ui.runtime import OWNED, UI_RUNTIME
from infrastructure.stages.frontend.interactions.design import api_ids, event_ids
from infrastructure.shared.project.entrypoints import import_path, resolve_entrypoint
from infrastructure.utils.files import save_text

EVENT_REGISTRY = "frontend/src/ui-events.ts"
API_CLIENT = "frontend/src/ui-api.ts"
PROTECTED = (*OWNED, EVENT_REGISTRY, API_CLIENT)

EVENT_TYPES = '''
export interface UiApiRequest {
  params?: Record<string, unknown>; query?: Record<string, unknown>;
  body?: Record<string, unknown>; headers?: Record<string, string>;
  credentials?: RequestCredentials;
}
export interface UiApiResponse { status: number; body: unknown; headers: Record<string, string> }
export interface UiEventContext {
  readonly data: Readonly<Record<string, unknown>>;
  readonly input: { value?: string; checked?: boolean; key?: string };
  readonly trigger: { id: string; source: string; event: string; guard: string | null };
  update(patch: Record<string, unknown>): void;
  navigate(pageId: string): void;
  api(apiId: string, request?: UiApiRequest): Promise<UiApiResponse>;
}
export type UiEventHandler = (context: UiEventContext) => void | Promise<void>;
'''

CLIENT_SOURCE = '''
export async function callApi(apiId: string, request: UiApiRequest = {}): Promise<UiApiResponse> {
  const signature = catalog[apiId];
  if (!signature) throw new Error(`Unknown backend API: ${apiId}`);
  const path = signature.path.replace(/:([A-Za-z_][A-Za-z0-9_]*)/g, (_, key: string) => {
    if (request.params?.[key] == null) throw new Error(`Missing route parameter: ${key}`);
    return encodeURIComponent(String(request.params[key]));
  });
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(request.query ?? {})) {
    if (value == null) continue;
    for (const item of Array.isArray(value) ? value : [value]) url.searchParams.append(key, String(item));
  }
  const headers = new Headers(request.headers);
  headers.delete("cookie"); headers.delete("set-cookie");
  const init: RequestInit = { method: signature.method, credentials: request.credentials ?? "same-origin", headers };
  if (signature.method !== "GET") {
    headers.set("content-type", "application/json");
    init.body = JSON.stringify(request.body ?? {});
  }
  const response = await fetch(url, init);
  const body = response.status === 204 ? null : await response.json();
  return { status: response.status, body, headers: Object.fromEntries(response.headers.entries()) };
}
'''

APP_SOURCE = '''
export function App() {
  const [data, setData] = useState<Record<string, unknown>>(() => ({ ...defaults }));
  const live = useRef(data);
  const [navigation, setNavigation] = useState(0);
  const entered = useRef(new Set<string>());
  const route = window.location.pathname;
  const selected = pages.find(page => page.route === route);
  const pageId = selected?.id ?? "";
  const display = initialPageData(pageId, data);
  const fixture = display !== data;

  const update = (patch: Record<string, unknown>) => {
    for (const key of Object.keys(patch)) if (!(key in defaults)) throw new Error(`Unknown frontend variable: ${key}`);
    live.current = { ...live.current, ...patch };
    setData(live.current);
  };
  const navigate = (id: string) => {
    const page = pages.find(item => item.id === id);
    if (!page) throw new Error(`Unknown page: ${id}`);
    window.history.pushState({}, "", page.route);
    setNavigation(value => value + 1);
  };
  const invoke = async (trigger: Trigger, input: UiEventContext["input"]) => {
    const handler = handlers[trigger.action];
    if (!handler) return;
    const effect = effects[trigger.action];
    const context: UiEventContext = {
      get data() { return live.current; }, input,
      trigger: { id: trigger.id, source: trigger.source, event: trigger.event, guard: trigger.guard },
      update: patch => {
        if (Object.keys(patch).some(key => !effect.write.includes(key))) throw new Error(`Undeclared event write: ${trigger.action}`);
        update(patch);
      },
      navigate: id => {
        if (!effect.pages.includes(id)) throw new Error(`Undeclared event navigation: ${trigger.action}`);
        navigate(id);
      },
      api: (id, request) => {
        if (!effect.apis.includes(id)) throw new Error(`Undeclared event API: ${trigger.action}`);
        return callApi(id, request);
      },
    };
    await handler(context);
  };
  const report = (error: unknown) => { setTimeout(() => { throw error; }, 0); };
  const capture = (kind: string, event: SyntheticEvent) => {
    if (kind === "submit") event.preventDefault();
    if (fixture) return;
    let target = event.target instanceof Element ? event.target : null;
    const sources: string[] = [];
    while (target && target !== event.currentTarget) {
      const id = target.getAttribute("data-testid");
      if (id) sources.push(id);
      target = target.parentElement;
    }
    const matches = sources.flatMap(source => triggers.filter(trigger => trigger.source === source && trigger.event === kind));
    if (matches.length && ["click", "submit", "keydown"].includes(kind)) event.preventDefault();
    const control = event.target as HTMLInputElement;
    const input = { value: control.value, checked: control.checked, key: (event as KeyboardEvent).key };
    const called = new Set<string>();
    void (async () => {
      for (const trigger of matches) {
        if (called.has(trigger.action)) continue;
        called.add(trigger.action);
        await invoke(trigger, input);
      }
    })().catch(report);
  };
  useEffect(() => {
    const pop = () => setNavigation(value => value + 1);
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (fixture || !selected) return;
    const key = `${navigation}:${pageId}`;
    if (entered.current.has(key)) return;
    entered.current.add(key);
    void (async () => {
      for (const trigger of triggers) if (trigger.source === selected.root && trigger.event === "mount") await invoke(trigger, {});
    })().catch(report);
  }, [navigation, pageId, fixture]);
  const Component = selected ? components[selected.id] : undefined;
  return <div onClickCapture={event => capture("click", event)} onChangeCapture={event => capture("change", event)}
    onInputCapture={event => capture("input", event)} onSubmitCapture={event => capture("submit", event)}
    onKeyDownCapture={event => capture("keydown", event)} onKeyUpCapture={event => capture("keyup", event)}>
    {Component ? <Component key={pageId} data={display} /> : <main><h1>Page not found</h1></main>}
  </div>;
}
'''


def event_module(eid):
    """Return the stable file-index module ID used to associate an event with its implementation."""
    return f"frontend:event:{eid}"


def sync_interactions(output, ui, interactions, backend, index, active_events):
    """Import model-selected functions directly; placeholders never touch their source."""
    active = set(active_events)
    if active - set(interactions["events"]):
        raise ValueError("Unknown active interaction event")
    save_text(output / "frontend/src/ui-runtime.ts", UI_RUNTIME + EVENT_TYPES)
    client = 'import type { UiApiRequest, UiApiResponse } from "./ui-runtime";\n'
    client += "const catalog: Record<string, { method: string; path: string }> = " + json.dumps({aid: {"method": api["signature"]["method"], "path": api["signature"]["path"]} for aid, api in backend["apis"].items()}) + ";\n"
    save_text(output / API_CLIENT, client + CLIENT_SOURCE)
    imports = ['import type { UiEventHandler } from "./ui-runtime";']
    registrations = []
    for number, eid in enumerate(sorted(active)):
        module = event_module(eid)
        entry = resolve_entrypoint(output, index, module, "frontend/src", (".ts", ".tsx"), PROTECTED)
        if entry:
            imported = import_path(EVENT_REGISTRY, entry["path"], extension="")
            imports.append(f'import {{ {entry["export"]} as event{number} }} from {json.dumps(imported)};')
            registrations.append(f"  {json.dumps(eid)}: event{number},")
        uses = [rid for rid, tids in interactions["requirements"].items() if eid in event_ids(interactions, tids)]
        paths = [EVENT_REGISTRY, API_CLIENT, "frontend/src/App.tsx", "frontend/src/ui-runtime.ts"]
        if entry:
            paths.append(entry["path"])
        index.record(paths, uses, module)
    save_text(output / EVENT_REGISTRY, "\n".join([*imports, "", "export const handlers: Record<string, UiEventHandler> = {", *registrations, "};", ""]))
    imports = ['import { useEffect, useRef, useState } from "react";',
        'import type { ComponentType, SyntheticEvent, KeyboardEvent } from "react";',
        'import type { UiPageProps, UiEventContext } from "./ui-runtime";',
        'import { initialPageData } from "./ui-runtime";', 'import { callApi } from "./ui-api";', 'import { handlers } from "./ui-events";']
    pages, components = [], []
    for number, (pid, page) in enumerate(ui["pages"].items()):
        entry = resolve_entrypoint(output, index, f"frontend:page:{pid}", "frontend/src", (".ts", ".tsx"), PROTECTED)
        if not entry:
            raise ValueError(f"Missing implemented page {pid}; complete step 10 first")
        imports.append(f'import {{ {entry["export"]} as Page{number} }} from {json.dumps(import_path("frontend/src/App.tsx", entry["path"], extension=""))};')
        pages.append({"id": pid, "route": page["route"], "root": page["root"]})
        components.append(f"{json.dumps(pid)}: Page{number}")
        index.record(["frontend/src/App.tsx"], owners(ui, pid), f"frontend:page:{pid}")
    effects = {eid: {"write": event["write"], "apis": sorted(api_ids(event)),
        "pages": [action["page"] for action in event["actions"] if action["kind"] == "navigate"]} for eid, event in interactions["events"].items() if eid in active}
    triggers = [{"id": tid, **{key: trigger[key] for key in ("source", "event", "guard", "action")}}
        for tid, trigger in interactions["triggers"].items() if trigger["action"] in active]
    source = "// Compiler-owned interaction state and trigger registration.\n" + "\n".join(imports) + "\n"
    source += "type Trigger = { id: string; source: string; event: string; guard: string | null; action: string };\n"
    source += "const defaults: Record<string, unknown> = " + json.dumps({var: binding["initial"] for var, binding in ui["bindings"].items()}) + ";\n"
    source += "const pages = " + json.dumps(pages) + ";\nconst components: Record<string, ComponentType<UiPageProps>> = {" + ", ".join(components) + "};\n"
    source += "const triggers: Trigger[] = " + json.dumps(triggers) + ";\n"
    source += "const effects: Record<string, { write: string[]; apis: string[]; pages: string[] }> = " + json.dumps(effects) + ";\n"
    save_text(output / "frontend/src/App.tsx", source + APP_SOURCE)
