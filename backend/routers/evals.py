"""Evals router: surfaces MLflow runs for the experiment mapped to a space."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.models import EvalRun, EvalSummary
from backend.routers._validators import validate_space_id
from backend.services import lakebase, mlflow_client

router = APIRouter(prefix="/api")


@router.get("/spaces/{space_id}/evals")
async def get_space_evals(space_id: str) -> dict:
    sid = validate_space_id(space_id)
    mapping = await lakebase.get_eval_mapping(sid)
    if not mapping:
        return EvalSummary(space_id=sid).model_dump(mode="json")

    exp = mlflow_client.get_experiment(mapping["experiment_id"])
    if exp is None:
        # Permission denied or experiment missing
        return EvalSummary(
            space_id=sid,
            experiment_id=mapping["experiment_id"],
            permission_denied=True,
        ).model_dump(mode="json")

    runs_raw = mlflow_client.search_runs(mapping["experiment_id"], max_results=50)
    runs = [EvalRun(**r) for r in runs_raw]
    return EvalSummary(
        space_id=sid,
        experiment_id=exp["experiment_id"],
        experiment_name=exp.get("name"),
        runs=runs,
    ).model_dump(mode="json")


@router.get("/evals/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    if not run_id or len(run_id) > 64:
        raise HTTPException(status_code=400, detail="invalid run_id")
    run = mlflow_client.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run
