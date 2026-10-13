"""Sequential workflow execution with a shared context."""

from collections.abc import Callable, Mapping, Sequence

WorkflowContext = dict[str, object]
WorkflowStep = Callable[[Mapping[str, object]], Mapping[str, object]]


def run_workflow(
    steps: Sequence[WorkflowStep],
    initial_context: Mapping[str, object] | None = None,
) -> WorkflowContext:
    """Run steps in order, merging each step's outputs into the workflow context."""
    context: WorkflowContext = dict(initial_context or {})
    for step in steps:
        context.update(step(context))
    return context
