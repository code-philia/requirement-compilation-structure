"""Native scoped file implementation with real initialization feedback."""

from copy import deepcopy
import hashlib
import json

from infrastructure.shared.agent import AgentTool, BaseAgent, AgentLoopExhausted
from infrastructure.shared.agent.feedback import compact_feedback
from infrastructure.shared.agent.tools import FileToolError
from infrastructure.shared.models.streaming import IncompleteModelStreamError
from infrastructure.utils.presentation.console import DemoConsole


class DatabaseFileAgent(BaseAgent):
    def __init__(self, instructions, files, gate, *, feedback_filter=None, **options):
        super().__init__(**options)
        self.instructions, self.files, self.gate = instructions, files, gate
        self.feedback_filter = feedback_filter or compact_feedback
        self.accepted = None
        self.last_feedback = None

    def build_system_prompt(self):
        return self.instructions + """
Use the advertised NATIVE function tools; do not serialize tool calls in response text.
Implement promptly from supplied files, schema and evidence. Batch independent reads;
do not reread unchanged supplied files or search without a named missing dependency.
Use edit_file for all persistent writes; file scope is enforced by the existing tools.
Use local exact-span replacements in shared files and preserve unrelated behavior.
When implementation is ready call finish_implementation. Its real result decides whether
this task is complete. On failure repair the reported cause and call it again. Do not
claim completion in text, suppress an initialization failure or weaken expected behavior.
Return independent edit_file calls together, rather than limiting each response to one
or two files. When all required files are ready, include finish_implementation as the
LAST call in the SAME response. Do not spend another model turn just to announce completion.
edit_file arguments are path, operation, new_content and optional old_content; they are
native function arguments, never wrapped in an arguments/tool_calls JSON text object.
"""

    def build_user_prompt(self, input):
        self._known_task = deepcopy(input)
        self._known_scope = deepcopy(self.files.scope_state())
        self._known_files = deepcopy(self.files.state())
        return {"task": input, "scope": self._known_scope, "files": self._known_files}

    def _context_updates(self):
        """Retain the conversation; send only newly selected or changed context."""
        files, scope = self.files.state(), self.files.scope_state()
        result = {"files": {path: record for path, record in files.items()
            if self._known_files.get(path) != record},
            "task_updates": {key: value for key, value in self.task.items()
                if key not in self._known_task or self._known_task[key] != value}}
        if scope != self._known_scope:
            result['scope'] = scope
        self._known_files, self._known_scope, self._known_task = deepcopy(files), deepcopy(scope), deepcopy(self.task)
        return {key: value for key, value in result.items() if value}

    def build_tools(self):
        tools = []
        for schema in self.files.schemas():
            name = schema["tool"]
            if name not in {"read_file", "list_files", "search_files", "edit_file"}:
                continue
            parameters = deepcopy(schema["parameters"])
            parameters["properties"].pop("tool", None)
            parameters["required"] = [key for key in parameters["required"] if key != "tool"]

            def bind_handler(tool_name):
                def execute(**arguments):
                    adapted = {}
                    if tool_name == "edit_file":
                        self.accepted = None
                        # Unambiguous common aliases do not need a wasted model round.
                        # Canonical arguments, scope and exact-span checks still apply.
                        for old, new in [('new_string', 'new_content'), ('old_string', 'old_content')]:
                            if old in arguments and new not in arguments:
                                arguments[new] = arguments.pop(old)
                                adapted[old] = new
                    try:
                        result = self.files.execute([{"tool": tool_name, **arguments}])
                        if tool_name == 'edit_file':
                            for change in self.files.last_changes:
                                if change['before'] != change['after']:
                                    version = (change['path'], hashlib.sha256(change['after'].encode()).hexdigest())
                                    if version not in self._seen_writes:
                                        self._turn_progress = True
                                        self._seen_writes.add(version)
                        if any('error' in item for item in result):
                            self._turn_failed = True
                            self.last_feedback = next(item['error'] for item in result if 'error' in item)
                        return {'results': result, 'normalized_arguments': adapted} if adapted else result
                    except FileToolError as error:
                        self._turn_failed = True
                        self.last_feedback = error.feedback
                        return {"status": "NEEDS_REPAIR", "feedback": error.feedback}
                return execute

            # Native protocol wording must not teach the old JSON tool envelope.
            description = schema["description"].replace("in diagnosis.reason", "briefly in your explanation").replace(
                "using separate read_file entries in one tool_calls array (at most eight context calls total)",
                "using several native read_file calls in the same response")
            if name == 'edit_file' and getattr(self.files, 'replaceable_files', None):
                description = ("Create or edit a scoped file using exact old_content. Full replacement is allowed only "
                    "for explicitly task-owned table SQL and the seed evidence manifest; other files require local edits.")
            tools.append(AgentTool(name, description, parameters, bind_handler(name)))
        tools.append(AgentTool("finish_implementation", "Run the task's real publication/initialization checks and receive repair feedback.",
            {"type": "object", "properties": {}, "additionalProperties": False}, self.finish))
        return tools

    def finish(self):
        try:
            result = self.gate()
        except (ValueError, RuntimeError) as error:
            self._turn_failed = True
            feedback = self.feedback_filter(getattr(error, "feedback", {"error": str(error)}))
            self.last_feedback = feedback
            self.accepted = None
            return {"status": "NEEDS_REPAIR", "feedback": feedback,
                **self._context_updates()}
        self.accepted = result
        return {"status": "GREEN", "checks": result}

    def run(self, input, max_turns=10, feedback=None, console=None, label="Database implementation"):
        if max_turns < 1:
            raise ValueError("max_turns must be positive")
        self.accepted, self.last_feedback, self.task = None, None, input
        self._seen_writes = set()
        self._turn_progress = self._turn_failed = False
        # Filters can select relevant schema/files before building the first prompt.
        initial = self.feedback_filter(feedback) if feedback is not None else None
        self.start(input)
        for path, record in self._known_files.items():
            if record.get('content') is not None:
                self._seen_writes.add((path, hashlib.sha256(record['content'].encode()).hexdigest()))
        if initial is not None:
            self.messages.append({"role": "user", "content": json.dumps(
                {"repair_feedback": initial}, ensure_ascii=False)})
        console = console or DemoConsole(False)
        # One-file-at-a-time progress can still finish a coordinated seed task.
        # This is an upper bound, not a requested response/file split.
        implementation_limit = max_turns
        if getattr(self, 'kind', None) == 'seeds':
            implementation_limit = max(max_turns, len(input.get('insert_files', {})) + 1)
        repair_limit, discovery_limit, idle_limit = max_turns, 2, 3
        maximum = implementation_limit + repair_limit + discovery_limit + idle_limit
        counters = {'implementation': 0, 'repair': 0, 'discovery': 0}
        idle, stop_reason = 0, 'bounded model-call budget reached'
        for turn in range(1, maximum + 1):
            self._turn_progress = self._turn_failed = False
            repair_only = counters['implementation'] >= implementation_limit
            remaining = {'implementation': max(0, implementation_limit-counters['implementation']),
                'repair': repair_limit-counters['repair'],
                'discovery': max(0, discovery_limit-counters['discovery'])}
            console.show(f"{label} | Native agent {turn}/{maximum}",
                f"Remaining rounds: implementation={remaining['implementation']}, repair={remaining['repair']}, "
                f"discovery={remaining['discovery']}. Batch writes and finish in the same response.")
            self.messages.append({'role': 'user', 'content': json.dumps({
                'round_budget': remaining,
                'next_action': ('Call finish_implementation now to identify any concrete remaining gaps; '
                    'further changes use the repair budget.' if repair_only else
                    'Use the supplied evidence to batch all ready file edits; include the manifest and '
                    'finish_implementation last when complete. Do not stop after an arbitrary one or two files.')}, ensure_ascii=False)})
            try:
                message = self.step(tool_choice="auto")
            except (ValueError, IncompleteModelStreamError) as error:
                counters['repair'] += 1
                self.last_feedback = {'error': str(error), 'error_type': type(error).__name__}
                self.messages.append({"role": "user", "content": str(error) + " Return a smaller complete native tool batch."})
            else:
                if message.tool_calls:
                    results = self.execute_tools(message)
                    self._turn_failed |= any(not json.loads(item['content']).get('ok', False) for item in results)
                if self.accepted is not None:
                    return {"status": "GREEN", "turns": turn, "rounds": counters, "checks": self.accepted}
                if self._turn_progress:
                    counters['repair' if repair_only else 'implementation'] += 1
                    if self._turn_failed and not repair_only:
                        counters['repair'] += 1
                    idle = 0
                elif self._turn_failed:
                    counters['repair'] += 1
                    idle = 0
                else:
                    counters['discovery'] += 1
                    idle += 1
                    if not message.tool_calls:
                        self.messages.append({"role": "user", "content":
                            "A text-only answer is not completion. Publish required files and call finish_implementation."})
                    if counters['discovery'] >= discovery_limit:
                        self.tools.pop('list_files', None)
                        self.tools.pop('search_files', None)
                        self.messages.append({"role": "user", "content":
                            "Discovery budget used. Use retained contents, read only a named missing span, "
                            "then batch edits or call finish_implementation for a concrete gap. No broad rescanning."})
            if counters['repair'] >= repair_limit:
                stop_reason = 'repair budget exhausted'
                break
            if idle >= idle_limit:
                stop_reason = 'consecutive rounds without edits or executable failure feedback'
                break
        error = AgentLoopExhausted(f"{label}: {stop_reason} after {turn} model calls; "
            f"rounds={counters}; files remain available for repair")
        error.turns, error.feedback, error.rounds = turn, self.last_feedback, counters
        raise error


