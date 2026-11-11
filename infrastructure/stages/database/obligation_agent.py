"""Read-only database obligation agent and its tool definitions."""

import json

from infrastructure.shared.agent.agent import BaseAgent
from infrastructure.shared.models.text import reasoning_arguments
from infrastructure.stages.database.obligation_utils import normalize_inference, check_symbols
from infrastructure.utils.presentation.formatting import format_schema
from infrastructure.utils.presentation.model_io import record_tool_execution


RECORD_SCHEMA = {"type": "object", "properties": {
    "read": {"type": "array", "items": {"type": "string"}},
    "write": {"type": "array", "items": {"type": "string"}}},
    "required": ["read", "write"], "additionalProperties": False}


class ObligationAgent(BaseAgent):
    def build_system_prompt(self) -> str:
        return """You are an architecture designer deriving database read/write obligations for
ONE requirement and its scenario steps. You receive the current requirement (name,
description, scenarios and parent module), candidate related fields, the complete
existing entity-name/description inventory, and potentially related complete entity
structures. Assume the completed schema is sufficient. Select existing fields to
express the requirement's persistent data effects.

For requirement r, its obligation O(r) = (R(r), W(r)):
- R(r) contains existing persistent values needed by specified behavior, including
  displayed values, lookup/filter/join keys, existence checks, authentication and
  authorization data.
- W(r) contains fields whose persisted values or record existence are created,
  changed or removed by specified behavior, including generated keys.
A field may be read, written, both, or neither. The sets cover specified branches,
not effects required on every invocation or an exhaustive SQL access whitelist.
Candidate related fields are hints: include missing relevant fields visible in the
schema and exclude irrelevant candidates. Do not force every candidate into a set.

Use native function tools:
- submit_obligations(requirement, steps): submit the COMPLETE analysis. requirement
  contains separate read and write arrays of qualified Entity.field names. steps
  maps EVERY supplied step ID to its own read and write arrays. Use [] for empty
  sets and steps={} when there are no steps. A valid submission ends the task.
- retrieve_entity(names): inspect complete additional existing entities only when
  the supplied structures do not provide enough information. Select relevant names
  from the entity inventory. This tool may be called ONLY ONCE, in the FIRST
  response, alone; pass all requested names in one list. Unknown names are silently
  skipped. Do not retrieve already provided structures or retrieve a missing
  candidate field when it is already visible in a supplied entity.

Derive each step's effects from its current When action and Then outcome, treating
Given as pre-existing context. Form requirement-level sets covering all its steps
plus additional behavior explicitly required by the description. Do not copy the
requirement-wide effects into every step or inherit another requirement's effects
through references or parent module context.

Examples (illustrative names; select only actual schema symbols):
- Refreshing a homepage to restore a username reads the session lookup key, account
  relation and username; writes []. Accounts/sessions created in Given do not count
  as writes of the refresh action.
- Registration reads Account.username to check duplicates. Successful creation
  writes required account fields and generated Account.id; duplicate rejection
  writes []. The requirement includes successful-branch writes. Returning a newly
  generated ID alone does not read a previously persisted ID.
- Login reads the stored password hash; the submitted password is input, not a DB
  field. Session writes are required only if the behavior specifies creating one.
- Opening/reopening an editor reads persisted data; saving writes changed fields.
  Cancel/rejection does not write unless specified. A later reload still reads
  persisted data even if an earlier creation returned it.
- Hard deletion writes all fields of the removed entity, including its key; soft
  deletion writes the actual changed flags. A purely local tab change has no DB
  reads or writes.

After optional retrieval, call submit_obligations. Put the result only in the tool
arguments, without duplicating it in assistant content or serializing tool calls
as text. On validation errors, submit a corrected COMPLETE result. You have at most
five model rounds, including retrieval and corrections. Preserve the schema and use
exact entity/field names. Infer effects from requirement evidence without inventing
features or incidental writes.
"""

    def build_user_prompt(self, input: dict) -> str:
        requirement = input["requirement"]
        entities = input["schema"]["entities"]
        provided = input["provided_entities"]
        paragraphs = [
            "Please derive the database read/write obligations for the following requirement.",
            f"Current requirement: {requirement['id']} — {requirement['name']}\n"
            f"Parent module: {requirement.get('parent_module') or '(none)'}\n"
            f"Description:\n{requirement['description']}",
        ]
        steps = []
        previous_scenario = None
        for step in input["steps"]:
            scenario = step["scenario"]
            if scenario["id"] != previous_scenario:
                steps.append(f"Scenario {scenario['id']}: {scenario['name']}")
                previous_scenario = scenario["id"]
            steps.append(f"Step {step['id']}")
            for key in ("Given", "When", "Then"):
                steps.append(f"{key}: {step[key]}")
            if step.get("references"):
                steps.append("References: " + ", ".join(step["references"]))
        paragraphs.append("Requirement scenarios and Given/When/Then steps:\n" +
            ("\n".join(steps) or "(none)"))
        candidates = []
        for field in input["related_fields"]:
            candidates.append(f"- {field}")
        paragraphs.append("Candidate related fields from schema construction. Review these as hints; "
            "add or exclude fields as needed:\n" + ("\n".join(candidates) or "(none)"))
        inventory = []
        available = []
        for name, entity in entities.items():
            inventory.append(f"- {name}: {entity['description']}")
            if name not in provided:
                available.append(name)
        paragraphs.append("All existing entities and their descriptions:\n" +
            ("\n".join(inventory) or "There are no existing entities."))
        paragraphs.append("Entities whose complete structures are already provided: " +
            (", ".join(provided) or "(none)") + ".")
        paragraphs.append("Complete entity structures from candidate associations and BM25 retrieval. "
            "Use these directly; do not request them again:\n" + format_schema(provided))
        if available:
            paragraphs.append("Entities available for additional retrieval: " + ", ".join(available) +
                ". Retrieve relevant entities only in the first response if their structures are "
                "needed; otherwise proceed directly to submit_obligations.")
        else:
            paragraphs.append("No additional entities are available for retrieval. "
                "Proceed directly to submit_obligations.")
        paragraphs.append("Use submit_obligations to submit complete read/write sets for the current "
            "requirement and every supplied step. Select existing fields; the schema remains read-only.")
        return "\n\n".join(paragraphs)

    def run(self, input: dict, max_rounds: int = 5) -> dict:
        if not 1 <= max_rounds <= 5:
            raise ValueError("Obligation agent requires between 1 and 5 rounds")
        messages = [{"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": self.build_user_prompt(input)}]
        self.messages = messages
        submit_tool = {"type": "function", "function": {"name": "submit_obligations",
            "description": "Submit the complete requirement and scenario-step read/write sets",
            "parameters": {"type": "object", "properties": {
                "requirement": RECORD_SCHEMA,
                "steps": {"type": "object", "additionalProperties": RECORD_SCHEMA}},
                "required": ["requirement", "steps"], "additionalProperties": False}}}
        available = []
        for name in input["schema"]["entities"]:
            if name not in input["provided_entities"]:
                available.append(name)
        retrieve_tool = {"type": "function", "function": {"name": "retrieve_entity",
            "description": "Inspect additional entities only when the initial context is insufficient",
            "parameters": {"type": "object", "properties": {"names": {"type": "array",
                "items": {"type": "string", "enum": available}}},
                "required": ["names"], "additionalProperties": False}}}
        step_ids = [step["id"] for step in input["steps"]]
        last_error = "No submission received"
        for round_number in range(1, max_rounds + 1):
            tools = [submit_tool]
            if round_number == 1 and available:
                tools.append(retrieve_tool)
            response = self.model._request(model=self.model.name, messages=messages, tools=tools,
                tool_choice="required", **reasoning_arguments(self.model.name, self.model.reasoning))
            if not response.choices:
                raise ValueError("Obligation model returned no choices")
            choice = response.choices[0]
            message = choice.message
            messages.append(message.model_dump(exclude_none=True))
            calls = message.tool_calls or []
            accepted = None
            errors = []
            for call in calls:
                try:
                    if len(calls) != 1 or choice.finish_reason == "length":
                        raise ValueError("Return exactly one complete tool call per round")
                    arguments = json.loads(call.function.arguments)
                    if call.function.name == "retrieve_entity":
                        if round_number != 1 or not available:
                            raise ValueError("Retrieval is allowed only in the first response")
                        names = arguments["names"]
                        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                            raise ValueError("names must be an array of entity names")
                        result = {}
                        for name in names:
                            if name in input["provided_entities"]:
                                raise ValueError(f"Entity was already provided: {name}")
                            if name in input["schema"]["entities"]:
                                result[name] = input["schema"]["entities"][name]
                    elif call.function.name == "submit_obligations":
                        if set(arguments["steps"]) != set(step_ids):
                            raise ValueError("Return exactly the supplied scenario step IDs")
                        inferred = normalize_inference(arguments, step_ids)
                        check_symbols([inferred["requirement"], *inferred["steps"].values()], input["schema"])
                        accepted = inferred
                        result = {"status": "SUCCESS"}
                    else:
                        raise ValueError(f"Unknown tool: {call.function.name}")
                except (ValueError, KeyError, TypeError, AttributeError) as error:
                    result = {"error": str(error)}
                    errors.append(str(error))
                messages.append({"role": "tool", "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False)})
                record_tool_execution(call.model_dump(exclude_none=True), result, logger=self.logger)
            if accepted is not None and not errors:
                return accepted
            if not calls:
                errors.append("Use retrieve_entity or submit_obligations through native tool calls")
            if errors:
                last_error = "; ".join(errors)
                messages.append({"role": "user", "content": "Correct the submission: " + last_error})
        raise RuntimeError(f"Obligation generation exhausted {max_rounds} model rounds: {last_error}")
