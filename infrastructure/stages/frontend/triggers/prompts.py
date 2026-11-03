"""Trigger design: native source, frontend data dependencies and ordered actions."""

INSTRUCTIONS = """Design complete frontend triggers for the supplied requirement using ui, backend_apis
and existing_triggers. Return {triggers:{}, requirement_triggers:[], step_triggers:{}}.
triggers maps trigger IDs to COMPLETE new or changed records with these separate fields:
- source: the emitting UI ELEMENT ID.
- event: the interaction or lifecycle event, such as mount, click, change or submit; implementation uses the actual framework.
- guard: an enabling condition in plain language, or null.
- read: array of frontend variable names consumed.
- write: array of frontend variable names updated.
- action: an ORDERED ARRAY of actions, not an event/handler ID.
Complete response example; substitute supplied IDs and behavior:
{
  "triggers": {
    "TR-save": {
      "source": "UI-form",
      "event": "submit",
      "guard": null,
      "read": [
        "form.text"
      ],
      "write": [
        "form.error"
      ],
      "action": [
        {
          "kind": "api",
          "api": "API-save",
          "description": "Submit form.text; show the rejection message or continue after success"
        }
      ]
    }
  },
  "requirement_triggers": [
    "TR-save"
  ],
  "step_triggers": {
    "STEP-save": [
      "TR-save"
    ]
  }
}

Each action contains kind and description. An API action uses kind="api" and api=API_ID.
A local UI action uses kind="ui" and ui=ELEMENT_ID for updates, feedback or navigation.
For navigation, reference the destination page's root element in ui and describe how its
concrete parameters/object identity are obtained. Implementation chooses the actual
router/navigation API; the element ID is a design reference, not its runtime argument.
Describe action conditions, request sources, response branches and transformations in
prose. Guards and actions are implemented as code, not interpreted as an expression DSL.

This design is a behavioral reference, not a compiler-interpreted routing/event/state DSL.
Reference existing controls by ID and preserve their original requirement-defined UI names
and roles. Adding behavior must not rename controls, translate captions or combine aliases.
Implementation owns native bindings, component state, input conversion and API calls.
Describe which value receives user input; visibility/status dependencies are not writable
input values. A mount trigger describes required page-entry work, not a forced global hook.
Include/reuse a page-entry trigger in requirement_triggers only when THIS requirement needs
its behavior. A shared page does not make all its triggers dependencies. Refer to earlier
behavior when appropriate; do not implement unrelated future workflows as incidental setup.
For list actions identify the clicked row/object; for requests describe concrete parameter
sources, conversions, success/rejection branches and resulting state updates. Do not rely
on an undocumented global event payload or a particular generated context interface.
Reuse trigger IDs where behavior is shared and preserve earlier behavior when updating.
When extending an existing operation, update/reuse its trigger instead of introducing
another independently firing trigger for the same action. Describe the logical operation
once; a submit button and its enclosing form are not two separate API submissions.
requirement_triggers associates this requirement's triggers; step_triggers maps scenario
EVERY supplied step to trigger lists, using [] for static/native behavior. Non-UI behavior needs no trigger.

Frontend variables are declared in each element.data as {var, dtype, constraints}.
They are declarations, not initial values or already loaded records. Describe required
page-entry loading, concrete object identity, success/failure updates and edit/cancel
behavior from the requirement. Images supply appearance, not preloaded business objects.
Do not invent production defaults or display fixtures in this stage.
The read and write arrays name FRONTEND variables, not DB fields. DB effects are derived
from called APIs. The API read union must cover required_obligations.read; additional
supporting reads are allowed. The API write union must equal required_obligations.write.
Each step must include calls covering its step_obligations;
conditional API effects may be broader than one rejection step. These are declarations,
not proof of implementation behavior. Return only trigger definitions and requirement/step associations.
Preserve the actual sequence of requests: entry/reload/reopening must retrieve persisted
data even when creation already returned those fields. Do not drop needed read triggers
to minimize a field union or rely on a previous form's in-memory values across reload.
Expected business outcomes come
from the requirement; API contracts supply transport and persistence behavior.
"""
