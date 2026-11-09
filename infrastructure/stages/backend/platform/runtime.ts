import { randomBytes, randomUUID, scryptSync, timingSafeEqual, createHash } from "node:crypto";
import type { Express, Request, RequestHandler } from "express";
import type Database from "better-sqlite3";
import { newEnforcer, newModelFromString, StringAdapter, type Enforcer } from "casbin";
import { createMachine, transition as xtransition } from "xstate";
import type { ApiHandler, ApiRequest, ApiResponse } from "../api/types.js";
import type { RoutePolicy, BackendAccess, Principal, MachineSpec, TransitionSpec } from "./types.js";
import { settings } from "./settings.js";

class Failure extends Error { constructor(public status: number, message: string) { super(message); } }
const quote = (name: string): string => {
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(name)) throw new Failure(500,"Invalid canonical identifier");
  return '"'+name+'"';
};
const locks = new WeakMap<Database.Database, Promise<void>>();
async function exclusive<T>(db: Database.Database, work: () => Promise<T>): Promise<T> {
  const before = locks.get(db) ?? Promise.resolve();
  let release!: () => void;
  locks.set(db, new Promise<void>(resolve => { release = resolve; }));
  await before;
  try { return await work(); } finally { release(); }
}
const hash = (value: string): string => createHash("sha256").update(value).digest("hex");
const stable = (value: unknown): string => JSON.stringify(value, (_key,v) => v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])) : v);
function sameOrigin(req: Request): void {
  if (req.headers.origin && new URL(req.headers.origin).host !== req.headers.host) throw new Failure(403,"Cross-origin credential request");
}
function token(req: Request): string {
  const cookie = req.headers.cookie?.split(";").map(p=>p.trim()).find(p=>p.startsWith("arc_session="));
  return cookie ? cookie.slice("arc_session=".length) : "";
}
function session(db: Database.Database, req: Request): {principal: Principal; csrf: string} {
  const row = db.prepare("SELECT s.user_id,s.unit_id,s.csrf_token,u.username FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?").get(hash(token(req)),new Date().toISOString()) as {user_id:string;unit_id:string;csrf_token:string;username:string}|undefined;
  if (!row) throw new Failure(401,"Authentication required");
  const roles = (db.prepare("SELECT role_id FROM user_ou_roles WHERE user_id=? AND unit_id=?").all(row.user_id,row.unit_id) as {role_id:string}[]).map(r=>r.role_id);
  if (!roles.length) throw new Failure(403,"No role in the active unit");
  return {principal: Object.freeze({id:row.user_id,username:row.username,unitId:row.unit_id,roles,admin:roles.includes("admin")}),csrf:row.csrf_token};
}
function csrf(req: Request, secret: string): void {
  if (!["GET","HEAD","OPTIONS"].includes(req.method)) {
    sameOrigin(req);
    if (req.headers["x-csrf-token"] !== secret) throw new Failure(403,"CSRF token required");
  }
}
async function enforcer(db: Database.Database, principal: Principal): Promise<Enforcer> {
  const instance = await newEnforcer(newModelFromString(settings.model),new StringAdapter(settings.policy));
  for (const role of principal.roles) await instance.addGroupingPolicy(principal.id,role,principal.unitId);
  const units = db.prepare("SELECT id,parent_id FROM org_units").all() as {id:string;parent_id:string|null}[];
  for (const row of units) {
    await instance.addNamedGroupingPolicy("g2",row.id,row.id);
    if (row.parent_id) await instance.addNamedGroupingPolicy("g2",row.id,row.parent_id);
  }
  return instance;
}
type Ownership = {resource:string;record_id:string;unit_id:string;owner_id:string|null;assignee_id:string|null};
function sameBoundary(db: Database.Database, principal: Principal, unit: string): boolean {
  if (principal.admin || settings.boundary === "none") return true;
  if (unit === principal.unitId) return true;
  if (settings.boundary !== "unit_tree") return false;
  const seen = new Set<string>();
  let current: string|null = unit;
  while (current && !seen.has(current)) {
    seen.add(current);
    const row = db.prepare("SELECT parent_id FROM org_units WHERE id=?").get(current) as {parent_id:string|null}|undefined;
    current = row?.parent_id ?? null;
    if (current === principal.unitId) return true;
  }
  return false;
}
function ownership(db: Database.Database, resource: string, id: string): Ownership|undefined {
  return db.prepare("SELECT resource,record_id,unit_id,owner_id,assignee_id FROM record_access WHERE resource=? AND record_id=?").get(resource,id) as Ownership|undefined;
}
async function permitted(db: Database.Database, e: Enforcer, principal: Principal, resource: string, action: string, record?: Ownership): Promise<boolean> {
  if (principal.admin) return true;
  if (record && !sameBoundary(db,principal,record.unit_id)) return false;
  // An operation without a record proves functional authorization only. Actual
  // record scopes are evaluated below using persisted ownership attributes.
  if(!record) {
    const rows=settings.policy.split('\n').map(line=>line.split(',').map(v=>v.trim())).filter(p=>p[0]==='p'&&principal.roles.includes(p[1])&&p[2]===resource&&p[3]===action);
    return rows.some(p=>p[5]==='allow')&&!rows.some(p=>p[4]==='all'&&p[5]==='deny');
  }
  return e.enforce(principal.id,principal.unitId,resource,action,record.owner_id ?? "",record.unit_id,record.assignee_id ?? "");
}
function resourceKey(resource: string): string {
  const spec = settings.resources[resource];
  if (!spec) throw new Failure(500,"Unknown canonical resource");
  return spec.key;
}
function registerRecord(db: Database.Database, principal: Principal, resource: string, id: string): void {
  const key = resourceKey(resource);
  if (!db.prepare(`SELECT 1 FROM ${quote(resource)} WHERE ${quote(key)}=?`).get(id)) throw new Failure(409,"Cannot assign a missing record");
  const current = ownership(db,resource,id);
  if (current) {
    if (!sameBoundary(db,principal,current.unit_id)) throw new Failure(403,"Record is outside active data boundary");
    return;
  }
  db.prepare("INSERT INTO record_access(id,resource,record_id,unit_id,owner_id,assignee_id) VALUES(?,?,?,?,?,NULL)").run(randomUUID(),resource,id,principal.unitId,principal.id);
}
function selected(request: ApiRequest, selector: string|null): string|null {
  if (!selector) return null;
  const [part,key] = selector.split(".");
  const value = (request[part as "params"|"body"|"query"] as Record<string,unknown>)?.[key];
  if (typeof value !== "string" && typeof value !== "number") throw new Failure(400,"Record identifier required");
  return String(value);
}
function machineNext(machine: MachineSpec, spec: TransitionSpec, state: string): string {
  if (!spec.from.includes(state)) throw new Failure(409,"Command is not allowed in current state");
  const names = machine.states.map((_,i)=>"s"+i);
  const nodes: Record<string,{on:Record<string,string>}> = {};
  machine.states.forEach((value,i)=>{ nodes[names[i]] = {on:{}}; for (const t of Object.values(machine.transitions)) if (t.from.includes(value)) nodes[names[i]].on[t.event]=names[machine.states.indexOf(t.to)]; });
  const m = createMachine({initial:names[machine.states.indexOf(machine.initial)],states:nodes});
  const snapshot = m.resolveState({value:names[machine.states.indexOf(state)],context:{}});
  const [next] = xtransition(m,snapshot,{type:spec.event});
  if (next.value !== names[machine.states.indexOf(spec.to)]) throw new Failure(409,"Invalid workflow transition");
  return spec.to;
}
type Row = Record<string,unknown>;
function businessSnapshot(db: Database.Database): Record<string,Map<string,Row>> {
  return Object.fromEntries(Object.entries(settings.tables).map(([table,spec])=>[table,new Map((db.prepare(`SELECT * FROM ${quote(table)}`).all() as Row[]).map(row=>[String(row[spec.key]),row]))]));
}
function validateWrites(db: Database.Database, principal: Principal, policy: RoutePolicy, before: ReturnType<typeof businessSnapshot>, ownedBefore: Map<string,Ownership>, advanced: Map<string,string>): void {
  const after = businessSnapshot(db);
  const writes = new Set(policy.writeTables ?? []);
  const created: [string,string][] = [];
  for (const [table,rows] of Object.entries(after)) for (const [id,row] of rows) {
    const old = before[table].get(id);
    if (!old) created.push([table,id]);
    if (old && stable(old) === stable(row)) continue;
    if (!writes.has(table)) throw new Failure(500,"Handler wrote outside route writeTables");
    if (old && settings.resources[table]) {
      const owned = ownedBefore.get(table+":"+id);
      if (!principal.admin && (!owned || !sameBoundary(db,principal,owned.unit_id))) throw new Failure(403,"Cross-boundary mutation rejected");
    }
    for (const machine of Object.values(settings.machines)) if (machine.entity===table) {
      if (!old && row[machine.state_field]!==machine.initial && advanced.get(table+":"+id)!==row[machine.state_field]) throw new Failure(409,"New record must use initial workflow state");
      if (old && old[machine.state_field]!==row[machine.state_field] && advanced.get(table+":"+id)!==row[machine.state_field]) throw new Failure(500,"Handler must leave workflow state to the platform");
    }
  }
  for (const [table,rows] of Object.entries(before)) for (const id of rows.keys()) if (!after[table].has(id)) {
    if (!(policy.writeTables ?? []).includes(table)) throw new Failure(500,"Undeclared database deletion");
    const owned=ownedBefore.get(table+":"+id);
    if (settings.resources[table] && !principal.admin && (!owned || !sameBoundary(db,principal,owned.unit_id))) throw new Failure(403,"Cross-boundary deletion rejected");
    if(!settings.resources[table]&&!principal.admin) for(const [field,target] of Object.entries(settings.tables[table].references)) {
      const [parent]=target.split('.');const value=rows.get(id)?.[field];
      const linked=value==null?undefined:ownership(db,parent,String(value));
      if(settings.resources[parent]&&(!linked||!sameBoundary(db,principal,linked.unit_id)))throw new Failure(403,"Cross-boundary association deletion rejected");
    }
    db.prepare("DELETE FROM record_access WHERE resource=? AND record_id=?").run(table,id);
  }
  for (const [table,id] of created) if(settings.resources[table]) registerRecord(db,principal,table,id);
  for (const [table,rows] of Object.entries(after)) for (const [id,row] of rows) {
    if (before[table].has(id) && stable(before[table].get(id))===stable(row)) continue;
    if(!settings.resources[table]&&!principal.admin)for(const [field,target]of Object.entries(settings.tables[table].references)) {
      const [parent]=target.split('.');const value=before[table].get(id)?.[field];
      if(value!=null&&settings.resources[parent]) {const linked=ownedBefore.get(parent+":"+String(value));if(!linked||!sameBoundary(db,principal,linked.unit_id))throw new Failure(403,"Cross-boundary association mutation rejected");}
    }
    for (const [field,target] of Object.entries(settings.tables[table].references)) {
      const value=row[field]; if (value===null || value===undefined) continue;
      const [targetTable]=target.split(".");
      if (settings.resources[targetTable] && !principal.admin) {
        const owned=ownership(db,targetTable,String(value));
        if (!owned || !sameBoundary(db,principal,owned.unit_id)) throw new Failure(403,"Related record is outside active data boundary");
      }
      if (targetTable==="users" && !principal.admin && !db.prepare("SELECT 1 FROM user_ou_roles WHERE user_id=? AND unit_id=?").get(value,principal.unitId)) throw new Failure(403,"Related user is outside active unit");
    }
  }
}
function handlerDatabase(db: Database.Database): Database.Database {
  const facade = new Proxy(db, {get(target,property) {
    if(property==="prepare") return (sqlText:string) => {
      const normalized=sqlText.replace(/\/\*[\s\S]*?\*\//g," ").replace(/--[^\r\n]*/g," ").trim();
      if(!/^(SELECT|WITH|INSERT|UPDATE|DELETE|REPLACE)\b/i.test(normalized))throw new Failure(500,"Business handlers may execute parameterized data SQL only");
      const statement=target.prepare(sqlText);
      const wrapped=new Proxy(statement,{get(item,key) {
        if(key==="database")return facade;
        const value=Reflect.get(item,key,item);
        if(typeof value!=="function")return value;
        return (...args:unknown[])=>{const result=Reflect.apply(value,item,args);return result===item?wrapped:result;};
      }});
      return wrapped;
    };
    if(property==="inTransaction"||property==="open"||property==="name")return Reflect.get(target,property,target);
    throw new Failure(500,"Transaction, DDL and connection lifecycle are owned by the platform");
  }});
  return facade;
}
function errorResponse(error: unknown): ApiResponse {
  return error instanceof Failure ? {status:error.status,body:{error:error.message}} : {status:500,body:{error:"Backend operation failed"}};
}
export function businessRoute(db: Database.Database, aid: string, policy: RoutePolicy, handler: ApiHandler): RequestHandler {
  return (req,res) => { void exclusive(db,async()=>{
    let begun=false;
    try {
      const {principal,csrf:secret}=session(db,req); csrf(req,secret);
      for (const id of policy.security.features) {
        const feature=settings.features.find(f=>f.id===id);
        if (!feature || (!principal.admin && (feature.denied_usernames.includes(principal.username) || !feature.allowed_roles.some(role=>principal.roles.includes(role))))) throw new Failure(403,"Feature entitlement required");
      }
      const e=await enforcer(db,principal);
      const recordDenied=(message:string)=>new Failure(policy.security.record_denial_status??403,policy.security.record_denial_status===404?"Record not found":message);
      for (const permission of policy.security.permissions) if (!await permitted(db,e,principal,permission.resource,permission.action)) throw new Failure(403,"Operation permission denied");
      db.exec("BEGIN IMMEDIATE"); begun=true;
      db.exec('CREATE TEMP TABLE IF NOT EXISTS arc_allowed(resource TEXT,action TEXT,record_id TEXT,PRIMARY KEY(resource,action,record_id)); DELETE FROM arc_allowed;');
      const used=new Set<string>();
      const assignments=new Map<string,string>();
      const advanced=new Map<string,string>();
      const advancedAudits: Row[]=[];
      for (const permission of policy.security.permissions) {
        const rows=db.prepare("SELECT resource,record_id,unit_id,owner_id,assignee_id FROM record_access WHERE resource=?").all(permission.resource) as Ownership[];
        for (const row of rows) if (await permitted(db,e,principal,permission.resource,permission.action,row)) db.prepare("INSERT OR IGNORE INTO arc_allowed VALUES(?,?,?)").run(permission.resource,permission.action,row.record_id);
      }
      const access: BackendAccess={principal,
        scope(resource,action,keyColumn="id") {
          if (!policy.security.permissions.some(p=>p.resource===resource && p.action===action)) throw new Failure(403,"Undeclared scope request");
          used.add(resource);
          const column=keyColumn.split('.').map(quote).join('.');
          return principal.admin ? {sql:"1=1",params:[]} : {sql:`CAST(${column} AS TEXT) IN (SELECT record_id FROM arc_allowed WHERE resource=? AND action=?)`,params:[resource,action]};
        },
        async advance(mid,tid,id) {
          const binding=policy.workflow?.related_transitions?.find(b=>b.machine===mid&&b.transition===tid);
          const machine=settings.machines[mid],spec=machine?.transitions[tid];
          if(!binding||!machine||!spec)throw new Failure(403,"Undeclared related transition");
          const permission=policy.security.permissions.find(p=>p.resource===machine.entity&&p.action===spec.action);
          if(!permission)throw new Failure(403,"Related transition permission required");
          if(!before[machine.entity].has(id))registerRecord(db,principal,machine.entity,id);
          const owned=ownership(db,machine.entity,id);
          if(!principal.admin&&!owned)throw new Failure(403,"Related record has no ownership");
          if(!await permitted(db,e,principal,machine.entity,spec.action,owned))throw new Failure(403,"Related transition permission denied");
          if(!principal.admin&&spec.roles.length&&!spec.roles.some(role=>principal.roles.includes(role)))throw new Failure(403,"Related transition actor role denied");
          if(!principal.admin&&spec.assigned_only&&owned?.assignee_id!==principal.id)throw new Failure(403,"Related transition assignment required");
          const row=db.prepare(`SELECT ${quote(machine.state_field)} AS state FROM ${quote(machine.entity)} WHERE ${quote(resourceKey(machine.entity))}=?`).get(id) as {state:string}|undefined;
          if(!row)throw new Failure(404,"Related workflow record not found");
          if(!before[machine.entity].has(id)&&!advanced.has(machine.entity+":"+id)&&row.state!==machine.initial)throw new Failure(409,"Child record must start in initial state");
          const next=machineNext(machine,spec,row.state);
          const changed=db.prepare(`UPDATE ${quote(machine.entity)} SET ${quote(machine.state_field)}=? WHERE ${quote(resourceKey(machine.entity))}=? AND ${quote(machine.state_field)}=?`).run(next,id,row.state);
          if(changed.changes!==1)throw new Failure(409,"Concurrent related workflow change");
          advanced.set(machine.entity+":"+id,next);used.add(machine.entity);
          const audit={id:randomUUID(),machine:mid,record_id:id,event:spec.event,from_state:row.state,to_state:next,actor_id:principal.id,unit_id:principal.unitId,occurred_at:new Date().toISOString()};
          db.prepare("INSERT INTO workflow_audit(id,machine,record_id,event,from_state,to_state,actor_id,unit_id,occurred_at) VALUES(?,?,?,?,?,?,?,?,?)").run(audit.id,mid,id,spec.event,row.state,next,principal.id,principal.unitId,audit.occurred_at);
          advancedAudits.push(audit);
        },
        assign(resource,id,assigneeId,requiredRole) {
          if(!policy.workflow||resource!==policy.security.resource||id!==selected(request,policy.security.record_id)||!policy.assignment)throw new Failure(403,"Assignment must be an explicit workflow effect");
          const owned=ownership(db,resource,id);
          if(!owned||!sameBoundary(db,principal,owned.unit_id))throw new Failure(403,"Cannot assign an inaccessible record");
          const bindings=db.prepare("SELECT role_id FROM user_ou_roles WHERE user_id=? AND unit_id=?").all(assigneeId,owned.unit_id) as {role_id:string}[];
          if(!bindings.length||(requiredRole&&!bindings.some(r=>r.role_id===requiredRole)))throw new Failure(403,"Assignee lacks the required unit role");
          db.prepare("UPDATE record_access SET assignee_id=? WHERE resource=? AND record_id=?").run(assigneeId,resource,id);
          assignments.set(resource+":"+id,assigneeId);
        },
        register(resource,id) { if (!(policy.writeTables ?? []).includes(resource)) throw new Failure(403,"Undeclared resource creation"); registerRecord(db,principal,resource,id); },
      };
      const request: ApiRequest={params:Object.fromEntries(Object.entries(req.params).map(([k,v])=>[k,String(v)])),query:req.query,body:req.body??{},headers:Object.fromEntries(Object.entries(req.headers).map(([k,v])=>[k,Array.isArray(v)?v.join(','):v])),access:Object.freeze(access)};
      const recordId=selected(request,policy.security.record_id);
      if (recordId!==null && policy.security.resource) {
        const resource=policy.security.resource;
        const owned=ownership(db,resource,recordId);
        if (!principal.admin && !owned) throw recordDenied("Record has no trusted data ownership");
        for (const p of policy.security.permissions.filter(p=>p.resource===resource)) if (!await permitted(db,e,principal,p.resource,p.action,owned)) throw recordDenied("Record permission denied");
        used.add(resource);

      }
      const key=req.headers['idempotency-key'];
      if ((policy.workflow || policy.security.operation==="bulk") && (typeof key!=="string" || !key || key.length>128)) throw new Failure(400,"Idempotency-Key required");
      const receiptId=typeof key==="string"?hash(principal.id+':'+principal.unitId+':'+aid+':'+key):null;
      const requestHash=hash(stable({aid,params:request.params,query:request.query,body:request.body}));
      if (receiptId) {
        const old=db.prepare("SELECT request_hash,response FROM command_receipts WHERE id=?").get(receiptId) as {request_hash:string;response:string}|undefined;
        if (old) { if(old.request_hash!==requestHash) throw new Failure(409,"Idempotency key reused with different request"); db.exec('COMMIT');begun=false;return JSON.parse(old.response) as ApiResponse; }
      }
      if (recordId!==null && policy.security.resource) {
        const resource=policy.security.resource;
        const machine=Object.values(settings.machines).find(m=>m.entity===resource);
        if (machine) {
          const row=db.prepare(`SELECT ${quote(machine.state_field)} AS state FROM ${quote(resource)} WHERE ${quote(resourceKey(resource))}=?`).get(recordId) as {state:string}|undefined;
          if (!row) throw new Failure(404,"Record not found");
          for (const p of policy.security.permissions.filter(p=>p.resource===resource)) if (!(machine.state_actions[row.state]??[]).includes(p.action)) throw new Failure(409,"Operation is unavailable in current state");
        }
      }
      let flow: {machine:MachineSpec;spec:TransitionSpec;previous:string;next:string}|undefined;
      if (policy.workflow) {
        const machine=settings.machines[policy.workflow.machine],spec=machine?.transitions[policy.workflow.transition];
        if (!machine || !spec || recordId===null) throw new Failure(500,"Invalid compiled workflow binding");
        if(!principal.admin && spec.roles.length && !spec.roles.some(role=>principal.roles.includes(role)))throw new Failure(403,"Workflow actor role denied");
        if(!principal.admin && spec.assigned_only && ownership(db,machine.entity,recordId)?.assignee_id!==principal.id)throw new Failure(403,"Command requires current assignment");
        const row=db.prepare(`SELECT ${quote(machine.state_field)} AS state FROM ${quote(machine.entity)} WHERE ${quote(resourceKey(machine.entity))}=?`).get(recordId) as {state:string}|undefined;
        if (!row) throw new Failure(404,"Record not found");
        flow={machine,spec,previous:row.state,next:machineNext(machine,spec,row.state)};
      }
      const before=businessSnapshot(db);
      const auditBefore=db.prepare("SELECT * FROM workflow_audit ORDER BY id").all() as Row[];
      const ownedBefore=new Map((db.prepare("SELECT resource,record_id,unit_id,owner_id,assignee_id FROM record_access").all() as Ownership[]).map(row=>[row.resource+":"+row.record_id,row]));
      const protectedNames=["roles","user_ou_roles","org_units","auth_sessions","command_receipts","platform_meta","users"];
      const protectedBefore=new Map(protectedNames.map(name=>[name,db.prepare(`SELECT * FROM ${quote(name)} ORDER BY id`).all() as Row[]]));
      const response=await handler(request,handlerDatabase(db));
      if (!response || response.status<200 || response.status>=300) { db.exec('ROLLBACK');begun=false;return response; }
      const auditAfter=db.prepare("SELECT * FROM workflow_audit ORDER BY id").all() as Row[];
      const expectedAudit=[...auditBefore,...advancedAudits].sort((a,b)=>String(a.id)<String(b.id)?-1:String(a.id)>String(b.id)?1:0);
      if(stable(auditAfter)!==stable(expectedAudit))throw new Failure(403,"Workflow audit may only be written by the platform");
      for(const [name,rows] of protectedBefore) {
        const current=db.prepare(`SELECT * FROM ${quote(name)} ORDER BY id`).all() as Row[];
        if(stable(rows)===stable(current))continue;
        if(["auth_sessions","command_receipts","workflow_audit","platform_meta"].includes(name))throw new Failure(403,"Compiler-owned infrastructure cannot be changed by a business handler");
        if(!principal.admin) {
          if(name!=="users"||current.length!==rows.length)throw new Failure(403,"Administrative role required for identity changes");
          for(let i=0;i<rows.length;i++)if(stable(rows[i])!==stable(current[i])) {
            if(rows[i].id!==principal.id||Object.keys(current[i]).some(k=>k!=="password_hash"&&stable(current[i][k])!==stable(rows[i][k]))||!/^scrypt\$[a-f0-9]{32}\$[a-f0-9]{128}$/.test(String(current[i].password_hash)))throw new Failure(403,"Only your own password hash may be changed");
          }
        }
        if(!(policy.writeTables ?? []).includes(name))throw new Failure(500,"Undeclared identity mutation");
      }
      for(const [key,old] of ownedBefore) {
        const current=ownership(db,old.resource,old.record_id);
        if(!current|| (stable(current)!==stable(old) && !(assignments.get(key)===current.assignee_id&&stable({...current,assignee_id:old.assignee_id})===stable(old))))throw new Failure(403,"Existing ownership cannot be rewritten by business SQL");
      }
      const createdOwnership=db.prepare("SELECT resource,record_id,unit_id,owner_id,assignee_id FROM record_access").all() as Ownership[];
      for(const row of createdOwnership)if(!ownedBefore.has(row.resource+":"+row.record_id)&&(row.unit_id!==principal.unitId||row.owner_id!==principal.id||row.assignee_id!==null))throw new Failure(403,"Ownership must come from trusted creation context");
      validateWrites(db,principal,policy,before,ownedBefore,advanced);
      if (!principal.admin) for (const table of new Set((policy.readResources ?? []).filter(t=>settings.resources[t]))) if (!used.has(table)) throw new Failure(500,"Business query omitted its required access scope");
      if (flow && policy.workflow) {
        const changed=db.prepare(`UPDATE ${quote(flow.machine.entity)} SET ${quote(flow.machine.state_field)}=? WHERE ${quote(resourceKey(flow.machine.entity))}=? AND ${quote(flow.machine.state_field)}=?`).run(flow.next,recordId,flow.previous);
        if(changed.changes!==1) throw new Failure(409,"Concurrent workflow change");
        db.prepare("INSERT INTO workflow_audit(id,machine,record_id,event,from_state,to_state,actor_id,unit_id,occurred_at) VALUES(?,?,?,?,?,?,?,?,?)").run(randomUUID(),policy.workflow.machine,recordId,flow.spec.event,flow.previous,flow.next,principal.id,principal.unitId,new Date().toISOString());
      }
      if(receiptId) db.prepare("INSERT INTO command_receipts(id,request_hash,response) VALUES(?,?,?)").run(receiptId,requestHash,JSON.stringify(response));
      db.exec('COMMIT');begun=false;return response;
    } catch(error) { if(begun) db.exec('ROLLBACK'); return errorResponse(error); }
  }).then(response=>{ if(!response) {res.status(500).json({error:"Invalid API response"});return;} for(const [key,value] of Object.entries(response.headers??{})) res.setHeader(key,value);res.status(response.status).send(response.body); }).catch(()=>res.status(500).json({error:"Backend operation failed"})); };
}
export function bootstrapOwnership(db: Database.Database): void {
  if(db.prepare("SELECT 1 FROM platform_meta WHERE id='ownership_initialized'").get()) return;
  const units=db.prepare("SELECT id FROM org_units").all() as {id:string}[];
  if(units.length===1) for(const [resource,spec] of Object.entries(settings.resources)) for(const row of db.prepare(`SELECT ${quote(spec.key)} AS id FROM ${quote(resource)}`).all() as {id:string}[]) {
    db.prepare("INSERT INTO record_access(id,resource,record_id,unit_id,owner_id,assignee_id) SELECT ?,?,?,?,NULL,NULL WHERE NOT EXISTS(SELECT 1 FROM record_access WHERE resource=? AND record_id=?)").run(randomUUID(),resource,String(row.id),units[0].id,resource,String(row.id));
  }
  db.prepare("INSERT INTO platform_meta(id,value) VALUES('ownership_initialized','1')").run();
}
export function registerPlatformAuth(app: Express, db: Database.Database): void {
  const route=(work:(req:Request)=>ApiResponse):RequestHandler=>(req,res)=>{void exclusive(db,async()=>{try{return work(req);}catch(error){return errorResponse(error);}}).then(result=>{for(const [k,v]of Object.entries(result.headers??{}))res.setHeader(k,v);res.status(result.status).send(result.body);}).catch(()=>res.status(500).json({error:"Authentication operation failed"}));};
  app.post('/api/auth/login',route(req=>{
    sameOrigin(req);
    const {username,password,unit}=req.body??{};
    if(typeof username!=="string"||typeof password!=="string"||password.length>4096)throw new Failure(400,"Account/password required");
    const user=db.prepare("SELECT id,username,password_hash FROM users WHERE username=?").get(username) as {id:string;username:string;password_hash:string}|undefined;
    let valid=false;
    if(user) {const [format,salt,digest]=user.password_hash.split('$');if(format==='scrypt'&&/^[a-f0-9]{32}$/i.test(salt??'')&&/^[a-f0-9]{128}$/i.test(digest??'')){const actual=scryptSync(password,Buffer.from(salt,'hex'),64);valid=timingSafeEqual(actual,Buffer.from(digest,'hex'));}}
    if(!valid||!user)throw new Failure(401,"Invalid account or password");
    const memberships=db.prepare("SELECT DISTINCT u.id,u.code FROM org_units u JOIN user_ou_roles r ON r.unit_id=u.id WHERE r.user_id=? ORDER BY u.code").all(user.id) as {id:string;code:string}[];
    const active=unit?memberships.find(u=>u.id===unit||u.code===unit):memberships[0];if(!active)throw new Failure(403,"No role in requested unit");
    const opaque=randomBytes(32).toString('hex'),secret=randomBytes(32).toString('hex');
    db.prepare("INSERT INTO auth_sessions(id,user_id,unit_id,csrf_token,expires_at) VALUES(?,?,?,?,?)").run(hash(opaque),user.id,active.id,secret,new Date(Date.now()+86400000).toISOString());
    return {status:200,body:{user:{id:user.id,username:user.username,unitId:active.id},csrfToken:secret},headers:{'set-cookie':`arc_session=${opaque}; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400${req.secure?'; Secure':''}`}};
  }));
  app.get('/api/auth/me',route(req=>{const {principal,csrf:secret}=session(db,req);return{status:200,body:{user:principal,csrfToken:secret}};}));
  app.post('/api/auth/logout',route(req=>{const current=session(db,req);csrf(req,current.csrf);db.prepare("DELETE FROM auth_sessions WHERE id=?").run(hash(token(req)));return{status:200,body:{ok:true},headers:{'set-cookie':'arc_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'}};}));
}
