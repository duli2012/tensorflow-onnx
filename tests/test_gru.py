# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT license.

"""Unit Tests for gru."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from backend_test_base import Tf2OnnxBackendTestBase

# pylint: disable=missing-docstring,invalid-name,unused-argument,using-constant-test

class GRUTests(Tf2OnnxBackendTestBase):
    def test_test_single_dynamic_gru_state_is_tuple(self):
        raise ValueError("Not implemented")

if __name__ == '__main__':
    Tf2OnnxBackendTestBase.trigger(GRUTests)
