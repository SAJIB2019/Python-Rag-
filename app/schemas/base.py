from pydantic import BaseModel, ConfigDict


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
