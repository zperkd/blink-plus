"""Browse and play Blink cloud clips using Home Assistant's Media browser."""

from datetime import timedelta
from homeassistant.components.media_player import MediaClass, MediaType, BrowseError
from homeassistant.components.media_source import (
    MediaSource,
    BrowseMediaSource,
    PlayMedia,
    Unresolvable,
)
from homeassistant.components.http.auth import async_sign_path
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState
from aiohttp import web
from .const import DOMAIN
from .cloud import CloudError


async def async_get_media_source(hass):
    return BlinkMedia(hass)


class BlinkMedia(MediaSource):
    name = "Blink cloud clips"

    def __init__(self, hass):
        super().__init__(DOMAIN)
        self.hass = hass

    def coordinator(self, entry_id):
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if (
            not entry
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise CloudError("Blink account is unavailable")
        return entry.runtime_data

    def folder(self, identifier, title, children):
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=identifier,
            title=title,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.VIDEO,
            can_play=False,
            can_expand=True,
            children=children,
        )

    async def async_browse_media(self, item):
        parts = item.identifier.split("/") if item.identifier else []
        try:
            if not parts:
                return self.folder(
                    None,
                    self.name,
                    [
                        self.folder(entry.entry_id, entry.title, [])
                        for entry in self.hass.config_entries.async_entries(DOMAIN)
                        if entry.state is ConfigEntryState.LOADED
                        and entry.runtime_data.options["cloud_enabled"]
                    ],
                )
            co = self.coordinator(parts[0])
            rows = await co.cloud.list()
            if len(parts) == 1:
                names = {r["device_id"]: r["name"] for r in rows.values()}
                return self.folder(
                    parts[0],
                    "Cameras",
                    [
                        self.folder(parts[0] + "/" + key, name, [])
                        for key, name in sorted(names.items(), key=lambda p: p[1])
                    ],
                )
            if len(parts) != 2:
                raise CloudError("Unknown cloud folder")
            children = []
            for key, row in rows.items():
                if row["device_id"] != parts[1]:
                    continue
                thumbnail = None
                if row["thumbnail"]:
                    thumbnail = async_sign_path(
                        self.hass,
                        f"/api/blink_plus/{parts[0]}/thumbnail/{key}",
                        timedelta(minutes=10),
                    )
                children.append(
                    BrowseMediaSource(
                        domain=DOMAIN,
                        identifier="/".join([*parts, key]),
                        title=row["created_at"]
                        .replace("T", " ")
                        .replace("+00:00", " UTC"),
                        media_class=MediaClass.VIDEO,
                        media_content_type="video/mp4",
                        can_play=True,
                        can_expand=False,
                        thumbnail=thumbnail,
                    )
                )
            return self.folder(item.identifier, "Cloud recordings", children)
        except CloudError as err:
            raise BrowseError(str(err)) from None

    async def async_resolve_media(self, item):
        parts = item.identifier.split("/") if item.identifier else []
        if len(parts) != 3:
            raise Unresolvable("Choose a cloud recording")
        try:
            row = await self.coordinator(parts[0]).cloud.lookup(parts[2])
            if row["device_id"] != parts[1]:
                raise CloudError("Unknown cloud recording")
        except CloudError as err:
            raise Unresolvable(str(err)) from None
        url = async_sign_path(
            self.hass,
            f"/api/blink_plus/{parts[0]}/video/{parts[2]}",
            timedelta(minutes=10),
        )
        return PlayMedia(url=url, mime_type="video/mp4")


class BlinkCloudView(HomeAssistantView):
    url = "/api/blink_plus/{entry_id}/{kind:video|thumbnail}/{clip_id}"
    name = "api:blink_plus:cloud"
    requires_auth = True

    async def get(self, request, entry_id, kind, clip_id):
        from homeassistant.components.http.const import KEY_HASS

        hass = request.app[KEY_HASS]
        try:
            co = BlinkMedia(hass).coordinator(entry_id)
            filename = await co.cloud.file(clip_id, thumbnail=kind == "thumbnail")
        except CloudError as err:
            raise web.HTTPNotFound(text=str(err)) from None
        return web.FileResponse(
            filename,
            headers={
                "Content-Type": "image/jpeg" if kind == "thumbnail" else "video/mp4",
                "Cache-Control": "private, max-age=60",
            },
        )
