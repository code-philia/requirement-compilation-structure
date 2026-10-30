"""Trigger design: native source, frontend data dependencies and ordered actions."""

INSTRUCTIONS = """Design complete frontend triggers for the supplied requirement using ui, backend_apis
and existing_triggers. Return {triggers:{}, requirement_triggers:[], step_triggers:{}}.
triggers maps trigger IDs to COMPLETE new or changed records with these separate fields:
- source: the emitting UI ELEMENT ID.
- event: mount, click, input, change, submit, keydown or keyup, captured by the host.
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
For navigation, reference the destination page's root element from ui.pages; it identifies
the page that implementation later passes to context.navigate by PAGE ID.
Describe action conditions, request sources, response branches and transformations in
prose. Guards and actions are implemented as code, not interpreted as an expression DSL.

The host synchronizes native editable values before business triggers. Add input/change
triggers for additional behavior such as filtering, not routine value copying. A mount
trigger represents page entry; use that page's root element as its source.
Reuse trigger IDs where behavior is shared and preserve earlier behavior when updating.
requirement_triggers associates this requirement's triggers; step_triggers maps scenario
steps to trigger lists, using [] for static/native behavior. Non-UI behavior needs no trigger.

The read and write arrays name FRONTEND variables, not DB fields. DB effects are derived
from called APIs. Return only trigger definitions and requirement/step associations.
Expected business outcomes come
from the requirement; API contracts supply transport and persistence behavior.
"""
