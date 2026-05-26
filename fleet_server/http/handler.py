"""Composed Fleet HTTP handler."""

from __future__ import annotations

from fleet_server.http.base import FleetHandlerBase
from fleet_server.http.routes.get import GetRoutesMixin
from fleet_server.http.routes.post import PostRoutesMixin
from fleet_server.http.routes.put import PutRoutesMixin
from fleet_server.http.routes.delete import DeleteRoutesMixin


class FleetHandler(
    GetRoutesMixin,
    PostRoutesMixin,
    PutRoutesMixin,
    DeleteRoutesMixin,
    FleetHandlerBase,
):
    """Route bodies live in ``fleet_server.http.routes``."""

    pass
