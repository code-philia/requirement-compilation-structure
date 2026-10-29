"""Order table dependency components before their dependents."""


def table_dependencies(schema: dict) -> dict:
    """Map each entity to the tables referenced by its foreign-key fields."""
    return {
        name: sorted({field["references"].split(".")[0] for field in entity["fields"].values() if field["references"] and field["references"].split(".")[0] in schema["entities"]})
        for name, entity in schema["entities"].items()
    }


def implementation_groups(schema: dict) -> list[list[str]]:
    # --- Extension point: dependency planning ---------------------------------
    # Tarjan's algorithm emits dependency-first strongly connected components
    # for edges table -> referenced table. SQLite accepts forward references
    # inside a cycle, so its members can be implemented in a stable name order.
    """Return dependency-first table groups; keep mutually referencing tables together in stable name order."""
    dependencies = table_dependencies(schema)
    indices, low = {}, {}
    stack, active, groups = [], set(), []

    def visit(name):
        """Apply Tarjan's depth-first search and emit a component when its dependency cycle closes."""
        indices[name] = low[name] = len(indices)
        stack.append(name)
        active.add(name)
        for target in dependencies[name]:
            if target not in indices:
                visit(target)
                low[name] = min(low[name], low[target])
            elif target in active:
                low[name] = min(low[name], indices[target])
        if low[name] == indices[name]:
            group = []
            while True:
                target = stack.pop()
                active.remove(target)
                group.append(target)
                if target == name:
                    break
            groups.append(sorted(group))

    for name in sorted(dependencies):
        if name not in indices:
            visit(name)
    return groups
