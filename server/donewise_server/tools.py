"""Six flat MCP tools, validated against the existing application contracts."""

from collections.abc import Callable
from datetime import datetime
from functools import partial

import anyio
from donewise_harness import contracts as c
from donewise_harness.harness import Context as HarnessContext
from donewise_harness.registry import RegistryUnavailable
from donewise_harness.spoken import amount
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.types import CallToolResult, TextContent
from pydantic import StrictBool, TypeAdapter, ValidationError

ELICITATION_TIMEOUT = 120


class PaymentConsent(c.Contract):
    approve: StrictBool


def invalid_input(exc: ValidationError, model) -> ToolError:
    # Only declared field names; unknown keys and validator messages may contain secrets.
    fields = sorted(
        {
            e["loc"][0] if e["loc"] and e["loc"][0] in model.model_fields else "input"
            for e in exc.errors()
        }
    )
    return ToolError("Invalid tool input: " + ", ".join(fields))


class SafeTool(Tool):
    """Validate the full contract before SDK errors can echo secret input values."""

    input_contract: type[c.Contract] = c.Contract
    validation_now: Callable[[], datetime] | None = None

    async def run(self, arguments, context, convert_result=False):
        if self.name == "approval_grant" and not arguments.get("consent_token"):
            raise ToolError("UNAUTHORIZED: consent capability required")
        try:
            self.input_contract.model_validate(
                arguments, context={"now": self.validation_now()} if self.validation_now else None
            )
        except ValidationError as exc:
            raise invalid_input(exc, self.input_contract) from None
        return await super().run(arguments, context, convert_result)


def harness_context(ctx: Context) -> HarnessContext:
    headers = ctx.headers
    run_id = headers.get("x-donewise-run-id")
    if not run_id:
        session_id = headers.get("mcp-session-id")
        if not session_id:
            raise ToolError("Missing MCP session")
        run_id = "run_" + session_id.replace("-", "")
    try:
        TypeAdapter(c.RunId).validate_python(run_id)
    except ValidationError:
        raise ToolError("Invalid X-DoneWise-Run-Id") from None
    return HarnessContext(user_id="demo", run_id=run_id)