def run_database_agent(model, instructions, task, files, gate, max_turns, console, label,
        feedback=None, feedback_filter=None):
    """Keep stage ownership while adapting existing scoped file tools to native calls."""
    return DatabaseFileAgent(instructions, files, gate, model=model,
        feedback_filter=feedback_filter).run(task, max_turns=max_turns,
            feedback=feedback, console=console, label=label)


class DatabaseImplementationAgent(DatabaseFileAgent):
    """Explicit task identity for batched tables, source seed SQL or runtime repair."""

    def __init__(self, kind, instructions, files, gate, **options):
        if kind not in {'tables', 'seeds', 'runtime'}:
            raise ValueError('Unknown database implementation task kind: ' + str(kind))
        self.kind = kind
        super().__init__(instructions, files, gate, **options)
        # These artifacts have one coordinated owner and independent real checks.
        # Shared application code and per-table seed records keep local-edit rules.
        self.files.replaceable_files = {path for path in (files.writable or set())
            if path.startswith('backend/src/db/tables/') and path.endswith('.sql')}
        if kind in {'seeds', 'runtime'}:
            self.files.replaceable_files.add('backend/src/db/seed-evidence.json')
        self.logger.name = type(self).__name__ + ':' + kind

    def build_system_prompt(self):
        instructions = super().build_system_prompt()
        if self.kind == 'seeds':
            instructions += """
COORDINATED SEED TASK
The task already supplies explicit source records, canonical DDL, insertion file paths,
existing insertion contents and the manifest path. Do not rediscover directories,
search for loaders/package configuration or inspect unrelated platform internals.
Use read_file only for a concrete omitted/changed span necessary for a repair.
Batch related parent and child INSERT edits together. Submit all ready edits in a
response; for small files aim for several files together instead of one or two.
Use additional responses only when the work genuinely needs another output batch.
The deliverable includes BOTH insertion SQL and the COMPLETE seed evidence manifest.
Write the manifest and call finish_implementation last in the final edit batch.
Keep explanations concise; spend the response on actual edits and source bindings.
Successful changed-file rounds have an implementation budget sized from this task's
insertion files; failed calls/checks have a separate repair budget. Do not exhaust
either by repeating discovery or changing files without a concrete purpose.
"""
        return instructions

    def build_user_prompt(self, input):
        return {"database_task": self.kind, **super().build_user_prompt(input)}
