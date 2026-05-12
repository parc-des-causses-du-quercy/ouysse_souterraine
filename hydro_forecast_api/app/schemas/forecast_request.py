"""
Marshmallow schemas for forecast request validation.
"""

from marshmallow import Schema, fields


class TributaryRequestSchema(Schema):
    lastQ = fields.Float(allow_none=True, load_default=None)


class KarstModRequestSchema(Schema):
    lastQ = fields.Float(allow_none=True, load_default=None)


class CustomMeteoComponentSchema(Schema):
    timestamps = fields.List(fields.String(), required=True)
    precipitation_mm = fields.List(fields.Float(), required=True)
    temperature_c = fields.List(fields.Float(), required=True)
    evapotranspiration_mm = fields.List(fields.Float(), required=True)


class ForecastRequestSchema(Schema):
    lastQ_datetime = fields.String(required=True)
    tributaries = fields.Dict(keys=fields.String(), values=fields.Nested(TributaryRequestSchema), load_default={})
    karstmod = fields.Nested(KarstModRequestSchema, load_default={})
    qsink_multiplier_override = fields.Float(allow_none=True, load_default=None)
    custom_meteo = fields.Dict(keys=fields.String(), values=fields.Nested(CustomMeteoComponentSchema), allow_none=True, load_default=None)
