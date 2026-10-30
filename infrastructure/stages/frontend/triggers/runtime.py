"""Step 12 lowering: bind each DOM trigger to its implementation.

Compiler-owned TypeScript strings provide UI state, canonical API calls, navigation,
and event registration. The model implements each trigger's business logic; the
compiler activates only the triggers accepted or currently being implemented."""

import json

from infrastructure.stages.frontend.ui.runtime import UI_RUNTIME
from infrastructure.shared.project.entrypoints import import_path, implementation_entrypoint
from infrastructure.utils.files import save_text

TRIGGER_REGISTRY = "frontend/src/ui-triggers.ts"
API_CLIENT = "frontend/src/ui-api.ts"

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
  const entered = useRef("");
  const epoch = useRef(0);
  const route = window.location.pathname;
  const selected = pages.find(page => page.route === route);
  const pageId = selected?.id ?? "";
  const display = initialPageData(pageId, data);
  const fixture = display !== data;

  const update = (patch: Record<string, unknown>) => {
    live.current = { ...live.current, ...patch };
    setData(live.current);
  };
  const navigate = (id: string) => {
    const page = pages.find(item => item.id === id);
    if (!page) throw new Error(`Unknown page: ${id}`);
    epoch.current += 1;
    window.history.pushState({}, "", page.route);
    setNavigation(value => value + 1);
  };
  const invoke = async (trigger: Trigger, input: UiTriggerContext["input"]) => {
    const handler = handlers[trigger.id];
    if (!handler) return;
    let started = epoch.current;
    const context: UiTriggerContext = {
      get data() { return live.current; }, input,
      trigger: { id: trigger.id, source: trigger.source, event: trigger.event },
      update: patch => {
        if (started === epoch.current) update(patch);
      },
      navigate: id => {
        if (started === epoch.current) { navigate(id); started = epoch.current; }
      },
      api: (id, request) => {
        return callApi(id, request);
      },
    };
    await handler(context);
  };
  const report = (error: unknown) => { setTimeout(() => { throw error; }, 0); };
  const capture = (kind: string, event: SyntheticEvent) => {
    if (!fixture && (kind === "input" || kind === "change")) syncInput(event.target, inputBindings, update);
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
    void (async () => {
      for (const trigger of matches) {
        await invoke(trigger, input);
      }
    })().catch(report);
  };
  useEffect(() => {
    const pop = () => { epoch.current += 1; setNavigation(value => value + 1); };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (fixture || !selected) return;
    const key = `${navigation}:${pageId}`;
    if (entered.current === key) return;
    entered.current = key;
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


def sync_triggers(output, ui, design, backend, active_triggers):
    """Import fixed handle exports directly; placeholders never touch their source."""
    active = set(active_triggers)
    active.intersection_update(design["triggers"])
    save_text(output / "frontend/src/ui-runtime.ts", UI_RUNTIME)
    client = 'import type { UiApiRequest, UiApiResponse } from "./ui-runtime";\n'
    client += "const catalog: Record<string, { method: string; path: string }> = " + json.dumps({aid: {"method": api["signature"]["method"], "path": api["signature"]["path"]} for aid, api in backend["apis"].items()}) + ";\n"
    save_text(output / API_CLIENT, client + CLIENT_SOURCE)
    imports = ['import type { UiTriggerHandler } from "./ui-runtime";']
    registrations = []
    for number, tid in enumerate(sorted(active)):
        entry = implementation_entrypoint(output, "trigger", tid)
        if entry:
            imported = import_path(TRIGGER_REGISTRY, entry["path"], extension="")
            imports.append(f'import {{ {entry["export"]} as trigger{number} }} from {json.dumps(imported)};')
            registrations.append(f"  {json.dumps(tid)}: trigger{number},")
    save_text(output / TRIGGER_REGISTRY, "\n".join([*imports, "", "export const handlers: Record<string, UiTriggerHandler> = {", *registrations, "};", ""]))
    imports = ['import { useEffect, useRef, useState } from "react";',
        'import type { ComponentType, SyntheticEvent, KeyboardEvent } from "react";',
        'import type { UiPageProps, UiTriggerContext } from "./ui-runtime";',
        'import { initialPageData, syncInput } from "./ui-runtime";', 'import { callApi } from "./ui-api";', 'import { handlers } from "./ui-triggers";']
    pages, components = [], []
    for number, (pid, page) in enumerate(ui["pages"].items()):
        entry = implementation_entrypoint(output, "page", pid)
        if not entry:
            raise ValueError(f"Missing implemented page {pid}; complete step 10 first")
        imports.append(f'import {{ {entry["export"]} as Page{number} }} from {json.dumps(import_path("frontend/src/App.tsx", entry["path"], extension=""))};')
        pages.append({"id": pid, "route": page["route"], "root": page["root"]})
        components.append(f"{json.dumps(pid)}: Page{number}")
    triggers = [{"id": tid, "source": trigger["source"], "event": trigger["event"]}
        for tid, trigger in design["triggers"].items() if tid in active]
    source = "// Compiler-owned interaction state and trigger registration.\n" + "\n".join(imports) + "\n"
    source += "type Trigger = { id: string; source: string; event: string };\n"
    source += "const defaults: Record<string, unknown> = " + json.dumps({var: binding["initial"] for var, binding in ui["bindings"].items()}) + ";\n"
    source += "const inputBindings: Record<string, string[]> = " + json.dumps({uid: node["data"] for uid, node in ui["elements"].items() if "user_write" in node.get("mode", []) and node.get("data")}) + ";\n"
    source += "const pages = " + json.dumps(pages) + ";\nconst components: Record<string, ComponentType<UiPageProps>> = {" + ", ".join(components) + "};\n"
    source += "const triggers: Trigger[] = " + json.dumps(triggers) + ";\n"
    save_text(output / "frontend/src/App.tsx", source + APP_SOURCE)
