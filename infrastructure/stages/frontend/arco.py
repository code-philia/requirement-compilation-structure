"""Shared Arco component and callback contracts for all four frontend passes."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from infrastructure.utils.files import save_json, save_text

PACKAGE = "@arco-design/web-react"
VERSION = "2.66.18"
KNOWLEDGE_ROOT = Path(__file__).resolve().parents[2] / "knowledge/arco"
REFERENCE_ROOT = "references/arco"
GUIDE = KNOWLEDGE_ROOT / "guide.md"
REFERENCE_PATH = REFERENCE_ROOT + "/guide.md"
PROVIDER_PATH = "frontend/src/design-system.tsx"

# Callback arguments are values from the React library, not DOM event guesses.
COMPONENTS = {
    "Layout": {}, "Layout.Header": {}, "Layout.Sider": {}, "Layout.Content": {},
    "Space": {}, "Grid.Row": {}, "Grid.Col": {}, "Card": {}, "Divider": {},
    "Typography.Text": {}, "Typography.Title": {}, "Typography.Paragraph": {},
    "Button": {"onClick": ["event"]}, "Link": {"onClick": ["event"]},
    "Form": {"onSubmit": ["values"], "onValuesChange": ["changedValues", "values"], "onSubmitFailed": ["errors"]},
    "Form.Item": {}, "Input": {"onChange": ["value", "event"]},
    "Input.Password": {"onChange": ["value", "event"]},
    "Input.TextArea": {"onChange": ["value", "event"]},
    "Input.Search": {"onChange": ["value", "event"], "onSearch": ["value"]},
    "InputNumber": {"onChange": ["value"]},
    "Select": {"onChange": ["value", "option"], "onSearch": ["value", "reason"], "onVisibleChange": ["visible"]},
    "TreeSelect": {"onChange": ["value", "extra"]},
    "Cascader": {"onChange": ["value", "selectedOptions", "extra"]},
    "Checkbox": {"onChange": ["checked", "event"]},
    "Checkbox.Group": {"onChange": ["values", "event"]},
    "Radio.Group": {"onChange": ["value", "event"]},
    "Switch": {"onChange": ["checked", "event"]},
    "DatePicker": {"onChange": ["dateString", "date"]},
    "DatePicker.RangePicker": {"onChange": ["dateStrings", "dates"]},
    "TimePicker": {"onChange": ["timeString", "time"]},
    "Upload": {"onChange": ["fileList", "file"], "onRemove": ["file", "fileList"]},
    "Table": {"onChange": ["pagination", "sorter", "filters", "extra"],
              "rowSelection.onChange": ["selectedRowKeys", "selectedRows"],
              "onRow.onClick": ["event"]},
    "Pagination": {"onChange": ["pageNumber", "pageSize"], "onPageSizeChange": ["size", "current"]},
    "Modal": {"onOk": ["event"], "onCancel": [], "afterOpen": [], "afterClose": []},
    "Drawer": {"onOk": ["event"], "onCancel": ["event"], "afterOpen": [], "afterClose": []},
    "Popconfirm": {"onOk": ["event"], "onCancel": ["event"], "onVisibleChange": ["visible"]},
    "Menu": {"onClickMenuItem": ["key", "event", "keyPath"], "onClickSubMenu": ["key", "openKeys", "keyPath"]},
    "Menu.Item": {}, "Menu.SubMenu": {},
    "Tabs": {"onChange": ["key"]}, "Tabs.TabPane": {},
    "Breadcrumb": {}, "Breadcrumb.Item": {}, "Steps": {}, "Steps.Step": {},
    "Descriptions": {}, "Tag": {}, "Badge": {}, "Alert": {}, "Empty": {},
    "Spin": {}, "Result": {}, "Image": {}, "Tooltip": {},
    "List": {}, "List.Item": {}, "Tree": {"onSelect": ["selectedKeys", "extra"]},
}
HTML = {"main", "section", "div", "span", "p", "h1", "h2", "h3", "nav", "a", "img", "ul", "li", "canvas", "svg"}
HTML_CALLBACKS = {"onClick", "onChange", "onSubmit", "onKeyDown", "onBlur", "onFocus", "onScroll"}

DESIGN_INSTRUCTIONS = '''
ARCO UI DESIGN CONTRACT
Use frontend_stack as the common design-system contract. Keep semantic element.type,
component_knowledge contains BM25 candidates with use cases and examples, not mandatory
choices. Use context_request kind=component to search missing use cases or read exact
component IDs before choosing. No search hit does not prove a component is absent.
mode/data/prop and source labels. Every new/changed element additionally declares
component={"library":"arco","name":"Table"} using the supplied component catalog.
Use Arco for controls, forms, tables, menus, dialogs, feedback and layout as appropriate.
Structural/semantic HTML or a custom visualization may instead use
component={"library":"html","name":"main","reason":"semantic page landmark"}.
Do not use HTML exceptions to replace Arco buttons/inputs/selects/forms/tables.
Component selection does not add features absent from requirements. Keep native semantic
types (input/button/table/etc), not type="arco.Table". Component names are implementation
choices, not user-visible copy. Static props stay in prop; dynamic declarations stay in data.
Choose InputNumber vs Input deliberately: exact decimal text must not lose precision.
Declare loading/error/empty, selection, pagination, dialog visibility and validation data
only where required. Screenshot records are appearance evidence, not production data.
Define editable forms and popup contents as explicit semantic elements; closed popup
visibility belongs in prop.visible and declared data, not a separate route per state.
Use the same shell/menu/components across pages; preserve existing page and element IDs.
'''

IMPLEMENT_INSTRUCTIONS = '''
COMMON ARCO PITFALLS — use these facts before searching references:
- Layout grid: import { Grid } from '@arco-design/web-react'; use Grid.Row/Grid.Col.
  Row and Col are not top-level exports. Update imports AND every JSX usage together.
- Select is a composite control. Reuse selectAriaLabel(sourceLabel) from the supplied
  frontend/src/components/accessibility.tsx on Select itself. Do not label both outer
  combobox and internal input via another label/htmlFor association. Reuse requiredLabel
  for visible required marks without changing accessible names. Test by the unique
  getByRole('combobox', {name: sourceLabel, exact:true}); Form.Item text alone may not name it.
- Drawer uses visible/onCancel/footer; check its exact API before borrowing Modal-only props.
- Make coherent, focused edit batches. When changing imports, update all matching uses.

ARCO IMPLEMENTATION CONTRACT
Follow task.frontend_stack and each element.component. Use the actual installed React
Arco components, not styled HTML imitations or Ant Design/Vue component APIs. Import from
@arco-design/web-react; icons from @arco-design/web-react/icon. Preserve the shared
DesignSystemProvider/CSS in frontend/src/design-system.tsx and wrap the app in it.
The compiler mounts its own knowledge base at readonly virtual paths references/arco/.
Read references/arco/guide.md and references/arco/api/2.66.18/**/*.d.ts
for exact props when a component is unfamiliar. Keep imports/version/provider intact.
task.component_knowledge contains selected component-use references. With list_files,
search_files and read_file, inspect references/arco/components/*.md for use cases and
references/arco/api/2.66.18/**/*.d.ts for exact API definitions. Search literal property names
within a narrow component glob, then read the relevant lines. Examples are illustrative
patterns, never production fixtures. Search misses do not authorize invented props.
These paths refer to compiler-owned references outside the application. Never copy
the knowledge base or its declarations into application sources or runtime imports.
Native wrappers are allowed for landmarks, layout, labels and test selectors.
Keep data-testid on a concrete visible control/container; render popup selectors inside
the actual portal content, not an invisible placeholder. Repeated rows need row-scoped
identity/selectors; do not assume test IDs remain unique in a data table.
For Form use Form.useForm and Form.Item field/rules, letting the form own collected
values OR explicitly own controlled values; avoid two competing stores. Use label/id
associations and original accessible names. Sync asynchronous record switches/reset/cancel
with setFieldsValue/resetFields or controlled state. initialValues is not an async loader.
Arco Input/Select/InputNumber/Checkbox onChange receives value/checked, not event.target.
Button.type controls visual style; htmlType="submit" submits a form. Use one submission
owner, typically Form.onSubmit; a Modal onOk can call form.submit, but must not also post.
Modal/Drawer visibility is visible, not open. Use loading/confirmLoading and preserve
user input/error feedback on failures. Table uses data, rowKey and columns, not dataSource.
Row actions close over the actual record; server pagination/filter/sort use canonical APIs.
Upload and date conversion must honor the real backend protocol; never guess an upload
endpoint. Preserve exact decimal text if required; do not round-trip it through JS Number.
Do not add API mutations during stage 08; stage 10 extends the same component handlers.
'''

TRIGGER_INSTRUCTIONS = '''
ARCO TRIGGER BINDING CONTRACT
Use component_knowledge and optional context_request kind=component for component-specific
form, selection, popup and callback patterns. The selected source component remains canonical.
For every new/changed trigger add binding={"component":"Form","callback":"onSubmit",
"arguments":["values"]}, selecting the source element.component.name and a callback
from frontend_stack.components. Keep the existing event as the semantic user action.
For page-entry lifecycle use callback="useEffect", arguments=[] (not a component prop).
For onRow.onClick, obtain record from Table.onRow(record) closure, not from the event.
Callbacks supply component values, not a universal DOM event. Describe conversions,
clicked record identity, controlled fields and Form validation in ordered actions.
Do not implement code in this design. Do not duplicate a form submission in a button
click trigger; preserve the stage-08 handler owner. Describe how dialog confirmation
delegates to that form, when appropriate. Server-controlled paging/filter/sort must
reload through the declared API; do not page the current slice a second time locally.
Pending/validation/error/success, cancellation, stale responses and repeated clicks
must respect the source behavior and backend CSRF/idempotency contracts. Frontend role
visibility never replaces backend authorization. Only declare source-required interactions.
'''

ACCEPTANCE_INSTRUCTIONS = '''
ARCO BROWSER INTERACTIONS
Use actual accessible controls and popup content. Arco Select is not a native select:
click it then choose the visible option; do not call selectOption on its wrapper.
Scope dialogs/menus/calendar popups by visible content even when portals mount in body.
Use row-scoped controls for repeated table actions. Avoid private Arco CSS classes/DOM
depth. Business expectations still come from original requirements, not library defaults.
'''


def stack_context(elements=None):
    """Supply the same compact callback vocabulary to design, implementation and repair."""
    names = {n.get("component", {}).get("name") for n in (elements or {}).values()}
    selected = {k:v for k,v in COMPONENTS.items() if not names or k in names}
    return {"library": "arco", "package": PACKAGE, "version": VERSION, "types_root": REFERENCE_ROOT+"/api/"+VERSION,
        "knowledge_root":REFERENCE_ROOT+"/components", "design_discovery_kind":"component",
        "provider": PROVIDER_PATH, "reference": REFERENCE_PATH,
        "components": deepcopy(selected), "semantic_html": sorted(HTML)}


def validate_components(elements):
    for uid, element in elements.items():
        component = element.get("component", {})
        library, name = component.get("library"), component.get("name")
        if library == "arco" and name in COMPONENTS:
            continue
        if library == "html" and name in HTML and component.get("reason") and element.get("type") not in {"button","input","checkbox","select","form","table"}:
            continue
        raise ValueError(f"{uid}: declare an installed Arco component, or a justified semantic HTML exception")


def validate_bindings(triggers, elements):
    for tid, trigger in triggers.items():
        source = elements.get(trigger.get("source"))
        if source is None:
            raise ValueError(f"{tid}: unknown trigger source")
        component = source.get("component")
        if not component:  # Old UI artifacts remain readable; rerun 07 for component design.
            continue
        binding = trigger.get("binding", {})
        callback = binding.get("callback")
        if binding.get("component") != component["name"]:
            raise ValueError(f"{tid}: binding must match source component {component['name']}")
        arguments = binding.get("arguments")
        if callback == "useEffect":
            if trigger.get("event") not in {"mount", "unmount", "page_entry"} or arguments != []:
                raise ValueError(f"{tid}: lifecycle binding needs a lifecycle event and no callback arguments")
        elif component["library"] == "arco":
            callbacks = COMPONENTS[component["name"]]
            if callback not in callbacks or arguments != callbacks[callback]:
                raise ValueError(f"{tid}: use canonical callback/arguments from {callbacks}")
        elif callback not in HTML_CALLBACKS or arguments != ["event"]:
            raise ValueError(f"{tid}: native callback must consume a DOM event")


def configure_arco(output):
    """Upgrade standard initialized workspaces without replacing application components."""
    package_path = output / "frontend/package.json"
    package = json.loads(package_path.read_text(encoding="utf-8-sig"))
    package.setdefault("dependencies", {})[PACKAGE] = VERSION
    save_json(package_path, package)
    from infrastructure.stages.frontend.arco_knowledge import record_knowledge_reference
    record_knowledge_reference(output)
    provider = output / PROVIDER_PATH
    if not provider.exists():
        template = Path(__file__).resolve().parents[2] / "shared/project/templates" / PROVIDER_PATH
        save_text(provider, template.read_text())
    main = output / "frontend/src/main.tsx"
    source = main.read_text(encoding="utf-8-sig")
    if "./design-system" not in source:
        standard = "<React.StrictMode><App /></React.StrictMode>"
        if standard in source:
            source = 'import { DesignSystemProvider } from "./design-system";\n' + source.replace(standard, "<React.StrictMode><DesignSystemProvider><App /></DesignSystemProvider></React.StrictMode>")
        elif PACKAGE + "/dist/css/arco.css" not in source:
            # Custom roots are integrated by the implementation agent, never regex-rewritten.
            source = 'import "@arco-design/web-react/dist/css/arco.css";\n' + source
        save_text(main, source)


def arco_references():
    """Return a compiler-owned readonly reference mount, never an app directory."""
    if not GUIDE.is_file() or not (KNOWLEDGE_ROOT / "api" / VERSION / "manifest.json").is_file():
        raise ValueError("Missing compiler Arco knowledge bundle; restore infrastructure/knowledge/arco")
    from infrastructure.stages.frontend.arco_knowledge import component_records
    index = KNOWLEDGE_ROOT / "components/index.json"
    if not index.is_file() or json.loads(index.read_text()) != component_records():
        raise ValueError("Arco component guides are stale; run python -m infrastructure.stages.frontend.arco_knowledge --rebuild-guides in plusplus")
    return {REFERENCE_ROOT: KNOWLEDGE_ROOT}


def validate_component_types(output):
    """Verify the installed library against compiler-owned API references without copying."""
    root = next((p for p in (output / "node_modules" / PACKAGE, output / "frontend/node_modules" / PACKAGE)
        if (p / "package.json").is_file()), None)
    if root is None:
        raise ValueError("Install frontend dependencies before validating the Arco version")
    version = json.loads((root / "package.json").read_text())["version"]
    if version != VERSION:
        raise ValueError(f"Expected {PACKAGE}@{VERSION}, found {version}; reinstall frontend dependencies")
    arco_references()
    manifest_path = KNOWLEDGE_ROOT / "api" / VERSION / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != version or manifest.get("package") != PACKAGE:
        raise ValueError("Compiler Arco API snapshot disagrees with the installed package")
    save_json(output / ".arc/arco_types.json", {"package": PACKAGE, "version":version,
        "reference":REFERENCE_ROOT+"/api/"+VERSION,
        "manifest_sha256":hashlib.sha256(manifest_path.read_bytes()).hexdigest()})
