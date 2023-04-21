import abc
from functools import partial
from types import ModuleType
from typing import Any, List, Optional

from lightning.app.core.work import LightningWork
from lightning.app.utilities.imports import _is_gradio_available, requires

from .theme import theme

if _is_gradio_available():
    import gradio
    from gradio import themes
else:
    gradio = ModuleType("gradio")
    gradio.themes = ModuleType("gradio.themes")
    gradio.themes.Base = ModuleType("gradio.themes.Base")


class ServeGradio(LightningWork, abc.ABC):
    """The ServeGradio Class enables to quickly create a ``gradio`` based UI for your LightningApp.

    In the example below, the ``ServeGradio`` is subclassed to deploy ``AnimeGANv2``.

    .. literalinclude:: ../../../../examples/app/components/serve/gradio/app.py
        :language: python

    The result would be the following:

    .. image:: https://pl-public-data.s3.amazonaws.com/assets_lightning/anime_gan.gif
        :alt: Animation showing how to AnimeGANv2 UI would looks like.
    """

    inputs: Any
    outputs: Any
    examples: Optional[List] = None
    enable_queue: bool = False
    title: Optional[str] = None
    description: Optional[str] = None

    _start_method = "spawn"

    def __init__(self, *args: Any, theme: Optional[themes.Base] = theme, **kwargs: Any):
        requires("gradio")(super().__init__(*args, **kwargs))
        assert self.inputs
        assert self.outputs
        self._model = None
        self._theme = theme

        self.ready = False

    @property
    def model(self):
        return self._model

    @abc.abstractmethod
    def predict(self, *args: Any, **kwargs: Any):
        """Override with your logic to make a prediction."""

    @abc.abstractmethod
    def build_model(self) -> Any:
        """Override to instantiate and return your model.

        The model would be accessible under self.model
        """

    def run(self, *args: Any, **kwargs: Any):
        if self._model is None:
            self._model = self.build_model()
        fn = partial(self.predict, *args, **kwargs)
        fn.__name__ = self.predict.__name__
        self.ready = True
        gradio.Interface(
            fn=fn,
            inputs=self.inputs,
            outputs=self.outputs,
            examples=self.examples,
            title=self.title,
            description=self.description,
            theme=self._theme,
        ).launch(
            server_name=self.host,
            server_port=self.port,
            enable_queue=self.enable_queue,
        )

    def configure_layout(self) -> str:
        return self.url
