"""M8 tool helper for generating code from one persisted M6 component card."""

from __future__ import annotations

from inspo_mcp.repositories.kits import KitRepository
from inspo_mcp.schemas import ComponentCodeGeneration, Framework
from inspo_mcp.services.component_codegen import ComponentCodeGenerator


def generate_component_code_for_run(
    kit_repository: KitRepository,
    *,
    run_id: str,
    framework: Framework,
    component_name: str,
) -> ComponentCodeGeneration:
    """Load the durable kit and generate exactly one named component."""

    return ComponentCodeGenerator().generate(
        kit_repository.get(run_id),
        framework=framework,
        component_name=component_name,
    )
