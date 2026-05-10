"""Command parsing API route for HustlerOS Phase 2."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder

from domain.schemas import ParseRequest, ParseResponse
from services.command_parser import CommandParser

router = APIRouter(prefix="/commands", tags=["commands"])
parser = CommandParser()


@router.post("/parse", response_model=ParseResponse)
async def parse_command(req: ParseRequest) -> ParseResponse:
    """Parse one WhatsApp-style command message."""

    command = await parser.parse(req.message, req.tenant_id)
    return ParseResponse(
        command_type=type(command).__name__,
        confidence=getattr(command, "confidence", 1.0),
        parsed=jsonable_encoder(command.__dict__),
        raw=req.message,
    )
