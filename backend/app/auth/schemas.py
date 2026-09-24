from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # Bounded so a login attempt cannot be used to push megabytes through bcrypt.
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class Session(BaseModel):
    username: str | None = Field(description='Null when nobody is signed in.')
