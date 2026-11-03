"""Step 10 orchestration: UI existence tests -> component repair -> regression.

Tests are rendered deterministically from the complete step 09 design. A shared
file agent implements one page at a time, with previously accepted page tests
included in its checks. Application integration is model-owned; shared test tools remain read-only."""

import json
from pathlib import Path

from infrastructure.shared.agent.context import SourceFiles
from infrastructure.shared.agent.discovery import project_index
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.shared.project.entrypoints import selected_path
from infrastructure.stages.frontend.ui.design import owners, page_context
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, existence_suite, require_green, test_path
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import save_json, save_text
from infrastructure.shared.project.git import checkpoint

INSTRUCTIONS = """Implement the current page from its UI/data reference design and requirements.
Read the supplied package/configuration and actual source to use the project's technology
stack. Create task.file_target or repair implementation_path, using exports, props and
state appropriate to the actual components. The design is a
reference prototype, not a fixed executable host or mandatory component API.

You own the application entrypoints, routing, component composition and state bindings.
Read task.application_entrypoints as needed and incrementally connect this page to the
existing application. Preserve all earlier routes/pages/exports and their behavior; never
rebuild the application with only this page. Support parameterized routes using the actual
router/framework or appropriate application code. Do not require a dynamic route pattern
to equal the literal browser pathname. Route metadata describes intended navigation.

Choose component-local state, a shared store or another appropriate mechanism. Initialize
safe unloaded values and explicit requirement defaults in application code; never manufacture
loaded business objects from reference images. element.data declares variables, types and
constraints, not a global store or an instruction to write one input value into every variable.
Use framework-native bindings/events. Controlled or uncontrolled fields are implementation
choices, but actual state changes must reliably update displayed/editable values, including
asynchronous loading and cancel/reset. Keep the input's value separate from visibility,
validation and other dependent state. Do not rely on compiler event capture or automatic
input synchronization; no such host is generated.

Render real layout, labels, controls and conditional content with original text and stable
data-testid=ELEMENT_ID selectors. Use the installed dependencies and configured styles.
Preserve every explicitly required UI name and role verbatim, including language, spelling
and case. Do not rename "Name" to "Shelf name", translate captions, or combine aliases.
Keep visible labels and computed accessible names consistent: associate labels correctly,
and do not override them with a different aria-label or concatenate unrelated text through
aria-labelledby. Use exact placeholders only when the requirement specifies placeholders;
an accessible field name alone does not prescribe a placeholder or HTML implementation.
Apply this to buttons, links, headings and named regions as well as form fields. If the
generated design or reference image conflicts with an explicit original UI contract, follow
the original requirement and explain the discrepancy. Unspecified wording is an implementation
choice; business object names still come from actual data, not reference examples.
This stage builds presentation, native editing and navigation, not business API operations,
session restoration or later requirements' workflows. Step 12 adds those interactions.
Keep one clear owner for each native form/navigation action. Later implementation must
extend that existing handler, not add another independently firing click/submit listener.

Preserve the presentation-test adapter in frontend/src/ui-runtime.ts. Call presentationData
with this page ID and a projection of the actual declared frontend values when rendering.
It supplies display-test overrides and exposes actual data keys; it does not own your state.
Do not copy display-test records into production initial values. If representative records
are needed, arrange them only in the writable presence suite's __ARC_UI_TEST_DATA__ setup.

The compiler compiles, runs current/accepted presence tests and builds; it never regenerates
App, routes, handlers or stores. Repair relevant writable sources without removing previous
behavior. Diagnose incorrect tests against original requirements and preserve meaningful
control/data-key assertions. Shared test/build infrastructure remains read-only.
"""


