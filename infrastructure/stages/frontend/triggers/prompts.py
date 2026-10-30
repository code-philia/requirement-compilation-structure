"""Trigger design: native source, frontend data dependencies and ordered actions."""

INSTRUCTIONS = """Design frontend triggers for the current requirement using its UI and backend APIs.
Return {triggers:{}, requirement_triggers:[], step_triggers:{}}.
Each trigger is a complete record keyed by its ID with:
source: emitting UI ID; event: native event name such as submit/click/change/mount;
guard: optional enabling condition in plain language, or null;
read: frontend variable names consumed; write: frontend variable names updated;
action: ordered list of actions.
Each action has kind and description. kind=api adds api (backend API ID).
kind=ui adds ui (target UI ID). UI actions describe local updates, navigation,
feedback, selection or other frontend behavior. Navigation targets the destination
page's root UI. Describe conditions, request value sources, response branches and
transformations in ordinary prose; implementation code performs them.

UI bindings already synchronize native editable values. Add input/change triggers
when the requirement calls for additional behavior, not merely to copy input values.
Use existing triggers by ID when appropriate; include complete changed records.
requirement_triggers lists this requirement's triggers; step_triggers associates
scenario steps with triggers. Backend-only requirements can return empty lists.

read/write are FRONTEND variables, never DB fields. Do not return DB obligations:
the compiler derives DB read/write sets from API calls and supplies them when coding.
Do not define separate events, handlers, P/Q contracts, mapping expression languages,
or executable code. Guards and action descriptions capture behavior. Tests use the
original requirement and API contracts to verify observable UI and database outcomes.
"""
