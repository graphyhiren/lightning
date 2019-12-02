"""
Multi-node example (GPU)
"""
import os
from argparse import ArgumentParser

import numpy as np
import torch

from pl_examples.basic_examples.lightning_module_template import LightningTemplateModel
from pytorch_lightning import Trainer

SEED = 2334
torch.manual_seed(SEED)
np.random.seed(SEED)


def main(hparams):
    """
    Main training routine specific for this project
    :param hparams:
    :return:
    """
    # ------------------------
    # 1 INIT LIGHTNING MODEL
    # ------------------------
    model = LightningTemplateModel(hparams)

    # ------------------------
    # 2 INIT TRAINER
    # ------------------------
    trainer = Trainer(
        gpus=2,
        num_nodes=2,
        distributed_backend='ddp'
    )

    # ------------------------
    # 3 START TRAINING
    # ------------------------
    trainer.fit(model)


if __name__ == '__main__':
    root_dir = os.path.dirname(os.path.realpath(__file__))
    parent_parser = ArgumentParser(add_help=False)

    # each LightningModule defines arguments relevant to it
    parser = LightningTemplateModel.add_model_specific_args(parent_parser, root_dir)
    hyperparams = parser.parse_args()

    # ---------------------
    # RUN TRAINING
    # ---------------------
    main(hyperparams)
