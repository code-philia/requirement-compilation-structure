"""Single-file edit_file proposals; validate the whole batch before applying it."""

import json
import re

EDIT_RULES = """修改应用时返回一个 JSON 对象，不要返回完整 HTML，也不要自动修改测试：
{"summary":"修改说明","edits":[{"tool":"edit_file","path":"expense.html","operation":"replace","old_content":"精确的原代码片段","new_content":"替换后的代码片段"}]}
只允许修改 expense.html。operation 只能是 replace；old_content 必须从当前源码原样复制，
并在依次应用前面修改后的代码中恰好出现一次。禁止整文件替换；支持多条局部修改。
new_content 可以为空（删除片段）。使用正常 JSON 转义换行和引号，不添加省略号或行号。
可以使用 json 代码块包裹对象。只提出修改，用户点击 Apply 才会应用。
"""


def parse_proposal(answer):
    text = answer.strip()
    block = re.search(r"```json\s*\n([\s\S]*?)```", text, re.IGNORECASE)
    if block:
        text = block[1].strip()
    try:
        proposal = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"修改列表不是有效 JSON：{error.msg}") from error
    if not isinstance(proposal, dict) or not isinstance(proposal.get("edits"), list):
        raise ValueError("请返回包含 edits 列表的 JSON 对象")
    edits = proposal["edits"]
    if not edits or len(edits) > 30:
        raise ValueError("每次请提出 1～30 项局部修改")
    for index, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            raise ValueError(f"第 {index} 项修改必须是对象")
        if edit.get("tool") != "edit_file" or edit.get("path") != "expense.html":
            raise ValueError(f"第 {index} 项只允许用 edit_file 修改 expense.html")
        if edit.get("operation") != "replace":
            raise ValueError(f"第 {index} 项必须使用 replace 操作")
        if not isinstance(edit.get("old_content"), str) or not edit["old_content"]:
            raise ValueError(f"第 {index} 项必须包含非空 old_content")
        if not isinstance(edit.get("new_content"), str):
            raise ValueError(f"第 {index} 项必须包含字符串 new_content")
    return {"summary": str(proposal.get("summary", "应用局部修改")), "edits": edits}


def apply_edits(html, edits):
    updated = html.replace("\r\n", "\n").replace("\r", "\n")
    for index, edit in enumerate(edits, 1):
        old = edit["old_content"].replace("\r\n", "\n").replace("\r", "\n")
        new = edit["new_content"].replace("\r\n", "\n").replace("\r", "\n")
        if old.strip() == updated.strip():
            raise ValueError(f"第 {index} 项试图替换整个文件，请改为局部修改")
        position = updated.find(old)
        if position < 0:
            raise ValueError(f"第 {index} 项 old_content 与当前代码不匹配，未应用任何修改")
        if updated.find(old, position + 1) >= 0:
            raise ValueError(f"第 {index} 项 old_content 不唯一，请扩大代码片段，未应用任何修改")
        updated = updated[:position] + new + updated[position + len(old):]
    if "<html" not in updated.lower() or "</html>" not in updated.lower():
        raise ValueError("修改后缺少完整 HTML 文档，未应用任何修改")
    return updated
