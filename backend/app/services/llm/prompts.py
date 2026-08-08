"""Grounded prompt construction for the explanation service.

The prompts here are the mechanism that keeps the LLM out of the analytical
loop. Two properties are enforced in code rather than trusted to instructions:

* the user prompt is assembled *only* from a validated
  :class:`~app.schemas.risk.ExplanationRequest`, so no free-form text reaches
  the model, and
* every number the model is allowed to mention is present in the prompt, and
  missing inputs are stated explicitly instead of being omitted.

These functions are pure and unit-tested; they make no network calls.
"""

from __future__ import annotations

from app.schemas.risk import ExplanationRequest

SYSTEM_PROMPT = """\
You are the briefing writer for UrbanPulse, an urban flood-risk platform.

You will receive a set of FACTS that were computed by statistical models and \
geospatial analysis. Your only job is to restate those facts as clear prose.

Rules you must follow without exception:
1. Use only the numbers, place names and findings given in the FACTS. Never \
introduce a value that is not present there.
2. Never estimate, extrapolate or round a probability into a different figure.
3. If the FACTS list missing inputs, state plainly that those inputs were \
unavailable and that the estimate is correspondingly less certain.
4. Do not give emergency, medical or evacuation instructions beyond the \
recommended actions supplied to you.
5. Do not speculate about causes that are not among the listed contributing \
factors.
6. Write plainly. No preamble, no closing pleasantries, no bullet lists unless \
the audience is an operator.
"""


def _format_probability(value: float) -> str:
    return f"{value * 100:.0f}%"


def build_user_prompt(request: ExplanationRequest) -> str:
    """Serialise a validated request into the FACTS block sent to the model."""
    prediction = request.prediction
    lines: list[str] = [
        "FACTS",
        "=====",
        f"Zone: {prediction.zone_name}",
        f"Waterlogging probability: {_format_probability(prediction.risk_probability)}",
        f"Risk band: {prediction.risk_band}",
        f"Model confidence: {_format_probability(prediction.confidence)}",
        (
            "Forecast window: "
            f"{prediction.forecast_window_start.isoformat()} to "
            f"{prediction.forecast_window_end.isoformat()}"
        ),
        f"Model version: {prediction.model_version}",
        "",
        "Contributing factors (from the model's own attributions, strongest first):",
    ]

    if prediction.top_contributions:
        for contribution in prediction.top_contributions:
            unit = f" {contribution.unit}" if contribution.unit else ""
            value = "unknown" if contribution.value is None else f"{contribution.value:g}{unit}"
            arrow = "increases" if contribution.direction == "increases_risk" else "decreases"
            lines.append(
                f"- {contribution.display_name}: {value} ({arrow} risk, "
                f"weight {abs(contribution.contribution):.3f})"
            )
    else:
        lines.append("- None available.")

    if prediction.missing_inputs:
        lines += [
            "",
            "Inputs that were unavailable for this prediction:",
            *(f"- {name}" for name in prediction.missing_inputs),
        ]

    if request.impact is not None:
        impact = request.impact
        population = (
            "not available"
            if impact.estimated_population_affected is None
            else str(impact.estimated_population_affected)
        )
        lines += [
            "",
            "Infrastructure impact:",
            f"- Roads affected: {len(impact.affected_roads)}",
            f"- Total affected road length: {impact.total_affected_length_km:.1f} km",
            f"- Zones above threshold: {impact.affected_zone_count}",
            f"- Zones fully cut off: {len(impact.isolated_zone_ids)}",
            f"- Estimated population affected: {population}",
        ]
        critical = [road for road in impact.affected_roads if road.is_critical_link]
        if critical:
            lines.append("- Critical links (removal disconnects the road graph):")
            lines += [
                f"  - {road.name or road.highway_class} ({road.affected_length_m:.0f} m affected)"
                for road in critical[:10]
            ]

    if request.actions:
        lines += ["", "Recommended actions:"]
        lines += [
            f"- [{action.priority}] {action.title} — {action.responsible_unit}"
            for action in request.actions
        ]

    audience_note = (
        "Write for a municipal control-room operator: precise, technical, terse."
        if request.audience == "operator"
        else "Write for the general public: plain language, no jargon, no alarmism."
    )

    lines += [
        "",
        "TASK",
        "====",
        audience_note,
        f"Produce at most {request.max_words} words summarising the situation above.",
    ]
    return "\n".join(lines)


def grounding_payload(request: ExplanationRequest) -> dict[str, object]:
    """The facts echoed back in the response so output can be audited."""
    return {
        "zone_id": str(request.prediction.zone_id),
        "risk_probability": request.prediction.risk_probability,
        "risk_band": request.prediction.risk_band,
        "model_version": request.prediction.model_version,
        "contribution_count": len(request.prediction.top_contributions),
        "missing_inputs": request.prediction.missing_inputs,
        "action_count": len(request.actions),
    }
