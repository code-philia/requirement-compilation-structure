"""The input requirement format, shared by manual edits and assistant tools."""

from copy import deepcopy
from pathlib import PurePosixPath
import re
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
import yaml


class Image(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    page: str = ""


class Description(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = ""
    image: list[Image] = Field(default_factory=list)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1)
    Given: str = Field(min_length=1)
    When: str = Field(min_length=1)
    Then: str = Field(min_length=1)
    references: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    steps: list[Step] = Field(min_length=1)


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: Description = Field(default_factory=Description)
    scenarios: list[Scenario] = Field(default_factory=list)
    children: list["Node"] = Field(default_factory=list)


def walk(tree):
    yield tree
    for child in tree["children"]:
        yield from walk(child)


def validate_document(value):
    # Reject cycles and excessive nesting before recursive schema validation.
    pending = [(value, 0)]
    visited = set()
    count = 0
    while pending:
        node, depth = pending.pop()
        if not isinstance(node, dict):
            raise ValueError("需求节点必须是对象")
        if id(node) in visited:
            raise ValueError("需求树中存在循环或重复引用的节点")
        visited.add(id(node))
        count += 1
        if depth > 20 or count > 500:
            raise ValueError("需求树最多 500 个节点、20 层，请按项目拆分")
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("children 必须是列表")
        for child in children:
            pending.append((child, depth + 1))
    try:
        tree = Node.model_validate(value).model_dump()
    except ValidationError as error:
        details = []
        for item in error.errors()[:8]:
            location = ".".join(str(part) for part in item["loc"])
            details.append(f"{location}：{item['msg']}")
        raise ValueError("需求格式不正确：\n" + "\n".join(details)) from error
    identifiers = set()
    for node in walk(tree):
        records = [node, *node["description"]["image"]]
        for scenario in node["scenarios"]:
            records.extend([scenario, *scenario["steps"]])
        for record in records:
            identifier = record["id"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", identifier):
                raise ValueError(f"ID {identifier} 仅可包含英文、数字、点、下划线、连字符")
            if identifier in identifiers:
                raise ValueError(f"ID 重复：{identifier}")
            identifiers.add(identifier)
        for image in node["description"]["image"]:
            path = PurePosixPath(image["reference"])
            if path.is_absolute() or ".." in path.parts or "\\" in image["reference"] or ":" in image["reference"]:
                raise ValueError("参考图只能使用输入目录内的相对路径")
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
                raise ValueError("参考图路径必须指向 PNG、JPG、WEBP、GIF 或 SVG 图片")
    return tree


def inspect_document(tree):
    issues = []
    nodes = list(walk(tree))
    targets = {"requirement": set(), "image": set(), "scenario": set(), "step": set()}
    scenarios = 0
    steps = 0
    for node in nodes:
        targets["requirement"].add(node["id"])
        for image in node["description"]["image"]:
            targets["image"].add(image["id"])
        for scenario in node["scenarios"]:
            targets["scenario"].add(scenario["id"])
            scenarios += 1
            for step in scenario["steps"]:
                targets["step"].add(step["id"])
                steps += 1
    for node in nodes:
        if not node["description"]["text"].strip():
            issues.append({"node_id": node["id"], "message": "尚未填写需求描述"})
        if not node["children"] and not node["scenarios"]:
            issues.append({"node_id": node["id"], "message": "叶子节点缺少验收场景"})
        if node["children"] and node["scenarios"]:
            issues.append({"node_id": node["id"], "message": "父节点包含验收场景；编译器按叶子分析业务，建议将场景归入对应叶子"})
        for scenario in node["scenarios"]:
            for step in scenario["steps"]:
                for reference in step["references"]:
                    for kind, identifier in re.findall(r"\\ref\[(requirement|image|scenario|step)\]\(([^)]+)\)", reference):
                        if identifier not in targets[kind]:
                            issues.append({"node_id": node["id"], "message": f"引用不存在：{reference}"})
    return {"nodes": len(nodes), "scenarios": scenarios, "steps": steps, "issues": issues}


def markdown_document(tree):
    lines = []

    def visit(node, depth):
        heading = "#" * min(depth + 1, 6)
        name = re.sub(r"[\r\n]+", " ", node["name"])
        lines.extend([f"{heading} {name}", "", f"`{node['id']}`", "", node["description"]["text"], ""])
        for image in node["description"]["image"]:
            lines.extend([f"参考图：{image['id']} · `{image['reference']}`", ""])
        for scenario in node["scenarios"]:
            lines.extend([f"**场景：{scenario['name']}** · `{scenario['id']}`", ""])
            for step in scenario["steps"]:
                lines.extend([
                    f"- **前置条件 Given：** {step['Given']}",
                    f"- **操作 When：** {step['When']}",
                    f"- **预期结果 Then：** {step['Then']}",
                ])
                if step["references"]:
                    lines.append("- **关联：** " + "、".join(step["references"]))
                lines.append("")
        for child in node["children"]:
            visit(child, depth + 1)

    visit(tree, 0)
    return "\n".join(lines)


def yaml_document(tree):
    return yaml.safe_dump(tree, allow_unicode=True, sort_keys=False, width=100)


def apply_operation(tree, name, arguments):
    document = deepcopy(tree)
    index = {}
    parents = {}
    for node in walk(document):
        index[node["id"]] = node
        for child in node["children"]:
            parents[child["id"]] = node
    if name == "replace_document":
        return validate_document(arguments["document"]), arguments["document"].get("id", "ROOT")
    identifier = arguments.get("node_id", arguments.get("parent_id"))
    if identifier not in index:
        raise ValueError(f"找不到节点 {identifier}，请先读取当前需求树")
    node = index[identifier]
    if name == "add_node":
        child = deepcopy(arguments["node"])
        if not child.get("id"):
            child["id"] = "REQ-" + uuid4().hex[:12].upper()
        position = arguments.get("position", len(node["children"]))
        if not isinstance(position, int) or not 0 <= position <= len(node["children"]):
            raise ValueError("插入位置超出子节点范围")
        node["children"].insert(position, child)
        identifier = child["id"]
    elif name == "update_node":
        patch = arguments["patch"]
        if not isinstance(patch, dict) or not patch or set(patch) - {"name", "description", "scenarios"}:
            raise ValueError("只可更新 name、description、scenarios；ID 和子节点通过专门工具维护")
        for key, value in patch.items():
            if key == "description" and isinstance(value, dict):
                node["description"].update(value)
            else:
                node[key] = value
    elif name == "move_node":
        parent = index.get(arguments["parent_id"])
        descendants = {item["id"] for item in walk(node)}
        if identifier not in parents or parent is None or parent["id"] in descendants:
            raise ValueError("不能移动根节点，也不能将节点移动到自身或其后代")
        parents[identifier]["children"].remove(node)
        position = arguments.get("position", len(parent["children"]))
        if not isinstance(position, int) or not 0 <= position <= len(parent["children"]):
            raise ValueError("移动位置超出范围")
        parent["children"].insert(position, node)
    elif name == "delete_node":
        if identifier not in parents:
            raise ValueError("根节点不能删除；可编辑其内容或新建项目")
        parent = parents[identifier]
        parent["children"].remove(node)
        identifier = parent["id"]
    else:
        raise ValueError(f"未知工具：{name}")
    return validate_document(document), identifier


def tool_definitions():
    node_schema = Node.model_json_schema()
    definitions = node_schema.pop("$defs", {})
    specs = [
        ("read_document", "读取最新完整需求树、版本和待完善项。", {}, []),
        ("read_node", "读取指定节点及其子树。", {"node_id": {"type": "string"}}, ["node_id"]),
        ("replace_document", "生成完整需求树；仅首次起草或用户明确要求整体替换时使用。", {"document": node_schema}, ["document"]),
        ("add_node", "在父节点下添加需求节点；不提供 ID 时自动分配。", {
            "parent_id": {"type": "string"}, "node": {"type": "object", "description": "需求节点，格式同输入 YAML；必填 name，可提供 id、description、scenarios、children。"},
            "position": {"type": "integer", "minimum": 0},
        }, ["parent_id", "node"]),
        ("update_node", "局部修改节点名称、描述或验收场景，不改变 ID 与 children。", {
            "node_id": {"type": "string"}, "patch": {"type": "object", "description": "只允许 name、description、scenarios；description.text 更新时保留原有图片。"},
        }, ["node_id", "patch"]),
        ("move_node", "移动需求及其子树到新父节点，保持稳定 ID。", {
            "node_id": {"type": "string"}, "parent_id": {"type": "string"}, "position": {"type": "integer", "minimum": 0},
        }, ["node_id", "parent_id"]),
        ("delete_node", "删除节点及全部后代。仅用户明确要求删除时使用。", {"node_id": {"type": "string"}}, ["node_id"]),
    ]
    tools = []
    for name, description, properties, required in specs:
        parameters = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}
        if name == "replace_document":
            parameters["$defs"] = definitions
        tools.append({"type": "function", "function": {"name": name, "description": description, "parameters": parameters}})
    return tools
