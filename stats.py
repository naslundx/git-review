#! /usr/bin/env python3

import subprocess
import re
from collections import Counter

DIRECTORY = "bridge/"
PATH = "*.py **/*.py"
ITERATIONS = 100


def run_pylint():
    pylint_proc = subprocess.run("pylint -j4 {} --rcfile=../pylint.rc".format(PATH), cwd=DIRECTORY, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
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
            diff = after_errors[name] - before_errors[name]  # or max(0, ???)

        if diff != 0:
            diff_errors[name] = diff

    return diff_errors


def check_stats():
    stats_proc = subprocess.run("git diff HEAD HEAD~1 --stat", cwd=DIRECTORY, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
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


def main():
    stats = {}
    diff_errors = {}
    after_output = run_pylint()
    before_output = after_output
    after_score = get_pylint_score(after_output)
    before_score = after_score

    for i in range(ITERATIONS):
        print("\n=== Iteration {} ===".format(i))

        # get author
        author_proc = subprocess.run("git log -1 --pretty=format:'%an'", cwd=DIRECTORY, shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
        author = str(author_proc.stdout)

        # get commit hash
        hash_proc = subprocess.run("git rev-parse HEAD", cwd=DIRECTORY, shell=True, check=True, stdout=subprocess.PIPE, universal_newlines=True)
        commit = str(hash_proc.stdout)

        # get stats
        lines_changed = check_stats()

        # revert latest commit
        subprocess.run("git reset --hard HEAD~1", cwd=DIRECTORY, shell=True, check=True, stdout=subprocess.PIPE)

        # update the score if python scripts changed
        if lines_changed > 0:
            before_output = run_pylint()
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

    print('\n')
    output_stats(stats)


if __name__ == "__main__":
    main()