def implement_ui(arc_dir: Path, design: dict, model, console, report: dict, max_turns: int = 10,
        images: dict | None = None, requirement_contexts: dict | None = None) -> dict:
    """Implement the complete saved UI/data design through component-existence TDD.

    Prepare the project and browser, generate initial presence tests, then
    repair model-selected page components until checks pass. Update the caller's
    report; application integration remains model-owned."""
    output = arc_dir.parent.resolve()
    prepare_frontend(output)
    console.show("UI TDD preparation | Dependencies", "Install workspace dependencies and Playwright Chromium. No backend is started.")
    install_dependencies(output)
    checks = FrontendChecks(output)
    checks.install_browser()
    checkpoint(output, stage="10", task="runtime", action="Prepare presentation adapter and browser tests",
        details={"pages": list(design["pages"])})
    accepted = []
    selection = SourceFiles(output, design)
    context_index = project_index(output,
        kinds=("page", "ui_element", "ui_data", "requirement", "test_requirement", "file"),
        file_roots=("frontend/src", "frontend/tests"))
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "ui_checks.json", report)
    for number, pid in enumerate(design["pages"], 1):
        uses = owners(design, pid)
        relative = test_path(pid)
        suite = existence_suite(design, pid)
        if not (output / relative).is_file():
            save_text(output / relative, suite)
        report["pages"][pid] = {"status": "TESTS_READY", "requirements": uses, "test_path": relative}
        save_json(arc_dir / "ui_checks.json", report)
        label = f"UI {number}/{len(design['pages'])} {pid}"
        checkpoint(output, stage="10", task=pid, action="Publish UI existence suite before implementation",
            status="TESTS_READY", details={"test_path": relative, "requirements": uses})
        console.show(label + " | Existence tests before implementation", (output / relative).read_text(encoding="utf-8"))
        files = [test_path(key) for key in [*accepted, pid]]

        def implementation_checks():
            """Check model-owned application sources and selected page tests."""
            compiled = checks.typecheck(files)
            if compiled["returncode"]:
                return {"typecheck": compiled, "tests": None}
            tested = checks.tests(files)
            return {"typecheck": compiled, "tests": tested}

        def implementation_gate():
            """Accept the current page only after compilation and presence tests pass."""
            result = implementation_checks()
            for kind in ("typecheck",):
                if result[kind] and result[kind]["returncode"]:
                    raise ValueError(f"{kind} failed: {result[kind]['output']}")
            require_green(result["tests"])
            return result

        with implementation_task(output, report["pages"][pid], console, "10 / " + pid):
            # Compile tests separately before deciding whether browser failure is RED.
            try:
                current = implementation_checks()
            except (ValueError, RuntimeError) as error:
                current = {"error": str(error), "typecheck": None, "tests": None}
            if current["tests"] is not None:
                report["pages"][pid]["status"] = "GREEN" if not current["tests"]["returncode"] else "REPAIR_REQUIRED"
                console.show(label + " | " + report["pages"][pid]["status"], current["tests"]["output"])
            save_json(arc_dir / "ui_checks.json", report)
            if current["tests"] and current["tests"]["returncode"] == 0:
                agent = {"turns": 0, "checks": current}
            else:
                context = {"page": page_context(design, pid), "application_entrypoints": list(APPLICATION_ENTRYPOINTS),
                    "requirements": [{key: value for key, value in (requirement_contexts or {}).get(rid, {"id": rid}).items() if key != "images"}
                        for rid in uses],
                    "visual_references": {iid: (images or {})[iid] for iid in design["pages"][pid]["images"]},
                    "implementation_path": selected_path(output, "page", pid)}
                workspace = selection.workspace(target=("page", pid),
                    references=["frontend/src/ui-runtime.ts", relative, "frontend/package.json",
                        "frontend/tsconfig.json", "frontend/playwright.ui.config.ts", *APPLICATION_ENTRYPOINTS])
                report["pages"][pid]["status"] = "IMPLEMENTING"
                agent = run_file_agent(model, INSTRUCTIONS, context, workspace, implementation_gate,
                    max_turns, console, label + " / Implementation", feedback=current,
                    feedback_filter=lambda value: selection.feedback(workspace, value), context_index=context_index)
            accepted.append(pid)
            report["pages"][pid].update({"status": "GREEN", "turns": agent["turns"],
                "implementation_path": selected_path(output, "page", pid),
                "checks": {key: value for key, value in agent["checks"]["tests"].items() if key != "output"}})
            save_json(arc_dir / "ui_checks.json", report)
            console.show(label + " | GREEN", agent["checks"]["tests"]["output"])
        save_json(arc_dir / "ui_checks.json", report)
    console.show("UI final verification", "All page tasks were attempted. Run display regression and build, retaining any failures.")
    files = [test_path(pid) for pid in design["pages"]]
    verification = final_checks(console,
        typecheck=(lambda: checks.typecheck(files), None),
        tests=(lambda: checks.tests(files), require_green),
        build=(checks.build, None))
    final = verification["tests"].get("result") or {}
    report["summary"] = {"pages": len(accepted), "tests": final.get("passed", 0), "failed": final.get("failed", 0)}
    complete_report(report, report["pages"].values(), verification)
    save_json(arc_dir / "ui_checks.json", report)
    return report
