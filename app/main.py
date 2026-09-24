"""FastAPI application for the ensemble beat grid service."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from . import db
from .grid import build_measure, parse_fraction
from .schemas import MeasureIn


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # One-command startup: initialise the SQLite schema on boot.
    db.init_db()
    yield


app = FastAPI(
    title="Ensemble Beat Grid API",
    description=(
        "Submit a measure (target duration + >= 2 voices of note/rest events "
        "with rational durations). Voice totals are accumulated with exact "
        "fractions; valid measures are stored with a half-open beat grid."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/measures",
    status_code=status.HTTP_201_CREATED,
    tags=["measures"],
    summary="Validate, grid and save a measure",
)
def create_measure(measure_in: MeasureIn) -> dict:
    """Validate totals and persist the measure.

    * ``201`` — every voice sums exactly to ``target_duration``; the measure
      is saved and its grid returned.
    * ``422`` — a duration string is malformed, or one or more voices do not
      sum to the target; nothing is saved. The response body lists every
      mismatching voice with its exact ``difference`` (``total - target``).
    """
    voices = [
        {
            "name": voice.name,
            "events": [event.model_dump() for event in voice.events],
        }
        for voice in measure_in.voices
    ]

    # parse_fraction raises ValueError on malformed rational strings.
    try:
        parse_fraction(measure_in.target_duration)
        result = build_measure(measure_in.target_duration, voices)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(exc)},
        ) from exc

    mismatches = result["mismatches"]
    if mismatches:
        # Voice totals do not match the target: report them, do not save.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "voice durations do not match target_duration",
                "mismatches": mismatches,
            },
        )

    measure = result["measure"]
    measure_id = db.insert_measure(measure)
    measure["id"] = measure_id
    return measure


@app.get(
    "/measures/{measure_id}",
    tags=["measures"],
    summary="Fetch a saved measure with its beat grid",
)
def read_measure(measure_id: int) -> dict:
    measure = db.get_measure(measure_id)
    if measure is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": f"measure {measure_id} not found"},
        )
    return measure
