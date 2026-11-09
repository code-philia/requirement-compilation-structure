"""Publish compiler-owned Casbin/XState backend infrastructure and route bindings."""

import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from infrastructure.utils.files import save_text, save_json

VERSIONS = {"casbin": "5.51.1", "xstate": "5.33.3", "decimal.js": "10.6.0"}
PLATFORM = Path(__file__).with_name("platform")
IDENTITY_TABLES = frozenset({"users", "roles", "org_units", "user_ou_roles", "auth_sessions", "command_receipts", "platform_meta", "workflow_audit"})


def identity_startup_assertions(raw, evidence):
    """Exact source memberships for compiler-bootstrapped accounts; never infer roles."""
    catalog = evidence["authorization"]["catalog"]
    roots = [u["id"] for u in catalog["units"] if u.get("parent") is None]
    if len(roots) != 1:
        raise ValueError("Identity bootstrap requires one root organizational unit")
    accounts = [dict(row["properties"]) for row in raw.get("data", [])
        if row.get("entity") == "test account" and row.get("lifecycle") == "SEED"]
    if not any(row.get("username") == "admin" for row in accounts):
        accounts.insert(0, {"username":"admin", "roles":[{"role":"admin", "unit":roots[0]}]})
    result = []
    for account in accounts:
        roles = list(account.get("roles", []))
        if account["username"] == "admin" and not any(r.get("role") == "admin" for r in roles):
            roles.append({"role":"admin", "unit":roots[0]})
        result.append({"username":account["username"], "roles":roles})
    return result


def identifier(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "arc-backend:" + value))


def sql(value):
    return "'" + str(value).replace("'", "''") + "'" if value is not None else "NULL"


