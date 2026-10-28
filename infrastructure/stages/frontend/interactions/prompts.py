"""Small fixed protocols for interaction decomposition and semantic P/Q."""

DECOMPOSE = """Design interactions for the current leaf using its UI and directly allocated APIs.
Return exactly {triggers:{}, events:{}, requirement_triggers:[], step_triggers:{}}.
Only return new or changed COMPLETE records. Existing IDs may be reused by reference.
All existing triggers/events are supplied; retain earlier behavior and associations.
Trigger fields: source (UI ID), event (mount/click/change/input/submit/keydown/keyup),
action (event ID). One trigger per source/native-event pair; share it by ID.
mount sources must be page roots; submit sources must be forms; native input/change
sources must be editable controls. Every current editable UI data variable needs an
input/change event that writes its latest native value. Do not submit on input changes.

Event fields: description, write (frontend variable names), actions (ordered array).
Each action has id, kind, description; kind=api adds api, kind=navigate adds page,
kind=local adds no fields. IDs are unique inside an event. Describe exact request value
sources, response branches, transformations and enabling conditions in description.
Use action IDs to distinguish repeated API calls. Frontend write permissions appear
ONLY on the event. No read sets, action writes, guards, DB effects, typed expressions,
request/update trees or explanations. API and navigation permissions are derived from
actions; DB effects are derived from called APIs by the compiler.

Call only the supplied backend_apis. Every directly allocated API must be used, including
read-only APIs or APIs with no DB effects. Preserve failure-without-writes. Local input
and navigation have no DB effects. A destination page's lifecycle API belongs to its
own requirement; do not copy it into the current requirement's events. Navigation uses
existing page IDs from page_inventory. UI-only variables are valid global state.

requirement_triggers associates this leaf's directly involved triggers. step_triggers
includes every own step ID exactly once, using [] for static/native behavior. Step
associations trace behavior; do not enforce step DB containment. Reuse handlers without
inventing redundant events. Do not change UI/data, backend interfaces or write code.
"""

CONTRACT = """Infer semantic P/Q for this fixed event, considering every supplied requirement use.
Return exactly {contract:{precondition:[STRING],postcondition:[STRING]}}.
P may be empty. Q must describe observable results, including relevant success/rejection
branches, frontend state, navigation and persistence/forbidden writes. Refer to fixed
API fields/statuses and action IDs in ordinary prose when useful. Describe enabling
conditions here; handler code implements them. Do not add pointers, expression trees,
action contracts, effect sets, backend-Q mappings, IDs or explanation fields.
The ordered actions already describe the workflow; P/Q describe its conditions/results.
Do not invent request fields, statuses, UI variables or business rules. Implementations
and real browser tests will check these descriptions; do not claim formal proof.
"""
