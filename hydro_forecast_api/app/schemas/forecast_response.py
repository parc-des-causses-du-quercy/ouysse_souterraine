"""
Marshmallow schemas for forecast response documentation.
"""

from marshmallow import Schema, fields


class TimeseriesSchema(Schema):
    timestamps = fields.List(fields.String())
    flow_m3_s = fields.List(fields.Float())


class ForecastMetadataSchema(Schema):
    assimilation_applied = fields.Boolean()
    active_tributaries = fields.List(fields.String())
    qsink_multiplier = fields.Float()


class ForecastResultSchema(Schema):
    arpege_reference_time = fields.String(allow_none=True)
    outlet_forecast = fields.Nested(TimeseriesSchema)
    tributary_forecasts = fields.Dict(keys=fields.String(), values=fields.Nested(TimeseriesSchema))
    metadata = fields.Nested(ForecastMetadataSchema)


class TaskResponseSchema(Schema):
    id = fields.String()
    point_id = fields.String()
    status = fields.String()
    created_at = fields.String()
    started_at = fields.String(allow_none=True)
    completed_at = fields.String(allow_none=True)
    duration_seconds = fields.Float(allow_none=True)
    result = fields.Nested(ForecastResultSchema, allow_none=True)
    error = fields.String(allow_none=True)
