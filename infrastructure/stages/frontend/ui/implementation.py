"""Step 08: incrementally implement leaf requirements and regress accepted UI.

Each requirement owns its related UI slice. Shared pages accumulate accepted
requirements; their presence suites never demand future requirements' controls.
"""

import json
from pathlib import Path

from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.recovery import implementation_task, final_checks, complete_report
from infrastructure.stages.frontend.ui.design import owners, page_context, page_elements, requirement_ui
from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.frontend.ui.runtime import APPLICATION_ENTRYPOINTS, prepare_frontend
from infrastructure.stages.frontend.ui.testing import FrontendChecks, existence_suite, require_green, test_path
from infrastructure.shared.project.dependencies import install_dependencies
from infrastructure.utils.files import read_artifact, save_json, save_text
from infrastructure.shared.project.git import checkpoint

INSTRUCTIONS = """Implement the current requirement's UI on task.page.
The supplied page is a requirement-scoped slice: owned elements plus structural ancestors,
not the complete final page. Add only this requirement's presentation, editing and navigation.
Do not implement future requirements just because they share this page or appear in an image.
Read the existing related components before editing. Extend shared pages incrementally and
preserve accepted_element_ids and every previously accepted requirement's UI and data bindings.
Read the supplied package/configuration and actual source to use the project's technology
stack. Read related files and incrementally edit or create components inside the frontend scope, using exports, props and
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
session restoration or later requirements' workflows. Step 10 adds those interactions.
Keep one clear owner for each native form/navigation action. Later implementation must
extend that existing handler, not add another independently firing click/submit listener.

Preserve the presentation-test adapter in frontend/src/ui-runtime.ts. Call presentationData
with this page ID and a projection of the actual declared frontend values when rendering.
It supplies display-test overrides and exposes actual data keys; it does not own your state.
Do not copy display-test records into production initial values. If representative records
are needed, arrange them only in the writable presence suite's __ARC_UI_TEST_DATA__ setup.

The compiler updates presence suites for the current and previously accepted requirements,
then compiles, runs regression checks and builds; it never regenerates
App, routes, handlers or stores. Repair relevant writable sources without removing previous
behavior. Diagnose incorrect tests against original requirements and preserve meaningful
control/data-key assertions. Shared test/build infrastructure remains read-only.
"""


