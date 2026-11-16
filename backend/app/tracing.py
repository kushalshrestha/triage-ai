"""OpenTelemetry setup (see ADR-0030) — a vendor-neutral tracing layer,
not a vendor SDK directly: instrument once here, and the trace data is
portable to any OTLP-compatible backend (Jaeger today, Langfuse or
another backend later) without touching call sites in `app/agent/`.

`BatchSpanProcessor`, not `SimpleSpanProcessor` — exports happen on a
background thread so a slow or unreachable collector never blocks a
request, the standard production choice.
"""
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import get_settings

tracer = trace.get_tracer("triageai")


def setup_tracing() -> None:
    settings = get_settings()
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: settings.otel_service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint))
    )
    trace.set_tracer_provider(provider)
