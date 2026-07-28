# visualization_node.py
import os
from foamagent.services.visualization import DEFAULT_OUTPUT_PNG, visualize_case

from foamagent.logger import get_logger

logger = get_logger(__name__)


# Routing should decide whether to enter this node (see router_func.llm_requires_visualization).

def visualization_node(state):
    """Visualization node: create a minimal PyVista screenshot for an OpenFOAM case.

    The attempt order and the artifact check live in services.visualization.visualize_case,
    which the MCP visualization tool calls as well. This node only unpacks the graph state
    and packs the result back into it.
    """
    user_requirement = state.get("user_requirement", "")
    case_dir = state.get("case_dir")

    logger.info("<visualization>")

    # Note: routing logic should decide whether we reach this node.

    if not case_dir:
        logger.info("</visualization>")
        return _failure(state, case_dir="", error="Missing case_dir")

    case_dir = os.path.abspath(case_dir)
    if not os.path.exists(case_dir):
        message = f"Case directory does not exist: {case_dir}"
        logger.info(message)
        logger.info("</visualization>")
        return _failure(state, case_dir=case_dir, error=message)

    result = visualize_case(
        case_dir,
        user_requirement,
        max_loop=getattr(state.get("config"), "max_loop", 2),
        output_png=DEFAULT_OUTPUT_PNG,
    )

    if not result.success:
        error_message = "Visualization failed after all attempts"
        logger.info(f"<visualization_error>{error_message}</visualization_error>")
        logger.info("</visualization>")
        return _failure(
            state,
            case_dir=case_dir,
            error=error_message,
            error_logs=result.error_logs,
        )

    logger.info("</visualization>")
    plot_configs = [
        {
            "plot_type": "pyvista",
            "field_name": result.field_name,
            "time_step": "latest",
            "output_format": "png",
            "output_path": result.output_image,
        }
    ]
    return {
        **state,
        "plot_configs": plot_configs,
        "plot_outputs": [result.output_image],
        "visualization_summary": {
            "total_plots_generated": 1,
            "plot_types": ["pyvista"],
            "fields_visualized": [result.field_name],
            "output_directory": case_dir,
            "pyvista_success": True,
            "used": result.used,
        },
        "pyvista_visualization": {
            "success": True,
            "output_image": result.output_image,
            "script": result.script,
            "used": result.used,
        },
    }


def _failure(state, *, case_dir, error, error_logs=None):
    summary = {
        "total_plots_generated": 0,
        "plot_types": [],
        "fields_visualized": [],
        "output_directory": case_dir,
        "pyvista_success": False,
        "error": error,
    }
    visualization = {"success": False, "error": error}
    if error_logs is not None:
        summary["error_logs"] = error_logs
        visualization["error_logs"] = error_logs

    return {
        **state,
        "plot_configs": [],
        "plot_outputs": [],
        "visualization_summary": summary,
        "pyvista_visualization": visualization,
    }
