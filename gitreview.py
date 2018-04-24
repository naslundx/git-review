#! /usr/bin/env python3

import subprocess
import re
import argparse
import sys
import shutil
import os
from collections import Counter


# run(): Run the analysis, return the output
# get_score(output): Extract the score as float
# match_errors(before, after): Find difference in errors, return map name:occurences
# relevant_line(line): return True if relevant file type is on this line (.*\.py\s for pylint)

class Analysis_Pylint:
    def __init__(self, cwd, target):
        self.cwd = cwd
        self.target = target
        shutil.copyfile('pylint.rc', os.path.join(cwd, 'pylint.rc'))

    def run(self):
        output = run_process("pylint -j4 {} --rcfile=pylint.rc".format(self.target), self.cwd, False)
        output = [line for line in output.split('\n') if line.strip()]
        return output

    def get_score(self, output):
        match = re.match(r'.*(\d\.\d\d)/10.*', output[-1])
        score = -100.0
        if match:
            score = float(match.groups()[0])
        return score

    def _get_errors(self, output):
        result = []
        for line in output:
            match = re.match(r'.*\((.+)\)$', line.strip())
            if match and "previous run" not in line:
                result.append(match.groups()[0])
        return result

    def match_errors(self, before, after):
        before_errors = Counter(self._get_errors(before))
        after_errors = Counter(self._get_errors(after))

        diff_errors = {}
        for name in after_errors:
            if name not in before_errors:
                diff = after_errors[name]
            else:
                diff = after_errors[name] - before_errors[name]

            if diff != 0:
                diff_errors[name] = diff

        for name in before_errors:
            if name not in diff_errors and name not in after_errors:
                diff_errors[name] = -before_errors[name]

        return diff_errors

    def relevant_line(self, line):
        return re.match(r'.*\.py\s', line)


class Analysis_Cppcheck:
    def __init__(self, cwd, target):
        self.cwd = cwd
        self.target = target

    def run(self):
        output = run_process("cppcheck {} --enable=all --inline-suppr".format(self.target), self.cwd, False)
        print(output)
        output = [line for line in output.split('\n') if line.strip()]
        return output

    def get_score(self, output):
        return 10.0 - len(output) / 10.0

    def _get_errors(self, output):
        result = []
        for line in output:
            match = re.match(r'.*\d\]: \((.+)\) ', line.strip())
            if match:
                result.append(match.groups()[0])
        return result

    def match_errors(self, before, after):
        before_errors = Counter(self._get_errors(before))
        after_errors = Counter(self._get_errors(after))

        diff_errors = {}
        for name in after_errors:
            if name not in before_errors:
                diff = after_errors[name]
            else:
                diff = after_errors[name] - before_errors[name]

            if diff != 0:
                diff_errors[name] = diff

        return diff_errors

    def relevant_line(self, line):
        return re.match(r'.*\.cpp\s', line) or re.match(r'.*\.hpp\s', line)


def check_stats(diff, tool):
    total = 0
    for line in diff:
        if tool.relevant_line(line):
            chg_match = re.match(r'.*\s\|\s(\d+)\s', line)
            if chg_match:
                total += int(chg_match.groups()[0])

    return total


def run_process(command, cwd, check=True):
    proc = subprocess.run(command, cwd=cwd, shell=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    return str(proc.stdout)


def assemble_errors(errors):
    result = {}
    for error in errors:
        for name in error:
            occurences = error[name]
            if name not in result:
                result[name] = []
            result[name].append(occurences)

    return result


def output_stats(stats):
    print("\n>>> Combined stats:")
    for author in stats:
        results = stats[author]
        score = sum([d for (d, _, _) in results])
        changes = sum([l_c for (_, l_c, _) in results])
        errors = assemble_errors([e for (_, _, e) in results])

        print("")
        print(author)
        print("Average score: {0:.3f}".format(score))
        print("Total changes: {}".format((changes)))
        print("Score / changes: {0:.5f}".format(score / changes))
        print("Errors: ", errors)


def review(options):
    stats = {}
    diff_errors = {}

    if options.tool == 'pylint':
        tool = Analysis_Pylint(options.cwd, options.target)
    elif options.tool == 'cppcheck':
        tool = Analysis_Cppcheck(options.cwd, options.target)
    else:
        print('Unrecognized tool: {}'.format(options.tool))
        return 1

    after_output = before_output = tool.run()
    after_score = before_score = tool.get_score(after_output)

    for i in range(options.iterations):
        print("\n=== Iteration {} ===".format(i))

        # get author
        author = run_process("git log -1 --pretty=format:'%an'", options.cwd)

        # get commit hash
        commit = run_process("git rev-parse HEAD", options.cwd)

        # get stats
        diff = run_process("git diff HEAD HEAD~1 --stat", options.cwd)
        diff = [line.strip() for line in diff.split('\n') if line.strip()]
        lines_changed = check_stats(diff, tool)

        # revert latest commit
        run_process("git reset --hard HEAD~1", options.cwd)

        # update the score if python scripts changed
        if lines_changed > 0:
            before_output = tool.run()
            before_score = tool.get_score(before_output)
            diff_errors = tool.match_errors(before_output, after_output)

        # compute the diff
        diff = after_score - before_score

        # No need to recompute
        after_output = before_output
        after_score = before_score

        print(author, lines_changed, "{0:.2f}".format(before_score), commit)

        # Keep going if nothing new happened or no lines changed
        if lines_changed <= 0:
            continue

        # Update stats
        new_data = (diff, lines_changed, diff_errors)
        if author in stats:
            stats[author].append(new_data)
        else:
            stats[author] = [new_data]
        print(stats)

    output_stats(stats)
    return 0


def main():
    arg_parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    arg_parser.epilog = "Git review."
    format_group = arg_parser.add_argument_group("Options")
    format_group.add_argument(
        "--cwd",
        default=".",
        help="Directory to execute in")
    format_group.add_argument(
        "--iterations",
        default='10',
        action='store',
        help="Iterations to perform")
    format_group.add_argument(
        "--tool",
        default='pylint',
        action='store',
        help='Which tool to use'
    )
    format_group.add_argument(
        "target",
        default=[],
        nargs="*")

    options = arg_parser.parse_args(sys.argv[1:])
    options.iterations = int(options.iterations)

    if not options.target:
        if options.tool == 'pylint':
            options.target = ['*.py', '**/*.py']
        elif options.tool == 'cppcheck':
            options.target = ['*.cpp', '*.hpp']

    options.target = ' '.join(options.target)
    return review(options)


if __name__ == "__main__":
    sys.exit(main())
