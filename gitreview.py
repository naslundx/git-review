#! /usr/bin/env python3

import subprocess
import re
import argparse
import sys
import shutil
import os
from collections import Counter


def run_pylint(target, cwd):
    pylint_proc = subprocess.run("pylint -j4 {} --rcfile=pylint.rc".format(target), cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    output = [line for line in pylint_proc.stdout.split('\n') if line.strip()]
    return output


def get_pylint_score(output):
    match = re.match(r'.*(\d\.\d\d)/10.*', output[-1])
    score = -100.0
    if match:
        score = float(match.groups()[0])
    return score


def match_pylint_errors(before, after):
    before_errors = []
    after_errors = []
    for line in before:
        py_match = re.match(r'.*\((.+)\)$', line.strip())
        if py_match and "previous run" not in line:
            before_errors.append(py_match.groups()[0])
    for line in after:
        py_match = re.match(r'.*\((.+)\)$', line.strip())
        if py_match and "previous run" not in line:
            after_errors.append(py_match.groups()[0])

    before_errors = Counter(before_errors)
    after_errors = Counter(after_errors)

    diff_errors = {}
    for name in after_errors:
        if name not in before_errors:
            diff = after_errors[name]
        else:
            diff = after_errors[name] - before_errors[name]

        if diff != 0:
            diff_errors[name] = diff

    return diff_errors


def check_stats(cwd):
    stats_proc = subprocess.run("git diff HEAD HEAD~1 --stat", cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    output = [line.strip() for line in stats_proc.stdout.split('\n') if line.strip()]

    total = 0
    for line in output:
        py_match = re.match(r'.*\.py\s', line)
        if py_match:
            chg_match = re.match(r'.*\s\|\s(\d+)\s', line)
            if chg_match:
                total += int(chg_match.groups()[0])

    return total


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
    after_output = run_pylint(options.target, options.cwd)
    before_output = after_output
    after_score = get_pylint_score(after_output)
    before_score = after_score

    for i in range(options.iterations):
        print("\n=== Iteration {} ===".format(i))

        # get author
        author_proc = subprocess.run("git log -1 --pretty=format:'%an'", cwd=options.cwd, shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
        author = str(author_proc.stdout)

        # get commit hash
        hash_proc = subprocess.run("git rev-parse HEAD", cwd=options.cwd, shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
        commit = str(hash_proc.stdout)

        # get stats
        lines_changed = check_stats(options.cwd)

        # revert latest commit
        subprocess.run("git reset --hard HEAD~1", cwd=options.cwd, shell=True, check=True, stdout=subprocess.PIPE)

        # update the score if python scripts changed
        if lines_changed > 0:
            before_output = run_pylint(options.target, options.cwd)
            before_score = get_pylint_score(before_output)
            diff_errors = match_pylint_errors(before_output, after_output)

        # compute the diff
        diff = after_score - before_score

        # No need to recompute
        after_output = before_output
        after_score = before_score

        print(author, lines_changed, "{0:.2f}".format(before_score), commit)

        # Keep going if nothing new happened or no lines changed
        if abs(diff) < 0.005 or lines_changed == 0:
            continue

        # Update stats
        new_data = (diff, lines_changed, diff_errors)
        if author in stats:
            stats[author].append(new_data)
        else:
            stats[author] = [new_data]
        print(stats)

    output_stats(stats)


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
        default='100',
        action='store',
        help="Iterations to perform")
    format_group.add_argument(
        "target",
        default=["*.py", "**/*.py"],
        nargs="*")

    options = arg_parser.parse_args(sys.argv[1:])
    options.target = ' '.join(options.target)
    options.iterations = int(options.iterations)
    shutil.copyfile('pylint.rc', os.path.join(options.cwd, 'pylint.rc'))
    review(options)


if __name__ == "__main__":
    main()
