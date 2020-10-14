from functools import partial

import numpy as np
import pytest
import torch
from sklearn.metrics import confusion_matrix

from pytorch_lightning.metrics.classification.confusion_matrix import ConfusionMatrix
from tests.metrics.classification.utils import (_binary_inputs, _binary_prob_inputs, _multiclass_inputs,
                                                _multiclass_prob_inputs, _multidim_multiclass_inputs,
                                                _multidim_multiclass_prob_inputs, _multilabel_inputs,
                                                _multilabel_prob_inputs)
from tests.metrics.utils import NUM_CLASSES, THRESHOLD, MetricTester

torch.manual_seed(42)


def _binary_prob_sk_metric(preds, target, normalize=None):
    sk_preds = (preds.view(-1).numpy() >= THRESHOLD).astype(np.uint8)
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


def _binary_sk_metric(preds, target, normalize=None):
    sk_preds = preds.view(-1).numpy()
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


def _multilabel_prob_sk_metric(preds, target, normalize=None):
    sk_preds = (preds.view(-1).numpy() >= THRESHOLD).astype(np.uint8)
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


def _multilabel_sk_metric(preds, target, normalize=None):
    sk_preds = preds.view(-1).numpy()
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


def _multiclass_prob_sk_metric(preds, target, normalize=None):
    sk_preds = torch.argmax(preds, dim=len(preds.shape) - 1).view(-1).numpy()
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


def _multiclass_sk_metric(preds, target, normalize=None):
    sk_preds = preds.view(-1).numpy()
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


def _multidim_multiclass_prob_sk_metric(preds, target, normalize=None):
    sk_preds = torch.argmax(preds, dim=len(preds.shape) - 2).view(-1).numpy()
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


def _multidim_multiclass_sk_metric(preds, target, normalize=None):
    sk_preds = preds.view(-1).numpy()
    sk_target = target.view(-1).numpy()

    return confusion_matrix(y_true=sk_target, y_pred=sk_preds, normalize=normalize)


@pytest.mark.parametrize("ddp", [True, False])
@pytest.mark.parametrize("dist_sync_on_step", [True, False])
@pytest.mark.parametrize("normalize", ['true', 'pred', 'all', None])
@pytest.mark.parametrize("preds, target, sk_metric, num_classes", [
    (_binary_prob_inputs.preds, _binary_prob_inputs.target, _binary_prob_sk_metric, 2),
    (_binary_inputs.preds, _binary_inputs.target, _binary_sk_metric, 2),
    (_multilabel_prob_inputs.preds, _multilabel_prob_inputs.target, _multilabel_prob_sk_metric, 2),
    (_multilabel_inputs.preds, _multilabel_inputs.target, _multilabel_sk_metric, 2),
    (_multiclass_prob_inputs.preds, _multiclass_prob_inputs.target, _multiclass_prob_sk_metric, NUM_CLASSES),
    (_multiclass_inputs.preds, _multiclass_inputs.target, _multiclass_sk_metric, NUM_CLASSES),
    (
        _multidim_multiclass_prob_inputs.preds,
        _multidim_multiclass_prob_inputs.target,
        _multidim_multiclass_prob_sk_metric,
        NUM_CLASSES
    ),
    (
        _multidim_multiclass_inputs.preds,
        _multidim_multiclass_inputs.target,
        _multidim_multiclass_sk_metric,
        NUM_CLASSES
    )
])
class TestConfusionMatrix(MetricTester):
    def test_confusion_matrix(self, ddp, dist_sync_on_step, normalize, preds, target, sk_metric, num_classes):
        self.run_metric_test(ddp=ddp,
                             preds=preds,
                             target=target,
                             metric_class=ConfusionMatrix,
                             sk_metric=partial(sk_metric, normalize=normalize),
                             dist_sync_on_step=dist_sync_on_step,
                             metric_args={"num_classes": num_classes,
                                          "threshold": THRESHOLD,
                                          "normalize": normalize}
                             )
