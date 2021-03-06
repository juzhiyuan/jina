from typing import Any

import numpy as np
import pytest

from jina.drivers.evaluate import FieldEvaluateDriver
from jina.drivers.helper import DocGroundtruthPair, array2pb
from jina.executors.evaluators import BaseEvaluator
from jina.proto import jina_pb2


class MockDiffEvaluator(BaseEvaluator):

    @property
    def metric(self):
        return 'MockDiffEvaluator'

    def evaluate(self, actual: Any, desired: Any, *args, **kwargs) -> float:
        return abs(len(actual) - len(desired))


@pytest.fixture(scope='function', params=['text', 'buffer', 'blob'])
def field_type(request):
    return request.param


@pytest.fixture(scope='function')
def doc_with_field_type(field_type):
    class DocCreator(object):
        def create(self):
            doc = jina_pb2.Document()
            if field_type == 'text':
                doc.text = 'aaa'
            elif field_type == 'buffer':
                doc.buffer = b'\x01\x02\x03'
            elif field_type == 'blob':
                doc.blob.CopyFrom(array2pb(np.array([1, 1, 1])))
            return doc

    return DocCreator()


@pytest.fixture(scope='function')
def groundtruth_with_field_type(field_type):
    class GTCreator(object):
        def create(self):
            gt = jina_pb2.Document()
            if field_type == 'text':
                gt.text = 'aaaa'
            elif field_type == 'buffer':
                gt.buffer = b'\x01\x02\x03\04'
            elif field_type == 'blob':
                gt.blob.CopyFrom(array2pb(np.array([1, 1, 1, 1])))
            return gt

    return GTCreator()


@pytest.fixture(scope='function')
def doc_groundtruth_pair(doc_with_field_type, groundtruth_with_field_type):
    class DocGroundtruthPairFactory(object):
        def create(self):
            return DocGroundtruthPair(
                doc=doc_with_field_type.create(),
                groundtruth=groundtruth_with_field_type.create()
            )

    return DocGroundtruthPairFactory()


@pytest.fixture(scope='function')
def ground_truth_pairs(doc_groundtruth_pair):
    doc_groundtruth_pairs = []
    for _ in range(10):
        doc_groundtruth_pairs.append(
            doc_groundtruth_pair.create()
        )
    return doc_groundtruth_pairs


@pytest.fixture
def mock_diff_evaluator():
    return MockDiffEvaluator()


class SimpleEvaluateDriver(FieldEvaluateDriver):
    @property
    def exec_fn(self):
        return self._exec_fn


@pytest.fixture(scope='function')
def simple_evaluate_driver(field_type):
    return SimpleEvaluateDriver(field=field_type)


def test_crafter_evaluate_driver(mock_diff_evaluator, simple_evaluate_driver, ground_truth_pairs):
    simple_evaluate_driver.attach(executor=mock_diff_evaluator, pea=None)
    simple_evaluate_driver._apply_all(ground_truth_pairs)
    for pair in ground_truth_pairs:
        doc = pair.doc
        assert len(doc.evaluations) == 1
        assert doc.evaluations[0].op_name == 'SimpleEvaluateDriver-MockDiffEvaluator'
        assert doc.evaluations[0].value == 1.0


class SimpleChunkEvaluateDriver(FieldEvaluateDriver):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.eval_request = None
        self._traversal_paths = ('c',)

    @property
    def exec_fn(self):
        return self._exec_fn

    @property
    def req(self) -> 'jina_pb2.Request':
        """Get the current (typed) request, shortcut to ``self.pea.request``"""
        return self.eval_request


@pytest.fixture(scope='function')
def doc_groundtruth_pair(doc_with_field_type, groundtruth_with_field_type):
    class DocGroundtruthPairFactory(object):
        def create(self):
            return DocGroundtruthPair(
                doc=doc_with_field_type.create(),
                groundtruth=groundtruth_with_field_type.create()
            )

    return DocGroundtruthPairFactory()


@pytest.fixture(scope='function')
def ground_truth_pairs(doc_groundtruth_pair):
    doc_groundtruth_pairs = []
    for _ in range(10):
        doc_groundtruth_pairs.append(
            doc_groundtruth_pair.create()
        )
    return doc_groundtruth_pairs


@pytest.fixture(scope='function')
def simple_chunk_evaluate_driver():
    def get_evaluate_driver(field_type):
        return SimpleChunkEvaluateDriver(field=field_type)

    return get_evaluate_driver


@pytest.fixture
def eval_request():
    def request(field_type):
        num_docs = 10
        req = jina_pb2.Request.IndexRequest()
        for idx in range(num_docs):
            doc = req.docs.add()
            gt = req.groundtruths.add()
            chunk_doc = doc.chunks.add()
            chunk_gt = gt.chunks.add()
            chunk_doc.granularity = 1
            chunk_gt.granularity = 1
            if field_type == 'text':
                chunk_doc.text = 'aaa'
                chunk_gt.text = 'aaaa'
            elif field_type == 'buffer':
                chunk_doc.buffer = b'\x01\x02\x03'
                chunk_gt.buffer = b'\x01\x02\x03\x04'
            elif field_type == 'blob':
                chunk_doc.blob.CopyFrom(array2pb(np.array([1, 1, 1])))
                chunk_gt.blob.CopyFrom(array2pb(np.array([1, 1, 1, 1])))
        return req

    return request


@pytest.mark.parametrize(
    'field_type',
    ['text', 'buffer', 'blob']
)
def test_crafter_evaluate_driver_in_chunks(field_type,
                                           simple_chunk_evaluate_driver,
                                           mock_diff_evaluator,
                                           eval_request):
    # this test proves that we can evaluate matches at chunk level,
    # proving that the driver can traverse in a parallel way docs and groundtruth
    req = eval_request(field_type)
    driver = simple_chunk_evaluate_driver(field_type)
    driver.attach(executor=mock_diff_evaluator, pea=None)
    driver.eval_request = req
    driver()

    assert len(req.docs) == len(req.groundtruths)
    assert len(req.docs) == 10
    for doc in req.docs:
        assert len(doc.evaluations) == 0  # evaluation done at chunk level
        assert len(doc.chunks) == 1
        chunk = doc.chunks[0]
        assert len(chunk.evaluations) == 1  # evaluation done at chunk level
        assert chunk.evaluations[0].op_name == 'SimpleChunkEvaluateDriver-MockDiffEvaluator'
        assert chunk.evaluations[0].value == 1.0
