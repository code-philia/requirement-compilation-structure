"""Joint UI/interaction design: one proposal per requirement, two compatible artifacts."""

from infrastructure.stages.frontend.context import load_frontend_context
from infrastructure.stages.frontend.ui.design import (
    INSTRUCTIONS as UI_RULES, empty_design, apply_proposal, normalize_design, data_symbols, requirement_ui)
from infrastructure.stages.frontend.ui.synthesis import bind_requirement_image_pages
from infrastructure.stages.frontend.triggers.prompts import INSTRUCTIONS as TRIGGER_RULES
from infrastructure.stages.frontend.triggers.design import empty_triggers, apply_decomposition, validate_coverage
from infrastructure.stages.frontend.arco import (
    DESIGN_INSTRUCTIONS, TRIGGER_INSTRUCTIONS, stack_context, validate_components, validate_bindings)
from infrastructure.stages.frontend.arco_knowledge import (
    ComponentContextIndex, retrieve_components, record_retrieval, record_knowledge_reference)
from infrastructure.stages.requirements.ui_evidence import UI_EVIDENCE_INSTRUCTIONS, validate_ui_mapping
from infrastructure.stages.database.obligations.records import normalize_obligations
from infrastructure.shared.agent.proposals import propose_json
from infrastructure.shared.models.text import TextModel
from infrastructure.utils.presentation.console import DemoConsole
from infrastructure.utils.files import read_artifact, save_json
from infrastructure.shared.rag.pages import PageRetriever


# Remove legacy sequencing instructions rather than asking the model to reconcile them.
JOINT_UI_RULES = UI_RULES.replace(
    'This stage declares the interface only. Return no code, tests, API definitions, triggers,',
    'Inside the ui object return no code, tests, API definitions, triggers,').replace(
    'Additional\ninteraction behavior belongs to step 09; real data loading and updates belong to step 10.',
    'Design the corresponding interaction behavior in the sibling interactions object now.')
JOINT_RULES = '''Design presentation AND executable interaction intent together for this requirement.
Return exactly {"ui": UI_PROPOSAL, "interactions": TRIGGER_PROPOSAL}.
The UI and trigger output instructions below apply inside their respective objects.
Use existing designs and the supplied API contracts. Design missing input controls,
loading/error/empty/permission states, routing, row identity and event ownership together.
Preserve earlier requirements and reuse their session/navigation triggers where needed.
Do not emit application code in this design proposal. Do not invent APIs or source policy.
Both objects are validated together; rejected proposals publish neither design.
'''


def design_frontend_joint(input_dir, arc_dir, pause=False, max_attempts=10):
    tree, schema, backend, images, contexts = load_frontend_context(arc_dir, input_dir)
    obligations = normalize_obligations(read_artifact(arc_dir, 'db_obligations.json'), tree)
    ui, triggers = empty_design(), empty_triggers(tree)
    ui['frontend_stack'] = stack_context()
    for rid in tree.requirements:
        ui['requirements'][rid] = []
    for sid in tree.steps:
        ui['steps'][sid] = []
    model, console, retriever = TextModel(), DemoConsole(pause), PageRetriever()
    record_knowledge_reference(arc_dir.parent)
    save_json(arc_dir / 'frontend_stack.json', ui['frontend_stack'])
    accepted = []
    for rid in tree.leaves:
        retrieved = retriever.retrieve(contexts[rid], ui, 3)
        components = retrieve_components(contexts[rid],
            {uid: node for page in retrieved['pages'].values() for uid, node in page['elements'].items()})
        record_retrieval(arc_dir, '07_design_frontend_joint', rid, components)
        # The API inventory is normally small per requirement; shared auth stays explicit.
        aids = set(backend['requirements'].get(rid, []))
        aids.update(aid for aid, api in backend['apis'].items() if api.get('platform_builtin'))
        request = {'requirement': contexts[rid], 'retrieved_pages': retrieved['pages'],
            'all_pages': ui['pages'], 'existing_triggers': triggers['triggers'],
            'backend_apis': {aid: backend['apis'][aid] for aid in aids},
            'required_obligations': obligations['requirements'][rid],
            'step_obligations': {sid: obligations['steps'][sid] for sid in tree.own_steps[rid]},
            'component_knowledge': components, 'frontend_stack': stack_context()}

        def accept(proposal):
            expected_steps = set(tree.own_steps[rid])
            for section, field in (("ui", "step_ui"), ("interactions", "step_triggers")):
                if set(proposal[section][field]) != expected_steps:
                    raise ValueError(f"{section}.{field} must contain exactly this requirement's steps")
            updated_ui = apply_proposal(ui, proposal['ui'], rid, tree)
            validate_components(proposal['ui']['elements'])
            bind_requirement_image_pages(updated_ui, contexts[rid], rid)
            normalize_design(updated_ui, tree)
            requirement_ui(updated_ui, [*accepted, rid])  # Check referenced nodes and parent cycles.
            for owner in [*accepted, rid]:
                validate_ui_mapping(updated_ui, contexts[owner].get('ui_evidence', {}), owner)
            for sid in tree.own_steps[rid]:
                proposal['interactions']['step_triggers'][sid]
            updated_triggers = apply_decomposition(triggers, proposal['interactions'], rid)
            # Shared updates must still be valid for ALL accepted requirements.
            validate_bindings(updated_triggers['triggers'], updated_ui['elements'])
            validate_coverage(updated_triggers, backend, obligations, tree, [*accepted, rid])
            return updated_ui, updated_triggers

        (ui, triggers), _ = propose_json(model,
            JOINT_UI_RULES + DESIGN_INSTRUCTIONS + UI_EVIDENCE_INSTRUCTIONS + '\n' +
            TRIGGER_RULES + TRIGGER_INSTRUCTIONS + '\n' + JOINT_RULES,
            request, accept, console, 'Joint frontend design ' + rid, max_attempts,
            context_index=ComponentContextIndex(lambda: {'page': ui['pages'],
                'ui_element': ui['elements'], 'ui_data': data_symbols(ui['elements']),
                'trigger': triggers['triggers'], 'api': backend['apis']}, arc_dir, '07_design_frontend_joint', rid))
        accepted.append(rid)
        save_json(arc_dir / 'ui_design.json', ui)
        save_json(arc_dir / 'frontend_triggers.json', triggers)
    save_json(arc_dir / 'ui_design.json', ui)
    save_json(arc_dir / 'frontend_triggers.json', triggers)
    return {'status': 'GREEN', 'requirements': accepted, 'pages': len(ui['pages']),
        'triggers': len(triggers['triggers']), 'mode': 'joint_design'}


def implement_frontend_joint(input_dir, arc_dir, pause=False):
    from infrastructure.pipeline.frontend_implementation import implement_frontend_triggers
    return implement_frontend_triggers(input_dir, arc_dir, pause=pause, joint_ui=True)
