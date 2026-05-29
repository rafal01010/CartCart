from enum import StrEnum
from typing import TextIO

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from app.core.settings import Settings


class TelemetryExporter(StrEnum):
    CONSOLE = "console"
    OTLP = "otlp"


def configure_telemetry(app: FastAPI, settings: Settings, stream: TextIO | None = None) -> None:
    app.state.telemetry_enabled = settings.telemetry_enabled
    if not settings.telemetry_enabled:
        return

    resource = Resource.create(
        {
            "service.name": settings.telemetry_service_name,
            "deployment.environment": settings.environment.value,
        }
    )
    tracer_provider = TracerProvider(resource=resource)

    if settings.telemetry_exporter == TelemetryExporter.CONSOLE:
        console_exporter = (
            ConsoleSpanExporter(out=stream) if stream is not None else ConsoleSpanExporter()
        )
        tracer_provider.add_span_processor(
            SimpleSpanProcessor(console_exporter)
        )
    else:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings.telemetry_otlp_endpoint)
            )
        )

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    app.state.telemetry_tracer_provider = tracer_provider
    app.state.telemetry_exporter = settings.telemetry_exporter
