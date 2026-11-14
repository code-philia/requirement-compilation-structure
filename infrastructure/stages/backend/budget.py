"""One backend budget: compile/fix iterations; legacy configuration names are retained."""

from dataclasses import dataclass
import os

READ_TOOLS = {'get_capabilities','search_capabilities','retrieve_schema',
    'read_file','list_files','search_files','bash'}


@dataclass
class BackendBudget:
    max_test_iterations: int = 10
    test_iterations: int = 0
    calls: int = 0
    reads: int = 0

    @classmethod
    def from_environment(cls):
        try:
            value = int(os.getenv('BACKEND_TEST_ITERATIONS','10'))
        except ValueError as error:
            raise ValueError('BACKEND_TEST_ITERATIONS must be a positive integer') from error
        if value < 1:
            raise ValueError('BACKEND_TEST_ITERATIONS must be a positive integer')
        return cls(value)

    def state(self):
        return {'test_iterations':self.test_iterations,'test_iteration_limit':self.max_test_iterations,
            'compile_iterations':self.test_iterations,'compile_iteration_limit':self.max_test_iterations,
            'model_calls':self.calls,'read_batches':self.reads,
            'policy':'Compilation/build repair attempts consume the budget; cached passing publication is free. No generated self-tests run. Cached failures count retries without rerunning commands.'}