def implement_ui(arc_dir: Path, design: dict, model, console, report: dict, max_turns: int = 10,
        images: dict | None = None, requirement_contexts: dict | None = None) -> dict:
    """Traverse leaf requirements; implement only their UI slices on each affected page."""
    output = arc_dir.parent.resolve()
    tree = RequirementTree(read_artifact(arc_dir, "requirements.json"))
    report["requirements"] = {
        rid: {"status": "PENDING" if not tree.children[rid] else "NO_DIRECT_UI",
            "requirement": rid, "requirements": [rid], "pages": []}
        for rid in tree.requirements
    }
    report["pages"] = {
        pid: {"status": "PENDING", "requirements": owners(design, pid),
            "test_path": test_path(pid)}
        for pid in design["pages"]
    }
    report["status"] = "IMPLEMENTING"
    save_json(arc_dir / "ui_checks.json", report)
    prepare_frontend(output)
    console.show("UI TDD preparation | Dependencies", "Install workspace dependencies and Playwright Chromium. No backend is started.")
    install_dependencies(output)
    checks = FrontendChecks(output)
    checks.install_browser()
    checkpoint(output, stage="08", task="runtime", action="Prepare requirement-driven UI implementation",
        details={"requirements": tree.leaves, "pages": list(design["pages"])})
    accepted = []
    accepted_pages = []
    for number, rid in enumerate(tree.leaves, 1):
        entry = report["requirements"][rid]
        requirement = (requirement_contexts or {}).get(rid, {
            **tree.requirements[rid], "steps": [tree.steps[sid] for sid in tree.own_steps[rid]]})
        label = f"UI requirement {number}/{len(tree.leaves)} {rid}"
        console.show(label + " | Requirement and related UI", json.dumps(requirement, ensure_ascii=False, indent=2))
        entry["status"] = "PREPARING"
        entry["page_results"] = {}
        # A requirement is the rollback boundary, including all pages it touches.
        with implementation_task(output, entry, console, "08 / " + rid):
            current_design = requirement_ui(design, [rid])
            accepted_design = requirement_ui(design, accepted)
            cumulative_design = requirement_ui(design, [*accepted, rid])
            entry["pages"] = list(current_design["pages"])
            entry["test_paths"] = [test_path(pid) for pid in entry["pages"]]
            if not entry["pages"]:
                entry["status"] = "NO_UI"
                console.show(label + " | No direct UI", "No UI nodes are associated with this leaf requirement.")
            completed_pages = list(accepted_pages)
            for pid in entry["pages"]:
                entry["current_page"] = pid
                relative = test_path(pid)
                # Refresh only the current page's cumulative contract. Other accepted
                # pages keep their suites; future requirements are excluded.
                save_text(output / relative, existence_suite(cumulative_design, pid))
                files = [test_path(key) for key in dict.fromkeys([*completed_pages, pid])]
                entry["status"] = "TESTS_READY"
                save_json(arc_dir / "ui_checks.json", report)
                console.show(label + " / " + pid + " | Scoped existence tests", (output / relative).read_text(encoding="utf-8"))
                checkpoint(output, stage="08", task=rid, action="Publish cumulative UI presence suite",
                    status="TESTS_READY", details={"page": pid, "requirements": [*accepted, rid], "test_path": relative})

                def implementation_checks():
                    compiled = checks.typecheck(files)
                    if compiled["returncode"]:
                        return {"typecheck": compiled, "tests": None}
                    return {"typecheck": compiled, "tests": checks.tests(files)}

                def implementation_gate():
                    result = implementation_checks()
                    if result["typecheck"]["returncode"]:
                        raise ValueError(f"TypeScript failed: {result['typecheck']['output']}")
                    require_green(result["tests"])
                    return result

                try:
                    current = implementation_checks()
                except (ValueError, RuntimeError) as error:
                    current = {"error": str(error), "typecheck": None, "tests": None}
                if (current["tests"] and current["tests"]["returncode"] == 0
                        and current["tests"].get("passed") and not current["tests"].get("errors")
                        and not current["tests"].get("failed")):
                    agent = {"turns": 0, "checks": current}
                else:
                    entry["status"] = "IMPLEMENTING"
                    save_json(arc_dir / "ui_checks.json", report)
                    context = {
                        "requirement": {key: value for key, value in requirement.items() if key != "images"},
                        "page": page_context(current_design, pid),
                        "accepted_requirements": list(accepted),
                        "accepted_element_ids": list(page_elements(accepted_design, pid))
                            if pid in accepted_design["pages"] else [],
                        "application_entrypoints": list(APPLICATION_ENTRYPOINTS),
                        "visual_references": {iid: (images or {}).get(iid, image)
                            for iid, image in requirement.get("images", {}).items()},
                    }
                    workspace = FileTools(output, ["frontend"], requirements=[rid], stage="ui",
                        files=["frontend/src/ui-runtime.ts", *files, "frontend/package.json",
                            "frontend/tsconfig.json", "frontend/playwright.ui.config.ts", *APPLICATION_ENTRYPOINTS])
                    agent = run_file_agent(model, INSTRUCTIONS, context, workspace, implementation_gate,
                        max_turns, console, label + " / " + pid + " / Implementation", feedback=current)
                entry["page_results"][pid] = {
                    "status": "GREEN", "turns": agent["turns"],
                    "files": agent.get("files", []),
                    "checks": {key: value for key, value in agent["checks"]["tests"].items() if key != "output"},
                }
                if pid not in completed_pages:
                    completed_pages.append(pid)
                console.show(label + " / " + pid + " | GREEN", agent["checks"]["tests"]["output"])
            if entry["pages"]:
                entry["status"] = "GREEN"
                entry.pop("current_page", None)
        if entry["status"] == "GREEN":
            accepted.append(rid)
            accepted_pages = completed_pages
        elif entry["status"] == "FAILED":
            for result in entry["page_results"].values():
                result["status"] = "ROLLED_BACK"
        for pid, page in report["pages"].items():
            statuses = [report["requirements"][owner]["status"] for owner in page["requirements"]]
            results = [report["requirements"][owner]["page_results"][pid]
                for owner in page["requirements"]
                if pid in report["requirements"][owner].get("page_results", {})
                and report["requirements"][owner]["status"] == "GREEN"]
            page["files"] = sorted({path for result in results for path in result["files"]})
            page["turns"] = sum(result["turns"] for result in results)
            if results:
                page["checks"] = results[-1]["checks"]
            if not statuses:
                page["status"] = "NO_DIRECT_UI"
            elif "FAILED" in statuses:
                page["status"] = "FAILED"
            elif all(status == "GREEN" for status in statuses):
                page["status"] = "GREEN"
            else:
                page["status"] = "PENDING"
        save_json(arc_dir / "ui_checks.json", report)

    console.show("UI final verification", "All leaf requirements were attempted. Regress accepted UI and build, retaining requirement failures.")
    files = [test_path(pid) for pid in accepted_pages]
    final_commands = {"typecheck": (lambda: checks.typecheck(files), None)}
    if files:
        final_commands["tests"] = (lambda: checks.tests(files), require_green)
    final_commands["build"] = (checks.build, None)
    verification = final_checks(console, **final_commands)
    final = verification.get("tests", {}).get("result") or {}
    report["summary"] = {
        "requirements": len(tree.leaves), "accepted_requirements": len(accepted),
        "failed_requirements": sum(entry["status"] == "FAILED" for entry in report["requirements"].values()),
        "pages": sum(page["status"] == "GREEN" for page in report["pages"].values()),
        "tests": final.get("passed", 0), "failed": final.get("failed", 0),
    }
    complete_report(report, report["requirements"].values(), verification)
    save_json(arc_dir / "ui_checks.json", report)
    return report