def publish_platform(output, evidence, plan, schema, raw):
    catalog = evidence["authorization"]["catalog"]
    if not any(r["id"] == "admin" for r in catalog["roles"]):
        catalog["roles"].append({"id": "admin", "name": "Administrator"})
    units = {row["id"]: identifier("unit:" + row["id"]) for row in catalog["units"]}
    if not units:
        raise ValueError("Backend identity needs a declared root organization unit")
    resources = {}
    for resource in catalog["resources"]:
        entity = schema["entities"].get(resource["id"])
        if not entity:
            raise ValueError(f"Authorization resource {resource['id']} is absent from canonical schema")
        keys = [key for key, field in entity["fields"].items() if field["primary_key"]]
        if len(keys) != 1:
            raise ValueError(f"Authorization resource {resource['id']} requires a single primary key")
        resources[resource["id"]] = {"key": keys[0], "references": {key: field["references"] for key, field in entity["fields"].items() if field["references"]}}
    policies = list(evidence["authorization"]["policies"]) + plan["additional_permissions"]
    # Administrative access is a persisted role, never a request-provided flag.
    policies += [{"role": "admin", "resource": r["id"], "action": a["id"], "scope": "all", "effect": "allow"} for r in catalog["resources"] for a in catalog["actions"]]
    policies = [p for p in policies if not (p["role"] == "admin" and p["effect"] == "deny")]
    policy_text = '\n'.join(dict.fromkeys(', '.join(['p', p['role'], p['resource'], p['action'], p['scope'], p['effect']]) for p in policies))
    tables = dict(resources)
    for name,entity in schema["entities"].items():
        if entity.get("origin") == "er_relationship":
            keys=[key for key,field in entity["fields"].items() if field["primary_key"]]
            if len(keys)!=1:raise ValueError(f"Association {name} needs one technical key")
            tables[name]={"key":keys[0],"references":{key:field["references"] for key,field in entity["fields"].items() if field["references"]}}
    config = {"tables":tables, "model": evidence["authorization"]["model"], "policy": policy_text, "resources": resources,
        "boundary": plan["default_boundary"], "features": plan["features"], "machines": plan["machines"]}
    save_text(output / "backend/src/platform/settings.ts", 'import type { PlatformSettings } from "./types.js";\nexport const settings: PlatformSettings = ' + json.dumps(config, ensure_ascii=False, indent=2) + ';\n')
    statements = []
    def insert(table, values, condition):
        statements.append(f'INSERT INTO "{table}" (' + ','.join('"'+key+'"' for key in values) + ') SELECT ' + ','.join(sql(v) for v in values.values()) + f' WHERE NOT EXISTS (SELECT 1 FROM "{table}" WHERE {condition});')
    for row in catalog["units"]:
        insert('org_units', {'id':units[row['id']], 'code':row['id'], 'name':row['name'], 'parent_id':units.get(row.get('parent'))}, 'code='+sql(row['id']))
    for row in catalog['roles']:
        insert('roles', {'id':row['id'], 'name':row['name']}, 'id='+sql(row['id']))
    accounts = [row['properties'] for row in raw.get('data', []) if row.get('entity') == 'test account' and row.get('lifecycle') == 'SEED']
    roots = [row['id'] for row in catalog['units'] if row.get('parent') is None]
    if len(roots) != 1:
        raise ValueError('Identity bootstrap requires one root organizational unit')
    if not any(row.get('username') == 'admin' for row in accounts):
        accounts.insert(0, {'username':'admin', 'password':'admin123456', 'roles':[{'role':'admin', 'unit':roots[0]}]})
    for account in accounts:
        username, password = account.get('username'), account.get('password')
        if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
            raise ValueError('Seed accounts require explicit username/password')
        salt = os.urandom(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
        encoded = 'scrypt$'+salt.hex()+'$'+digest.hex()
        insert('users', {'id':identifier('user:'+username), 'username':username, 'password_hash':encoded}, 'username='+sql(username))
        assignments = list(account.get('roles', []))
        if username == 'admin' and not any(r.get('role') == 'admin' for r in assignments):
            assignments.append({'role':'admin','unit':roots[0]})
        for row in assignments:
            if row.get('unit') not in units or row.get('role') not in {r['id'] for r in catalog['roles']}:
                raise ValueError(f'Invalid seed role binding for {username}')
            uid = units[row['unit']]
            statements.append('INSERT INTO user_ou_roles (id,user_id,unit_id,role_id) SELECT '+sql(identifier('binding:'+username+':'+row['unit']+':'+row['role']))+',id,'+sql(uid)+','+sql(row['role'])+' FROM users WHERE username='+sql(username)+' AND NOT EXISTS(SELECT 1 FROM user_ou_roles WHERE user_id=users.id AND unit_id='+sql(uid)+' AND role_id='+sql(row['role'])+');')
    bootstrap = '\n'.join(statements)
    save_text(output / 'backend/src/platform/bootstrap.ts', 'import type Database from "better-sqlite3";\nexport function bootstrapPlatform(db: Database.Database): void { db.pragma("defer_foreign_keys = ON"); db.exec('+json.dumps(bootstrap)+'); }\n')
    for asset in ('runtime.ts', 'types.ts'):
        save_text(output / 'backend/src/platform' / asset, (PLATFORM / asset).read_text())
    package_path = output / 'backend/package.json'
    package = json.loads(package_path.read_text())
    package.setdefault('dependencies', {}).update(VERSIONS)
    save_json(package_path, package)
    initializer = output / 'backend/src/db/initialize.ts'
    wire_initializer(initializer)
    app = output / 'backend/src/app.ts'
    source = app.read_text()
    if 'registerPlatformAuth' not in source:
        marker='  if (connection) registerApis(app, connection);'
        if marker not in source:
            raise ValueError("Application template has no compiler API registration hook")
        source = 'import { registerPlatformAuth } from "./platform/runtime.js";\n'+source
        source = source.replace('  if (connection) registerApis(app, connection);', '  if (connection) { registerPlatformAuth(app, connection); registerApis(app, connection); }')
        save_text(app, source)
    types = output / 'backend/src/api/types.ts'
    source = types.read_text()
    if 'BackendAccess' not in source:
        if 'export interface ApiRequest {' not in source:
            raise ValueError("API template has no compiler request-context hook")
        source = 'import type { BackendAccess } from "../platform/types.js";\n'+source
        source = source.replace('export interface ApiRequest {', 'export interface ApiRequest {\n  access: BackendAccess;')
        save_text(types, source)


def wire_initializer(path):
    if not path.is_file():
        return
    source = path.read_text()
    if 'bootstrapPlatform' not in source:
        if '      seedDatabase(connection);' not in source:
            raise ValueError("DB initializer has no compiler bootstrap hook")
        source = 'import { bootstrapPlatform } from "../platform/bootstrap.js";\nimport { bootstrapOwnership } from "../platform/runtime.js";\n'+source
        source = source.replace('      seedDatabase(connection);', '      bootstrapPlatform(connection);\n      seedDatabase(connection);\n      bootstrapOwnership(connection);')
        save_text(path, source)


def implementation_path(aid):
    return 'backend/src/api/implementations/api_'+hashlib.sha256(aid.encode()).hexdigest()[:20]+'.ts'


def publish_routes(output, design, foundation):
    if not foundation.get('enabled'):
        return
    lines = ['import type { Express } from "express";', 'import type Database from "better-sqlite3";', 'import { guardedRoute } from "../platform/runtime.js";']
    registrations = []
    for index, (aid, api) in enumerate(sorted(design['apis'].items(), key=lambda item: (item[1]['signature']['path'].count(':'), -len(item[1]['signature']['path']), item[0]))):
        if api.get('platform_builtin'):
            continue
        relative = implementation_path(aid)
        module = Path(relative).stem
        path = output / relative
        if not path.exists():
            save_text(path, 'import type { ApiHandler } from "../types.js";\nexport const handle: ApiHandler = async () => ({ status: 501, body: { error: "Not implemented" } });\n')
        lines.append(f'import {{ handle as handler{index} }} from "./implementations/{module}.js";')
        method, route = api['signature']['method'].lower(), api['signature']['path']
        if method not in {'get','post','put','patch','delete'} or not route.startswith('/api/'):
            raise ValueError(f'Invalid protected route {aid}')
        contract = {key: api[key] for key in ('security','workflow','read','write')}
        registrations.append(f'  app.{method}({json.dumps(route)}, guardedRoute(connection, {json.dumps(aid)}, {json.dumps(contract,ensure_ascii=False)}, handler{index}));')
    lines.append('export function registerApis(app: Express, connection: Database.Database): void {\n'+'\n'.join(registrations)+'\n}')
    save_text(output / 'backend/src/api/register.ts', '\n'.join(lines)+'\n')
    save_json(output / '.arc/backend_implementation_files.json', {aid: implementation_path(aid) for aid, api in design['apis'].items() if not api.get('platform_builtin')})
