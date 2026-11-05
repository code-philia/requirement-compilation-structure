"""Interpret a small, explicit Playwright Python subset without exec or eval."""

import ast
import asyncio
import time

from playwright.async_api import async_playwright, expect

APP_URL = "http://classroom-app.test/"
CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'"
)
LOCATORS = {"get_by_role", "get_by_label", "get_by_text", "get_by_test_id", "locator"}
ACTIONS = {"fill", "click", "press", "check", "uncheck", "select_option"}
ASSERTIONS = {
    "to_have_text", "to_contain_text", "to_have_count", "to_have_value",
    "to_be_visible", "to_be_hidden", "to_be_enabled", "to_be_disabled",
}


def literal(node):
    if isinstance(node, ast.Name) and node.id == "APP_URL":
        return APP_URL
    if isinstance(node, ast.Constant) and isinstance(
        node.value, (str, int, float, bool, type(None))
    ):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [literal(item) for item in node.elts]
    raise ValueError("参数仅支持文本、数字、布尔值、列表和 APP_URL")


def expression(node):
    if isinstance(node, ast.Name) and node.id == "page":
        return {"kind": "page"}
    if not isinstance(node, ast.Call):
        raise ValueError("仅支持 page 定位、操作与 expect 断言")
    if isinstance(node.func, ast.Name) and node.func.id == "expect":
        if len(node.args) != 1 or node.keywords:
            raise ValueError("expect 只接受一个定位器")
        parent = expression(node.args[0])
        if parent["kind"] != "locator":
            raise ValueError("expect 必须作用于页面定位器")
        return {"kind": "expect", "parent": parent}
    if not isinstance(node.func, ast.Attribute):
        raise ValueError("不支持此函数调用")
    parent = expression(node.func.value)
    method = node.func.attr
    kind = parent["kind"]
    if kind in {"page", "locator"} and method in LOCATORS:
        result = "locator"
    elif kind == "locator" and method in {"nth", "filter"}:
        result = "locator"
    elif kind == "locator" and method in ACTIONS:
        result = "action"
    elif kind == "expect" and method in ASSERTIONS:
        result = "assertion"
    elif kind == "page" and method == "goto":
        result = "action"
    else:
        raise ValueError(f"不支持 {kind}.{method}；只允许课堂页面操作与断言")
    args = [literal(arg) for arg in node.args]
    kwargs = {}
    for keyword in node.keywords:
        if keyword.arg is None or keyword.arg.startswith("_"):
            raise ValueError("不支持展开参数或私有参数")
        kwargs[keyword.arg] = literal(keyword.value)
    if method == "goto" and (args != [APP_URL] or kwargs):
        raise ValueError("页面只能访问 APP_URL")
    if "timeout" in kwargs:
        raise ValueError("等待时间由课堂执行器统一管理，请勿设置 timeout")
    return {
        "kind": result,
        "parent": parent,
        "method": method,
        "args": args,
        "kwargs": kwargs,
    }


def parse_script(source):
    if len(source) > 60000:
        raise ValueError("测试脚本过长，请拆分测试意图")
    try:
        module = ast.parse(source)
    except SyntaxError as error:
        raise ValueError(f"脚本第 {error.lineno} 行语法错误：{error.msg}") from error
    cases = []
    names = set()
    for node in module.body:
        if isinstance(node, ast.ImportFrom):
            if node.module == "playwright.async_api" and not node.level and all(
                item.name in {"expect", "Page"} and item.asname is None for item in node.names
            ):
                continue
            raise ValueError("只允许导入 playwright.async_api 的 expect、Page")
        if (
            not isinstance(node, ast.AsyncFunctionDef)
            or not node.name.startswith("test_")
        ):
            raise ValueError("脚本只允许 import 和 async def test_名称(page)")
        arguments = node.args
        if (
            [arg.arg for arg in arguments.args] != ["page"] or arguments.posonlyargs
            or arguments.kwonlyargs or arguments.vararg or arguments.kwarg
            or arguments.defaults or node.decorator_list
        ):
            raise ValueError("每个测试仅接收 page 参数，不使用装饰器或默认参数")
        if node.name in names:
            raise ValueError("测试名称不能重复")
        names.add(node.name)
        steps = []
        for statement in node.body:
            if (
                not isinstance(statement, ast.Expr)
                or not isinstance(statement.value, ast.Await)
            ):
                raise ValueError("测试内仅支持 await 页面操作或断言，不使用变量、循环、分支")
            operation = expression(statement.value.value)
            if operation["kind"] not in {"action", "assertion"}:
                raise ValueError("每一步必须是页面操作或断言")
            steps.append({
                "code": ast.get_source_segment(source, statement),
                "operation": operation,
            })
        if not steps or steps[0]["operation"].get("method") != "goto":
            raise ValueError("每个测试第一步必须是 await page.goto(APP_URL)")
        if not any(step["operation"]["kind"] == "assertion" for step in steps):
            raise ValueError("每个测试至少包含一个 expect 断言")
        if len(steps) > 60:
            raise ValueError("每个用例最多 60 步")
        cases.append({"name": node.name, "steps": steps})
    if not cases or len(cases) > 12:
        raise ValueError("请生成 1～12 个独立测试用例")
    return cases


