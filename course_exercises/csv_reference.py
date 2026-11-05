"""Deterministic reference for the classroom's CSV cleaning rules."""

import csv
import argparse
from datetime import datetime
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
import re


def inspect_orders(source: str):
    reader = csv.reader(StringIO(source.lstrip("\ufeff")), strict=True)
    expected = [
        "order_id",
        "city",
        "status",
        "quantity",
        "unit_price",
        "order_date",
        "email",
        "remark",
    ]
    try:
        header = next(reader, [])
        if header != expected:
            raise ValueError("CSV 表头应为：" + ",".join(expected))
        rows = list(reader)
    except csv.Error as error:
        raise ValueError("CSV 引号或列结构无法解析：" + str(error)) from error

    valid = []
    errors = []
    duplicates = []
    changes = []
    seen = {}
    for number, cells in enumerate(rows, 1):
        if len(cells) != len(expected):
            errors.append(
                {
                    "row": number,
                    "order_id": cells[0] if cells else "",
                    "issues": [
                        {
                            "column": "CSV",
                            "reason": "应为 8 列，实际为 " + str(len(cells)),
                        }
                    ],
                }
            )
            continue
        raw = dict(zip(expected, cells))
        row = {}
        for column, value in raw.items():
            row[column] = value.strip()
        identity = row["order_id"]
        if identity in seen:
            duplicates.append(
                {"row": number, "order_id": identity, "first_row": seen[identity]}
            )
            continue
        seen[identity] = number
        issues = []
        if not re.fullmatch(r"O[0-9]{3}", identity):
            issues.append({"column": "order_id", "reason": "必须为 O 加三位数字"})
        if not row["city"]:
            issues.append({"column": "city", "reason": "城市不能为空"})
        row["status"] = row["status"].lower()
        if row["status"] not in {"paid", "pending", "cancelled"}:
            issues.append({"column": "status", "reason": "状态不在允许范围内"})
        if not re.fullmatch(r"[0-9]+", row["quantity"]) or int(row["quantity"]) <= 0:
            issues.append({"column": "quantity", "reason": "必须为正整数"})
        price = row["unit_price"]
        if not re.fullmatch(
            r"(?:[0-9]+|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?", price
        ):
            issues.append(
                {
                    "column": "unit_price",
                    "reason": "必须为最多两位小数的非负价格，千位分隔需合法",
                }
            )
        else:
            row["unit_price"] = format(Decimal(price.replace(",", "")), ".2f")
        date = row["order_date"]
        try:
            if not re.fullmatch(
                r"[0-9]{4}(-[0-9]{2}-[0-9]{2}|/[0-9]{2}/[0-9]{2})", date
            ):
                raise ValueError("格式错误")
            row["order_date"] = datetime.strptime(
                date.replace("/", "-"), "%Y-%m-%d"
            ).strftime("%Y-%m-%d")
        except ValueError:
            issues.append(
                {"column": "order_date", "reason": "日期格式错误或公历日期不存在"}
            )
        email = row["email"]
        email_parts = email.split("@")
        domain = email_parts[-1]
        domain_parts = domain.split(".")
        if (
            len(email_parts) != 2
            or not email_parts[0]
            or len(domain_parts) < 2
            or not all(domain_parts)
            or re.search(r"\s", email)
        ):
            issues.append({"column": "email", "reason": "不符合本题简化邮箱格式"})
        row_changes = []
        for column in expected:
            if raw[column] != row[column]:
                row_changes.append(
                    {"column": column, "from": raw[column], "to": row[column]}
                )
        if row_changes:
            changes.append({"row": number, "changes": row_changes})
        if issues:
            errors.append({"row": number, "order_id": identity, "issues": issues})
            continue
        valid.append(row)

    statuses = {"paid": 0, "pending": 0, "cancelled": 0}
    cities = {}
    quantity = 0
    revenue = Decimal("0")
    for row in valid:
        statuses[row["status"]] += 1
        if row["status"] != "paid":
            continue
        count = int(row["quantity"])
        amount = Decimal(row["unit_price"]) * count
        quantity += count
        revenue += amount
        city = cities.setdefault(row["city"], {"orders": 0, "revenue": Decimal("0")})
        city["orders"] += 1
        city["revenue"] += amount
    city_totals = []
    for name, totals in cities.items():
        city_totals.append(
            {
                "city": name,
                "orders": totals["orders"],
                "revenue": format(totals["revenue"], ".2f"),
            }
        )
    return {
        "total_rows": len(rows),
        "valid_rows": len(valid),
        "duplicate_rows": len(duplicates),
        "error_rows": len(errors),
        "error_items": sum(len(item["issues"]) for item in errors),
        "valid_ids": [row["order_id"] for row in valid],
        "statuses": statuses,
        "paid_orders": statuses["paid"],
        "quantity": quantity,
        "revenue": format(revenue, ".2f"),
        "cities": city_totals,
        "errors": errors,
        "duplicates": duplicates,
        "changes": changes,
        "cleaned_rows": valid,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()
    result = inspect_orders(args.csv_file.read_text(encoding="utf-8-sig"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
