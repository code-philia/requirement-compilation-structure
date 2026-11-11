"""Database schema design agent and its entity tools."""

from copy import deepcopy
import json

from infrastructure.shared.agent.agent import BaseAgent
from infrastructure.shared.models.text import reasoning_arguments
from infrastructure.stages.database.schema import apply_patch, check_related_fields
from infrastructure.utils.presentation.model_io import record_tool_execution


FIELD_PROPERTIES = {
    "description": {"type": "string"},
    "type": {"type": "string", "enum": ["string", "integer", "number", "boolean", "date", "datetime", "uuid", "json"]},
    "nullable": {"type": "boolean"},
    "primary_key": {"type": "boolean"},
    "unique": {"type": "boolean"},
    "references": {"type": ["string", "null"]},
    "constraints": {"type": "array", "items": {"type": "string"}},
}

# ==================================
#  Tools for constructing db schema
# ==================================

def create_entity(schema: dict, name: str, entity: dict) -> None:
    """Create one complete entity, rejecting names that already exist."""
    if name in schema["entities"]:
        raise ValueError(f"Entity already exists: {name}; use update_entity")
    if not isinstance(entity.get("description"), str) or not isinstance(entity.get("fields"), dict):
        raise ValueError("A new entity requires description and fields")
    for field, definition in entity["fields"].items():
        missing = set(FIELD_PROPERTIES) - definition.keys()
        if missing:
            raise ValueError(f"New field {name}.{field} is missing properties: {sorted(missing)}")
    schema["entities"][name] = deepcopy(entity)


def update_entity(schema: dict, name: str, entity: dict) -> None:
    """Merge supplied properties and fields, preserving omitted definitions."""
    if name not in schema["entities"]:
        raise ValueError(f"Unknown entity: {name}; use create_entity")
    for field, definition in entity.get("fields", {}).items():
        if field not in schema["entities"][name]["fields"]:
            missing = set(FIELD_PROPERTIES) - definition.keys()
            if missing:
                raise ValueError(f"New field {name}.{field} is missing properties: {sorted(missing)}")
    updated = apply_patch(schema, {"entities": {name: entity}})
    schema["entities"][name] = updated["entities"][name]


def retrieve_entity(schema: dict, names: list[str]) -> dict:
    """Return complete definitions in requested order, silently skipping unknown names."""
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("names must be a list of entity names")
    result = {}
    for name in names:
        if name in schema["entities"]:
            result[name] = deepcopy(schema["entities"][name])
    return result


# ==================================
#  Agent for constructing db schema
# ==================================

