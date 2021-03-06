# Copyright 1999-2020 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


class DataFrameRuntimeOptimizeRule:
    @staticmethod
    def match(chunk, graph, keys):
        return False

    @staticmethod
    def apply(chunk, graph, keys):
        pass


class DataFrameRuntimeOptimizer:
    _rules = []

    def __init__(self, graph):
        self._graph = graph

    @staticmethod
    def register_rule(rule):
        DataFrameRuntimeOptimizer._rules.append(rule)

    @classmethod
    def is_available(cls):
        return True

    def optimize(self, keys=None):
        visited = set()
        for c in list(self._graph.topological_iter()):
            if c in visited:
                continue
            visited.add(c)
            for rule in self._rules:
                if rule.match(c, self._graph, keys):
                    rule.apply(c, self._graph, keys)


class DataSourceHeadRule(DataFrameRuntimeOptimizeRule):
    @staticmethod
    def match(chunk, graph, keys):
        from ....dataframe.datasource.read_csv import DataFrameReadCSV
        from ....dataframe.datasource.read_sql import DataFrameReadSQL
        from ....dataframe.indexing.iloc import DataFrameIlocGetItem

        op = chunk.op
        inputs = graph.predecessors(chunk)
        if len(inputs) == 1 and isinstance(op, DataFrameIlocGetItem) and \
                op.is_head() and isinstance(inputs[0].op, (DataFrameReadCSV, DataFrameReadSQL)) and \
                inputs[0].key not in keys:
            return True
        return False

    @staticmethod
    def apply(chunk, graph, keys):
        from ....dataframe.utils import parse_index

        data_source_chunk = graph.predecessors(chunk)[0]
        nrows = data_source_chunk.op.nrows or 0
        head = chunk.op.indexes[0].stop
        # delete read_csv from graph
        graph.remove_node(data_source_chunk)

        head_data_source_chunk_op = data_source_chunk.op.copy().reset_key()
        head_data_source_chunk_op._nrows = max(nrows, head)
        head_data_source_chunk_params = data_source_chunk.params
        head_data_source_chunk_params['_key'] = chunk.key
        head_data_source_chunk_params['shape'] = (head,) + chunk.shape[1:]
        if chunk.index_value.has_value():
            pd_index = chunk.index_value.to_pandas()[:head]
            head_data_source_chunk_params['index_value'] = parse_index(pd_index)
        head_data_source_chunk = head_data_source_chunk_op.new_chunk(
            data_source_chunk.inputs, kws=[head_data_source_chunk_params]).data
        graph.add_node(head_data_source_chunk)

        for succ in list(graph.iter_successors(chunk)):
            succ_inputs = succ.inputs
            new_succ_inputs = []
            for succ_input in succ_inputs:
                if succ_input is chunk:
                    new_succ_inputs.append(head_data_source_chunk)
                else:
                    new_succ_inputs.append(succ_input)
            succ.inputs = new_succ_inputs
            graph.add_edge(head_data_source_chunk, succ)

        graph.remove_node(chunk)


DataFrameRuntimeOptimizer.register_rule(DataSourceHeadRule)
