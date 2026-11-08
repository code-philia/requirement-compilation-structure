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
        self.raw = {}
        self.parents = {}

        def identifier(node, kind):
            """Read a requirement, scenario or step ID from the JSON document."""
            return node["id"]

        def items(node, key):
            """Read an optional list field and reject malformed child, scenario, step, or reference collections."""
            value = node.get(key, [])
            return value

        def visit(node):
            """Index one requirement and its own steps, recurse into children, then append its postorder ID."""
            rid = identifier(node, "requirement")
            self.raw[rid] = node
            description = node.get("description", "")
            if isinstance(description, dict):
                description = description.get("text", "")
            self.requirements[rid] = {"id": rid, "name": node.get("name", ""), "description": description}
            self.own_steps[rid] = []
            for scenario in items(node, "scenarios"):
                sid = identifier(scenario, "scenario")
                for step in items(scenario, "steps"):
                    step_id = identifier(step, "step")
                    record = {"id": step_id, "scenario": {"id": sid, "name": scenario.get("name", "")}}
                    for key in ("Given", "When", "Then"):
                        record[key] = step.get(key, step.get(key.lower(), ""))
                    record["references"] = items(step, "references")
                    self.steps[step_id] = record
                    self.own_steps[rid].append(step_id)
            self.children[rid] = [visit(child) for child in items(node, "children")]
            for child in self.children[rid]:
                self.parents[child] = rid
            self.postorder.append(rid)
            return rid

        visit(root)
        # Only leaves own business analysis; parents organize the requirement tree.
        document_order = [rid for rid in self.requirements if not self.children[rid]]
        def leaf_descendants(rid):
            if rid not in self.children:
                raise ValueError(f"Unknown requirement dependency {rid}")
            return {rid} if not self.children[rid] else set().union(*(leaf_descendants(c) for c in self.children[rid]))
        dependencies = {}
        for rid in document_order:
            current, refs = rid, set()
            while current:
                refs.update(self.raw[current].get("dependencies",[]) or [])
                current = self.parents.get(current)
            if rid in refs:
                raise ValueError(f"Self dependency at {rid}")
            dependencies[rid] = set().union(*(leaf_descendants(ref) for ref in refs)) - {rid} if refs else set()
        self.leaves = []
        pending = list(document_order)
        while pending:
            ready = next((rid for rid in pending if dependencies[rid] <= set(self.leaves)),None)
            if ready is None:
                raise ValueError("Requirement dependencies form a cycle after module expansion")
            self.leaves.append(ready)
            pending.remove(ready)

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
