"""Frontend inputs retain image/page evidence alongside normalized requirements."""

from infrastructure.stages.requirements.tree import RequirementTree
from infrastructure.stages.requirements.images import build_image_catalog
from infrastructure.utils.files import read_artifact
from infrastructure.stages.frontend.arco import stack_context


def load_ui_design(arc_dir, tree):
    from infrastructure.stages.frontend.ui.design import normalize_design
    return normalize_design(read_artifact(arc_dir, "ui_design.json"), tree)


def load_ui_context(arc_dir, input_dir):
    """Load image evidence and optional shared backend semantics for frontend generation."""
    raw = read_artifact(arc_dir, "requirements.json")
    tree = RequirementTree(raw)
    if (arc_dir / "backend_evidence.json").is_file():
        tree.backend_evidence = read_artifact(arc_dir,"backend_evidence.json")
        tree.backend_foundation = read_artifact(arc_dir,"backend_foundation.json")
    analysis = read_artifact(arc_dir, "visual_analysis.json")
    catalog = build_image_catalog(raw, input_dir)
    source_path = arc_dir / "visual_analysis_sources.json"
    sources = read_artifact(arc_dir, source_path.name) if source_path.is_file() else {}
    if not isinstance(analysis, dict) or not isinstance(sources, dict):
        raise ValueError("Invalid image analysis artifacts; rerun stage 01")
    images = {}
    for iid, image in catalog["images"].items():
        reference = image["reference"]
        if image["source_field"] == "ui" and reference not in analysis:
            raise ValueError(f"Missing UI image analysis for {reference}; rerun stage 01")
        if reference in analysis and (
            (image["source_field"] == "ui" or reference in sources)
            and sources.get(reference) != image["sha256"]
        ):
            raise ValueError(f"Image analysis is stale or unverified for {reference}; rerun stage 01")
        images[iid] = {**image, "analysis": analysis.get(reference, {})}
    contexts = {}
    for rid in tree.leaves:
        refs = catalog["requirements"].get(rid, [])
        contexts[rid] = {**tree.requirements[rid], "steps": [tree.steps[sid] for sid in tree.own_steps[rid]],
            "frontend_stack": stack_context(),
            "images": {key: images[key] for key in refs},
            "backend_foundation": getattr(tree,"backend_foundation",{"enabled":False}),
            "platform_http": {"login":"POST /api/auth/login", "me":"GET /api/auth/me", "logout":"POST /api/auth/logout",
                "csrf":"Login/me returns csrfToken. Use browser cookies and X-CSRF-Token for mutations; recover via me after reload.",
                "idempotency":"Use Idempotency-Key for workflow commands; keep key stable for retries of the same intent, generate a new key for changed inputs."} if getattr(tree,"backend_foundation",{}).get("enabled") else {}}
    return tree, images, contexts


def load_frontend_context(arc_dir, input_dir):
    """Combine visual requirements with database and API artifacts for design stages."""
    tree, images, contexts = load_ui_context(arc_dir, input_dir)
    schema = read_artifact(arc_dir, "db_schema.json")
    contracts = read_artifact(arc_dir, "backend_apis.json")
    return tree, schema, contracts, images, contexts


def behavior_contexts(contexts):
    """Behavior stages use structured requirement text without repeated visual evidence."""
    return {rid: {key: value for key, value in context.items() if key != "images"}
        for rid, context in contexts.items()}
