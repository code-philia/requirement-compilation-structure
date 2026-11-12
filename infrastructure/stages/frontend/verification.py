"""Shared real-browser, source coverage and build acceptance for frontend construction."""

from infrastructure.shared.agent.recovery import final_checks, complete_report
from infrastructure.stages.backend.runtime import api_test_paths
from infrastructure.stages.backend.testing import BackendChecks, require_green as require_backend_green
from infrastructure.stages.frontend.triggers.diagnosis import source_coverage
from infrastructure.stages.frontend.triggers.testing import E2EChecks, test_path
from infrastructure.stages.frontend.ui.testing import FrontendChecks, require_green, test_path as ui_test_path
from infrastructure.utils.files import read_artifact, save_json
import re


def navigation_evidence(ui, executed):
    records = executed.get('navigation',[])
    declared = {item['route'] for item in ui.get('pages',{}).values()
        if isinstance(item.get('route'),str) and item['route'].startswith('/')}
    without_evidence = []
    for route in sorted(declared):
        pattern = re.escape(route)
        pattern = re.sub(r':[A-Za-z_][A-Za-z0-9_]*',r'[^/]+',pattern)
        pattern = re.sub(r'\\\{[^{}]+\\\}',r'[^/]+',pattern)
        if not any(re.fullmatch(pattern,row.get('to','')) for row in records):
            without_evidence.append(route)
    return {'click_navigation':records,'declared_routes_without_recorded_click_evidence':without_evidence,
        'policy':'Advisory evidence from completed navigation helper assertions, not a new stage gate. '
            'Direct URL access or visible menu text alone does not certify reachability. '
            'Manual browser navigation tests may exist without helper annotations.'}


def require_stable_acceptance(result):
    require_green(result)
    if result.get("skipped") or result.get("flaky"):
        raise ValueError("Requirement acceptance includes skipped or unstable tests")


def original_source_requirement_dependencies(raw, rid):
    if raw.get('id') == rid:
        return raw.get('dependencies', [])
    for child in raw.get('children', []) or []:
        found = original_source_requirement_dependencies(child, rid)
        if found is not None:
            return found
    return None


def verify_frontend(arc_dir, tree, backend, ui, console, report, *, checks=None):
    """Check current files after the requirement implementation pass."""
    output = arc_dir.parent.resolve()
    checks = checks if checks is not None else E2EChecks(output)
    ui_checks = FrontendChecks(output)
    console.show("Final frontend verification", "Run requirement acceptance suites, UI regression, backend checks and builds against current sources.")
    files = [test_path(rid) for rid in tree.leaves
        if (output / test_path(rid)).is_file()]
    ui_files = [] if ui.get("outline") else [ui_test_path(pid) for pid in ui["pages"] if (output / ui_test_path(pid)).is_file()]
    api_checks = BackendChecks(output)
    api_files = api_test_paths(output, backend["apis"])
    verification = final_checks(console,
        typecheck=(lambda: checks.typecheck(files), None),
        e2e=(lambda: checks.tests(files), require_stable_acceptance)) if files else final_checks(console,
            typecheck=(lambda: checks.typecheck([]), None))
    if ui_files:
        verification.update(final_checks(console, ui=(lambda: ui_checks.tests(ui_files), require_green)))
    verification.update(final_checks(console,
        backend_typecheck=(api_checks.typecheck, None),
        backend_tests=(lambda: api_checks.tests(api_files), require_backend_green if api_files else None),
        build=(checks.build, None)))
    raw = read_artifact(arc_dir, 'requirements.json')
    executed = verification.get('e2e', {}).get('result') or {}
    report['navigation_evidence'] = navigation_evidence(ui,executed)
    coverage = source_coverage(tree, raw, report, output, test_path, executed)
    verification['source_coverage'] = coverage
    failed_requirements = [rid for rid in tree.leaves
        if report['requirements'].get(rid, {}).get('status') not in {'GREEN', 'NO_UI'}]
    verification['requirement_completion'] = {'status': 'FAILED' if failed_requirements else 'GREEN',
        'failed_requirements': failed_requirements}
    incomplete_dependencies = [
        {'requirement': rid, 'dependency': dep,
         'dependency_status': report['requirements'].get(dep, {}).get('status', 'UNKNOWN')}
        for rid in tree.leaves if report['requirements'].get(rid, {}).get('status') == 'GREEN'
        for dep in (original_source_requirement_dependencies(raw, rid) or [])
        if dep in tree.leaves and report['requirements'].get(dep, {}).get('status') not in {'GREEN', 'NO_UI'}]
    verification['dependency_chain'] = {'status': 'FAILED' if incomplete_dependencies else 'GREEN',
        'unverified_edges': incomplete_dependencies,
        'policy': 'An isolated scenario pass does not certify a failed dependency implementation.'}
    final = verification.get("e2e", {}).get("result") or {}
    ui_final = verification.get("ui", {}).get("result") or {}
    accepted = [rid for rid in tree.leaves if report["requirements"].get(rid, {}).get("status") == "GREEN"]
    implemented = {tid for rid in accepted for tid in report["requirements"][rid].get("target_triggers", [])}
    report["summary"] = {"requirements": len(accepted), "triggers": len(implemented),
        "e2e_tests": final.get("passed", 0), "ui_tests": ui_final.get("passed", 0),
        "failed": max(len(failed_requirements), len(coverage['missing_requirements']),
                      int(bool(coverage['missing_scenarios'])), final.get("failed", 0) + ui_final.get("failed", 0)),
        "failed_requirements": len(failed_requirements),
        "failed_tests": final.get("failed", 0) + ui_final.get("failed", 0),
        "missing_scenarios": len(coverage['missing_scenarios']),
        "missing_test_requirements": len(coverage['missing_requirements']),
        "unverified_dependency_edges": len(incomplete_dependencies)}
    complete_report(report, report["requirements"].values(), verification)
    save_json(arc_dir / "frontend_e2e.json", report)
    return report
