from models import NamePostConfig  # 2. Import your custom model.

import lightning as L
from lightning.app.api import Post


class Flow(L.LightningFlow):

    def __init__(self):
        super().__init__()
        self.names = []

    def run(self):
        print(self.names)

    # 3. Annotate your input with your custom pydantic model.
    def handle_post(self, config: NamePostConfig):
        self.names.append(config.name)
        return f'The name {config} was registered'

    def configure_api(self):
        return [
            Post(
                route="/name",
                method=self.handle_post,
            )
        ]


app = L.LightningApp(Flow())
