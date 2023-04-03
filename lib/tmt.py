"""
Functions and helpers for result management when working with TMT, the test
execution framework (https://github.com/teemtee/tmt).

TMT has a 'result:custom' feature (in test's main.fmf), which allows us to
supply completely custom results as a YAML file, and TMT will use it as-is
to represent a result from the test itself, and any results "under" it,
effectively allowing a test to report more than 1 result.
"""

import os
import re
import logging
import shutil
import textwrap
from pathlib import Path

import util

_log = logging.getLogger(__name__).debug

_valid_results = ['pass', 'fail', 'warn', 'error', 'info']

RESULTS_FILE = 'results.yaml'


def _compose_results_yaml(keyvals):
    """
    Trivial hack to output simple YAML without a PyYAML depedency.
    """
    def printval(x):
        if type(x) is list:
            # python str(list) format is compatible with YAML
            return str(x)
        else:
            # account for name/note having complex content
            x = x.replace('"', '\\"')
            return f'"{x}"'
    it = iter(keyvals.items())
    # prefix first item with '-'
    key, value = next(it)
    out = f'- {key}: {printval(value)}\n'
    for key, value in it:
        out += f'  {key}: {printval(value)}\n'
    return out


def _sanitize_yaml_id(string):
    """
    Remove anything that shouldn't appear in a YAML identifier (ie. key name),
    whether the limitation comes from YAML itself, or its use by TMT.
    """
    return re.sub('[^\w/ _-]', '', string, flags=re.A).strip()


# TODO: dict() support for logs, key as filename, value as log contents ?
def report(result, name=None, note=None, logs=None):
    """
    Report a TMT result.

    'name' will be appended to the currently running test name,
    allowing the test to report one or more sub-results.
    It should always start with '/'.
    If empty, result for the test itself is reported.

    'logs' is a list of file paths (relative to CWD) to be copied
    over to the TMT test data directory and associated with the
    new result.
    """

    if result not in _valid_results:
        raise SyntaxError(f"{result} is not a valid result")
    if name and name[0] != '/':
        raise SyntaxError("name must start with a slash")
    if not name:
        name = '/'  # https://github.com/teemtee/tmt/issues/1855

    name = _sanitize_yaml_id(name)

    new_result = {
        'name': name,
        'result': result,
    }
    if note:
        new_result['note'] = util.make_printable(note)

    test_data = Path(os.environ['TMT_TEST_DATA'])

    # copy logs to tmt test data dir
    if logs:
        log_entries = []
        for log in logs:
            log = Path(log)
            # put logs into a name-based subdir tree inside the data dir,
            # so that multiple results can have the same log names
            dst = test_data / name[1:]
            dst.mkdir(parents=True, exist_ok=True)
            dstfile = dst / log.name
            _log(f"copying log {log} to {dstfile}")
            shutil.copyfile(log, dstfile)
            log_entries.append(str(dstfile.relative_to(test_data)))
        new_result['log'] = log_entries

    yaml_addition = _compose_results_yaml(new_result)
    _log(f"appending to results:\n{textwrap.indent(yaml_addition.rstrip(), '  ')}")

    with open(test_data / RESULTS_FILE, 'a') as f:
        f.write(yaml_addition)
