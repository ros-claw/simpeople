"""Actual USD binding regression plus strict frozen-probe preparation."""
import ast
import hashlib
import importlib.util
from pathlib import Path

import numpy as np
from pxr import Vt
import pytest


spec=importlib.util.spec_from_file_location('sdk_index_builder',Path(__file__).parents[1]/'scripts/prepare_sdk_index_probe.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


@pytest.mark.parametrize('dimensions',[(4,81),(4,101)])
def test_actual_usd_token_array_accepts_the_fixed_numpy_argmax_index(dimensions):
    values=Vt.TokenArray(['joint_'+str(i) for i in range(dimensions[1])])
    errors=np.zeros(dimensions);errors[-1,-1]=2
    worst=np.unravel_index(errors.argmax(),errors.shape)
    assert isinstance(worst[1],np.integer)
    with pytest.raises(TypeError):values[worst[1]]
    assert str(values[int(worst[1])])=='joint_'+str(dimensions[1]-1)


@pytest.fixture
def original(tmp_path):
    path=tmp_path/'probe.py'
    path.write_text("position_name=str(original.GetJointsAttr().Get()[worst[1]])\n"
                    "angle_name=str(original.GetJointsAttr().Get()[worst_angle[1]])\n"
                    "values=retarget(local, source, target)\n")
    return path


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def test_only_the_two_usd_binding_indices_change(original):
    before=original.read_bytes();text=builder.generate(original,digest(original))
    tree=ast.parse(text)
    # Removing precisely the two introduced int() nodes recovers the old AST.
    class Unwrap(ast.NodeTransformer):
        calls=0
        def visit_Call(self,node):
            self.generic_visit(node)
            if isinstance(node.func,ast.Name) and node.func.id=='int':
                assert len(node.args)==1 and not node.keywords
                self.calls+=1;return node.args[0]
            return node
    unwrap=Unwrap();recovered=unwrap.visit(tree)
    assert unwrap.calls==2
    assert ast.dump(recovered)==ast.dump(ast.parse(before))
    assert original.read_bytes()==before


def test_stale_source_hash_is_rejected(original):
    with pytest.raises(ValueError):builder.generate(original,'0'*64)


@pytest.mark.parametrize('fault',['missing','duplicate','already_fixed'])
def test_drift_or_repeated_patches_are_rejected(original,fault):
    text=original.read_text()
    if fault=='missing':text=text.replace('worst_angle[1]','wrong_index')
    elif fault=='duplicate':text+=text
    else:text=text.replace('[worst[1]]','[int(worst[1])]')
    original.write_text(text)
    with pytest.raises(ValueError):builder.generate(original,digest(original))
