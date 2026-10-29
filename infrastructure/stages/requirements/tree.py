"""Index requirement containment while retaining each scenario's step context."""

import json


# --- Extension point: requirement representation and traversal ----------------
# Extend normalization or reference handling here. Stable IDs, explicit step
# ownership, and correct postorder are shared contracts of steps 02 through 04.
class RequirementTree:
    """Normalized requirement and scenario indexes with explicit step ownership and traversal order."""
    def __init__(self, root: dict) -> None:
        """Index requirements and scenario steps while validating IDs and ownership.

        Build children, own_steps, leaf order, and child-before-parent postorder
        once so later stages share the same containment semantics."""
        self.requirements = {}
        self.steps = {}
        self.children = {}
        self.own_steps = {}
        self.postorder = []

        def identifier(node, kind):
            """Read a requirement, scenario or step ID from the JSON document."""
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"].strip():
                raise ValueError(f"Each {kind} must have a nonempty string id")
            return node["id"]

        def items(node, key):
            """Read an optional list field and reject malformed child, scenario, step, or reference collections."""
            value = node.get(key, [])
            if not isinstance(value, list):
                raise ValueError(f"{key} must be a list: {node['id']}")
            return value

        def visit(node):
            """Index one requirement and its own steps, recurse into children, then append its postorder ID."""
            rid = identifier(node, "requirement")
            description = node.get("description", "")
            if isinstance(description, dict):
                description = description.get("text", "")
            if not isinstance(description, str) or not isinstance(node.get("name", ""), str):
                raise ValueError(f"Invalid name or description: {rid}")
            self.requirements[rid] = {"id": rid, "name": node.get("name", ""), "description": description}
            self.own_steps[rid] = []
            for scenario in items(node, "scenarios"):
                sid = identifier(scenario, "scenario")
                for step in items(scenario, "steps"):
                    step_id = identifier(step, "step")
                    record = {"id": step_id, "scenario": {"id": sid, "name": scenario.get("name", "")}}
                    for key in ("Given", "When", "Then"):
                        record[key] = step.get(key, step.get(key.lower(), ""))
                        if not isinstance(record[key], str):
                            raise ValueError(f"{key} must be text: {step_id}")
                    record["references"] = items(step, "references")
                    self.steps[step_id] = record
                    self.own_steps[rid].append(step_id)
            self.children[rid] = [visit(child) for child in items(node, "children")]
            self.postorder.append(rid)
            return rid

        visit(root)
        # Only leaves own model-driven business analysis; parents aggregate results.
        self.leaves = [rid for rid in self.requirements if not self.children[rid]]

    def concatenated_steps(self, requirement_id: str) -> str:
        """Render only this requirement's own steps, preserving scenario labels, Given/When/Then, and references."""
        lines = []
        previous_scenario = None
        for step_id in self.own_steps[requirement_id]:
            step = self.steps[step_id]
            scenario = step["scenario"]
            if scenario["id"] != previous_scenario:
                lines.append(f"Scenario {scenario['id']}: {scenario['name']}")
                previous_scenario = scenario["id"]
            lines.append(f"Step {step_id}")
            lines.extend(f"{key}: {step[key]}" for key in ("Given", "When", "Then"))
            if step["references"]:
                lines.append("References: " + json.dumps(step["references"], ensure_ascii=False))
        return "\n".join(lines)
