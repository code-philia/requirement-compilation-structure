export interface Principal { id: string; username: string; unitId: string; roles: string[]; admin: boolean }
export interface BackendAccess {
  principal: Principal;
  scope(resource: string, action: string, keyColumn?: string): { sql: string; params: string[] };
  register(resource: string, id: string): void;
  advance(machine: string, transition: string, recordId: string): Promise<void>;
  assign(resource: string, id: string, assigneeId: string, requiredRole?: string): void;
}
export interface SecurityContract {
  mode: "session" | "policy";
  permissions: {resource: string; action: string}[];
  features: string[];
  resource: string | null;
  record_id: string | null;
  action: string | null;
  operation: "read" | "create" | "update" | "delete" | "command" | "bulk";
}
export interface ApiContract {
  security: SecurityContract;
  workflow: null | { machine: string; transition: string; record_id: string; guard_bindings: Record<string,string>; effect_bindings: Record<string,string>; related_transitions?: {machine:string;transition:string;guard_bindings:Record<string,string>;effect_bindings:Record<string,string>}[] };
  read: string[]; write: string[];
}
export interface TransitionSpec {
  roles: string[]; assigned_only: boolean;
  action: string;
  event: string; from: string[]; to: string; process_refs: string[]; requirements: string[];
  guards: {id: string; description: string}[];
  effects: {id: string; description: string; fields: string[]}[];
}
export interface MachineSpec {
  entity: string; state_field: string; initial: string; states: string[]; requirements: string[];
  state_actions: Record<string,string[]>;
  transitions: Record<string,TransitionSpec>;
}
export interface PlatformSettings {
  model: string; policy: string;
  resources: Record<string,{key:string;references:Record<string,string>}>;
  tables: Record<string,{key:string;references:Record<string,string>}>;
  boundary: "none" | "unit" | "unit_tree";
  features: {id:string;allowed_roles:string[];denied_usernames:string[]}[];
  machines: Record<string,MachineSpec>;
}
