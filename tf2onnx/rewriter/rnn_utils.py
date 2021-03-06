# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT license.

"""
tf2onnx.rewriter.rnn_utils - rnn support
"""

import logging
import numpy as np
from enum import Enum
from onnx import helper
from tf2onnx import utils
from tf2onnx.graph import Node
from tf2onnx.graph_matcher import *

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tf2onnx.rewriter.rnn_utils")

class REWRITER_RESULT(Enum):
    SKIP = 1
    OK = 2
    FAIL = 3


class RnnWeight:
    def __init__(self, node, np_val, np_dtype):
        self.node = node
        self.value = np_val
        self.dtype = np_dtype


class RnnWeights:
    def __init__(self, kernel, bias, forget_bias):
        self.kernel = kernel
        self.bias = bias
        self.forget_bias = forget_bias


class RnnInitializers:
    def __init__(self, c_init, h_init, c_h_shared_init):
        self.c_init_input_id = None
        self.h_init_input_id = None
        self.share_init_node = None
        self.share_init_input_id = None

        if c_h_shared_init:
            self.share_init_input_id = c_h_shared_init
            self.share_init_node = True
        else:
            self.c_init_input_id = c_init
            self.h_init_input_id = h_init
            self.share_init_node = False


class RnnProperties:
    def __init__(self):
        # RNN input who are outside of rnn scope
        self.input_node = None
        self.input_id = None
        self.var_initializers = {}

        self.onnx_input_ids = {}

        self.time_major = False
        self.x_input_id = None # used to serve lstm's 1st input
        self.input_size = None
        self.hidden_size = None

        self.batch_size_node = None # only for fill constant workaround

    def is_valid(self):
        if not self.input_node:
            log.error("no input node found for current rnn, skip")
            return False
        else:
            log.debug("input node with port id " + self.input_id)

        return True


# TensorFlow LSTMCell/BasicLSTMCell computation graph matching
xc_pattern = OpTypePattern('Split', inputs=[
    OpTypePattern("Const"), # axis for split
    OpTypePattern("BiasAdd", name="bias_add", inputs=[
        OpTypePattern("MatMul", inputs=[
            OpTypePattern("ConcatV2|Concat", name="xh"),
            OpTypePattern("Enter", inputs=[
                OpTypePattern("*", name="cell_kernel"),
            ]),
        ]),
        OpTypePattern("Enter", inputs=[
            OpTypePattern("*", name="cell_bias"),
        ]),
    ]),
])


lstmcell_pattern = \
    OpTypePattern('Mul', name='ht', inputs=[
        OpTypePattern("Sigmoid", name="ot", inputs=[xc_pattern]),
        OpTypePattern('Tanh', inputs=[
            OpTypePattern("Add", name="ct", inputs=[
                OpTypePattern("Mul", inputs=[
                    OpTypePattern("Sigmoid", name="ft", inputs=[
                        OpTypePattern("Add", inputs=[
                            xc_pattern,
                            OpTypePattern("*", name="ft_bias"),
                        ]),
                    ]),
                    OpTypePattern("*"),
                ]),
                OpTypePattern("Mul", inputs=[
                    OpTypePattern("Sigmoid", name="it", inputs=[xc_pattern]),
                    OpTypePattern("Tanh", name="gt", inputs=[xc_pattern]),
                ]),
            ]),
        ]),
    ])

class RNNUnitType(Enum):
    LSTMCell = 0 # TF LSTMCell and BasicLSTMCell share the same pattern
    GRUCell = 1


rnn_cell_patterns = {
    RNNUnitType.LSTMCell: lstmcell_pattern,
    RNNUnitType.GRUCell: None
}


def get_pattern(cell_type_name):
    return rnn_cell_patterns[cell_type_name]


def get_weights_from_const_node(node):
    temp = node
    val = None
    dtype = None
    # this would help ignore Identity in non-const_folded graph.
    while temp.type == 'Identity':
        temp = temp.inputs[0]

    if temp and temp.type == 'Const':
        val = temp.get_tensor_value()
        dtype = utils.ONNX_TO_NUMPY_DTYPE[temp.dtype]
        log.debug("found weights " + temp.name)
    else:
        log.error("weight node seems not to be Const, skip, node name is " + temp.name)
        return

    return RnnWeight(node, val, dtype)


def check_is_timemajor_transpose(node):
    # TensorFlow transpose node has perm as its second input
    if node.type != "Transpose" :
        return

    perm_node = node.inputs[1]
    if perm_node.is_const():
        if list(node.inputs[1].get_tensor_value()) == [1, 0, 2]:
            return True
        else:
            return
    elif check_is_unfolded_perm(perm_node):
        return True
    else:
        raise ValueError("Not supported yet")


# todo: fix this
def check_is_unfolded_perm(perm_node):
    # For some case, like HallWay, the perm is a ConcatV2,
    # but it should be calculated when constant-fold. TODO: investigate why not constant fold.
    # current workaround: use np to calculate the val explicitly. 
    if perm_node.type == "ConcatV2" and len(perm_node.inputs) == 3:
        const_node_val = perm_node.inputs[0].get_tensor_value()
        if list(const_node_val) != [1, 0]:
            return False

        range_node = perm_node.inputs[1]
        range_start = range_node.inputs[0].get_tensor_value()
        range_limit = range_node.inputs[1].get_tensor_value()
        range_delta = range_node.inputs[2].get_tensor_value()
        if range_node.type == "Range" and range_start == [2] and range_limit == [3] and range_delta == [1]:
            # we just hard code this now
            # todo: refine this
            return True
    return False


def make_onnx_node(g, op_type, inputs, attr=None, output_count=1, skip_conversion=True):
    if attr is None:
        attr = {}
    node_name = utils.make_name(op_type)
    outputs = [node_name + ":" + str(i) for i in np.arange(output_count)]
    node = Node(
        helper.make_node(op_type, inputs, outputs, name = node_name, **attr),
        g, skip_conversion = skip_conversion)

    return node


def is_reverse_op(op):
    return op.type in ("ReverseV2", "ReverseSequence")
