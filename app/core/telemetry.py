from contextlib import nullcontext

from opentelemetry import trace


def configure(settings):
    if not settings.otel_enabled:
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_traces_endpoint))
    )
    trace.set_tracer_provider(provider)
    return provider


def span(name):
    tracer = trace.get_tracer("rag-fastapi")
    return tracer.start_as_current_span(name) if tracer else nullcontext()