class SchemaAgent(BaseAgent):
    def build_system_prompt(self) -> str:
        return """You are an architecture designer incrementally completing ONE application's
persistent database schema. You receive the current requirement (name, description,
scenarios and parent module), the complete existing entity-name/description inventory,
and potentially related complete entities selected by BM25. Identify required new
entities and fields, or reuse and extend existing definitions. Include data only read
by this requirement, even when its creation belongs to another requirement.

Use native function tools:
- create_entity(name, entity): create a new entity with description and fields.
  Every new field requires description, type, nullable, primary_key, unique,
  references (null or Entity.field), and constraints (array of strings).
- update_entity(name, entity): update an EXISTING entity. Supply only changed
  entity/field properties; omitted properties remain unchanged. New fields require
  all field properties. references=null explicitly clears a reference. Do not rename
  existing concepts or erase unrelated behavior. Reuse exact entity and field names.
- retrieve_entity(names): inspect complete definitions of additional existing
  entities when their names/descriptions indicate relevance and the supplied BM25
  results do not already contain them. Skip retrieval when no additional relevant
  entities exist. This tool may be called ONLY ONCE, in the FIRST response, alone;
  pass all requested names in one list. Unknown names are silently skipped.

After optional retrieval, return a batch of native create_entity/update_entity calls.
Each mutation call must include related_fields: the COMPLETE list of persistent fields
needed by this requirement across all entities, including unchanged reused fields.
Do not put related_fields in assistant content when using mutation tools. Associations
must reference fields that exist after the batch completes; they do not create fields.
If no entity changes are needed, return no tool calls and content containing only
{"related_fields":["Entity.field"]}; use [] for requirements without persistent data.
After tool errors, correct failed operations and include the complete related_fields
again. Successful operations remain applied; never repeat successful create calls.
One response may contain multiple create/update calls, executed in order.

Use SQL-compatible names. Derive constraints from requirement evidence rather than
example fixture values. Store password hashes and omit transient confirmation inputs.
Preserve all previously accepted entities, fields and requirement associations.
"""

    def build_user_prompt(self, input: dict) -> str:
        requirement = input["requirement"]
        entities = input["schema"]["entities"]
        provided = input["retrieved_entities"]
        paragraphs = [
            "Please complete the application's persistent database schema for the following requirement.",
            f"Current requirement: {requirement['id']} — {requirement['name']}\n"
            f"Parent module: {requirement.get('parent_module') or '(none)'}\n"
            f"Description:\n{requirement['description']}",
            "Requirement scenarios and Given/When/Then steps:\n" + (requirement.get("steps") or "(none)"),
        ]
        inventory = []
        available = []
        for name, entity in entities.items():
            inventory.append(f"- {name}: {entity['description']}")
            if name not in provided:
                available.append(name)
        paragraphs.append("All existing entities and their descriptions:\n" + ("\n".join(inventory) or "There are no existing entities."))
        paragraphs.append("Entities whose complete structures are already provided: " +
            (", ".join(provided) or "(none)") + ".")
        paragraphs.append("Complete entity structures already provided by BM25 retrieval. Use these directly; "
            "do not request them again:\n" + json.dumps(provided, ensure_ascii=False, indent=2))
        if available:
            paragraphs.append("Entities available for additional retrieval: " + ", ".join(available) +
                ". Retrieve only relevant entities from this list whose full structure is needed; "
                "otherwise proceed directly to creation or updates.")
        else:
            paragraphs.append("No additional entities are available for retrieval. Proceed directly to "
                "creation or updates, or return the field associations if no changes are needed.")
        paragraphs.append("Use create_entity for new entities and update_entity for partial changes to existing "
            "entities. Include the complete requirement-related field list in each mutation call as instructed.")
        return "\n\n".join(paragraphs)

    def run(self, input: dict, max_rounds: int = 5) -> dict:
        if not 1 <= max_rounds <= 5:
            raise ValueError("Schema agent requires between 1 and 5 rounds")
        schema = deepcopy(input["schema"])
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": self.build_user_prompt(input)},
        ]
        self.messages = messages
        tools = []

        """ Prepare tool definitions """

        for name in ("create_entity", "update_entity"):
            field_schema = {"type": "object", "properties": FIELD_PROPERTIES,
                "additionalProperties": False}
            if name == "create_entity":
                field_schema["required"] = list(FIELD_PROPERTIES)
            entity_schema = {"type": "object", "properties": {
                "description": {"type": "string"},
                "fields": {"type": "object", "additionalProperties": field_schema}},
                "additionalProperties": False}
            if name == "create_entity":
                entity_schema["required"] = ["description", "fields"]
            tools.append({"type": "function", "function": {"name": name,
                "description": "Create a complete new entity" if name == "create_entity" else "Merge changes into an existing entity",
                "parameters": {"type": "object", "properties": {
                    "name": {"type": "string"}, "entity": entity_schema,
                    "related_fields": {"type": "array", "items": {"type": "string"},
                        "description": "Complete requirement-related Entity.field list across all entities after this batch"}},
                    "required": ["name", "entity", "related_fields"], "additionalProperties": False}}})
        tools.append({"type": "function", "function": {"name": "retrieve_entity",
            "description": "Retrieve additional complete entities once, only in the first response",
            "parameters": {"type": "object", "properties": {
                "names": {"type": "array", "items": {"type": "string"}}},
                "required": ["names"], "additionalProperties": False}}})
        available = []
        for name in schema["entities"]:
            if name not in input["retrieved_entities"]:
                available.append(name)
        if available:
            tools[-1]["function"]["parameters"]["properties"]["names"]["items"]["enum"] = available
        retrieved = False
        last_error = "No final entity batch received"
        for round_number in range(1, max_rounds + 1):
            active_tools = tools[:2]
            if round_number == 1 and available:
                active_tools = tools
            response = self.model._request(model=self.model.name, messages=messages,
                tools=active_tools, **reasoning_arguments(self.model.name, self.model.reasoning))
            if not response.choices:
                raise ValueError("Schema model returned no choices")
            choice = response.choices[0]
            message = choice.message
            messages.append(message.model_dump(exclude_none=True))
            calls = message.tool_calls or []
            errors = []
            results = []
            retrieval_round = False
            related_fields = []
            for call in calls:
                try:
                    arguments = json.loads(call.function.arguments)
                    if call.function.name == "retrieve_entity":
                        if round_number != 1 or retrieved or len(calls) != 1:
                            raise ValueError("retrieve_entity is allowed once, alone in the first response")
                        retrieved = True
                        retrieval_round = True
                        names = arguments.get("names")
                        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
                            raise ValueError("names must be a list of entity names")
                        if any(name in input["retrieved_entities"] for name in names):
                            raise ValueError("These entity structures were already provided; use the supplied structures directly")
                        result = retrieve_entity(schema, **arguments)
                    elif call.function.name == "create_entity":
                        fields = arguments.pop("related_fields")
                        if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
                            raise ValueError("related_fields must be a list of Entity.field strings")
                        create_entity(schema, **arguments)
                        related_fields.extend(fields)
                        result = {"status": "SUCCESS"}
                    elif call.function.name == "update_entity":
                        fields = arguments.pop("related_fields")
                        if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
                            raise ValueError("related_fields must be a list of Entity.field strings")
                        update_entity(schema, **arguments)
                        related_fields.extend(fields)
                        result = {"status": "SUCCESS"}
                    else:
                        raise ValueError(f"Unknown tool: {call.function.name}")
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    result = {"error": str(error)}
                    errors.append(str(error))
                results.append({"role": "tool", "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False)})
                record_tool_execution(call.model_dump(exclude_none=True), result, logger=self.logger)
            messages.extend(results)
            if choice.finish_reason == "length":
                errors.append("Model output was truncated; return complete tool calls with related_fields parameters")
            if not retrieval_round:
                try:
                    if calls:
                        fields = related_fields
                    else:
                        content = json.loads(message.content or "{}")
                        fields = content["related_fields"]
                    check_related_fields(schema, fields)
                except (ValueError, TypeError, KeyError) as error:
                    errors.append(f"Invalid related_fields: {error}")
                if not errors:
                    schema["requirements"][input["requirement"]["id"]] = sorted(set(fields))
                    return schema
            if errors:
                last_error = "; ".join(errors)
                messages.append({"role": "user", "content": "Correct these errors: " + last_error})
        raise RuntimeError(f"Schema design exhausted {max_rounds} model rounds: {last_error}")
