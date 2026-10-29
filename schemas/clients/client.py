from pydantic import BaseModel, Field


class Client(BaseModel):
    parent_client_id: str | None = None
    parent_client_name: str | None = None
    client_id: str
    client_name: str


class ConfirmClientDetailDecision(BaseModel):
    parent_client_id: str | None = None
    parent_client_name: str | None = None
    client_id: str
    client_name: str
    confirm: bool = Field(description="Confirm client details.")