def make_tools(harness):
    async def invoke(model, method, ctx, values):
        try:
            inp = model.model_validate(values, context={"now": harness.clock.now()})
            context = harness_context(ctx)
            arg = inp.operation_id if model is c.OperationGetInput else inp
            kwargs = {}
            if model is c.ApprovalGrantInput:
                kwargs["granted_by"] = (
                    c.GrantedBy.SESSION_UI
                    if ctx.headers.get("x-donewise-channel") == "session-ui"
                    else c.GrantedBy.MCP_CLIENT
                )
            result = await anyio.to_thread.run_sync(partial(method, arg, context, **kwargs))
            capability = ctx.client_capabilities.elicitation if ctx.client_capabilities else None
            if (
                model is c.PaymentChargeInput
                and inp.approval_id is None
                and result.outcome == c.Outcome.NEEDS_APPROVAL
                and capability is not None
                and (capability.form is not None or capability.url is None)
            ):
                try:
                    with anyio.fail_after(ELICITATION_TIMEOUT):
                        consent = await ctx.elicit(
                            f"Approve a {amount(result.expected)} test charge to {inp.payee} "
                            f"for the {inp.concept}?",
                            PaymentConsent,
                        )
                    accepted = consent.action == "accept" and consent.data.approve is True
                except TimeoutError:
                    accepted = None  # Return the durable NEEDS_APPROVAL receipt unchanged.
                except ValueError:
                    accepted = False  # Missing or non-boolean content never grants consent.
                if accepted is not None:
                    result = await anyio.to_thread.run_sync(
                        partial(harness.complete_elicitation, inp, context, result, accepted)
                    )
        except ValidationError as exc:
            raise invalid_input(exc, model) from None
        except PermissionError:
            raise ToolError("UNAUTHORIZED: invalid consent capability for this run") from None
        except RegistryUnavailable:
            raise ToolError("REGISTRY_UNAVAILABLE: operation state unavailable") from None
        except (LookupError, TimeoutError) as exc:
            raise ToolError(str(exc)) from None
        return CallToolResult(
            content=[
                TextContent(type="text", text=result.spoken + "\n\n" + result.model_dump_json())
            ],
            structured_content=result.model_dump(mode="json"),
            is_error=False,
        )

    async def calendar_create_verified(
        ctx: Context,
        submission_id: c.Text,
        title: c.Text,
        start: c.UtcDatetime,
        end: c.UtcDatetime,
        timezone: c.Timezone,
        notes: str | None = None,
    ) -> c.CalendarCreateResult:
        return await invoke(
            c.CalendarCreateInput,
            harness.calendar_create,
            ctx,
            {
                "submission_id": submission_id,
                "title": title,
                "start": start,
                "end": end,
                "timezone": timezone,
                "notes": notes,
            },
        )

    async def calendar_reschedule_verified(
        ctx: Context,
        submission_id: c.Text,
        new_start: c.UtcDatetime,
        new_end: c.UtcDatetime,
        timezone: c.Timezone,
        event_id: c.EventId | None = None,
        event_query: c.Text | None = None,
        retry_of_operation_id: c.OperationId | None = None,
    ) -> c.CalendarRescheduleResult:
        return await invoke(
            c.CalendarRescheduleInput,
            harness.calendar_reschedule,
            ctx,
            {
                "submission_id": submission_id,
                "event_id": event_id,
                "event_query": event_query,
                "new_start": new_start,
                "new_end": new_end,
                "timezone": timezone,
                "retry_of_operation_id": retry_of_operation_id,
            },
        )

    async def payment_charge_verified(
        ctx: Context,
        submission_id: c.Text,
        amount_minor: c.PositiveAmount,
        currency: c.Currency,
        payee: c.Text,
        concept: c.Text,
        approval_id: c.ApprovalId | None = None,
        retry_of_operation_id: c.OperationId | None = None,
    ) -> c.PaymentChargeResult:
        return await invoke(
            c.PaymentChargeInput,
            harness.payment_charge,
            ctx,
            {
                "submission_id": submission_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "payee": payee,
                "concept": concept,
                "approval_id": approval_id,
                "retry_of_operation_id": retry_of_operation_id,
            },
        )

    async def operation_get(
        ctx: Context,
        operation_id: c.OperationId,
    ) -> c.OperationView:
        return await invoke(
            c.OperationGetInput,
            harness.operation_get,
            ctx,
            {
                "operation_id": operation_id,
            },
        )

    async def approval_grant(
        ctx: Context,
        approval_request_id: c.ApprovalId,
        consent_token: c.Text,
    ) -> c.ApprovalGrantResult:
        return await invoke(
            c.ApprovalGrantInput,
            harness.approval_grant,
            ctx,
            {
                "approval_request_id": approval_request_id,
                "consent_token": consent_token,
            },
        )

    async def receipts_recap(
        ctx: Context,
        run_id: c.RunId | None = None,
    ) -> c.RecapResult:
        return await invoke(
            c.ReceiptsRecapInput,
            harness.receipts_recap,
            ctx,
            {
                "run_id": run_id,
            },
        )

    functions = [
        calendar_create_verified,
        calendar_reschedule_verified,
        payment_charge_verified,
        operation_get,
        approval_grant,
        receipts_recap,
    ]
    tools = []
    for fn, spec in zip(functions, c.TOOL_SPECS, strict=True):
        tool = SafeTool.from_function(fn, description=spec.description, structured_output=True)
        tool.input_contract = spec.input_model
        tool.validation_now = harness.clock.now
        # SDK argument-model titles/config differ from Contract; publish the canonical schema.
        # invoke() validates the full model as well, including cross-field validators.
        tool.parameters = spec.input_model.model_json_schema()
        tools.append(tool)
    return tools
