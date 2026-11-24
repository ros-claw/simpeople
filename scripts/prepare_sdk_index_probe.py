"""Fix only NumPy scalar indices passed to the USD TokenArray binding.

This prepares a new probe. It never edits the original, runs Kit or changes the
retarget data, numerical operations, source asset or acceptance thresholds.
"""
import argparse
import ast
import hashlib
from pathlib import Path


def generate(original, expected_sha256):
    original = Path(original)
    data = original.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('original probe differs from frozen plan')
    text = data.decode()
    for index in ['worst[1]', 'worst_angle[1]']:
        before = 'original.GetJointsAttr().Get()['+index+']'
        after = 'original.GetJointsAttr().Get()[int('+index+')]'
        if text.count(before) != 1:
            raise ValueError('unexpected USD index integration point: '+index)
        text = text.replace(before, after)
    ast.parse(text)
    return text


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--original', required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    text = generate(args.original, args.expected_sha256)
    with Path(args.output).open('x') as stream:
        stream.write(text)
