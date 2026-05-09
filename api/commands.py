"""Command parsing API router."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Annotated, Any

from fastapi import APIRouter, status
from fastapi.encoders import jsonable_encoder

from domain.schemas import CommandParseRequest, CommandParseResponse
from services.command_parser import CommandParser

router = APIRouter(prefix="/api/commands", tags=["commands"])


@router.post('/parse', response_model=CommandParseResponse, status_code=status.HTTP_200_OK)
async def parse_command(payload: CommandParseRequest) -> dict[str, Any]:
    command = CommandParser().parse(
        payload.text,
        tenant_id=payload.tenant_id,
        correlation_id=payload.correlation_id,
    )
    encoded_payload = jsonable_encoder(asdict(command) if is_dataclass(command) else command)
    return {
        "command_type": type(command).__name__,
        "payload": encoded_payload,
    }