def resolve(operation, page):
    if operation["kind"] == "page":
        return page
    parent = resolve(operation["parent"], page)
    if operation["kind"] == "expect":
        return expect(parent)
    return getattr(parent, operation["method"])(*operation["args"], **operation["kwargs"])


async def execute_suite(session, execution, folder, save):
    cases = parse_script(execution["script"])
    started = time.perf_counter()
    browser = None
    try:
        async with async_playwright() as playwright:
            try:
                browser = await playwright.chromium.launch()
                async with asyncio.timeout(180):
                    for case_index, case in enumerate(cases):
                        result = {
                            "name": case["name"],
                            "status": "RUNNING",
                            "steps": [],
                            "error": "",
                        }
                        execution["cases"].append(result)
                        save(session)
                        context = await browser.new_context(
                            viewport={"width": 1120, "height": 760},
                            service_workers="block",
                            accept_downloads=False,
                        )
                        try:
                            async def route_request(route):
                                if (
                                    route.request.url != APP_URL
                                    or route.request.resource_type != "document"
                                ):
                                    await route.abort()
                                    return
                                await route.fulfill(
                                    status=200,
                                    content_type="text/html",
                                    body=execution["html"],
                                    headers={"Content-Security-Policy": CSP},
                                )

                            await context.route("**/*", route_request)
                            await context.route_web_socket(
                                "**/*", lambda socket: socket.close(),
                            )
                            await context.tracing.start(
                                screenshots=True, snapshots=True, sources=False,
                            )
                            page = await context.new_page()
                            page.set_default_timeout(4000)
                            expect.set_options(timeout=4000)
                            for index, step in enumerate(case["steps"]):
                                entry = {
                                    "code": step["code"],
                                    "status": "RUNNING",
                                    "error": "",
                                    "screenshot": None,
                                    "duration": 0,
                                }
                                result["steps"].append(entry)
                                save(session)
                                tick = time.perf_counter()
                                try:
                                    await resolve(step["operation"], page)
                                    entry["status"] = "PASSED"
                                except Exception as error:
                                    entry.update(status="FAILED", error=str(error)[:5000])
                                entry["duration"] = time.perf_counter() - tick
                                filename = f"{execution['id']}-{case_index}-{index}.png"
                                try:
                                    await page.screenshot(
                                        path=folder / filename,
                                        timeout=3000,
                                        animations="disabled",
                                    )
                                    entry["screenshot"] = filename
                                except Exception:
                                    pass
                                execution["duration"] = time.perf_counter() - started
                                save(session)
                                if entry["status"] == "FAILED":
                                    result.update(status="FAILED", error=entry["error"])
                                    break
                            if result["status"] == "RUNNING":
                                result["status"] = "PASSED"
                            trace = f"{execution['id']}-{case_index}.zip"
                            await context.tracing.stop(path=folder / trace)
                            result["trace"] = trace
                        finally:
                            await context.close()
                        save(session)
                execution["status"] = "PASSED"
                for case in execution["cases"]:
                    if case["status"] == "FAILED":
                        execution["status"] = "FAILED"
                        break
            finally:
                if browser is not None:
                    await browser.close()
    finally:
        execution["duration"] = time.perf_counter() - started
        save(session)
