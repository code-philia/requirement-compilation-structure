"""Frontend inputs retain image/page evidence alongside normalized requirements."""

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.requirements.images import build_image_catalog
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.stages.requirements.data import load_data, data_context
from infrastructure.stages.requirements.ui_evidence import compile_ui_evidence, ui_context
from infrastructure.stages.frontend.arco import stack_context


def load_ui_design(arc_dir, tree):
    from infrastructure.stages.frontend.ui.design import normalize_design
    return normalize_design(read_artifact(arc_dir, "ui_design.json"), tree)


def load_ui_context(arc_dir, input_dir):
    """Load image evidence and optional shared backend semantics for frontend generation."""
    raw = read_artifact(arc_dir, "requirements.json")
    tree = RequirementTree(raw)
    tree.validation_data = load_data(arc_dir)
    tree.ui_evidence = compile_ui_evidence(raw, input_dir)
    save_json(arc_dir / "ui_evidence.json", tree.ui_evidence)
    if (arc_dir / "backend_evidence.json").is_file():
        tree.backend_evidence = read_artifact(arc_dir,"backend_evidence.json")
        tree.backend_foundation = read_artifact(arc_dir,"backend_foundation.json")
    analysis = read_artifact(arc_dir, "visual_analysis.json") if (arc_dir / "visual_analysis.json").is_file() else {}
    catalog = build_image_catalog(raw, input_dir)
    source_path = arc_dir / "visual_analysis_sources.json"
    sources = read_artifact(arc_dir, source_path.name) if source_path.is_file() else {}
    if not isinstance(analysis, dict):
        analysis = {}
    if not isinstance(sources, dict):
        sources = {}
    images = {}
    for iid, image in catalog["images"].items():
        reference = image["reference"]
        if reference not in analysis:
            image = {**image, "analysis_gap": "Image analysis unavailable; use original screenshot and requirement UI evidence. Do not invent unseen details."}
        if reference in analysis and (
            (image["source_field"] == "ui" or reference in sources)
            and sources.get(reference) != image["sha256"]
        ):
            analysis.pop(reference, None)
            image = {**image, "analysis_gap": "Stale image analysis excluded; use original screenshot and requirement evidence."}
        images[iid] = {**image, "analysis": analysis.get(reference, {})}
    contexts = {}
    for rid in tree.leaves:
        refs = catalog["requirements"].get(rid, [])
        contexts[rid] = {**tree.requirements[rid], "steps": [tree.steps[sid] for sid in tree.own_steps[rid]],
            "validation_data": data_context(tree.validation_data,rid),
            "ui_evidence": ui_context(tree.ui_evidence,rid),
            "frontend_stack": stack_context(),
            "images": {key: images[key] for key in refs},
            "backend_foundation": getattr(tree,"backend_foundation",{"enabled":False}),
            "platform_http": {"login":"POST /api/auth/login", "me":"GET /api/auth/me", "logout":"POST /api/auth/logout",
                "registration_options":"GET /api/auth/registration-options returns enabled,userTypes [{id,label}].",
                "registration":"POST /api/auth/register {username,password,userType}; show only configured source user types; after 201 return to login, no auto-login.",
                "csrf":"Login/me returns csrfToken. Use browser cookies and X-CSRF-Token for mutations; recover via me after reload.",
                "idempotency":"Use Idempotency-Key for workflow commands; keep key stable for retries of the same intent, generate a new key for changed inputs."} if getattr(tree,"backend_foundation",{}).get("enabled") else {}}
    return tree, images, contexts


def load_frontend_context(arc_dir, input_dir):
    """Combine visual requirements with database and API artifacts for design stages."""
    tree, images, contexts = load_ui_context(arc_dir, input_dir)
    schema = read_artifact(arc_dir, "db_schema.json")
    contracts = read_artifact(arc_dir, "backend_endpoints.json") if (arc_dir / "backend_endpoints.json").is_file() else {
        "apis": {}, "requirements": {}, "diagnostics": ["Backend endpoint handoff is unavailable; implement from original source and inspect actual handlers. Missing backend capabilities are repair items, never frontend mocks."]}
    return tree, schema, contracts, images, contexts


def behavior_contexts(contexts):
    """Behavior stages use structured requirement text without repeated visual evidence."""
    return {rid: {key: value for key, value in context.items() if key != "images"}
        for rid, context in contexts.items()}
