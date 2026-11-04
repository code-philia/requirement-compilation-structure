"""Read final failure evidence without confusing an expected red test with a failure."""


def collect_failures(artifacts, stages, calls):
    failures = []
    seen = set()
    definitions = (
        ("db_checks", "04", "数据库验收", "entities"),
        ("backend_tdd", "06", "后端实现与验收", "apis"),
        ("ui_checks", "08", "界面实现与验收", "pages"),
        ("frontend_e2e", "10", "逐需求实现与验收", "requirements"),
        ("independent_acceptance", "10", "独立验收", "requirements"),
    )
    requirement_names = {}
    pending = [artifacts.get("requirements", {})]
    while pending:
        requirement = pending.pop()
        if requirement.get("id"):
            requirement_names[requirement["id"]] = requirement.get(
                "name", requirement["id"]
            )
        pending.extend(requirement.get("children") or [])

    def add(source, code, label, target, record, owners=None, node_ids=None):
        key = (source, target)
        if key in seen:
            return
        seen.add(key)
        stage = next((stage for stage in stages if stage["id"].startswith(code)), None)
        error = record.get("error") or "验收未通过，请展开查看原始反馈。"
        phase = record.get("phase") or "ACCEPTANCE"
        if "/ Generation" in error:
            phase = "GENERATION"
        owners = list(dict.fromkeys(owners or []))
        stage_calls = [call for call in calls if call["stage"] == code]
        matching_calls = [call for call in stage_calls if call.get("task_id") == target]
        if not matching_calls:
            matching_calls = [
                call
                for call in stage_calls
                if set(call.get("requirement_ids") or []).intersection(owners)
            ]
        if source == "independent_acceptance":
            independent_calls = [
                call
                for call in matching_calls
                if "independent acceptance" in call.get("activity", "").lower()
            ]
            if independent_calls:
                matching_calls = independent_calls
        failures.append(
            {
                "id": source + ":" + target,
                "stage": stage["id"] if stage else code,
                "stage_label": stage["label"] if stage else code,
                "label": label,
                "target": target,
                "requirement_ids": owners,
                "requirement_names": {
                    owner: requirement_names.get(owner, owner) for owner in owners
                },
                "node_ids": list(
                    dict.fromkeys(
                        (node_ids or []) + ["req:" + owner for owner in owners]
                    )
                ),
                "phase": phase,
                "error": error,
                "source": ".arc/" + source + ".json"
                if source != "compilation"
                else ".arc/compilation.json",
                "call_ids": [call["id"] for call in matching_calls],
                "record": record,
            }
        )

    for source, code, label, registry in definitions:
        report = artifacts.get(source) or {}
        entries = dict(report.get(registry) or {})
        for record in report.get("failures") or []:
            target = (
                record.get("api")
                or record.get("page")
                or record.get("requirement")
                or record.get("task")
            )
            if target:
                entries.setdefault(target, record)
        for target, record in entries.items():
            if not isinstance(record, dict) or record.get("status") != "FAILED":
                continue
            owners = []
            node_ids = []
            if registry == "requirements":
                owners.append(target)
            elif registry == "apis":
                node_ids.append("api:" + target)
                for owner, api_ids in (
                    artifacts.get("backend_apis", {}).get("requirements", {}).items()
                ):
                    if target in api_ids:
                        owners.append(owner)
            elif registry == "pages":
                root = (
                    artifacts.get("ui_design", {})
                    .get("pages", {})
                    .get(target, {})
                    .get("root")
                )
                if root:
                    node_ids.append("ui:" + root)
                for owner, element_ids in (
                    artifacts.get("ui_design", {}).get("requirements", {}).items()
                ):
                    if root and root in element_ids:
                        owners.append(owner)
            owners.extend(record.get("requirements") or [])
            add(source, code, label, target, record, owners, node_ids)
        # Requirement-level summaries also expose affected owners if a report has
        # no concrete API failure to explain their status.
        if registry == "apis":
            for owner, record in report.get("requirements", {}).items():
                if record.get("status") != "FAILED":
                    continue
                if any(
                    owner in failure["requirement_ids"]
                    and failure["stage"].startswith(code)
                    for failure in failures
                ):
                    continue
                add(source, code, label, owner, record, [owner])
        for check, record in report.get("verification", {}).items():
            if record.get("status") != "FAILED":
                continue
            if check == "independent_acceptance" and any(
                entry.get("status") == "FAILED"
                for entry in artifacts.get("independent_acceptance", {})
                .get("requirements", {})
                .values()
            ):
                continue
            add(source, code, label + " · 最终检查", "verification:" + check, record)
        if report.get("status") == "FAILED" and not any(
            failure["id"].startswith(source + ":") for failure in failures
        ):
            add(source, code, label, "report", report)

    for stage in stages:
        if stage["status"] not in {"FAILED", "COMPLETED_WITH_FAILURES", "INTERRUPTED"}:
            continue
        if any(failure["stage"] == stage["id"] for failure in failures):
            continue
        add(
            "compilation",
            stage["id"][:2],
            "阶段异常",
            stage["id"],
            {
                "status": stage["status"],
                "error": stage.get("error")
                or "该阶段异常结束，未记录可归属的具体需求；请结合阶段日志排查。",
            },
        )
    return sorted(failures, key=lambda failure: (failure["stage"], failure["id"]))
